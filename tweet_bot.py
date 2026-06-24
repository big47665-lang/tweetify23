#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Scrapes tweets by category (funny, political, news, gaming, cringe/unhinged)
- Filters for Persian (fa) and English (en) only
- Posts to Telegram groups where the bot is admin
- Runs on a schedule, no duplicate posts

Requirements: pip install -r requirements.txt
"""

import os
import json
import time
import logging
import random
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tweepy
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

# Twitter API v2 Bearer Token (free tier — read-only, 500k tweets/month)
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN", "YOUR_BEARER_TOKEN")

# Comma-separated list of Telegram group/channel chat IDs (e.g. "-1001234567890")
RAW_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")
CHAT_IDS: list[str] = [c.strip() for c in RAW_CHAT_IDS.split(",") if c.strip()]

# How often to post (seconds). Default: every 15 minutes
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", 900))

# How many tweets to fetch per category per cycle
TWEETS_PER_CATEGORY = int(os.environ.get("TWEETS_PER_CATEGORY", 10))

# File to track already-posted tweet IDs
SEEN_IDS_FILE = Path("seen_tweet_ids.json")

# ─── Category Search Queries ──────────────────────────────────────────────────
# Each category has English + Persian queries. Only lang:fa and lang:en tweets
# are fetched. Twitter search operators: -is:retweet, min_faves, lang:

CATEGORIES = {
    "😂 Funny": [
        # English
        '(funny OR lmao OR lol OR hilarious OR omg) -is:retweet lang:en min_faves:500',
        # Persian
        '(خنده OR بامزه OR خندیدم OR "میخندم") -is:retweet lang:fa min_faves:200',
    ],
    "🏛️ Political": [
        '(politics OR government OR president OR election OR senate OR "white house") -is:retweet lang:en min_faves:500',
        '(سیاست OR دولت OR رئیس‌جمهور OR انتخابات OR پارلمان) -is:retweet lang:fa min_faves:200',
    ],
    "📰 News": [
        '(breaking OR "just in" OR "breaking news" OR developing) -is:retweet lang:en min_faves:300',
        '(خبر فوری OR اخبار OR گزارش OR جدیدترین) -is:retweet lang:fa min_faves:100',
    ],
    "🎮 Gaming": [
        '(gaming OR "game pass" OR PlayStation OR Xbox OR Nintendo OR "new game" OR giveaway) -is:retweet lang:en min_faves:300',
        '(بازی OR گیمینگ OR پلی‌استیشن OR ایکس‌باکس OR نینتندو) -is:retweet lang:fa min_faves:100',
    ],
    "🤦 Unhinged": [
        # Wild takes, facepalm moments, bizarre tweets
        '(ratio OR "skill issue" OR "touch grass" OR "this is real" OR "i can\'t believe") -is:retweet lang:en min_faves:1000',
        '(باورم نمیشه OR عجیبه OR چی گفت OR "چطور ممکنه") -is:retweet lang:fa min_faves:300',
    ],
}

# ─── Seen IDs persistence ─────────────────────────────────────────────────────

def load_seen_ids() -> set[str]:
    if SEEN_IDS_FILE.exists():
        data = json.loads(SEEN_IDS_FILE.read_text())
        return set(data)
    return set()


def save_seen_ids(ids: set[str]) -> None:
    # Keep only the last 5000 to avoid unbounded growth
    trimmed = list(ids)[-5000:]
    SEEN_IDS_FILE.write_text(json.dumps(trimmed))


# ─── Twitter client ───────────────────────────────────────────────────────────

def make_twitter_client() -> tweepy.Client:
    return tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)


def fetch_tweets(client: tweepy.Client, query: str, max_results: int = 10) -> list[dict]:
    """Return a list of tweet dicts {id, text, author_id, lang, url}."""
    try:
        resp = client.search_recent_tweets(
            query=query,
            max_results=max(10, min(max_results, 100)),  # API min=10, max=100
            tweet_fields=["id", "text", "lang", "author_id", "created_at", "public_metrics"],
            expansions=["author_id"],
            user_fields=["username", "name"],
        )
    except tweepy.TweepyException as e:
        log.warning("Twitter search failed for query '%s': %s", query[:60], e)
        return []

    if not resp.data:
        return []

    # Build username map
    users = {u.id: u for u in (resp.includes.get("users") or [])}

    tweets = []
    for t in resp.data:
        author = users.get(t.author_id)
        username = author.username if author else "unknown"
        name = author.name if author else "Unknown"
        url = f"https://twitter.com/{username}/status/{t.id}"
        tweets.append({
            "id": str(t.id),
            "text": t.text,
            "lang": t.lang or "und",
            "username": username,
            "name": name,
            "url": url,
            "likes": t.public_metrics.get("like_count", 0) if t.public_metrics else 0,
            "retweets": t.public_metrics.get("retweet_count", 0) if t.public_metrics else 0,
        })

    return tweets


# ─── Telegram helpers ─────────────────────────────────────────────────────────

def format_tweet(category: str, tweet: dict) -> str:
    lang_flag = "🇮🇷" if tweet["lang"] == "fa" else "🇬🇧"
    return (
        f"{category} {lang_flag}\n\n"
        f"{tweet['text']}\n\n"
        f"👤 {tweet['name']} (@{tweet['username']})\n"
        f"❤️ {tweet['likes']:,}  🔁 {tweet['retweets']:,}\n"
        f"🔗 {tweet['url']}"
    )


async def post_to_telegram(bot: Bot, chat_ids: list[str], text: str) -> None:
    for chat_id in chat_ids:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=None,  # plain text — tweet content may break Markdown
                disable_web_page_preview=False,  # show tweet card
            )
            log.info("Posted to chat %s", chat_id)
            await asyncio.sleep(1)  # avoid flood limits
        except TelegramError as e:
            log.error("Telegram error for chat %s: %s", chat_id, e)


# ─── Core loop ────────────────────────────────────────────────────────────────

async def run_cycle(bot: Bot, twitter: tweepy.Client, seen_ids: set[str]) -> None:
    log.info("=== Starting new cycle at %s ===", datetime.now(timezone.utc).isoformat())

    for category, queries in CATEGORIES.items():
        for query in queries:
            tweets = fetch_tweets(twitter, query, max_results=TWEETS_PER_CATEGORY)
            new_tweets = [t for t in tweets if t["id"] not in seen_ids]

            if not new_tweets:
                log.info("[%s] No new tweets for query: %s", category, query[:60])
                continue

            # Pick one random tweet per query to avoid flooding
            tweet = random.choice(new_tweets)
            text = format_tweet(category, tweet)

            await post_to_telegram(bot, CHAT_IDS, text)
            seen_ids.add(tweet["id"])
            save_seen_ids(seen_ids)

            # Small delay between categories
            await asyncio.sleep(3)

    log.info("=== Cycle complete. Next run in %ds ===", POST_INTERVAL)


async def main() -> None:
    # Validate config
    missing = []
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        missing.append("TELEGRAM_BOT_TOKEN")
    if TWITTER_BEARER_TOKEN == "YOUR_BEARER_TOKEN":
        missing.append("TWITTER_BEARER_TOKEN")
    if not CHAT_IDS:
        missing.append("TELEGRAM_CHAT_IDS")
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    twitter = make_twitter_client()
    seen_ids = load_seen_ids()

    log.info("Bot started. Posting to %d chat(s) every %ds", len(CHAT_IDS), POST_INTERVAL)

    while True:
        try:
            await run_cycle(bot, twitter, seen_ids)
        except Exception as e:
            log.exception("Unexpected error in cycle: %s", e)
        await asyncio.sleep(POST_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
