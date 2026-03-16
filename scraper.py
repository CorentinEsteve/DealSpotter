"""Scrape leboncoin listing data using curl_cffi.

Two approaches for search:
  1. JSON API (POST api.leboncoin.fr/finder/search) — clean, structured data
  2. HTML scraping (__NEXT_DATA__) — fallback if API fails

Both use curl_cffi with Chrome TLS fingerprint + DataDome cookies.
Cookies are auto-refreshed from Chrome on block (403).

Individual listings use the same curl_cffi + __NEXT_DATA__ approach.
"""

import json
import logging
import os
import random
import re
import time
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

log = logging.getLogger("bikeflip.scraper")

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lbc_cookies.json")

# --- Cookie management ---

def _load_cookies() -> dict:
    """Load saved DataDome/leboncoin cookies from file."""
    if not os.path.exists(COOKIES_FILE):
        return {}
    try:
        with open(COOKIES_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cookies(cookies: dict):
    """Save cookies to file for reuse across runs."""
    try:
        existing = _load_cookies()
        existing.update(cookies)
        with open(COOKIES_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except OSError as e:
        log.warning(f"[scraper] Failed to save cookies: {e}")


def _try_refresh_cookies_from_chrome() -> bool:
    """Try to auto-refresh cookies from Chrome. Returns True if successful."""
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".leboncoin.fr")
        cookies = {c.name: c.value for c in cj}
        if cookies:
            _save_cookies(cookies)
            datadome = [k for k in cookies if "datadome" in k.lower()]
            log.info(f"[scraper] Auto-refreshed {len(cookies)} cookies from Chrome ({len(datadome)} DataDome)")
            return True
    except Exception as e:
        log.debug(f"[scraper] Chrome cookie refresh failed: {e}")
    return False


# --- Session management ---

def _get_session() -> curl_requests.Session:
    """Create a curl_cffi session with Chrome impersonation and saved cookies."""
    session = curl_requests.Session(impersonate="chrome")
    session.headers.update({
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })

    cookies = _load_cookies()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".leboncoin.fr")

    return session


def _get_api_session() -> curl_requests.Session:
    """Create a curl_cffi session configured for the JSON API."""
    session = curl_requests.Session(impersonate="chrome")
    session.headers.update({
        "Accept": "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://www.leboncoin.fr",
        "Referer": "https://www.leboncoin.fr/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "api_key": "ba0c2dad52b3ec",
    })

    cookies = _load_cookies()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".leboncoin.fr")

    return session


_proxy = os.environ.get("LBC_PROXY")


# --- Core fetch with auto-retry ---

def _fetch_with_retry(fetch_fn, max_retries: int = 2):
    """Run a fetch function. On block, try refreshing cookies from Chrome and retry."""
    result = fetch_fn()
    if result is not None:
        return result

    # Blocked — try refreshing cookies from Chrome
    if _try_refresh_cookies_from_chrome():
        log.info("[scraper] Retrying with fresh Chrome cookies...")
        result = fetch_fn()
        if result is not None:
            return result

    return None


def _fetch_page(url: str, proxy: str | None = None) -> str | None:
    """Fetch a leboncoin page via curl_cffi. Returns HTML or None if blocked."""
    session = _get_session()

    kwargs = {"timeout": 15}
    if proxy:
        kwargs["proxies"] = {"https": proxy, "http": proxy}

    try:
        resp = session.get(url, **kwargs)

        # Save any new cookies
        try:
            jar = resp.cookies
            resp_cookies = {name: jar[name] for name in jar}
            if resp_cookies:
                _save_cookies(resp_cookies)
        except Exception:
            pass

        html = resp.text

        if _is_blocked(html):
            log.warning(f"[scraper] DataDome blocked {url} (status={resp.status_code})")
            return None

        return html

    except Exception as e:
        log.warning(f"[scraper] Request failed for {url}: {e}")
        return None


def _is_blocked(html: str) -> bool:
    """Check if the response is a CAPTCHA/block page."""
    lower = html.lower()
    return any(s in lower for s in [
        "captcha-delivery.com", "datadome", "geo.captcha-delivery",
        "accès temporairement restreint",
    ])


