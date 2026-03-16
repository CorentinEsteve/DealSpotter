import json
import logging
import random
import time
import schedule
from config import (
    POLL_INTERVAL_SECONDS,
    SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX, SEARCH_URLS,
    MAX_SEARCH_PAGES,
    ACTIVE_CATEGORIES, CATEGORIES,
    # Backward-compat (legacy SEARCH_URLS path)
    SEARCH_BASE, SEARCH_QUERIES, QUERIES_PER_CYCLE,
)
import db
from evaluator import pre_filter, evaluate_listing
from flip_calculator import calculate_flip_margin
from scraper import scrape_search, scrape_search_from_config, scrape_listing
from telegram_bot import send_telegram_alert, start_telegram_bots

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("dealspotter.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("dealspotter.pipeline")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

_consecutive_scrape_failures = 0
MAX_NEW_SCRAPES_PER_CYCLE = 20  # Cap individual listing scrapes per cycle to avoid DataDome

# --- Query rotation state per category ---
_rotation_offsets = {}  # {"bikes": {"B": 0, "C": 0}, "furniture": {"B": 0, "C": 0}}


def get_queries_for_cycle(category: str, cat_config: dict) -> list[dict]:
    """Select which queries to run this cycle, rotating B and C tiers.

    Tier A: all queries every cycle (generic catch-all)
    Tier B: rotate N from the pool (brand-specific)
    Tier C: rotate N from the pool (vintage/niche)
    """
    search_queries = cat_config.get("search_queries", [])
    queries_per_cycle = cat_config.get("queries_per_cycle", {"A": None, "B": 4, "C": 1})

    # Initialize rotation offsets for this category if needed
    if category not in _rotation_offsets:
        _rotation_offsets[category] = {"B": 0, "C": 0}

    tier_groups = {}
    for q in search_queries:
        tier = q.get("tier", "A")
        tier_groups.setdefault(tier, []).append(q)

    queries = []

    for tier, pool in sorted(tier_groups.items()):
        n = queries_per_cycle.get(tier)
        if n is None or n >= len(pool):
            # Run all queries in this tier
            queries.extend(pool)
        else:
            # Rotate: pick n queries starting from offset
            offset = _rotation_offsets[category].get(tier, 0)
            selected = [pool[(offset + i) % len(pool)] for i in range(n)]
            _rotation_offsets[category][tier] = (offset + n) % len(pool)
            queries.extend(selected)

    keywords = [q["text"] for q in queries]
    log.info(f"[pipeline] [{category}] Cycle queries ({len(queries)}): {', '.join(keywords)}")
    return queries


def _scrape_all_searches(category: str, cat_config: dict, run_stats: dict) -> list[dict]:
    """Scrape all search queries for this cycle. Returns deduplicated listings."""
    all_listings = []
    seen_ids = set()

    search_queries = cat_config.get("search_queries", [])

    if search_queries:
        # Build search_base with lbc_category injected
        search_base = {
            **cat_config["search_base"],
            "category": cat_config["lbc_category"],
        }
        queries = get_queries_for_cycle(category, cat_config)
        for query in queries:
            try:
                results = scrape_search_from_config(query, search_base, max_pages=MAX_SEARCH_PAGES)
                for listing in results:
                    lbc_id = listing.get("lbc_id")
                    if lbc_id and lbc_id not in seen_ids:
                        seen_ids.add(lbc_id)
                        all_listings.append(listing)
                log.info(f"[pipeline] [{category}] '{query['text']}': {len(results)} listings")
                time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))
            except Exception as e:
                log.error(f"[pipeline] [{category}] Search '{query['text']}' failed: {e}")
        log.info(f"[pipeline] [{category}] {len(all_listings)} unique listings from {len(queries)} queries")
    else:
        # Legacy: SEARCH_URLS from .env (only for bikes backward compat)
        for search_url in SEARCH_URLS:
            try:
                results = scrape_search(search_url, max_pages=MAX_SEARCH_PAGES)
                for listing in results:
                    lbc_id = listing.get("lbc_id")
                    if lbc_id and lbc_id not in seen_ids:
                        seen_ids.add(lbc_id)
                        all_listings.append(listing)
                log.info(f"[pipeline] [{category}] {len(results)} listings from search URL")
                if len(SEARCH_URLS) > 1:
                    time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))
            except Exception as e:
                log.error(f"[pipeline] [{category}] Search scrape failed: {e}")
        log.info(f"[pipeline] [{category}] {len(all_listings)} unique listings from {len(SEARCH_URLS)} URL(s)")

    run_stats["scraped"] = len(all_listings)
    return all_listings


