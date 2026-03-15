# DealSpotter

Monitor leboncoin bike listings and surface undervalued flip opportunities using AI evaluation.

## Setup

1. **Create a Python virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual credentials
   ```

   You need:
   - **Telegram Bot Token**: Create a bot via @BotFather on Telegram
   - **Telegram Chat ID**: Send a message to your bot, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - **Anthropic API Key**: From console.anthropic.com
   - **Search URLs**: Go to leboncoin.fr, set up your search (category, location, keywords, price range), copy the URL

3. **Set up leboncoin access (one-time):**

   Browse leboncoin.fr in Chrome, then export cookies:

   ```bash
   # Option A — auto-export (close Chrome first):
   python -c "from scraper import export_chrome_cookies; export_chrome_cookies()"

   # Option B — manual (from Chrome DevTools → Network → copy Cookie header):
   python -c "from scraper import import_cookies_manual; import_cookies_manual('PASTE_HERE')"
   ```

   Verify: `python -c "from scraper import test_access; test_access()"`

4. **Run:**
   ```bash
   python main.py
   ```

## How it works

1. Polls leboncoin search URLs every 5 minutes
2. Extracts all listings from search results (title, price, photos, location, condition)
3. Deduplicates by listing ID (SQLite)
4. Pre-filters on search data (price range, keywords, seller type) — no extra requests
5. Fetches full listing page for description (only for listings that pass pre-filter)
6. AI evaluation via Claude (text-only or vision with photos)
7. Calculates flip margin (buy price + fees + transport vs. resale estimate)
8. Sends Telegram alert for listings with margin >= 80€

## Telegram commands

- `/status` — Current pipeline status
- `/stats` — Weekly summary statistics

## Project structure

| File | Purpose |
|------|---------|
| `config.py` | All configuration and thresholds |
| `db.py` | SQLite database operations |
| `scraper.py` | curl_cffi scraper — search results + individual listings |
| `evaluator.py` | Tiered AI evaluation (text → vision) |
| `prompts.py` | LLM prompts in French |
| `flip_calculator.py` | Margin calculation with fees |
| `telegram_bot.py` | Telegram alerts and bot callbacks |
| `main.py` | Entry point and pipeline orchestration |