# --- JSON API search ---

def _build_search_payload(url: str, page: int = 1, limit: int = 35) -> dict:
    """Convert a leboncoin search URL into a JSON API payload.

    Parses the URL query parameters and builds the payload expected by
    POST api.leboncoin.fr/finder/search.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    payload = {
        "limit": limit,
        "limit_alu": 3,
        "offset": limit * (page - 1),
        "sort_by": params.get("sort", ["time"])[0],
        "sort_order": params.get("order", ["desc"])[0],
        "filters": {
            "enums": {"ad_type": ["offer"]},
            "ranges": {},
            "location": {},
        },
        "extend": True,
        "listing_source": "direct-search" if page == 1 else "pagination",
    }

    # Category
    if "category" in params:
        payload["filters"]["category"] = {"id": params["category"][0]}

    # Text search
    if "text" in params:
        payload["filters"]["keywords"] = {"text": params["text"][0]}

    # Price range
    if "price" in params:
        price_str = params["price"][0]
        parts = price_str.split("-")
        if len(parts) == 2:
            price_range = {}
            if parts[0]:
                try:
                    price_range["min"] = int(parts[0])
                except ValueError:
                    pass
            if parts[1]:
                try:
                    price_range["max"] = int(parts[1])
                except ValueError:
                    pass
            if price_range:
                payload["filters"]["ranges"]["price"] = price_range

    # Owner type
    if "owner_type" in params:
        payload["owner_type"] = params["owner_type"][0]

    # Locations
    if "locations" in params:
        location_list = _parse_locations_string(params["locations"][0])
        if location_list:
            payload["filters"]["location"]["locations"] = location_list

    return payload


def _extract_api_listing(ad: dict) -> dict:
    """Convert a JSON API ad object into our standard listing format."""
    # Price (API returns price_cents)
    price = None
    if ad.get("price_cents"):
        price = ad["price_cents"] / 100
    elif ad.get("price"):
        price_list = ad["price"]
        if isinstance(price_list, list) and price_list:
            price = float(price_list[0])
        elif isinstance(price_list, (int, float)):
            price = float(price_list)

    # Photos
    images = ad.get("images", {})
    photo_urls = []
    if isinstance(images, dict):
        photo_urls = images.get("urls_large", []) or images.get("urls", []) or []
    elif isinstance(images, list):
        photo_urls = images

    # Location
    loc = ad.get("location", {})
    location_parts = []
    for key in ["city", "department_name", "region_name"]:
        val = loc.get(key)
        if val:
            location_parts.append(val)
    location = ", ".join(location_parts) if location_parts else None
    zipcode = loc.get("zipcode")
    if zipcode and location:
        location = f"{location} ({zipcode})"

    # Seller type
    owner = ad.get("owner", {})
    seller_type = owner.get("type", "particulier")
    if seller_type == "private":
        seller_type = "particulier"

    # Attributes
    attributes = {}
    for attr in ad.get("attributes", []):
        key = attr.get("key_label") or attr.get("key")
        value = attr.get("value_label") or attr.get("value")
        if key and value:
            attributes[key] = value

    list_id = str(ad.get("list_id", ""))
    return {
        "lbc_id": list_id,
        "url": ad.get("url") or f"https://www.leboncoin.fr/ad/{list_id}",
        "title": ad.get("subject"),
        "price": price,
        "description": ad.get("body"),
        "photo_urls": photo_urls,
        "location": location,
        "seller_type": seller_type,
        "seller_name": owner.get("name"),
        "attributes": attributes,
    }


def _execute_api_search(payload: dict) -> tuple[list[dict], int] | None:
    """Execute an API search with the given payload. Returns (listings, max_pages) or None."""
    session = _get_api_session()

    kwargs = {"timeout": 15}
    if _proxy:
        kwargs["proxies"] = {"https": _proxy, "http": _proxy}

    try:
        resp = session.post("https://api.leboncoin.fr/finder/search", json=payload, **kwargs)

        # Save cookies
        try:
            resp_cookies = {name: resp.cookies[name] for name in resp.cookies}
            if resp_cookies:
                _save_cookies(resp_cookies)
        except Exception:
            pass

        if resp.status_code == 403:
            log.warning("[scraper] API blocked (403)")
            return None

        if resp.status_code != 200:
            log.warning(f"[scraper] API returned status {resp.status_code}")
            return None

        data = resp.json()
        ads = data.get("ads", [])
        total = data.get("total", 0)
        max_pages = data.get("max_pages", (total + 34) // 35 if total else 1)

        listings = [_extract_api_listing(ad) for ad in ads]
        return listings, max_pages

    except Exception as e:
        log.warning(f"[scraper] API search failed: {e}")
        return None


def _search_via_api(url: str, page: int = 1) -> tuple[list[dict], int] | None:
    """Search via the JSON API using a URL. Returns (listings, total_pages) or None."""
    payload = _build_search_payload(url, page=page)
    return _execute_api_search(payload)


# --- Config-based search (structured queries) ---

def _parse_locations_string(locations_str: str) -> list[dict]:
    """Parse a leboncoin locations string into API location list."""
    location_list = []
    for loc in locations_str.split(","):
        loc_parts = loc.split("__")
        prefix = loc_parts[0].split("_")
        if len(prefix) >= 2 and len(prefix[0]) == 1:
            loc_type = prefix[0]
            loc_id = prefix[1]
            if loc_type == "d":
                location_list.append({"locationType": "department", "department_id": loc_id})
            elif loc_type == "r":
                location_list.append({"locationType": "region", "region_id": loc_id})
        elif len(loc_parts) >= 2:
            area_parts = loc_parts[1].split("_")
            area = {"lat": float(area_parts[0]), "lng": float(area_parts[1])}
            if len(area_parts) >= 3:
                area["default_radius"] = int(area_parts[2])
            if len(area_parts) >= 4:
                area["radius"] = int(area_parts[3])
            location_list.append({"locationType": "city", "area": area})
    return location_list


def _build_search_payload_from_config(query: dict, base: dict, page: int = 1, limit: int = 35) -> dict:
    """Build API payload from structured config (SEARCH_BASE + query dict)."""
    payload = {
        "limit": limit,
        "limit_alu": 3,
        "offset": limit * (page - 1),
        "sort_by": base.get("sort", "time"),
        "sort_order": base.get("order", "desc"),
        "filters": {
            "category": {"id": base["category"]},
            "enums": {"ad_type": ["offer"]},
            "keywords": {"text": query["text"]},
            "ranges": {
                "price": {
                    "min": base["price_min"],
                    "max": base["price_max"],
                }
            },
            "location": {},
        },
        "owner_type": base.get("owner_type", "private"),
        "extend": True,
        "listing_source": "direct-search" if page == 1 else "pagination",
    }

    if base.get("locations"):
        location_list = _parse_locations_string(base["locations"])
        if location_list:
            payload["filters"]["location"]["locations"] = location_list

    return payload


def _search_via_api_config(query: dict, base: dict, page: int = 1) -> tuple[list[dict], int] | None:
    """Search via JSON API using structured config. Returns (listings, max_pages) or None."""
    payload = _build_search_payload_from_config(query, base, page=page)
    return _execute_api_search(payload)


def scrape_search_from_config(query: dict, base: dict, max_pages: int = 3) -> list[dict]:
    """Search leboncoin using structured config (SEARCH_BASE + query).

    Same flow as scrape_search() but builds payload directly from config.
    Tries JSON API first, falls back to HTML scraping.

    Args:
        query: Dict with at least {"text": "search keywords"}.
        base: SEARCH_BASE dict with category, locations, price, etc.
        max_pages: Max pages to scrape.
    """
    keyword = query["text"]
    all_listings = []

    for page in range(1, max_pages + 1):
        def try_api():
            return _search_via_api_config(query, base, page=page)

        result = _fetch_with_retry(try_api)

        if result is not None:
            listings, total_available = result
            if not listings:
                if page == 1:
                    log.warning(f"[scraper] '{keyword}' returned 0 ads")
                break

            all_listings.extend(listings)
            total_pages = min(total_available, max_pages)
            log.info(f"[scraper] '{keyword}' page {page}/{total_pages}: {len(listings)} listings "
                     f"(total available: {total_available} pages)")

            if page >= total_available:
                break
        else:
            # Fallback: build a URL from config and try HTML scraping
            from urllib.parse import urlencode
            params = {
                "category": base["category"],
                "text": keyword,
                "price": f"{base['price_min']}-{base['price_max']}",
                "owner_type": base.get("owner_type", "private"),
                "sort": base.get("sort", "time"),
                "order": base.get("order", "desc"),
            }
            if base.get("locations"):
                params["locations"] = base["locations"]
            if page > 1:
                params["page"] = str(page)
            fallback_url = f"https://www.leboncoin.fr/recherche?{urlencode(params)}"

            log.info(f"[scraper] '{keyword}' API unavailable, trying HTML for page {page}")

            def try_html():
                return _fetch_page(fallback_url, proxy=_proxy)

            html = _fetch_with_retry(try_html)
            if html is None:
                log.warning(f"[scraper] '{keyword}' page {page} blocked on both API and HTML")
                break

            ads = _parse_search_data(html)
            if not ads:
                break

            page_listings = [_extract_search_listing(ad) for ad in ads]
            all_listings.extend(page_listings)
            log.info(f"[scraper] '{keyword}' page {page}: {len(ads)} listings via HTML")

        # Polite delay between pages
        if page < max_pages:
            time.sleep(random.uniform(2.0, 4.0))

    log.info(f"[scraper] '{keyword}' returned {len(all_listings)} total listings")
    return all_listings


# --- HTML-based search (fallback) ---

def _parse_search_data(html: str) -> list | None:
    """Extract listing ads from a search results page's __NEXT_DATA__."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None

    try:
        next_data = json.loads(script.string)
    except json.JSONDecodeError:
        return None

    return (next_data.get("props", {})
                     .get("pageProps", {})
                     .get("searchData", {})
                     .get("ads"))


