#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Fetches tweets by category (funny, political, news, gaming, unhinged)
- Filters for Persian (fa) and English (en) only
- Posts to Telegram groups where the bot is admin
- Uses requests directly instead of tweepy to avoid Python 3.13 issues
"""

import os
import json
import logging
import random
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import requests
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
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN", "YOUR_BEARER_TOKEN")
RAW_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")
CHAT_IDS = [c.strip() for c in RAW_CHAT_IDS.split(",") if c.strip()]
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", 900))
TWEETS_PER_CATEGORY = int(os.environ.get("TWEETS_PER_CATEGORY", 10))
SEEN_IDS_FILE = Path("seen_tweet_ids.json")

# ─── Category Search Queries ──────────────────────────────────────────────────
CATEGORIES = {
    "😂 Funny": [
        "(funny OR lmao OR lol OR hilarious OR omg) -is:retweet lang:en min_faves:500",
        "(خنده OR بامزه OR خندیدم OR میخندم) -is:retweet lang:fa min_faves:200",
    ],
    "🏛️ Political": [
        "(politics OR government OR president OR election OR senate) -is:retweet lang:en min_faves:500",
        "(سیاست OR دولت OR انتخابات OR پارلمان) -is:retweet lang:fa min_faves:200",
    ],
    "📰 News": [
        "(breaking OR urgent OR developing) -is:retweet lang:en min_faves:300",
        "(خبر فوری OR اخبار OR گزارش) -is:retweet lang:fa min_faves:100",
    ],
    "🎮 Gaming": [
        "(gaming OR PlayStation OR Xbox OR Nintendo) -is:retweet lang:en min_faves:300",
        "(بازی OR گیمینگ OR پلی استیشن OR ایکس باکس) -is:retweet lang:fa min_faves:100",
    ],
    "🤦 Unhinged": [
        "(ratio OR skill issue OR touch grass) -is:retweet lang:en min_faves:1000",
        "(باورم نمیشه OR عجیبه OR چی گفت) -is:retweet lang:fa min_faves:300",
    ],
}

# ─── Seen IDs ─────────────────────────────────────────────────────────────────

def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-5000:]))


# ─── Twitter API (using requests directly) ────────────────────────────────────

def fetch_tweets(query, max_results=10):
    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": "Bearer " + TWITTER_BEARER_TOKEN}
    params = {
        "query": query,
        "max_results": max(10, min(max_results, 100)),
        "tweet.fields": "id,text,lang,author_id,created_at,public_metrics",
        "expansions": "author_id",
        "user.fields": "username,name",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 429:
            log.warning("Twitter rate limit hit, skipping this query")
            return []
        if resp.status_code != 200:
            log.warning("Twitter API error %d: %s", resp.status_code, resp.text[:200])
            return []

        data = resp.json()
        tweets_data = data.get("data", [])
        users_list = data.get("includes", {}).get("users", [])
        users = {u["id"]: u for u in users_list}

        tweets = []
        for t in tweets_data:
            author = users.get(t.get("author_id", ""), {})
            username = author.get("username", "unknown")
            name = author.get("name", "Unknown")
            metrics = t.get("public_metrics", {})
            url_str = "https://twitter.com/" + username + "/status/" + t["id"]
            tweets.append({
                "id": t["id"],
                "text": t["text"],
                "lang": t.get("lang", "und"),
                "username": username,
                "name": name,
                "url": url_str,
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
            })
        return tweets

    except Exception as e:
        log.warning("Request failed: %s", e)
        return []


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
            log.error("Telegram error for chat %s: %s", chat_id, e)


# ─── Main cycle ───────────────────────────────────────────────────────────────

async def run_cycle(bot, seen_ids):
    log.info("=== Cycle started at %s ===", datetime.now(timezone.utc).isoformat())

    for category, queries in CATEGORIES.items():
        for query in queries:
            tweets = fetch_tweets(query, max_results=TWEETS_PER_CATEGORY)
            new_tweets = [t for t in tweets if t["id"] not in seen_ids]

            if not new_tweets:
                log.info("No new tweets for: %s", query[:50])
                continue

            tweet = random.choice(new_tweets)
            await post_to_telegram(bot, format_tweet(category, tweet))
            seen_ids.add(tweet["id"])
            save_seen_ids(seen_ids)
            await asyncio.sleep(3)

    log.info("=== Cycle done. Next in %ds ===", POST_INTERVAL)


async def main():
    missing = []
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        missing.append("TELEGRAM_BOT_TOKEN")
    if TWITTER_BEARER_TOKEN == "YOUR_BEARER_TOKEN":
        missing.append("TWITTER_BEARER_TOKEN")
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
            log.exception("Error in cycle: %s", e)
        await asyncio.sleep(POST_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