def run_pipeline_for_category(category: str, cat_config: dict):
    """Single pipeline run for one category.

    Flow: scrape search → dedup → pre-filter → fetch full listing → AI evaluate → alert
    """
    global _consecutive_scrape_failures

    # Reset failure counter for each category (don't let bikes failures block furniture)
    _consecutive_scrape_failures = 0

    label = cat_config.get("label", category)
    log.info(f"[pipeline] ── {label} ──────────────────────────────────")

    search_queries = cat_config.get("search_queries", [])
    if not search_queries and not SEARCH_URLS:
        log.warning(f"[pipeline] [{category}] No searches configured — skipping")
        return

    # --- Run counters ---
    run_stats = {
        "scraped": 0,
        "already_seen": 0,
        "new": 0,
        "pre_filtered": 0,
        "scrape_failed": 0,
        "scrape_capped": 0,
        "pending_evaluated": 0,
        "evaluated": 0,
        "eval_failed": 0,
        "alerted": 0,
        "margins": [],
        "skip_reasons": {},
    }

    # Step 1: Scrape all searches (with rotation + pagination)
    all_listings = _scrape_all_searches(category, cat_config, run_stats)

    # Step 2: Process each listing
    scrapes_this_cycle = 0

    for listing in all_listings:
        lbc_id = listing.get("lbc_id", "???")
        try:
            # Dedup — skip if already in DB
            if db.listing_exists(lbc_id):
                run_stats["already_seen"] += 1
                continue

            run_stats["new"] += 1

            # Pre-filter on search data (free, no API calls, no extra requests)
            should_skip, reason = pre_filter(listing, category)

            # Insert into DB (dedup gate)
            db.insert_listing(
                lbc_id=lbc_id,
                url=listing["url"],
                title=listing.get("title"),
                price=listing.get("price"),
                description=listing.get("description"),
                photo_urls=listing.get("photo_urls"),
                location=listing.get("location"),
                seller_type=listing.get("seller_type"),
                category=category,
            )

            if should_skip:
                db.update_status(lbc_id, "skipped", skip_reason=reason)
                run_stats["pre_filtered"] += 1
                run_stats["skip_reasons"][reason] = run_stats["skip_reasons"].get(reason, 0) + 1
                log.info(f"[pipeline] [{category}] {lbc_id} — pre-filtered: {reason}")
                continue

            # The search API already returns full description + photos.
            # Only fetch the individual listing page if description is missing/short.
            has_description = len(listing.get("description") or "") > 50

            if not has_description:
                # Cap individual listing scrapes per cycle to avoid DataDome
                if scrapes_this_cycle >= MAX_NEW_SCRAPES_PER_CYCLE:
                    run_stats["scrape_capped"] += 1
                    # Still evaluate with what we have from the search API
                    has_description = True  # proceed with partial data

                elif _consecutive_scrape_failures >= 5:
                    log.warning(f"[pipeline] [{category}] {lbc_id} — scraping paused (5+ failures)")
                    # Still evaluate with what we have
                    has_description = True

                else:
                    scraped = scrape_listing(listing["url"])
                    if scraped is None:
                        _consecutive_scrape_failures += 1
                        run_stats["scrape_failed"] += 1
                        log.warning(f"[pipeline] [{category}] {lbc_id} — scrape failed, using API data")
                        time.sleep(random.uniform(5.0, 10.0))
                        # Don't skip — evaluate with what the API gave us
                    else:
                        _consecutive_scrape_failures = 0
                        scrapes_this_cycle += 1
                        db.update_listing_data(lbc_id, scraped)
                        listing.update(scraped)
                        time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))

            # AI evaluation
            result = evaluate_listing(listing, category)
            if result is None:
                db.update_status(lbc_id, "skipped", skip_reason="eval_failed")
                run_stats["eval_failed"] += 1
                continue

            # Calculate flip margin
            resale_min = result.get("estimated_resale_min", 0)
            resale_max = result.get("estimated_resale_max", 0)
            if not resale_min or not resale_max:
                db.update_status(lbc_id, "skipped", skip_reason="no_resale_estimate")
                run_stats["eval_failed"] += 1
                continue

            margin = calculate_flip_margin(listing["price"], resale_min, resale_max, category)
            run_stats["evaluated"] += 1
            run_stats["margins"].append(margin["margin_mid"])

            db.update_evaluation(
                lbc_id=lbc_id,
                eval_tier=result.get("eval_tier", 0),
                ai_item_name=result.get("item_name"),
                ai_brand=result.get("brand"),
                ai_model=result.get("model"),
                ai_condition=result.get("condition"),
                ai_confidence=result.get("confidence"),
                estimated_resale_min=resale_min,
                estimated_resale_max=resale_max,
                flip_margin=margin["margin_mid"],
                status="evaluated",
            )

            log.info(f"[pipeline] [{category}] {lbc_id} — margin {margin['margin_mid']}€ "
                     f"(ROI {margin['roi_percent']}%) — "
                     f"{'ALERT' if margin['is_worth_it'] else 'no alert'}")

            # Alert if worth it
            if margin["is_worth_it"]:
                listing_data = db.get_listing(lbc_id) or listing
                eval_data = {
                    "ai_item_name": result.get("item_name", listing.get("title")),
                    "ai_condition": result.get("condition", "inconnu"),
                    "reasoning": result.get("reasoning", ""),
                    "category": category,
                    "category_label": label,
                }
                try:
                    send_telegram_alert(listing_data, eval_data, margin)
                    db.mark_alerted(lbc_id)
                    run_stats["alerted"] += 1
                except Exception as e:
                    log.error(f"[pipeline] [{category}] {lbc_id} — Telegram send failed: {e}")

        except Exception as e:
            log.error(f"[pipeline] [{category}] Error processing {lbc_id}: {e}")
            db.update_status(lbc_id, "error", skip_reason=str(e)[:200])
            continue

    # Step 3: Pick up any pending listings from DB that weren't evaluated yet
    #         (e.g. from a previous run where scraping failed before evaluation)
    MAX_PENDING_PER_CYCLE = 30  # Avoid hammering the API with hundreds of evals at once
    pending = db.get_pending_listings(category)
    if pending:
        log.info(f"[pipeline] [{category}] {len(pending)} pending listings in DB, evaluating up to {MAX_PENDING_PER_CYCLE}")
        pending = pending[:MAX_PENDING_PER_CYCLE]
        for row in pending:
            lbc_id = row["lbc_id"]
            try:
                # Convert DB row to listing dict for evaluator
                photo_urls = row.get("photo_urls")
                if isinstance(photo_urls, str):
                    try:
                        photo_urls = json.loads(photo_urls)
                    except (json.JSONDecodeError, TypeError):
                        photo_urls = []

                listing_data = {
                    "lbc_id": lbc_id,
                    "url": row["url"],
                    "title": row.get("title"),
                    "price": row.get("price"),
                    "description": row.get("description"),
                    "photo_urls": photo_urls,
                    "location": row.get("location"),
                    "seller_type": row.get("seller_type"),
                }

                result = evaluate_listing(listing_data, category)
                if result is None:
                    db.update_status(lbc_id, "skipped", skip_reason="eval_failed")
                    run_stats["eval_failed"] += 1
                    continue

                resale_min = result.get("estimated_resale_min", 0)
                resale_max = result.get("estimated_resale_max", 0)
                if not resale_min or not resale_max:
                    db.update_status(lbc_id, "skipped", skip_reason="no_resale_estimate")
                    run_stats["eval_failed"] += 1
                    continue

                margin = calculate_flip_margin(listing_data["price"], resale_min, resale_max, category)
                run_stats["evaluated"] += 1
                run_stats["pending_evaluated"] += 1
                run_stats["margins"].append(margin["margin_mid"])

                db.update_evaluation(
                    lbc_id=lbc_id,
                    eval_tier=result.get("eval_tier", 0),
                    ai_item_name=result.get("item_name"),
                    ai_brand=result.get("brand"),
                    ai_model=result.get("model"),
                    ai_condition=result.get("condition"),
                    ai_confidence=result.get("confidence"),
                    estimated_resale_min=resale_min,
                    estimated_resale_max=resale_max,
                    flip_margin=margin["margin_mid"],
                    status="evaluated",
                )

                log.info(f"[pipeline] [{category}] {lbc_id} (pending) — margin {margin['margin_mid']}€ "
                         f"(ROI {margin['roi_percent']}%) — "
                         f"{'ALERT' if margin['is_worth_it'] else 'no alert'}")

                if margin["is_worth_it"]:
                    eval_data = {
                        "ai_item_name": result.get("item_name", listing_data.get("title")),
                        "ai_condition": result.get("condition", "inconnu"),
                        "reasoning": result.get("reasoning", ""),
                        "category": category,
                        "category_label": label,
                    }
                    try:
                        send_telegram_alert(listing_data, eval_data, margin)
                        db.mark_alerted(lbc_id)
                        run_stats["alerted"] += 1
                    except Exception as e:
                        log.error(f"[pipeline] [{category}] {lbc_id} — Telegram send failed: {e}")

            except Exception as e:
                log.error(f"[pipeline] [{category}] Error evaluating pending {lbc_id}: {e}")
                db.update_status(lbc_id, "error", skip_reason=str(e)[:200])

    # --- Run summary ---
    _log_run_summary(category, run_stats)


