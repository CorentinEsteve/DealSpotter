import logging
import asyncio
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, QUIET_HOURS_START, QUIET_HOURS_END

log = logging.getLogger("bikeflip.telegram")

# Queue for alerts generated during quiet hours
_alert_queue = []


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


def is_quiet_hours() -> bool:
    """Check if current time is within quiet hours."""
    hour = datetime.now().hour
    if QUIET_HOURS_START > QUIET_HOURS_END:
        # Wraps midnight: e.g. 23:00 to 07:00
        return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END
    else:
        return QUIET_HOURS_START <= hour < QUIET_HOURS_END


def format_alert_message(listing: dict, evaluation: dict, margin: dict) -> str:
    """Format a rich alert message in MarkdownV2 for Telegram."""
    item_name = escape_md(evaluation.get("ai_item_name", listing.get("title", "Vélo")))
    location = escape_md(listing.get("location", "Inconnu"))
    buy_price = listing.get("price", 0)
    resale_min = margin.get("resale_min", 0)
    resale_max = margin.get("resale_max", 0)
    margin_mid = margin.get("margin_mid", 0)
    roi = margin.get("roi_percent", 0)
    condition = escape_md(evaluation.get("ai_condition", "inconnu"))
    reasoning = escape_md(evaluation.get("reasoning", ""))
    url = listing.get("url", "")

    msg = (
        f"🚲 *OPPORTUNITÉ FLIP*\n\n"
        f"*{item_name}*\n"
        f"📍 {location}\n\n"
        f"💰 Achat: {escape_md(str(int(buy_price)))}€\n"
        f"📈 Revente estimée: {escape_md(str(int(resale_min)))}–{escape_md(str(int(resale_max)))}€\n"
        f"✅ Marge nette: \\~{escape_md(str(int(margin_mid)))}€ \\(ROI {escape_md(str(roi))}%\\)\n\n"
        f"État: {condition}\n"
        f"Pourquoi: {reasoning}\n\n"
        f"🔗 [Voir l'annonce]({url})"
    )
    return msg


