import logging
import asyncio
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from config import (
    TELEGRAM_BOTS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ACTIVE_CATEGORIES, CATEGORIES,
)

log = logging.getLogger("dealspotter.telegram")

def _get_bot_credentials(category: str = None) -> tuple:
    """Get (token, chat_id) for a category. Falls back to bikes bot."""
    if category and category in TELEGRAM_BOTS:
        bot_cfg = TELEGRAM_BOTS[category]
        token = bot_cfg.get("token")
        chat_id = bot_cfg.get("chat_id")
        if token and chat_id:
            return token, chat_id
    # Fallback to bikes / default bot
    return TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    escaped = ""
    for char in str(text):
        if char in special_chars:
            escaped += f"\\{char}"
        else:
            escaped += char
    return escaped


def format_alert_message(listing: dict, evaluation: dict, margin: dict) -> str:
    """Format a rich alert message in MarkdownV2 for Telegram."""
    # Category-aware header
    category_label = evaluation.get("category_label", "🚲 Vélo")
    header_emoji = category_label.split(" ")[0] if category_label else "🔔"

    item_name = escape_md(evaluation.get("ai_item_name", listing.get("title", "Article")))
    location = escape_md(listing.get("location", "Inconnu"))
    buy_price = listing.get("price", 0)
    resale_min = margin.get("resale_min", 0)
    resale_max = margin.get("resale_max", 0)
    margin_mid = margin.get("margin_mid", 0)
    roi = margin.get("roi_percent", 0)
    reasoning = escape_md(evaluation.get("reasoning", ""))
    url = listing.get("url", "")

    # Pretty-print condition
    condition_raw = evaluation.get("ai_condition", "inconnu")
    condition_display = escape_md(condition_raw.replace("_", " ").capitalize())

    msg = (
        f"{header_emoji} *{item_name}*\n\n"
        f"📍 {location}\n\n"
        f"💰 Prix: {escape_md(str(int(buy_price)))}€\n"
        f"📈 Revente estimée: {escape_md(str(int(resale_min)))}–{escape_md(str(int(resale_max)))}€\n"
        f"✅ Marge nette: \\~{escape_md(str(int(margin_mid)))}€ \\(ROI {escape_md(str(roi))}%\\)\n"
        f"🔎 État: {condition_display}\n\n"
        f"Pourquoi: {reasoning}\n\n"
        f"🔗 [Voir l'annonce]({url})"
    )
    return msg


