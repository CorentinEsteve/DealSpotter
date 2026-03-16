import sqlite3
import json
import logging
import os
from datetime import datetime, date

DB_PATH = "dealspotter.db"
OLD_DB_PATH = "bikeflip.db"
log = logging.getLogger("dealspotter.db")


def get_connection():
    """Get a SQLite connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate_old_db():
    """Rename bikeflip.db → dealspotter.db if old file exists."""
    if os.path.exists(OLD_DB_PATH) and not os.path.exists(DB_PATH):
        os.rename(OLD_DB_PATH, DB_PATH)
        log.info(f"Migrated {OLD_DB_PATH} → {DB_PATH}")


def _migrate_add_category():
    """Add category column if it doesn't exist (safe for existing data)."""
    conn = get_connection()
    cursor = conn.execute("PRAGMA table_info(listings)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "category" not in columns:
        conn.execute("ALTER TABLE listings ADD COLUMN category TEXT DEFAULT 'bikes'")
        conn.commit()
        log.info("Migration: added 'category' column to listings table")
    conn.close()


def init_db():
    """Create the listings table if it doesn't exist, run migrations."""
    _migrate_old_db()

    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            lbc_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            price REAL,
            description TEXT,
            photo_urls TEXT,
            location TEXT,
            seller_type TEXT,
            category TEXT DEFAULT 'bikes',
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            eval_tier INTEGER,
            ai_item_name TEXT,
            ai_brand TEXT,
            ai_model TEXT,
            ai_condition TEXT,
            ai_confidence REAL,
            estimated_resale_min REAL,
            estimated_resale_max REAL,
            flip_margin REAL,

            status TEXT DEFAULT 'new',
            skip_reason TEXT,
            alerted_at TIMESTAMP,
            user_feedback TEXT
        )
    """)
    conn.commit()
    conn.close()

    _migrate_add_category()
    log.info("Database initialized")


def listing_exists(lbc_id: str) -> bool:
    """Check if a listing already exists in the database. This is the dedup gate."""
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM listings WHERE lbc_id = ?", (lbc_id,)).fetchone()
    conn.close()
    return row is not None


def insert_listing(lbc_id: str, url: str, title: str = None, price: float = None,
                   description: str = None, photo_urls: list = None,
                   location: str = None, seller_type: str = None,
                   category: str = "bikes"):
    """Insert a new listing into the database. Ignores if already exists (belt-and-suspenders)."""
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO listings
        (lbc_id, url, title, price, description, photo_urls, location, seller_type, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lbc_id, url, title, price, description,
        json.dumps(photo_urls) if photo_urls else None,
        location, seller_type, category
    ))
    conn.commit()
    conn.close()


def update_listing_data(lbc_id: str, scraped_data: dict):
    """Enrich a listing with full data scraped from the listing page."""
    conn = get_connection()
    conn.execute("""
        UPDATE listings SET
            title = COALESCE(?, title),
            price = COALESCE(?, price),
            description = ?,
            photo_urls = ?,
            location = COALESCE(?, location),
            seller_type = COALESCE(?, seller_type)
        WHERE lbc_id = ?
    """, (
        scraped_data.get("title"),
        scraped_data.get("price"),
        scraped_data.get("description"),
        json.dumps(scraped_data.get("photo_urls")) if scraped_data.get("photo_urls") else None,
        scraped_data.get("location"),
        scraped_data.get("seller_type"),
        lbc_id,
    ))
    conn.commit()
    conn.close()


def update_evaluation(lbc_id: str, eval_tier: int, ai_item_name: str = None,
                      ai_brand: str = None, ai_model: str = None,
                      ai_condition: str = None, ai_confidence: float = None,
                      estimated_resale_min: float = None, estimated_resale_max: float = None,
                      flip_margin: float = None, status: str = "evaluated"):
    """Update a listing with evaluation results."""
    conn = get_connection()
    conn.execute("""
        UPDATE listings SET
            eval_tier = ?, ai_item_name = ?, ai_brand = ?, ai_model = ?,
            ai_condition = ?, ai_confidence = ?, estimated_resale_min = ?,
            estimated_resale_max = ?, flip_margin = ?, status = ?
        WHERE lbc_id = ?
    """, (
        eval_tier, ai_item_name, ai_brand, ai_model,
        ai_condition, ai_confidence, estimated_resale_min,
        estimated_resale_max, flip_margin, status, lbc_id
    ))
    conn.commit()
    conn.close()


def update_status(lbc_id: str, status: str, skip_reason: str = None):
    """Update the status of a listing."""
    conn = get_connection()
    if skip_reason:
        conn.execute("UPDATE listings SET status = ?, skip_reason = ? WHERE lbc_id = ?",
                     (status, skip_reason, lbc_id))
    else:
        conn.execute("UPDATE listings SET status = ? WHERE lbc_id = ?", (status, lbc_id))
    conn.commit()
    conn.close()


def mark_alerted(lbc_id: str):
    """Mark a listing as alerted with timestamp."""
    conn = get_connection()
    conn.execute("UPDATE listings SET status = 'alerted', alerted_at = ? WHERE lbc_id = ?",
                 (datetime.now().isoformat(), lbc_id))
    conn.commit()
    conn.close()


def update_feedback(lbc_id: str, feedback: str):
    """Update user feedback from Telegram buttons."""
    conn = get_connection()
    conn.execute("UPDATE listings SET user_feedback = ? WHERE lbc_id = ?", (feedback, lbc_id))
    conn.commit()
    conn.close()


def get_alerts_today_count(category: str = None) -> int:
    """Count how many alerts were sent today, optionally filtered by category."""
    conn = get_connection()
    today = date.today().isoformat()
    if category:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM listings "
            "WHERE alerted_at IS NOT NULL AND alerted_at >= ? AND category = ?",
            (today, category)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM listings WHERE alerted_at IS NOT NULL AND alerted_at >= ?",
            (today,)
        ).fetchone()
    conn.close()
    return row["cnt"]


def get_pending_listings(category: str = None) -> list:
    """Get listings with status='new' awaiting evaluation."""
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM listings WHERE status = 'new' AND category = ? ORDER BY first_seen_at",
            (category,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM listings WHERE status = 'new' ORDER BY first_seen_at"
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_listing(lbc_id: str) -> dict:
    """Get a single listing by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM listings WHERE lbc_id = ?", (lbc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_stats(category: str = None) -> dict:
    """Get summary statistics, optionally filtered by category."""
    conn = get_connection()
    where = " AND category = ?" if category else ""
    params = (category,) if category else ()

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE 1=1{where}", params).fetchone()["cnt"]
    evaluated = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'evaluated'{where}", params).fetchone()["cnt"]
    alerted = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'alerted'{where}", params).fetchone()["cnt"]
    skipped = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'skipped'{where}", params).fetchone()["cnt"]
    interested = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'interested'{where}", params).fetchone()["cnt"]
    good_feedback = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE user_feedback = 'good'{where}", params).fetchone()["cnt"]
    bad_feedback = conn.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE user_feedback = 'bad'{where}", params).fetchone()["cnt"]
    conn.close()
    return {
        "total": total,
        "evaluated": evaluated,
        "alerted": alerted,
        "skipped": skipped,
        "interested": interested,
        "good_feedback": good_feedback,
        "bad_feedback": bad_feedback,
    }