def _extract_search_listing(ad: dict) -> dict:
    """Convert a search result __NEXT_DATA__ ad into our standard listing format."""
    data = _extract_listing_data(ad)

    list_id = str(ad.get("list_id", ""))
    data["lbc_id"] = list_id
    data["url"] = ad.get("url") or f"https://www.leboncoin.fr/ad/{list_id}"
    return data


def _get_total_pages_from_html(html: str) -> int:
    """Extract total pages from search __NEXT_DATA__."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return 1

    try:
        next_data = json.loads(script.string)
    except json.JSONDecodeError:
        return 1

    total = (next_data.get("props", {})
                      .get("pageProps", {})
                      .get("searchData", {})
                      .get("total", 0))
    return max(1, (total + 34) // 35) if total else 1


def _add_page_param(url: str, page: int) -> str:
    """Add or replace the page parameter in a search URL."""
    from urllib.parse import urlencode, urlunparse

    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["page"] = [str(page)]
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


# --- Public search API ---

def scrape_search(url: str, max_pages: int = 3) -> list[dict]:
    """Fetch a leboncoin search URL with pagination.

    Tries the JSON API first (cleaner, more reliable), falls back to HTML scraping.
    On DataDome block, auto-refreshes cookies from Chrome and retries.

    Args:
        url: Leboncoin search URL (copied from browser).
        max_pages: Max pages to scrape (default 3 = ~105 listings).
    """
    all_listings = []

    for page in range(1, max_pages + 1):
        # Try JSON API first
        def try_api():
            return _search_via_api(url, page=page)

        result = _fetch_with_retry(try_api)

        if result is not None:
            listings, total_available = result
            if not listings:
                if page == 1:
                    log.warning("[scraper] Search returned 0 ads")
                break

            all_listings.extend(listings)
            total_pages = min(total_available, max_pages)
            log.info(f"[scraper] Page {page}/{total_pages}: {len(listings)} listings via API "
                     f"(total available: {total_available} pages)")

            if page >= total_available:
                break
        else:
            # Fallback to HTML scraping
            log.info(f"[scraper] API unavailable, trying HTML scraping for page {page}")
            page_url = _add_page_param(url, page) if page > 1 else url

            def try_html():
                return _fetch_page(page_url, proxy=_proxy)

            html = _fetch_with_retry(try_html)
            if html is None:
                log.warning(f"[scraper] Page {page} blocked on both API and HTML")
                break

            ads = _parse_search_data(html)
            if not ads:
                break

            page_listings = [_extract_search_listing(ad) for ad in ads]
            all_listings.extend(page_listings)
            total_available = min(_get_total_pages_from_html(html), max_pages)
            log.info(f"[scraper] Page {page}: {len(ads)} listings via HTML")

            if page >= total_available:
                break

        # Polite delay between pages
        if page < max_pages:
            time.sleep(random.uniform(2.0, 4.0))

    log.info(f"[scraper] Search returned {len(all_listings)} total listings")
    return all_listings


# --- Individual listing ---

def _parse_next_data(html: str) -> dict | None:
    """Extract listing data from __NEXT_DATA__ JSON blob."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None

    try:
        next_data = json.loads(script.string)
    except json.JSONDecodeError:
        return None

    return (next_data.get("props", {})
                     .get("pageProps", {})
                     .get("ad"))


