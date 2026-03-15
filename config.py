import os
from dotenv import load_dotenv

load_dotenv()

# --- Environment variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# --- Legacy: comma-separated search URLs (kept for backward compat) ---
SEARCH_URLS = [u.strip() for u in os.getenv("SEARCH_URLS", "").split(",") if u.strip()]

# --- Structured search config (replaces SEARCH_URLS) ---
SEARCH_BASE = {
    "category": "55",  # Vélos
    "locations": "Sartrouville_78500__48.94217_2.16285_3254_5000",
    "price_min": 50,
    "price_max": 1000,
    "owner_type": "private",
    "sort": "time",
    "order": "desc",
}

SEARCH_QUERIES = [
    # Tier A: generic — every cycle
    {"text": "velo course", "tier": "A"},
    {"text": "velo route", "tier": "A"},
    {"text": "velo gravel", "tier": "A"},
    # Tier B: brand-specific — rotate 4 per cycle
    {"text": "trek velo", "tier": "B"},
    {"text": "specialized velo", "tier": "B"},
    {"text": "giant velo", "tier": "B"},
    {"text": "canyon velo", "tier": "B"},
    {"text": "cannondale velo", "tier": "B"},
    {"text": "lapierre velo", "tier": "B"},
    {"text": "scott velo", "tier": "B"},
    {"text": "orbea velo", "tier": "B"},
    {"text": "bmc velo", "tier": "B"},
    {"text": "triban", "tier": "B"},
    {"text": "van rysel", "tier": "B"},
    {"text": "btwin", "tier": "B"},
    # Tier C: vintage — rotate 1 per cycle
    {"text": "velo peugeot course", "tier": "C"},
    {"text": "velo motobecane", "tier": "C"},
    {"text": "velo gitane course", "tier": "C"},
    {"text": "velo mercier course", "tier": "C"},
]

# How many queries per tier per cycle (None = all)
QUERIES_PER_CYCLE = {"A": None, "B": 4, "C": 1}

# --- Thresholds ---
MIN_FLIP_MARGIN_EUR = 50          # Minimum expected net profit to trigger alert
MIN_PRICE_EUR = 50                # Ignore listings below this
MAX_PRICE_EUR = 1000              # Ignore listings above this
MAX_DISTANCE_KM = 40              # Max pickup distance from Sartrouville
VISION_CONFIDENCE_THRESHOLD = 0.6 # Below this, skip the listing

# --- Costs (for flip margin calculation) ---
PLATFORM_FEE_PERCENT = 0.08       # ~8% leboncoin selling fee
TRANSPORT_COST_EUR = 10           # Average gas/tolls per pickup
TIME_COST_EUR = 15                # ~1h for pickup + relist + handover

# --- Polling ---
POLL_INTERVAL_SECONDS = 300       # 5 minutes

# --- Evaluation tiers ---
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

# --- Pre-filter keywords (French — all leboncoin listings are in French) ---
SKIP_KEYWORDS = [
    # Electric / non-target
    "électrique", "vae", "e-bike", "ebike", "trottinette",
    # Kids
    "enfant", "enfants", "junior", "fille", "garçon",
    # Non-bikes
    "appartement", "recherche", "cherche", "échange", "troc",
    # Parts / broken
    "pièces détachées", "pièces", "pour pièce", "hs",
    "volé", "cassé", "accidenté", "épave",
    # Wrong bike types
    "vtt", "bmx", "pliant", "pliable", "cargo", "tandem",
    # Indoor / accessories
    "home trainer", "hometrainer", "rouleaux",
    "accessoire", "accessoires", "casque", "chaussures", "maillot",
    # Bundle lots
    "lot de",
]
SKIP_SELLER_TYPES = ["pro"]  # Skip professional sellers ("particulier" only)

# --- Junk indicators in French (instant skip) ---
JUNK_INDICATORS = [
    "pour pièce", "à restaurer entièrement", "hors service",
    "ne fonctionne plus", "cadre fissuré", "cadre cassé",
    "sans roue", "manque roue", "sans selle",
]

# --- Positive condition keywords in French (boost confidence in Tier 1) ---
GOOD_CONDITION_FR = ["comme neuf", "très bon état", "excellent état",
                     "neuf", "jamais utilisé", "peu roulé", "peu servi",
                     "état impeccable", "parfait état", "quasi neuf"]

# --- Bike brands with strong resale value ---
HIGH_VALUE_BRANDS = [
    # Modern performance
    "trek", "specialized", "giant", "canyon", "cannondale",
    "bmc", "scott", "cube", "orbea", "lapierre", "merida",
    "focus", "felt", "ribble",
    # Premium
    "cervélo", "pinarello", "bianchi", "look", "time", "wilier",
    "colnago", "factor", "3t",
    # Decathlon ecosystem
    "btwin", "b'twin", "van rysel", "triban", "rockrider", "decathlon",
    # Vintage (high flip potential in urban markets)
    "peugeot", "motobécane", "motobecane", "gitane", "mercier",
    "lejeune", "helyett", "bertin",
]

# --- Scraper ---
SCRAPE_DELAY_MIN = 2.0            # Min seconds between requests
SCRAPE_DELAY_MAX = 5.0            # Max seconds between requests
MAX_SCRAPES_PER_HOUR = 30         # Safety cap
MAX_SEARCH_PAGES = 3              # Max pages per search URL (35 listings/page)

# --- Telegram ---
MAX_ALERTS_PER_DAY = 10           # Avoid notification fatigue
QUIET_HOURS_START = 23            # No alerts between 23:00 and 07:00
QUIET_HOURS_END = 7