def run_pipeline(categories: list = None):
    """Run pipeline for specified categories (or all active ones)."""
    cats = categories or ACTIVE_CATEGORIES
    for category in cats:
        cat_config = CATEGORIES.get(category)
        if not cat_config:
            log.error(f"[pipeline] Unknown category '{category}' — skipping")
            continue
        run_pipeline_for_category(category, cat_config)


def _log_run_summary(category: str, stats: dict):
    """Log a clear summary at the end of each pipeline run."""
    margins = stats["margins"]
    margin_str = ""
    if margins:
        avg_margin = sum(margins) / len(margins)
        best = max(margins)
        worst = min(margins)
        margin_str = f" | margins: avg {avg_margin:.0f}€, best {best:.0f}€, worst {worst:.0f}€"

    skip_detail = ""
    if stats["skip_reasons"]:
        top_reasons = sorted(stats["skip_reasons"].items(), key=lambda x: -x[1])[:5]
        skip_detail = " | top skip: " + ", ".join(f"{r} ({n})" for r, n in top_reasons)

    capped_str = f" | Capped (next cycle): {stats.get('scrape_capped', 0)}" if stats.get("scrape_capped") else ""

    pending_str = f" | From DB pending: {stats.get('pending_evaluated', 0)}" if stats.get("pending_evaluated") else ""

    log.info(
        f"[pipeline] ── [{category}] Run summary ──────────────────────\n"
        f"  Scraped: {stats['scraped']} | Already seen: {stats['already_seen']} | New: {stats['new']}\n"
        f"  Pre-filtered: {stats['pre_filtered']} | Scrape failed: {stats['scrape_failed']}{capped_str}\n"
        f"  AI evaluated: {stats['evaluated']}{pending_str} | Eval failed: {stats['eval_failed']} | Alerted: {stats['alerted']}"
        f"{margin_str}{skip_detail}\n"
        f"  ──────────────────────────────────────────────────────────"
    )

    # Also log cumulative DB stats for this category
    db_stats = db.get_stats(category)
    log.info(
        f"[pipeline] [{category}] DB totals: {db_stats['total']} total | "
        f"{db_stats['evaluated']} evaluated | {db_stats['skipped']} skipped | "
        f"{db_stats['alerted']} alerted | {db_stats['interested']} interested"
    )