def _extract_listing_data(ad: dict) -> dict:
    """Convert a __NEXT_DATA__ ad object into our standard listing format."""
    title = ad.get("subject")

    price = None
    price_list = ad.get("price", [])
    if isinstance(price_list, list) and price_list:
        price = float(price_list[0])
    elif isinstance(price_list, (int, float)):
        price = float(price_list)

    photo_urls = []
    images = ad.get("images", {})
    if isinstance(images, dict):
        photo_urls = images.get("urls_large", []) or images.get("urls", []) or []
    elif isinstance(images, list):
        photo_urls = [u for u in images if isinstance(u, str)]

    location_data = ad.get("location", {})
    location_parts = []
    for key in ["city", "department_name", "region_name"]:
        val = location_data.get(key)
        if val:
            location_parts.append(val)
    location = ", ".join(location_parts) if location_parts else None
    zipcode = location_data.get("zipcode")
    if zipcode and location:
        location = f"{location} ({zipcode})"

    owner = ad.get("owner", {})
    seller_type = owner.get("type", "particulier")
    if seller_type == "private":
        seller_type = "particulier"

    attributes = {}
    for attr in ad.get("attributes", []):
        key = attr.get("key_label") or attr.get("key")
        value = attr.get("value_label") or attr.get("value")
        if key and value:
            attributes[key] = value

    return {
        "title": title,
        "price": price,
        "description": ad.get("body"),
        "photo_urls": photo_urls,
        "location": location,
        "seller_type": seller_type,
        "seller_name": owner.get("name"),
        "attributes": attributes,
    }