def build_inline_keyboard(lbc_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard buttons for a listing alert."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Intéressé", callback_data=f"interested:{lbc_id}"),
            InlineKeyboardButton("❌ Passer", callback_data=f"skip:{lbc_id}"),
        ],
        [
            InlineKeyboardButton("📸 Analyser photos", callback_data=f"analyze:{lbc_id}"),
        ],
        [
            InlineKeyboardButton("👍", callback_data=f"good:{lbc_id}"),
            InlineKeyboardButton("👎", callback_data=f"bad:{lbc_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _send_alert_async(listing: dict, evaluation: dict, margin: dict):
    """Send a single alert message via Telegram (async)."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    message = format_alert_message(listing, evaluation, margin)
    keyboard = build_inline_keyboard(listing["lbc_id"])

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        log.info(f"[telegram] {listing['lbc_id']} — Alert sent")
    except Exception as e:
        log.error(f"[telegram] {listing['lbc_id']} — Failed to send alert: {e}")
        raise


def send_telegram_alert(listing: dict, evaluation: dict, margin: dict):
    """Send alert (sync wrapper). Called from the main pipeline."""
    asyncio.run(_send_alert_async(listing, evaluation, margin))


def queue_alert(listing: dict, evaluation: dict, margin: dict):
    """Queue an alert for later sending (during quiet hours)."""
    _alert_queue.append((listing, evaluation, margin))
    log.info(f"[telegram] {listing['lbc_id']} — Queued (quiet hours)")


def send_queued_alerts():
    """Send all queued alerts. Called when quiet hours end."""
    if not _alert_queue:
        return
    log.info(f"[telegram] Sending {len(_alert_queue)} queued alerts")
    for listing, evaluation, margin in _alert_queue:
        try:
            send_telegram_alert(listing, evaluation, margin)
        except Exception as e:
            log.error(f"[telegram] Failed to send queued alert: {e}")
    _alert_queue.clear()


async def _send_text_async(text: str):
    """Send a plain text message via Telegram."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)


def send_telegram_text(text: str):
    """Send a plain text message (sync wrapper)."""
    asyncio.run(_send_text_async(text))


# --- Callback handlers (for T12) ---

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
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Marqué comme intéressé")

        elif action == "skip":
            db.update_status(lbc_id, "skipped", skip_reason="user_skip")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"❌ Passé")

        elif action == "analyze":
            await query.message.reply_text("📸 Analyse des photos en cours...")
            listing = db.get_listing(lbc_id)
            if listing:
                from evaluator import evaluate_with_vision
                result = evaluate_with_vision(listing)
                if result:
                    response = (
                        f"📸 Résultat analyse photos:\n\n"
                        f"Identifié: {result.get('ai_item_name', 'N/A')}\n"
                        f"Marque: {result.get('brand', 'N/A')}\n"
                        f"Matériau: {result.get('frame_material', 'N/A')}\n"
                        f"Groupe: {result.get('component_group', 'N/A')}\n"
                        f"Condition: {result.get('condition', 'N/A')}\n"
                        f"Confiance: {result.get('confidence', 'N/A')}\n"
                        f"Revente: {result.get('estimated_resale_min', '?')}–{result.get('estimated_resale_max', '?')}€"
                    )
                    await query.message.reply_text(response)
                else:
                    await query.message.reply_text("❌ Impossible d'analyser les photos")

        elif action == "good":
            db.update_feedback(lbc_id, "good")
            await query.message.reply_text("👍 Feedback enregistré — bon deal")

        elif action == "bad":
            db.update_feedback(lbc_id, "bad")
            await query.message.reply_text("👎 Feedback enregistré — mauvais deal")

        else:
            log.warning(f"[telegram] Unknown action: {action}")

    except Exception as e:
        log.error(f"[telegram] Button callback error: {e}\n{traceback.format_exc()}")
        try:
            await query.message.reply_text(f"❌ Erreur: {e}")
        except Exception:
            pass


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    import db
    from datetime import date

    pending = len(db.get_pending_listings())
    alerts_today = db.get_alerts_today_count()
    stats = db.get_stats()

    text = (
        f"📊 Status\n\n"
        f"En attente: {pending}\n"
        f"Alertes aujourd'hui: {alerts_today}/{10}\n"
        f"Total traité: {stats['total']}\n"
        f"Skippé: {stats['skipped']}\n"
        f"Alerté: {stats['alerted']}\n"
        f"Intéressé: {stats['interested']}"
    )
    await update.message.reply_text(text)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command with detailed breakdown."""
    import db

    stats = db.get_detailed_stats()

    # Skip reasons summary (top 5)
    skip_lines = ""
    if stats.get("skip_reasons"):
        top = sorted(stats["skip_reasons"].items(), key=lambda x: -x[1])[:5]
        skip_lines = "\n".join(f"  • {reason}: {count}" for reason, count in top)
        skip_lines = f"\n\n🚫 Top raisons de skip:\n{skip_lines}"

    # Margin info
    margin_lines = ""
    if stats.get("margin_avg"):
        margin_lines = (
            f"\n\n💰 Marges (annonces évaluées):\n"
            f"  Moyenne: {stats['margin_avg']}€\n"
            f"  Meilleure: {stats['margin_best']}€\n"
            f"  Pire: {stats['margin_worst']}€\n"
            f"  Positives: {stats['margin_positive']} | Négatives: {stats['margin_negative']}"
        )

    # Price range
    price_lines = ""
    if stats.get("price_avg"):
        price_lines = (
            f"\n\n🏷️ Prix évalués: {stats['price_min']}–{stats['price_max']}€ "
            f"(moy. {stats['price_avg']}€)"
        )

    text = (
        f"📈 Statistiques DealSpotter\n\n"
        f"📊 Pipeline:\n"
        f"  Total annonces: {stats['total']}\n"
        f"  Nouvelles aujourd'hui: {stats['new_today']}\n"
        f"  Évaluées: {stats['evaluated']}\n"
        f"  Alertées: {stats['alerted']}\n"
        f"  Skippées: {stats['skipped']}\n"
        f"  Intéressé: {stats['interested']}"
        f"{skip_lines}{margin_lines}{price_lines}\n\n"
        f"👍👎 Feedback:\n"
        f"  Bon deal: {stats['good_feedback']} | Mauvais: {stats['bad_feedback']}"
    )
    await update.message.reply_text(text)


def start_telegram_bot_async():
    """Start the Telegram bot in a background thread for callback handling.

    Uses asyncio directly instead of run_polling() to avoid signal handler
    issues (signal handlers can only be set in the main thread).
    """
    import asyncio
    import threading

    async def run_bot():
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CallbackQueryHandler(button_callback))
        app.add_handler(CommandHandler("status", status_command))
        app.add_handler(CommandHandler("stats", stats_command))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("[telegram] Bot started, listening for callbacks")

        # Keep running until the thread is killed (daemon thread)
        stop_event = asyncio.Event()
        await stop_event.wait()

    def thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_bot())
        except Exception as e:
            log.error(f"[telegram] Bot thread error: {e}")

    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()
