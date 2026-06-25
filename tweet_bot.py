#!/usr/bin/env python3
"""
Tweet Sharing Bot - Clean Edition
- Clean text (no blue sections)
- Translation buttons (EN/FA)
- Photos with text in caption
"""

import os
import json
import logging
import random
import asyncio
import re
import io
from datetime import datetime, timezone
from pathlib import Path
import requests
import xml.etree.ElementTree as ET
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError
from googletrans import Translator

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
RAW_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")
CHAT_IDS = [c.strip() for c in RAW_CHAT_IDS.split(",") if c.strip()]
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", 600))
NEWS_INTERVAL = int(os.environ.get("NEWS_INTERVAL_SECONDS", 900))
SEEN_IDS_FILE = Path("seen_tweet_ids.json")

# ═══════════════════════════════════════════════════════════════
#   CUSTOMIZE YOUR ACCOUNTS HERE
# ═══════════════════════════════════════════════════════════════

CATEGORY_ACCOUNTS = {
    "Funny": {
        "accounts": ["dril", "dadsaysjokes", "funnytweeter", "thedad"],
        "emoji": "🟨🟨🟨",
    },
    "Political": {
        "accounts": ["Reuters", "AP", "politico", "axios"],
        "emoji": "🔴🔴🔴",
    },
    "News": {
        "accounts": ["BBCBreaking", "Reuters", "AP", "nytimes"],
        "emoji": "🔵🔵🔵",
    },
    "Gaming": {
        "accounts": ["IGN", "PlayStation", "Xbox", "GameSpot"],
        "emoji": "🟣🟣🟣",
    },
    "Unhinged": {
        "accounts": ["dril", "NotGaryBusey", "TweetsByKosta"],
        "emoji": "🟠🟠⚠️",
    },
}

IRAN_ACCOUNTS = [
    "IranIntl_Fa",
    "bbcpersian",
    "VOAIran",
    "manototv",
    "RFE_FARSI",
]

BLOCKED_KEYWORDS = ["Islamic Republic", "gov.ir", "khamenei", "rouhani", "Revolutionary Guard"]

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
}

TREND_KEYWORDS = [
    "Ukraine",
    "Palestine",
    "Trump",
    "Biden",
    "China",
    "Russia",
    "AI",
    "Elon Musk",
    "SpaceX",
    "Tesla",
    "Iran",
    "Israel",
]

translator = Translator()


def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-10000:]))


def clean_text(text):
    """Remove HTML, extra whitespace, links"""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove URLs
    text = re.sub(r"http[s]?://\S+", "", text).strip()
    return text


def translate_text(text, lang):
    """Translate text to Persian or English"""
    try:
        if lang == "fa":
            result = translator.translate(text, src_language="en", dest_language="fa")
        else:
            result = translator.translate(text, src_language="fa", dest_language="en")
        return result.text
    except Exception as e:
        log.warning("Translation error: %s", e)
        return text


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
        items = root.findall(".//item")
        tweets = []
        for item in items:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            guid = item.findtext("guid", link).strip()
            
            clean = clean_text(desc) or title
            if not clean or len(clean) < 5:
                continue
            
            tweet_id = link.rstrip("/").split("/")[-1].replace("#m", "")
            
            # Extract media
            media_urls = []
            soup_match = re.findall(r'src="([^"]*\.(?:jpg|jpeg|png|mp4|webm))"', desc)
            media_urls.extend(soup_match)
            
            tweets.append({
                "id": tweet_id if tweet_id.isdigit() else guid,
                "text": clean[:400],
                "username": username,
                "url": "https://twitter.com/" + username,
                "media": media_urls,
            })
        log.info("Got %d tweets from @%s", len(tweets), username)
        return tweets
    except Exception as e:
        log.warning("RSS error for @%s: %s", username, e)
        return []


def search_trending(instance, keyword):
    """Search for trending topic tweets"""
    search_url = instance + "/search?q=" + requests.utils.quote(keyword) + "&f=tweets"
    try:
        resp = requests.get(search_url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        
        tweets = []
        # Extract text and usernames from Nitter HTML
        text_blocks = re.findall(r'<div class="tweet-content">([^<]+)</div>', resp.text)
        username_blocks = re.findall(r'<a class="username">(@\w+)</a>', resp.text)
        
        for i, text in enumerate(text_blocks[:5]):
            username = username_blocks[i].replace("@", "") if i < len(username_blocks) else "unknown"
            clean = clean_text(text)
            tweets.append({
                "text": clean[:350],
                "username": username,
            })
        return tweets
    except Exception as e:
        log.warning("Search error for '%s': %s", keyword, e)
        return []


def download_media(url):
    """Download media file"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return io.BytesIO(resp.content)
    except Exception as e:
        log.warning("Media download failed: %s", e)
    return None


def get_translation_buttons(tweet_text):
    """Create translation buttons"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇬🇧 English", callback_data=f"translate_en:{tweet_text[:20]}"),
            InlineKeyboardButton("🇮🇷 فارسی", callback_data=f"translate_fa:{tweet_text[:20]}"),
        ]
    ])


async def send_tweet_text(bot, tweet, emoji_prefix):
    """Send tweet as text with translation buttons"""
    text = emoji_prefix + "\n\n" + tweet["text"] + "\n\n@" + tweet["username"] + "\n— @Tweet1fy_bot"
    
    keyboard = get_translation_buttons(tweet["text"])
    
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Telegram error %s: %s", chat_id, e)


