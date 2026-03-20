import os
from dotenv import load_dotenv

load_dotenv()

# --- Environment variables ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# --- Per-category Telegram bots ---
TELEGRAM_BOTS = {
    "bikes": {
        "token": os.getenv("TELEGRAM_BOT_TOKEN_BIKES", os.getenv("TELEGRAM_BOT_TOKEN")),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_BIKES", os.getenv("TELEGRAM_CHAT_ID")),
    },
    "furniture": {
        "token": os.getenv("TELEGRAM_BOT_TOKEN_FURNITURE"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_FURNITURE"),
    },
    "motos": {
        "token": os.getenv("TELEGRAM_BOT_TOKEN_MOTOS"),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID_MOTOS"),
    },
}

# Backward compat
TELEGRAM_BOT_TOKEN = TELEGRAM_BOTS["bikes"]["token"]
TELEGRAM_CHAT_ID = TELEGRAM_BOTS["bikes"]["chat_id"]

# --- Legacy: comma-separated search URLs (kept for backward compat) ---
SEARCH_URLS = [u.strip() for u in os.getenv("SEARCH_URLS", "").split(",") if u.strip()]

# --- Polling ---
POLL_INTERVAL_SECONDS = 300       # 5 minutes

# --- Evaluation tiers ---
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"

# --- Scraper ---
SCRAPE_DELAY_MIN = 2.0            # Min seconds between requests
SCRAPE_DELAY_MAX = 5.0            # Max seconds between requests
MAX_SCRAPES_PER_HOUR = 30         # Safety cap
MAX_SEARCH_PAGES = 3              # Max pages per search URL (35 listings/page)

# --- Telegram ---

# ═══════════════════════════════════════════════════════════════════
# MULTI-CATEGORY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

ACTIVE_CATEGORIES = ["bikes", "furniture", "motos"]

CATEGORIES = {
    # ── BIKES ──────────────────────────────────────────────────────
    "bikes": {
        "label": "🚲 Vélo",
        "lbc_category": "55",
        "search_base": {
            "locations": "Sartrouville_78500__48.94217_2.16285_3254_10000",
            "price_min": 200,
            "price_max": 2000,
            "owner_type": "private",
            "sort": "time",
            "order": "desc",
        },
        "search_queries": [
            {"text": "velo course", "tier": "A"},
            {"text": "velo route", "tier": "A"},
            {"text": "velo gravel", "tier": "A"},
            {"text": "velo course vintage", "tier": "B"},
            {"text": "velo route carbone", "tier": "B"},
        ],
        "queries_per_cycle": {"A": None, "B": 1},
        "skip_keywords": [
            # Electric / non-target
            "électrique", "vae", "e-bike", "ebike", "trottinette",
            # Kids
            "enfant", "enfants", "junior",
            # Non-bikes
            "appartement", "recherche", "cherche", "échange", "troc",
            # Parts / broken
            "pièces détachées", "pour pièce", "hs",
            "volé", "cassé", "accidenté", "épave",
            # Wrong bike types
            "vtt", "bmx", "pliant", "pliable", "cargo", "tandem",
            # Indoor / accessories
            "home trainer", "hometrainer", "rouleaux",
            "accessoire", "accessoires", "casque", "chaussures", "maillot",
            # Bundle lots
            "lot de",
        ],
        "junk_indicators": [
            "pour pièce", "à restaurer entièrement", "hors service",
            "ne fonctionne plus", "cadre fissuré", "cadre cassé",
            "sans roue", "manque roue", "sans selle",
        ],
        "skip_seller_types": ["pro"],
        "min_price": 50,
        "max_price": 2000,
        "max_distance_km": 40,
        "min_flip_margin": 50,
        "platform_fee_pct": 0.08,
        "transport_cost": 10,
        "time_cost": 15,
        "vision_confidence_threshold": 0.6,
    },

    # ── FURNITURE ──────────────────────────────────────────────────
    "furniture": {
        "label": "🪑 Mobilier design",
        "lbc_category": "19",  # Ameublement
        "search_base": {
            "locations": "Sartrouville_78500__48.94217_2.16285_3254_10000",
            "price_min": 5,
            "price_max": 250,
            "owner_type": "private",
            "sort": "time",
            "order": "desc",
        },
        "search_queries": [
            {"text": "chaise design vintage", "tier": "A"},
            {"text": "lampe vintage", "tier": "A"},
            {"text": "miroir vintage", "tier": "A"},
            {"text": "table basse vintage", "tier": "A"},
            {"text": "lampadaire vintage", "tier": "B"},
            {"text": "tabouret vintage bois", "tier": "B"},
            {"text": "fauteuil vintage", "tier": "B"},
            {"text": "luminaire ancien", "tier": "B"},
            {"text": "lampe tiffany", "tier": "B"},
            {"text": "lampe vitrail", "tier": "B"},
        ],
        "queries_per_cycle": {"A": None, "B": 3},
        "skip_keywords": [
            # Too large / out of scope
            "canapé", "lit", "matelas", "armoire", "bibliothèque",
            # Wrong rooms
            "cuisine", "salle de bain",
            # Mass market
            "ikea", "conforama", "but", "maison du monde",
            # Kids
            "enfant", "bébé", "jouet",
            # Non-items
            "recherche", "cherche", "échange",
        ],
        "junk_indicators": [
            "à restaurer entièrement", "hors service",
            "cassé", "fissuré", "manque pied", "taché",
            "moisi", "rongé", "vermoulure",
        ],
        "skip_seller_types": ["pro"],
        "min_price": 5,
        "max_price": 250,
        "max_distance_km": 40,
        "min_flip_margin": 40,
        "platform_fee_pct": 0.08,
        "transport_cost": 15,
        "time_cost": 15,
        "vision_confidence_threshold": 0.5,
    },

    # ── MOTOS (A2) ─────────────────────────────────────────────────
    "motos": {
        "label": "🏍️ Moto A2",
        "lbc_category": "3",  # Motos
        "search_base": {
            "locations": "Sartrouville_78500__48.94217_2.16285_3254_25000",
            "price_min": 500,
            "price_max": 7000,
            "owner_type": "private",
            "sort": "time",
            "order": "desc",
        },
        "search_queries": [
            # Generic — catch most listings, AI filters A2 compatibility
            {"text": "moto A2", "tier": "A"},
            {"text": "moto roadster", "tier": "A"},
            {"text": "moto trail", "tier": "B"},
            {"text": "moto custom", "tier": "B"},
            {"text": "moto sportive", "tier": "B"},
            {"text": "moto naked", "tier": "B"},
        ],
        "queries_per_cycle": {"A": None, "B": 2},
        "skip_keywords": [
            # Wrong vehicles
            "scooter", "quad", "50cc", "125cc", "mobylette", "cyclomoteur",
            "trottinette", "vélo",
            # Parts / broken
            "pièces détachées", "pour pièce", "hs", "épave",
            "volé", "accidenté", "non roulant",
        ],
        "junk_indicators": [
            "pour pièce", "ne démarre pas", "ne roule pas",
            "moteur hs", "cadre tordu", "accidentée",
            "carte grise perdue", "sans carte grise",
        ],
        "skip_seller_types": ["pro"],
        "min_price": 500,
        "max_price": 7000,
        "max_distance_km": 40,
        "min_flip_margin": 100,
        "platform_fee_pct": 0.0,
        "transport_cost": 50,
        "time_cost": 50,
        "vision_confidence_threshold": 0.5,
    },
}

# ═══════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE ALIASES (point to "bikes" category)
# Used by any code that still imports flat constants.
# ═══════════════════════════════════════════════════════════════════
_bikes = CATEGORIES["bikes"]

SEARCH_BASE = {**_bikes["search_base"], "category": _bikes["lbc_category"]}
SEARCH_QUERIES = _bikes["search_queries"]
QUERIES_PER_CYCLE = _bikes["queries_per_cycle"]

MIN_FLIP_MARGIN_EUR = _bikes["min_flip_margin"]
MIN_PRICE_EUR = _bikes["min_price"]
MAX_PRICE_EUR = _bikes["max_price"]
MAX_DISTANCE_KM = _bikes["max_distance_km"]
VISION_CONFIDENCE_THRESHOLD = _bikes["vision_confidence_threshold"]

PLATFORM_FEE_PERCENT = _bikes["platform_fee_pct"]
TRANSPORT_COST_EUR = _bikes["transport_cost"]
TIME_COST_EUR = _bikes["time_cost"]

SKIP_KEYWORDS = _bikes["skip_keywords"]
SKIP_SELLER_TYPES = _bikes["skip_seller_types"]
JUNK_INDICATORS = _bikes["junk_indicators"]
