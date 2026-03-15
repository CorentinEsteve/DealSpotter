import logging
import random
import time
import schedule
from config import (
    POLL_INTERVAL_SECONDS, MAX_ALERTS_PER_DAY,
    SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX, SEARCH_URLS,
    MAX_SEARCH_PAGES,
    SEARCH_BASE, SEARCH_QUERIES, QUERIES_PER_CYCLE,
)
import db
from evaluator import pre_filter, evaluate_listing
from flip_calculator import calculate_flip_margin
from scraper import scrape_search, scrape_search_from_config, scrape_listing
from telegram_bot import (
    send_telegram_alert, send_queued_alerts, is_quiet_hours,
    queue_alert, start_telegram_bot_async,
)

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bikeflip.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bikeflip.pipeline")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

_consecutive_scrape_failures = 0

# --- Query rotation state (resets on restart, full coverage in ~20 min) ---
_rotation_offsets = {"B": 0, "C": 0}


def get_queries_for_cycle() -> list[dict]:
    """Select which queries to run this cycle, rotating B and C tiers.

    Tier A: all queries every cycle (generic catch-all)
    Tier B: rotate N from the pool (brand-specific)
    Tier C: rotate N from the pool (vintage)
    """
    tier_groups = {}
    for q in SEARCH_QUERIES:
        tier = q.get("tier", "A")
        tier_groups.setdefault(tier, []).append(q)

    queries = []

    for tier, pool in sorted(tier_groups.items()):
        n = QUERIES_PER_CYCLE.get(tier)
        if n is None or n >= len(pool):
            # Run all queries in this tier
            queries.extend(pool)
        else:
            # Rotate: pick n queries starting from offset
            offset = _rotation_offsets.get(tier, 0)
            selected = [pool[(offset + i) % len(pool)] for i in range(n)]
            _rotation_offsets[tier] = (offset + n) % len(pool)
            queries.extend(selected)

    keywords = [q["text"] for q in queries]
    log.info(f"[pipeline] Cycle queries ({len(queries)}): {', '.join(keywords)}")
    return queries


def _scrape_all_searches(run_stats: dict) -> list[dict]:
    """Scrape all search queries for this cycle. Returns deduplicated listings."""
    all_listings = []
    seen_ids = set()

    use_structured = bool(SEARCH_QUERIES)

    if use_structured:
        queries = get_queries_for_cycle()
        for query in queries:
            try:
                results = scrape_search_from_config(query, SEARCH_BASE, max_pages=MAX_SEARCH_PAGES)
                for listing in results:
                    lbc_id = listing.get("lbc_id")
                    if lbc_id and lbc_id not in seen_ids:
                        seen_ids.add(lbc_id)
                        all_listings.append(listing)
                log.info(f"[pipeline] '{query['text']}': {len(results)} listings")
                time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))
            except Exception as e:
                log.error(f"[pipeline] Search '{query['text']}' failed: {e}")
        log.info(f"[pipeline] {len(all_listings)} unique listings from {len(queries)} queries")
    else:
        # Legacy: SEARCH_URLS from .env
        for search_url in SEARCH_URLS:
            try:
                results = scrape_search(search_url, max_pages=MAX_SEARCH_PAGES)
                for listing in results:
                    lbc_id = listing.get("lbc_id")
                    if lbc_id and lbc_id not in seen_ids:
                        seen_ids.add(lbc_id)
                        all_listings.append(listing)
                log.info(f"[pipeline] {len(results)} listings from search URL")
                if len(SEARCH_URLS) > 1:
                    time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))
            except Exception as e:
                log.error(f"[pipeline] Search scrape failed: {e}")
        log.info(f"[pipeline] {len(all_listings)} unique listings from {len(SEARCH_URLS)} URL(s)")

    run_stats["scraped"] = len(all_listings)
    return all_listings


