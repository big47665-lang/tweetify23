#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Uses Nitter (free Twitter mirror) - no API key needed, no credits, no limits
- Fetches tweets by category (funny, political, news, gaming, unhinged)
- Persian and English only
- Posts to Telegram groups where bot is admin
"""

import os
import json
import logging
import random
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
RAW_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")
CHAT_IDS = [c.strip() for c in RAW_CHAT_IDS.split(",") if c.strip()]
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", 600))
SEEN_IDS_FILE = Path("seen_tweet_ids.json")

# ─── Nitter instances (fallback list if one is down) ─────────────────────────
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
]

# ─── Search queries per category ─────────────────────────────────────────────
CATEGORIES = {
    "😂 Funny": [
        ("funny OR lmao OR lol OR hilarious", "en"),
        ("خنده OR بامزه OR خندیدم", "fa"),
    ],
    "🏛️ Political": [
        ("politics OR government OR president OR election", "en"),
        ("سیاست OR دولت OR انتخابات", "fa"),
    ],
    "📰 News": [
        ("breaking OR urgent OR developing", "en"),
        ("خبر فوری OR اخبار OR گزارش", "fa"),
    ],
    "🎮 Gaming": [
        ("gaming OR PlayStation OR Xbox OR Nintendo", "en"),
        ("بازی OR گیمینگ OR پلی استیشن", "fa"),
    ],
    "🤦 Unhinged": [
        ("ratio OR skill issue OR touch grass OR wild", "en"),
        ("باورم نمیشه OR عجیبه OR چی گفت", "fa"),
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ─── Seen IDs ─────────────────────────────────────────────────────────────────

def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-5000:]))


# ─── Nitter scraper ───────────────────────────────────────────────────────────

def get_working_instance():
    for instance in NITTER_INSTANCES:
        try:
            r = requests.get(instance, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                log.info("Using Nitter instance: %s", instance)
                return instance
        except Exception:
            continue
    log.warning("No Nitter instance available")
    return None


def scrape_tweets(instance, query, lang, max_tweets=15):
    search_url = instance + "/search?q=" + requests.utils.quote(query) + "&f=tweets"
    tweets = []

    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            log.warning("Nitter returned %d for query: %s", resp.status_code, query[:40])
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.find_all("div", class_="timeline-item")

        for item in items[:max_tweets]:
            # Skip retweets
            if item.find("div", class_="retweet-header"):
                continue

            tweet_link = item.find("a", class_="tweet-link")
            if not tweet_link:
                continue

            tweet_path = tweet_link.get("href", "")
            tweet_id = tweet_path.split("/")[-1].replace("#m", "")

            content_div = item.find("div", class_="tweet-content")
            if not content_div:
                continue
            text = content_div.get_text(separator=" ").strip()

            # Basic language filter
            persian_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
            total_chars = max(len(text), 1)
            is_persian = (persian_chars / total_chars) > 0.2

            if lang == "fa" and not is_persian:
                continue
            if lang == "en" and is_persian:
                continue

            username_tag = item.find("a", class_="username")
            username = username_tag.get_text().strip().replace("@", "") if username_tag else "unknown"

            fullname_tag = item.find("a", class_="fullname")
            name = fullname_tag.get_text().strip() if fullname_tag else username

            stats = item.find("div", class_="tweet-stats")
            likes = 0
            retweets = 0
            if stats:
                stat_items = stats.find_all("span", class_="tweet-stat")
                for stat in stat_items:
                    icon = stat.find("span", class_=lambda x: x and "icon" in x)
                    val = stat.get_text().strip()
                    if icon:
                        icon_class = " ".join(icon.get("class", []))
                        try:
                            num = int(val.replace(",", "").replace(".", "").strip())
                        except ValueError:
                            num = 0
                        if "heart" in icon_class:
                            likes = num
                        elif "retweet" in icon_class:
                            retweets = num

            tweet_url = "https://twitter.com" + tweet_path.replace("#m", "")

            tweets.append({
                "id": tweet_id,
                "text": text,
                "lang": lang,
                "username": username,
                "name": name,
                "url": tweet_url,
                "likes": likes,
                "retweets": retweets,
            })

    except Exception as e:
        log.warning("Scraping failed for query '%s': %s", query[:40], e)

    return tweets


# ─── Telegram ─────────────────────────────────────────────────────────────────

def format_tweet(category, tweet):
    lang_flag = "🇮🇷" if tweet["lang"] == "fa" else "🇬🇧"
    return (
        category + " " + lang_flag + "\n\n"
        + tweet["text"] + "\n\n"
        + "👤 " + tweet["name"] + " (@" + tweet["username"] + ")\n"
        + "❤️ " + str(tweet["likes"]) + "  🔁 " + str(tweet["retweets"]) + "\n"
        + "🔗 " + tweet["url"]
    )


async def post_to_telegram(bot, text):
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            log.info("Posted to chat %s", chat_id)
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Telegram error for %s: %s", chat_id, e)


# ─── Main cycle ───────────────────────────────────────────────────────────────

async def run_cycle(bot, seen_ids):
    log.info("=== Cycle started at %s ===", datetime.now(timezone.utc).isoformat())

    instance = get_working_instance()
    if not instance:
        log.error("No Nitter instance available, skipping cycle")
        return

    for category, queries in CATEGORIES.items():
        for query, lang in queries:
            tweets = scrape_tweets(instance, query, lang)
            new_tweets = [t for t in tweets if t["id"] not in seen_ids]

            if not new_tweets:
                log.info("No new tweets for: %s (%s)", query[:40], lang)
                continue

            tweet = random.choice(new_tweets)
            await post_to_telegram(bot, format_tweet(category, tweet))
            seen_ids.add(tweet["id"])
            save_seen_ids(seen_ids)

            log.info("Posted [%s] tweet by @%s", category, tweet["username"])
            await asyncio.sleep(4)

    log.info("=== Cycle done. Next in %ds ===", POST_INTERVAL)


async def main():
    missing = []
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CHAT_IDS:
        missing.append("TELEGRAM_CHAT_IDS")
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    seen_ids = load_seen_ids()
    log.info("Bot started (Nitter mode). Posting to %d chat(s) every %ds", len(CHAT_IDS), POST_INTERVAL)

    while True:
        try:
            await run_cycle(bot, seen_ids)
        except Exception as e:
            log.exception("Error in cycle: %s", e)
        await asyncio.sleep(POST_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