def _extract_from_html(html: str) -> dict | None:
    """Fallback extraction from rendered HTML."""
    soup = BeautifulSoup(html, "html.parser")

    def text(selector):
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else None

    title = text("[data-qa-id='adview_title']")
    if not title:
        return None

    price_text = text("[data-qa-id='adview_price']")
    price = None
    if price_text:
        cleaned = re.sub(r'[^\d,.]', '', price_text).replace(',', '.')
        try:
            price = float(cleaned)
        except ValueError:
            pass

    return {
        "title": title,
        "price": price,
        "description": text("[data-qa-id='adview_description_container']"),
        "photo_urls": [],
        "location": text("[data-qa-id='adview_location_informations']"),
        "seller_type": "pro" if soup.select_one("[data-qa-id='adview_pro_badge']") else "particulier",
        "seller_name": text("[data-qa-id='adview_contact_name']"),
        "attributes": {},
    }


def _normalize_url(url: str) -> str:
    """Convert any leboncoin listing URL to the /ad/ format."""
    m = re.search(r'leboncoin\.fr/(?:ad/)?([^/]+)/(\d+)', url)
    if m:
        category, listing_id = m.group(1), m.group(2)
        return f"https://www.leboncoin.fr/ad/{category}/{listing_id}"
    return url


def scrape_listing(url: str) -> dict | None:
    """Fetch a single listing page for full description.

    Auto-refreshes cookies from Chrome on block.
    Returns dict or None if all methods fail.
    """
    normalized = _normalize_url(url)

    def try_fetch():
        return _fetch_page(normalized, proxy=_proxy)

    html = _fetch_with_retry(try_fetch)
    if html is None:
        return None

    ad = _parse_next_data(html)
    if ad:
        data = _extract_listing_data(ad)
        log.info(f"[scraper] Scraped {url} via __NEXT_DATA__ — title={data['title']}")
        return data

    data = _extract_from_html(html)
    if data:
        log.info(f"[scraper] Scraped {url} via HTML fallback — title={data['title']}")
        return data

    log.warning(f"[scraper] Could not extract data from {url}")
    return None