def run_pipeline():
    """Single pipeline run. Called by scheduler every 5 minutes.

    Flow: scrape search → dedup → pre-filter → fetch full listing → AI evaluate → alert
    """
    global _consecutive_scrape_failures

    if not SEARCH_QUERIES and not SEARCH_URLS:
        log.error("[pipeline] No searches configured — nothing to do")
        return

    # --- Run counters ---
    run_stats = {
        "scraped": 0,
        "already_seen": 0,
        "new": 0,
        "pre_filtered": 0,
        "scrape_failed": 0,
        "evaluated": 0,
        "eval_failed": 0,
        "alerted": 0,
        "margins": [],       # list of margin values for evaluated listings
        "skip_reasons": {},  # reason -> count
    }

    # Step 1: Scrape all searches (with rotation + pagination)
    all_listings = _scrape_all_searches(run_stats)

    # Step 2: Process each listing
    for listing in all_listings:
        lbc_id = listing.get("lbc_id", "???")
        try:
            # Dedup — skip if already in DB
            if db.listing_exists(lbc_id):
                run_stats["already_seen"] += 1
                continue

            run_stats["new"] += 1

            # Pre-filter on search data (free, no API calls, no extra requests)
            should_skip, reason = pre_filter(listing)

            # Insert into DB (dedup gate)
            db.insert_listing(
                lbc_id=lbc_id,
                url=listing["url"],
                title=listing.get("title"),
                price=listing.get("price"),
                photo_urls=listing.get("photo_urls"),
                location=listing.get("location"),
                seller_type=listing.get("seller_type"),
            )

            if should_skip:
                db.update_status(lbc_id, "skipped", skip_reason=reason)
                run_stats["pre_filtered"] += 1
                run_stats["skip_reasons"][reason] = run_stats["skip_reasons"].get(reason, 0) + 1
                log.info(f"[pipeline] {lbc_id} — pre-filtered: {reason}")
                continue

            # Fetch full listing page for description
            if _consecutive_scrape_failures >= 3:
                log.warning(f"[pipeline] {lbc_id} — scraping paused (3+ failures), skipping")
                run_stats["scrape_failed"] += 1
                continue

            scraped = scrape_listing(listing["url"])
            if scraped is None:
                _consecutive_scrape_failures += 1
                db.update_status(lbc_id, "skipped", skip_reason="scrape_failed")
                run_stats["scrape_failed"] += 1
                log.warning(f"[pipeline] {lbc_id} — scrape failed")
                continue
            _consecutive_scrape_failures = 0

            db.update_listing_data(lbc_id, scraped)
            listing.update(scraped)
            time.sleep(random.uniform(SCRAPE_DELAY_MIN, SCRAPE_DELAY_MAX))

            # AI evaluation
            result = evaluate_listing(listing)
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

            margin = calculate_flip_margin(listing["price"], resale_min, resale_max)
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

            log.info(f"[pipeline] {lbc_id} — margin {margin['margin_mid']}€ "
                     f"(ROI {margin['roi_percent']}%) — "
                     f"{'ALERT' if margin['is_worth_it'] else 'no alert'}")

            # Alert if worth it
            if margin["is_worth_it"]:
                if db.get_alerts_today_count() < MAX_ALERTS_PER_DAY:
                    listing_data = db.get_listing(lbc_id) or listing
                    eval_data = {
                        "ai_item_name": result.get("item_name", listing.get("title")),
                        "ai_condition": result.get("condition", "inconnu"),
                        "reasoning": result.get("reasoning", ""),
                    }

                    if not is_quiet_hours():
                        try:
                            send_telegram_alert(listing_data, eval_data, margin)
                            db.mark_alerted(lbc_id)
                            run_stats["alerted"] += 1
                        except Exception as e:
                            log.error(f"[pipeline] {lbc_id} — Telegram send failed: {e}")
                            queue_alert(listing_data, eval_data, margin)
                    else:
                        queue_alert(listing_data, eval_data, margin)
                        log.info(f"[pipeline] {lbc_id} — Queued (quiet hours)")
                else:
                    log.info(f"[pipeline] Daily alert limit reached, skipping {lbc_id}")

        except Exception as e:
            log.error(f"[pipeline] Error processing {lbc_id}: {e}")
            db.update_status(lbc_id, "error", skip_reason=str(e)[:200])
            continue

    # --- Run summary ---
    _log_run_summary(run_stats)


def _log_run_summary(stats: dict):
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

    log.info(
        f"[pipeline] ── Run summary ──────────────────────────────────\n"
        f"  Scraped: {stats['scraped']} | Already seen: {stats['already_seen']} | New: {stats['new']}\n"
        f"  Pre-filtered: {stats['pre_filtered']} | Scrape failed: {stats['scrape_failed']}\n"
        f"  AI evaluated: {stats['evaluated']} | Eval failed: {stats['eval_failed']} | Alerted: {stats['alerted']}"
        f"{margin_str}{skip_detail}\n"
        f"  ──────────────────────────────────────────────────────────"
    )

    # Also log cumulative DB stats periodically
    db_stats = db.get_stats()
    log.info(
        f"[pipeline] DB totals: {db_stats['total']} total | "
        f"{db_stats['evaluated']} evaluated | {db_stats['skipped']} skipped | "
        f"{db_stats['alerted']} alerted | {db_stats['interested']} interested"
    )


def main():
    """Entry point. Start scheduler and Telegram bot."""
    log.info("DealSpotter starting...")
    db.init_db()

    if not SEARCH_QUERIES and not SEARCH_URLS:
        log.error("No searches configured — exiting")
        return

    if SEARCH_QUERIES:
        tier_counts = {}
        for q in SEARCH_QUERIES:
            tier = q.get("tier", "A")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        tier_str = ", ".join(f"Tier {t}: {n}" for t, n in sorted(tier_counts.items()))
        log.info(f"Monitoring {len(SEARCH_QUERIES)} search queries ({tier_str})")
    else:
        log.info(f"Monitoring {len(SEARCH_URLS)} search URL(s) (legacy mode)")

    # Start Telegram bot FIRST so it can receive commands immediately
    try:
        start_telegram_bot_async()
        time.sleep(1)  # Let the bot thread initialize
        log.info("[pipeline] Telegram bot listener started")
    except Exception as e:
        log.error(f"[pipeline] Failed to start Telegram bot: {e}")

    send_queued_alerts()
    run_pipeline()

    schedule.every(POLL_INTERVAL_SECONDS).seconds.do(run_pipeline)

    log.info(f"Scheduler running — polling every {POLL_INTERVAL_SECONDS}s")

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