def build_inline_keyboard(lbc_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard buttons for a listing alert."""
    keyboard = [
        [
            InlineKeyboardButton("👍 Intéressé", callback_data=f"interested:{lbc_id}"),
            InlineKeyboardButton("👎 Passer", callback_data=f"pass:{lbc_id}"),
        ],
        [
            InlineKeyboardButton("📸 Analyser photos", callback_data=f"analyze:{lbc_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _send_alert_async(listing: dict, evaluation: dict, margin: dict):
    """Send a single alert message via Telegram (async)."""
    category = evaluation.get("category", "bikes")
    token, chat_id = _get_bot_credentials(category)
    bot = Bot(token=token)
    message = format_alert_message(listing, evaluation, margin)
    keyboard = build_inline_keyboard(listing["lbc_id"])

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        log.info(f"[telegram:{category}] {listing['lbc_id']} — Alert sent")
    except Exception as e:
        log.error(f"[telegram:{category}] {listing['lbc_id']} — Failed to send alert: {e}")
        raise


def send_telegram_alert(listing: dict, evaluation: dict, margin: dict):
    """Send alert (sync wrapper). Called from the main pipeline."""
    asyncio.run(_send_alert_async(listing, evaluation, margin))



async def _send_text_async(text: str, category: str = None):
    """Send a plain text message via Telegram."""
    token, chat_id = _get_bot_credentials(category)
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text=text)


def send_telegram_text(text: str, category: str = None):
    """Send a plain text message (sync wrapper)."""
    asyncio.run(_send_text_async(text, category))


# --- Callback handlers ---

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    import db
    import traceback

    query = update.callback_query
    await query.answer()

    data = query.data
    log.info(f"[telegram] Button pressed: {data}")

    try:
        action, lbc_id = data.split(":", 1)
    except ValueError:
        log.error(f"[telegram] Invalid callback data: {data}")
        return

    try:
        if action == "interested":
            db.update_status(lbc_id, "interested")
            db.update_feedback(lbc_id, "good")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("👍 Intéressé")

        elif action == "pass":
            db.update_status(lbc_id, "skipped", skip_reason="user_pass")
            db.update_feedback(lbc_id, "bad")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("👎 Passé")

        elif action == "analyze":
            await query.message.reply_text("📸 Analyse des photos en cours...")
            listing = db.get_listing(lbc_id)
            if listing:
                from evaluator import evaluate_with_vision
                category = listing.get("category", "bikes")
                result = evaluate_with_vision(listing, category)
                if result:
                    response = (
                        f"📸 Résultat analyse photos:\n\n"
                        f"Identifié: {result.get('item_name', 'N/A')}\n"
                        f"Marque: {result.get('brand', 'N/A')}\n"
                        f"Condition: {result.get('condition', 'N/A')}\n"
                        f"Confiance: {result.get('confidence', 'N/A')}\n"
                        f"Revente: {result.get('estimated_resale_min', '?')}–{result.get('estimated_resale_max', '?')}€"
                    )
                    await query.message.reply_text(response)
                else:
                    await query.message.reply_text("❌ Impossible d'analyser les photos")

        else:
            log.warning(f"[telegram] Unknown action: {action}")

    except Exception as e:
        log.error(f"[telegram] Button callback error: {e}\n{traceback.format_exc()}")
        try:
            await query.message.reply_text(f"❌ Erreur: {e}")
        except Exception:
            pass


def _make_status_handler(bot_categories: list):
    """Create a /status handler scoped to specific categories."""
    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        import db

        if len(bot_categories) == 1:
            cat = bot_categories[0]
            cat_config = CATEGORIES.get(cat, {})
            label = cat_config.get("label", cat)
            stats = db.get_stats(cat)
            detailed = db.get_detailed_stats(cat)

            total = stats["total"]
            evaluated = stats["evaluated"]
            eval_pct = f"{evaluated / total * 100:.0f}%" if total > 0 else "—"
            new_today = detailed.get("new_today", 0)
            alerts_today = db.get_alerts_today_count(cat)

            text = (
                f"{label} DealSpotter\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📬 Alertes aujourd'hui: {alerts_today}\n"
                f"📊 Nouvelles annonces: {new_today}\n\n"
                f"🔍 Total scanné: {total}\n"
                f"🤖 Évalué par IA: {evaluated} ({eval_pct})\n"
                f"✅ Total alertes: {stats['alerted']}\n"
                f"⭐ Intéressé: {stats['interested']}\n\n"
                f"📎 /stats pour le détail complet"
            )
        else:
            # Multi-category bot (both)
            alerts_today = db.get_alerts_today_count()
            stats = db.get_stats()
            detailed = db.get_detailed_stats()
            total = stats["total"]
            evaluated = stats["evaluated"]
            eval_pct = f"{evaluated / total * 100:.0f}%" if total > 0 else "—"
            new_today = detailed.get("new_today", 0)

            text = (
                f"🔎 DealSpotter\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📬 Alertes aujourd'hui: {alerts_today}\n"
                f"📊 Nouvelles annonces: {new_today}\n\n"
                f"🔍 Total scanné: {total}\n"
                f"🤖 Évalué par IA: {evaluated} ({eval_pct})\n"
                f"✅ Total alertes: {stats['alerted']}\n"
                f"⭐ Intéressé: {stats['interested']}\n"
            )
            text += "\n"
            for cat in bot_categories:
                cat_config = CATEGORIES.get(cat, {})
                cat_label = cat_config.get("label", cat)
                cat_stats = db.get_stats(cat)
                cat_alerts = db.get_alerts_today_count(cat)
                text += f"{cat_label}: {cat_stats['total']} scannées, {cat_alerts} alertes aujourd'hui\n"
            text += f"\n📎 /stats pour le détail complet"

        await update.message.reply_text(text)
    return status_command


def _make_stats_handler(bot_categories: list):
    """Create a /stats handler scoped to specific categories."""
    async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        import db

        text = f"📈 DealSpotter — Stats détaillées\n"
        text += f"━━━━━━━━━━━━━━━━━━\n"

        for cat in bot_categories:
            cat_config = CATEGORIES.get(cat, {})
            label = cat_config.get("label", cat)
            stats = db.get_detailed_stats(cat)
            total = stats["total"]
            evaluated = stats["evaluated"]
            alerted = stats["alerted"]

            if total == 0:
                text += f"\n{label}: aucune annonce encore\n"
                continue

            eval_pct = f"{evaluated / total * 100:.0f}%" if total > 0 else "—"
            alert_pct = f"{alerted / evaluated * 100:.1f}%" if evaluated > 0 else "—"

            text += f"\n{label}\n"
            text += (
                f"  🔄 {total} scannées → {evaluated} évaluées ({eval_pct}) → {alerted} alertées ({alert_pct})\n"
                f"  Nouvelles aujourd'hui: {stats.get('new_today', 0)}\n"
                f"  Intéressé: {stats.get('interested', 0)}\n"
            )

            if stats.get("margin_avg") and stats["margin_avg"] != 0:
                pos = stats["margin_positive"]
                neg = stats["margin_negative"]
                pos_pct = f"{pos / (pos + neg) * 100:.0f}%" if (pos + neg) > 0 else "—"
                text += (
                    f"  💰 Marge moy: {stats['margin_avg']}€ | "
                    f"Best: +{stats['margin_best']}€ | "
                    f"Rentables: {pos}/{pos + neg} ({pos_pct})\n"
                )

        # Skip reasons + feedback (across all shown categories)
        text += f"\n━━━━━━━━━━━━━━━━━━\n"
        if len(bot_categories) == 1:
            global_stats = db.get_detailed_stats(bot_categories[0])
        else:
            global_stats = db.get_detailed_stats()

        if global_stats.get("skip_reasons"):
            top = sorted(global_stats["skip_reasons"].items(), key=lambda x: -x[1])[:5]
            lines = "\n".join(f"  {reason}: {count}" for reason, count in top)
            text += f"🚫 Top filtres:\n{lines}\n"

        good = global_stats.get("interested", 0)
        bad = global_stats.get("good_feedback", 0) + global_stats.get("bad_feedback", 0)
        # Show user feedback summary
        total_feedback = good + bad
        if total_feedback > 0:
            text += f"\n👍 {good} intéressé  👎 {total_feedback - good} passé\n"
        else:
            text += f"\n⚠️ 0 feedback — utilise 👍/👎 sur les alertes!\n"

        await update.message.reply_text(text)
    return stats_command


def start_telegram_bots(categories: list = None):
    """Start Telegram bot(s) in background thread(s) for callback handling.

    Each unique bot token gets its own polling thread.
    If both categories share the same token, only one bot is started.
    """
    import threading

    if categories is None:
        categories = list(ACTIVE_CATEGORIES)

    # Group categories by bot token (avoid starting same bot twice)
    token_groups = {}  # token -> list of categories
    for cat in categories:
        token, chat_id = _get_bot_credentials(cat)
        if not token or not chat_id:
            log.warning(f"[telegram] No bot configured for '{cat}' — skipping")
            continue
        token_groups.setdefault(token, []).append(cat)

    for token, cats in token_groups.items():
        cat_labels = ", ".join(cats)

        async def run_bot(bot_token=token, bot_categories=cats):
            app = Application.builder().token(bot_token).build()
            app.add_handler(CallbackQueryHandler(button_callback))
            app.add_handler(CommandHandler("status", _make_status_handler(bot_categories)))
            app.add_handler(CommandHandler("stats", _make_stats_handler(bot_categories)))

            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            log.info(f"[telegram] Bot started for [{', '.join(bot_categories)}]")

            stop_event = asyncio.Event()
            await stop_event.wait()

        def thread_target(coro=run_bot):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(coro())
            except Exception as e:
                log.error(f"[telegram] Bot thread error: {e}")

        thread = threading.Thread(target=thread_target, daemon=True)
        thread.start()
        log.info(f"[telegram] Starting bot thread for [{cat_labels}]")


# Backward compat alias
def start_telegram_bot_async():
    """Start all configured Telegram bots."""
    start_telegram_bots()
