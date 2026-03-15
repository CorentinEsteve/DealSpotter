"""Quick diagnostic: does the Telegram bot listener work?
Run this standalone — it ONLY starts the bot listener, nothing else.
Then send /status or /stats in your Telegram chat.
Press Ctrl+C to stop.
"""
import asyncio
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f">>> RECEIVED COMMAND from chat_id={update.effective_chat.id}")
    await update.message.reply_text(f"✅ Bot is alive! Your chat_id = {update.effective_chat.id}")

async def main():
    print(f"Bot token: {TELEGRAM_BOT_TOKEN[:10]}...{TELEGRAM_BOT_TOKEN[-5:]}")
    print(f"Expected chat_id: {TELEGRAM_CHAT_ID}")
    print("Starting bot... Send /test, /status, or /stats in Telegram")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("status", test_command))
    app.add_handler(CommandHandler("stats", test_command))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    print("✅ Polling started — waiting for messages...")

    stop = asyncio.Event()
    await stop.wait()

if __name__ == "__main__":
    asyncio.run(main())
