#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
Uses Nitter RSS feeds - much harder to block than scraping
No API key needed, completely free
"""

import os
import json
import logging
import random
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import requests
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

# Nitter instances to try
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSS reader)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

# Popular accounts to pull tweets from per category
# Using RSS from specific accounts is much more reliable than search
CATEGORY_ACCOUNTS = {
    "😂 Funny": [
        "dril", "dadsaysjokes", "Seinfeld2000", "funnytweeter",
        "thedad", "UncleDynamite", "middleclassfancy",
    ],
    "🏛️ Political": [
        "Reuters", "AP", "BBCWorld", "CNN", "politico",
        "thehill", "axios",
    ],
    "📰 News": [
        "BreakingNews", "BBCBreaking", "Reuters", "AP",
        "nytimes", "guardian",
    ],
    "🎮 Gaming": [
        "IGN", "Kotaku", "PlayStation", "Xbox",
        "NintendoAmerica", "GameSpot", "PCGamer",
    ],
    "🤦 Unhinged": [
        "dril", "dadsaysjokes", "NotGaryBusey",
        "thetoddler", "TweetsByKosta",
    ],
}

# Persian news/content accounts
PERSIAN_ACCOUNTS = [
    "IranIntl_Fa", "bbcpersian", "VOAIran",
    "manototv", "IranWire",
]


def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-5000:]))


def get_working_instance():
    instances = NITTER_INSTANCES.copy()
    random.shuffle(instances)
    for instance in instances:
        try:
            r = requests.get(instance, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                log.info("Using Nitter: %s", instance)
                return instance
        except Exception:
            continue
    return None


def fetch_rss(instance, username):
    url = instance + "/" + username + "/rss"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.content)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        items = root.findall(".//item")
        tweets = []

        for item in items:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            guid = item.findtext("guid", link).strip()

            # Clean up description (remove HTML tags simply)
            import re
            clean_desc = re.sub(r"<[^>]+>", "", desc).strip()
            text = clean_desc if clean_desc else title

            if not text or len(text) < 5:
                continue

            # Extract tweet ID from link
            tweet_id = link.rstrip("/").split("/")[-1].replace("#m", "")

            # Detect language
            persian_chars = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
            lang = "fa" if persian_chars > 5 else "en"

            tweets.append({
                "id": tweet_id if tweet_id.isdigit() else guid,
                "text": text[:500],
                "lang": lang,
                "username": username,
                "name": username,
                "url": "https://twitter.com/" + username,
                "likes": 0,
                "retweets": 0,
            })

        log.info("Got %d tweets from @%s", len(tweets), username)
        return tweets

    except ET.ParseError:
        log.warning("RSS parse error for @%s", username)
        return []
    except Exception as e:
        log.warning("RSS fetch error for @%s: %s", username, e)
        return []


def format_tweet(category, tweet):
    lang_flag = "🇮🇷" if tweet["lang"] == "fa" else "🇬🇧"
    return (
        category + " " + lang_flag + "\n\n"
        + tweet["text"] + "\n\n"
        + "👤 @" + tweet["username"] + "\n"
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
        log.error("All Nitter instances down!")
        return

    posted = 0

    # English accounts by category
    for category, accounts in CATEGORY_ACCOUNTS.items():
        account = random.choice(accounts)
        tweets = fetch_rss(instance, account)
        new_tweets = [t for t in tweets if t["id"] not in seen_ids]

        if new_tweets:
            tweet = random.choice(new_tweets)
            await post_to_telegram(bot, format_tweet(category, tweet))
            seen_ids.add(tweet["id"])
            save_seen_ids(seen_ids)
            log.info("Posted [%s] from @%s", category, account)
            posted += 1
            await asyncio.sleep(4)

    # Persian accounts
    persian_account = random.choice(PERSIAN_ACCOUNTS)
    tweets = fetch_rss(instance, persian_account)
    new_tweets = [t for t in tweets if t["id"] not in seen_ids]
    if new_tweets:
        tweet = random.choice(new_tweets)
        tweet["lang"] = "fa"
        await post_to_telegram(bot, format_tweet("📰 Persian News", tweet))
        seen_ids.add(tweet["id"])
        save_seen_ids(seen_ids)
        log.info("Posted Persian tweet from @%s", persian_account)
        posted += 1

    log.info("=== Cycle done. Posted %d tweets. Next in %ds ===", posted, POST_INTERVAL)


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
    log.info("Bot started (RSS mode). Posting every %ds", POST_INTERVAL)

    while True:
        try:
            await run_cycle(bot, seen_ids)
        except Exception as e:
            log.exception("Error: %s", e)
        await asyncio.sleep(POST_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