# --- Setup utilities ---

def export_chrome_cookies():
    """Export leboncoin cookies from Chrome.

    Run: python -c "from scraper import export_chrome_cookies; export_chrome_cookies()"
    """
    try:
        import browser_cookie3
    except ImportError:
        print("Install browser_cookie3: pip install browser_cookie3")
        return

    try:
        cj = browser_cookie3.chrome(domain_name=".leboncoin.fr")
        cookies = {c.name: c.value for c in cj}
    except Exception as e:
        print(f"Error reading Chrome cookies: {e}")
        print("Make sure Chrome is closed, then retry.")
        return

    if not cookies:
        print("No leboncoin cookies found in Chrome.")
        return

    _save_cookies(cookies)
    datadome_keys = [k for k in cookies if "datadome" in k.lower()]
    print(f"Exported {len(cookies)} cookies ({len(datadome_keys)} DataDome)")
    print(f"Saved to {COOKIES_FILE}")


def import_cookies_manual(cookie_string: str):
    """Import cookies from a raw cookie header string.

    Run: python -c "from scraper import import_cookies_manual; import_cookies_manual('...')"
    """
    cookies = {}
    for pair in cookie_string.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, value = pair.split("=", 1)
            cookies[name.strip()] = value.strip()

    _save_cookies(cookies)
    datadome_keys = [k for k in cookies if "datadome" in k.lower()]
    print(f"Imported {len(cookies)} cookies ({len(datadome_keys)} DataDome)")
    print(f"Saved to {COOKIES_FILE}")


def check_lbc_access() -> bool:
    """Quick health check: can we reach the LBC search API?
    Returns True if API works, False if blocked.
    Tries refreshing cookies once on failure."""
    def try_api():
        return _search_via_api(
            "https://www.leboncoin.fr/recherche?category=55&text=velo&price=50-500",
            page=1,
        )

    result = _fetch_with_retry(try_api)
    return result is not None


def test_access():
    """Test if we can access leboncoin.

    Run: python -c "from scraper import test_access; test_access()"
    """
    print("Testing JSON API search...")
    result = _search_via_api(
        "https://www.leboncoin.fr/recherche?category=55&text=velo+route&price=50-1000",
        page=1,
    )
    if result:
        listings, total_pages = result
        print(f"API OK — {len(listings)} listings, {total_pages} total pages")
        if listings:
            print(f"  First: {listings[0]['price']}€ — {listings[0]['title'][:60]}")
        return

    print("API blocked. Trying HTML scraping...")
    html = _fetch_page("https://www.leboncoin.fr/recherche?category=55&text=velo+route")
    if html and not _is_blocked(html):
        ads = _parse_search_data(html)
        if ads:
            print(f"HTML OK — {len(ads)} listings")
            return

    print("BLOCKED — cookies need refreshing.")
    print("\nRefresh cookies:")
    print("  1. Browse leboncoin.fr in Chrome")
    print("  2. Close Chrome")
    print("  3. Run: python -c \"from scraper import export_chrome_cookies; export_chrome_cookies()\"")
    print("  4. Or: python -c \"from scraper import import_cookies_manual; import_cookies_manual('PASTE')\"")