def get_detailed_stats(category: str = None) -> dict:
    """Get detailed statistics including skip reasons and margin distribution."""
    conn = get_connection()

    base = get_stats(category)
    where = " AND category = ?" if category else ""
    params = (category,) if category else ()

    # Skip reason breakdown
    rows = conn.execute(
        f"SELECT skip_reason, COUNT(*) as cnt FROM listings "
        f"WHERE status = 'skipped' AND skip_reason IS NOT NULL{where} "
        f"GROUP BY skip_reason ORDER BY cnt DESC",
        params
    ).fetchall()
    base["skip_reasons"] = {row["skip_reason"]: row["cnt"] for row in rows}

    # Margin distribution for evaluated listings
    margin_rows = conn.execute(
        f"SELECT flip_margin FROM listings WHERE flip_margin IS NOT NULL{where} ORDER BY flip_margin DESC",
        params
    ).fetchall()
    margins = [row["flip_margin"] for row in margin_rows]
    if margins:
        base["margin_avg"] = round(sum(margins) / len(margins), 1)
        base["margin_best"] = round(max(margins), 1)
        base["margin_worst"] = round(min(margins), 1)
        base["margin_positive"] = sum(1 for m in margins if m > 0)
        base["margin_negative"] = sum(1 for m in margins if m <= 0)
    else:
        base["margin_avg"] = 0
        base["margin_best"] = 0
        base["margin_worst"] = 0
        base["margin_positive"] = 0
        base["margin_negative"] = 0

    # Today's activity
    today = date.today().isoformat()
    base["new_today"] = conn.execute(
        f"SELECT COUNT(*) as cnt FROM listings WHERE first_seen_at >= ?{where}",
        (today, *params)
    ).fetchone()["cnt"]

    # Price range of evaluated listings
    price_row = conn.execute(
        f"SELECT MIN(price) as min_p, MAX(price) as max_p, AVG(price) as avg_p "
        f"FROM listings WHERE status IN ('evaluated', 'alerted'){where}",
        params
    ).fetchone()
    base["price_min"] = round(price_row["min_p"] or 0)
    base["price_max"] = round(price_row["max_p"] or 0)
    base["price_avg"] = round(price_row["avg_p"] or 0)

    conn.close()
    return base
