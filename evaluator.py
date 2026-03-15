import json
import re
import logging
import time
import base64
import httpx
import anthropic
from config import (
    ANTHROPIC_API_KEY, HAIKU_MODEL, SONNET_MODEL,
    MIN_PRICE_EUR, MAX_PRICE_EUR,
    SKIP_KEYWORDS, SKIP_SELLER_TYPES, JUNK_INDICATORS,
    HIGH_VALUE_BRANDS, VISION_CONFIDENCE_THRESHOLD,
)
from prompts import TEXT_ONLY_PROMPT, VISION_PROMPT
import db

log = logging.getLogger("bikeflip.evaluator")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# --- Tier 0: Pre-filter (free) ---

def pre_filter(listing: dict) -> tuple:
    """Returns (should_skip, reason). No API calls.
    All keyword matching is in French since leboncoin is a French platform."""

    title_lower = (listing.get("title") or "").lower()
    desc_lower = (listing.get("description") or "").lower()
    price = listing.get("price", 0)

    # Price out of range
    if price < MIN_PRICE_EUR:
        return True, f"prix_trop_bas ({price}€)"
    if price > MAX_PRICE_EUR:
        return True, f"prix_trop_haut ({price}€)"

    # Blocked keywords in title
    for kw in SKIP_KEYWORDS:
        if kw in title_lower:
            return True, f"mot_clé_bloqué ({kw})"

    # Junk indicators in title or description
    for kw in JUNK_INDICATORS:
        if kw in title_lower or kw in desc_lower:
            return True, f"annonce_épave ({kw})"

    # Pro seller
    if listing.get("seller_type") in SKIP_SELLER_TYPES:
        return True, "vendeur_pro"

    return False, ""


# --- JSON parsing helpers ---

def parse_llm_json(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown wrapping and preamble."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code blocks
    cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON object from the response
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    log.error(f"[evaluator] Failed to parse JSON from LLM response: {text[:200]}...")
    return None


# --- Tier 1: Text-only (Claude Haiku) ---

def evaluate_text_only(listing: dict) -> dict:
    """Evaluate listing using text only (Tier 1, Claude Haiku).
    Returns parsed evaluation dict or None on failure."""

    prompt = TEXT_ONLY_PROMPT.format(
        title=listing.get("title", ""),
        price=listing.get("price", 0),
        description=listing.get("description", "Pas de description"),
        location=listing.get("location", "Inconnu"),
    )

    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        result_text = response.content[0].text
        result = parse_llm_json(result_text)
        if result:
            result["eval_tier"] = 1
            log.info(f"[evaluator] {listing['lbc_id']} — Tier 1 text-only — "
                     f"confidence {result.get('confidence', '?')}")
        return result

    except anthropic.RateLimitError:
        log.warning(f"[evaluator] Rate limited on Tier 1, waiting 30s...")
        time.sleep(30)
        return None
    except Exception as e:
        log.error(f"[evaluator] Tier 1 failed for {listing['lbc_id']}: {e}")
        return None


# --- Tier 2: Vision (Claude Sonnet) ---

def fetch_images(photo_urls: list, max_images: int = 4) -> list:
    """Download listing images and return as base64-encoded data.
    Returns list of dicts with 'type', 'media_type', 'data'."""
    if not photo_urls:
        return []

    images = []
    for url in photo_urls[:max_images]:
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "image/jpeg")
                media_type = content_type.split(";")[0].strip()
                if media_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                    media_type = "image/jpeg"
                b64_data = base64.standard_b64encode(resp.content).decode("utf-8")
                images.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_data,
                    }
                })
        except Exception as e:
            log.warning(f"[evaluator] Failed to fetch image {url}: {e}")

    return images


def evaluate_with_vision(listing: dict) -> dict:
    """Evaluate listing using photos + text (Tier 2, Claude Sonnet).
    Returns parsed evaluation dict or None on failure."""

    # Get photo URLs from listing
    photo_urls_raw = listing.get("photo_urls")
    if isinstance(photo_urls_raw, str):
        try:
            photo_urls = json.loads(photo_urls_raw)
        except json.JSONDecodeError:
            photo_urls = []
    elif isinstance(photo_urls_raw, list):
        photo_urls = photo_urls_raw
    else:
        photo_urls = []

    images = fetch_images(photo_urls)
    if not images:
        log.warning(f"[evaluator] {listing['lbc_id']} — No images available for Tier 2")
        # Fall back to text-only with Sonnet (still more capable than Haiku)
        return evaluate_text_only_sonnet(listing)

    prompt_text = VISION_PROMPT.format(
        title=listing.get("title", ""),
        price=listing.get("price", 0),
        description=listing.get("description", "Pas de description"),
        location=listing.get("location", "Inconnu"),
    )

    # Build message content: images first, then text prompt
    content = images + [{"type": "text", "text": prompt_text}]

    try:
        response = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )
        result_text = response.content[0].text
        result = parse_llm_json(result_text)
        if result:
            result["eval_tier"] = 2
            log.info(f"[evaluator] {listing['lbc_id']} — Tier 2 vision — "
                     f"confidence {result.get('confidence', '?')}")
        return result

    except anthropic.RateLimitError:
        log.warning(f"[evaluator] Rate limited on Tier 2, waiting 30s...")
        time.sleep(30)
        return None
    except Exception as e:
        log.error(f"[evaluator] Tier 2 failed for {listing['lbc_id']}: {e}")
        return None


def evaluate_text_only_sonnet(listing: dict) -> dict:
    """Fallback: text-only evaluation using Sonnet (when no images for Tier 2)."""
    prompt = TEXT_ONLY_PROMPT.format(
        title=listing.get("title", ""),
        price=listing.get("price", 0),
        description=listing.get("description", "Pas de description"),
        location=listing.get("location", "Inconnu"),
    )

    try:
        response = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        result_text = response.content[0].text
        result = parse_llm_json(result_text)
        if result:
            result["eval_tier"] = 2
            log.info(f"[evaluator] {listing['lbc_id']} — Tier 2 text-only (no images) — "
                     f"confidence {result.get('confidence', '?')}")
        return result
    except Exception as e:
        log.error(f"[evaluator] Tier 2 text-only failed for {listing['lbc_id']}: {e}")
        return None


# --- Tier routing ---

def evaluate_listing(listing: dict) -> dict:
    """Route listing through the cheapest adequate AI evaluation tier.

    Pre-filter (Tier 0) is NOT called here — it runs earlier in the pipeline
    (in main.py) on search data, before fetching full listing pages.

    This function assumes the listing has already been enriched with scraped data
    (full description, photos, seller_type, etc).

    Returns evaluation result dict or None if evaluation failed.
    """
    lbc_id = listing.get("lbc_id", "???")

    # Decide tier based on enriched data
    title_lower = (listing.get("title") or "").lower()
    has_known_brand = any(brand in title_lower for brand in HIGH_VALUE_BRANDS)
    has_clear_description = len(listing.get("description") or "") > 100

    if has_known_brand and has_clear_description:
        # Tier 1: text-only (cheap)
        result = evaluate_text_only(listing)
        if result and result.get("confidence", 0) >= VISION_CONFIDENCE_THRESHOLD:
            return result
        # Fall through to Tier 2 if not confident enough
        log.info(f"[evaluator] {lbc_id} — Tier 1 low confidence, escalating to Tier 2")

    # Tier 2: vision (more expensive but more accurate)
    result = evaluate_with_vision(listing)

    # Small delay between API calls to avoid rate limits
    time.sleep(0.5)

    return result
