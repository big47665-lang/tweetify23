#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot - Nitter version
No API key needed, completely free
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

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
RAW_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")
CHAT_IDS = [c.strip() for c in RAW_CHAT_IDS.split(",") if c.strip()]
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", 600))
SEEN_IDS_FILE = Path("seen_tweet_ids.json")

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.1d4.us",
]

CATEGORIES = {
    "😂 Funny": [
        "funny lmao lol hilarious",
        "خنده بامزه خندیدم",
    ],
    "🏛️ Political": [
        "politics government president election",
        "سیاست دولت انتخابات",
    ],
    "📰 News": [
        "breaking news urgent",
        "خبر فوری اخبار",
    ],
    "🎮 Gaming": [
        "gaming PlayStation Xbox Nintendo",
        "بازی گیمینگ پلی استیشن",
    ],
    "🤦 Unhinged": [
        "ratio wild unbelievable",
        "باورم نمیشه عجیبه",
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-5000:]))


def get_working_instance():
    random.shuffle(NITTER_INSTANCES)
    for instance in NITTER_INSTANCES:
        try:
            r = requests.get(instance, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                log.info("Using Nitter: %s", instance)
                return instance
        except Exception:
            continue
    return None


def is_persian(text):
    count = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    return count > 5


def scrape_nitter(instance, query):
    url = instance + "/search?q=" + requests.utils.quote(query) + "&f=tweets"
    tweets = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            log.warning("Nitter %d for: %s", resp.status_code, query[:30])
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.find_all("div", class_="timeline-item")
        log.info("Found %d items for query: %s", len(items), query[:30])

        for item in items:
            # Skip retweets
            if item.find("div", class_="retweet-header"):
                continue

            # Get tweet link
            tweet_link = item.find("a", class_="tweet-link")
            if not tweet_link:
                continue
            tweet_path = tweet_link.get("href", "")
            tweet_id = tweet_path.strip("/").split("/")[-1].replace("#m", "")
            if not tweet_id.isdigit():
                continue

            # Get text
            content = item.find("div", class_="tweet-content")
            if not content:
                continue
            text = content.get_text(separator=" ").strip()
            if len(text) < 10:
                continue

            # Get username
            username_tag = item.find("a", class_="username")
            username = username_tag.get_text().strip().lstrip("@") if username_tag else "unknown"

            fullname_tag = item.find("a", class_="fullname")
            name = fullname_tag.get_text().strip() if fullname_tag else username

            # Get stats
            likes = 0
            retweets = 0
            stat_spans = item.find_all("span", class_="tweet-stat")
            for span in stat_spans:
                txt = span.get_text().strip().replace(",", "")
                icon = span.find("span")
                if icon:
                    classes = " ".join(icon.get("class", []))
                    try:
                        num = int("".join(filter(str.isdigit, txt)))
                    except ValueError:
                        num = 0
                    if "heart" in classes or "like" in classes:
                        likes = num
                    elif "retweet" in classes:
                        retweets = num

            tweet_url = "https://twitter.com" + tweet_path.replace("#m", "")
            persian = is_persian(text)

            tweets.append({
                "id": tweet_id,
                "text": text,
                "lang": "fa" if persian else "en",
                "username": username,
                "name": name,
                "url": tweet_url,
                "likes": likes,
                "retweets": retweets,
            })

    except Exception as e:
        log.warning("Scrape error for '%s': %s", query[:30], e)

    log.info("Parsed %d valid tweets for: %s", len(tweets), query[:30])
    return tweets


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
            log.info("Posted to %s", chat_id)
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Telegram error %s: %s", chat_id, e)


async def run_cycle(bot, seen_ids):
    log.info("=== Cycle started %s ===", datetime.now(timezone.utc).isoformat())

    instance = get_working_instance()
    if not instance:
        log.error("All Nitter instances down, skipping cycle")
        return

    for category, queries in CATEGORIES.items():
        for query in queries:
            tweets = scrape_nitter(instance, query)
            new_tweets = [t for t in tweets if t["id"] not in seen_ids]

            if not new_tweets:
                log.info("No new tweets for: %s", query[:30])
                continue

            tweet = random.choice(new_tweets)
            text = format_tweet(category, tweet)
            await post_to_telegram(bot, text)
            seen_ids.add(tweet["id"])
            save_seen_ids(seen_ids)
            log.info("Posted [%s] by @%s", category, tweet["username"])
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
    log.info("Bot started. Posting to %d chat(s) every %ds", len(CHAT_IDS), POST_INTERVAL)

    while True:
        try:
            await run_cycle(bot, seen_ids)
        except Exception as e:
            log.exception("Error: %s", e)
        await asyncio.sleep(POST_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