async def send_tweet_media(bot, tweet, emoji_prefix, media_url):
    """Send tweet with media (photo/video) and text in caption"""
    caption = emoji_prefix + "\n\n" + tweet["text"] + "\n\n@" + tweet["username"] + "\n— @Tweet1fy_bot"
    
    media_bytes = download_media(media_url)
    if not media_bytes:
        await send_tweet_text(bot, tweet, emoji_prefix)
        return
    
    is_video = media_url.lower().endswith((".mp4", ".webm"))
    keyboard = get_translation_buttons(tweet["text"])
    
    for chat_id in CHAT_IDS:
        try:
            if is_video:
                await bot.send_video(
                    chat_id=chat_id,
                    video=media_bytes,
                    caption=caption,
                    reply_markup=keyboard,
                )
            else:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=media_bytes,
                    caption=caption,
                    reply_markup=keyboard,
                )
            media_bytes.seek(0)
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Telegram media error %s: %s", chat_id, e)


async def run_category_cycle(bot, seen_ids):
    """Post from category accounts"""
    log.info("=== Category cycle started ===")
    instance = get_working_instance()
    if not instance:
        log.error("No Nitter instance!")
        return

    posted = 0
    for category, config in CATEGORY_ACCOUNTS.items():
        account = random.choice(config["accounts"])
        tweets = fetch_rss(instance, account)
        new = [t for t in tweets if t["id"] not in seen_ids]
        
        if not new:
            log.info("No new tweets from @%s", account)
            continue
        
        tweet = random.choice(new)
        emoji = config["emoji"]
        
        if tweet.get("media"):
            await send_tweet_media(bot, tweet, emoji, tweet["media"][0])
        else:
            await send_tweet_text(bot, tweet, emoji)
        
        seen_ids.add(tweet["id"])
        save_seen_ids(seen_ids)
        log.info("Posted [%s] from @%s", category, account)
        posted += 1
        await asyncio.sleep(4)

    log.info("=== Category cycle done. Posted %d ===", posted)


async def run_news_cycle(bot, seen_ids):
    """Post trending news"""
    log.info("=== News cycle started ===")
    instance = get_working_instance()
    if not instance:
        return

    trends = random.sample(TREND_KEYWORDS, min(3, len(TREND_KEYWORDS)))
    
    for trend in trends:
        log.info("Searching for trend: %s", trend)
        tweets = search_trending(instance, trend)
        
        for i, tweet in enumerate(tweets[:2]):
            if i >= 2:
                break
            
            tweet_id = trend + "_" + tweet["username"] + "_" + str(i)
            if tweet_id in seen_ids:
                continue
            
            emoji = "📰📰📰"
            if tweet.get("media"):
                await send_tweet_media(bot, tweet, emoji, tweet["media"][0])
            else:
                await send_tweet_text(bot, tweet, emoji)
            
            seen_ids.add(tweet_id)
            save_seen_ids(seen_ids)
            await asyncio.sleep(3)

    log.info("=== News cycle done ===")


async def run_iran_cycle(bot, seen_ids):
    """Post Iran-specific content"""
    log.info("=== Iran cycle started ===")
    instance = get_working_instance()
    if not instance:
        return

    account = random.choice(IRAN_ACCOUNTS)
    tweets = fetch_rss(instance, account)
    new = [t for t in tweets if t["id"] not in seen_ids]
    
    if not new:
        log.info("No new Iran tweets")
        return
    
    # Filter government accounts
    filtered = []
    for tweet in new:
        skip = False
        for keyword in BLOCKED_KEYWORDS:
            if keyword.lower() in tweet["username"].lower():
                skip = True
                break
        if not skip:
            filtered.append(tweet)
    
    if not filtered:
        log.info("All Iran tweets from blocked accounts")
        return
    
    tweet = random.choice(filtered)
    emoji = "🇮🇷🇮🇷🇮🇷"
    
    if tweet.get("media"):
        await send_tweet_media(bot, tweet, emoji, tweet["media"][0])
    else:
        await send_tweet_text(bot, tweet, emoji)
    
    seen_ids.add(tweet["id"])
    save_seen_ids(seen_ids)
    log.info("Posted Iran tweet from @%s", account)


async def main():
    missing = []
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CHAT_IDS:
        missing.append("TELEGRAM_CHAT_IDS")
    if missing:
        log.error("Missing: %s", ", ".join(missing))
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    seen_ids = load_seen_ids()
    log.info("Bot started - Clean edition with translations")

    category_timer = 0
    news_timer = 0
    iran_timer = 0

    while True:
        try:
            if category_timer <= 0:
                await run_category_cycle(bot, seen_ids)
                category_timer = POST_INTERVAL
            
            if news_timer <= 0:
                await run_news_cycle(bot, seen_ids)
                news_timer = NEWS_INTERVAL
            
            if iran_timer <= 0:
                await run_iran_cycle(bot, seen_ids)
                iran_timer = 600

            await asyncio.sleep(60)
            category_timer -= 60
            news_timer -= 60
            iran_timer -= 60

        except Exception as e:
            log.exception("Error: %s", e)
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