def main():
    """Entry point. Accepts --category bikes|furniture|all (default: all)."""
    import argparse

    parser = argparse.ArgumentParser(description="DealSpotter — find undervalued items on leboncoin")
    parser.add_argument(
        "--category", "-c",
        choices=list(CATEGORIES.keys()) + ["all"],
        default="all",
        help="Which category to run (default: all)",
    )
    args = parser.parse_args()

    # Determine which categories to run
    if args.category == "all":
        categories = list(ACTIVE_CATEGORIES)
    else:
        categories = [args.category]

    cat_labels = ", ".join(CATEGORIES[c]["label"] for c in categories)
    log.info(f"DealSpotter starting — {cat_labels}")
    db.init_db()

    # Log active categories
    for category in categories:
        cat_config = CATEGORIES[category]
        search_queries = cat_config.get("search_queries", [])
        if search_queries:
            tier_counts = {}
            for q in search_queries:
                tier = q.get("tier", "A")
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
            tier_str = ", ".join(f"Tier {t}: {n}" for t, n in sorted(tier_counts.items()))
            log.info(f"{cat_config['label']} — {len(search_queries)} search queries ({tier_str})")
        else:
            log.info(f"{cat_config['label']} — using legacy SEARCH_URLS")

    # Start Telegram bot(s) FIRST so they can receive commands immediately
    try:
        start_telegram_bots(categories)
        time.sleep(1)  # Let the bot thread(s) initialize
    except Exception as e:
        log.error(f"[pipeline] Failed to start Telegram bot(s): {e}")

    run_pipeline(categories)

    schedule.every(POLL_INTERVAL_SECONDS).seconds.do(lambda: run_pipeline(categories))

    log.info(f"Scheduler running — polling every {POLL_INTERVAL_SECONDS}s")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
