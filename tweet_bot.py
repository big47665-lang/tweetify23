#!/usr/bin/env python3
"""
Tweet Sharing Bot - Retweet Edition
- Iran emoji: ☀️☀️🦁☀️☀️
- Retweet formatting with separators
- Media with full text in caption
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
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError

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
        "accounts": ["dril", "shitpost_2077", "funnytweeter", "gaming_leake"],  
        "emoji": "🟨🟨🟨🟨🟨🟨",
    },
    "Political": {  
        "accounts": ["Reuters", "AP", "politico", "axios"],  
        "emoji": "🔴🔴🔴🔴🔴🔴",
    },
    "News": {  
        "accounts": ["BBCBreaking", "Reuters", "ManotoNews", "nytimes", "guardian", "DiscussingFilm"],  
        "emoji": "🔵🔵🔵🔵🔵🔵",
    },
    "Gaming": {  
        "accounts": ["IGN", "PlayStation", "Xbox", "GameSpot", "Dexerto", "InternetH0F"],  
        "emoji": "🟣🟣🟣🟣🟣🟣",
    },
    "Unhinged": {  
        "accounts": ["dril", "", "TweetsByKosta", "insaneposes", "middleclassfancy", "LocalBateman"],  
        "emoji": "🟠🟠⚠️⚠️🟠🟠",
    },
}

IRAN_ACCOUNTS = [
    "IranIntl_Fa",
    "MatinSenPai",
    "BhFak46419",
    "Realneo101",
    "thetwelfth_Imam",
    "PahlaviReza",
    "SAVAK071",
]

IRAN_EMOJI = "☀️☀️🦁☀️☀️"

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
    "PS5",
    "XBOX",
    "Trump",
    "GTA VI",
    "War",
    "GTA 6",
    "AI",
    "Elon Musk",
    "SpaceX",
    "Tesla",
    "Iran",
    "Israel",
]

IRAN_TRENDS = [
    "ایران",
    "خامنه ای",
    "دولت",
    "سیاست",
    "خبر",
    "اقتصاد",
    "جاوید شاه",
    "ذرت",
    "عرزشی",
    "کتلت",
]

def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-10000:]))


def clean_text(text):
    """Remove HTML, extra whitespace, links"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"http[s]?://\S+", "", text).strip()
    return text


def translate_to_persian(text):
    """Translate English text to Persian using free API"""
    try:
        # Using MyMemory Translation API (free, no key needed)
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text[:500],  # API limit
            "langpair": "en|fa"
        }
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("responseStatus") == 200:
                translated = data["responseData"]["translatedText"]
                return translated if translated else text
    except Exception as e:
        log.warning("Translation to Persian failed: %s", e)
    return text


def translate_to_english(text):
    """Translate Persian text to English using free API"""
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text[:500],
            "langpair": "fa|en"
        }
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("responseStatus") == 200:
                translated = data["responseData"]["translatedText"]
                return translated if translated else text
    except Exception as e:
        log.warning("Translation to English failed: %s", e)
    return text


def detect_retweet(text):
    """
    Detect if tweet is a retweet
    Returns: (is_retweet, retweeter_username, original_text, original_username)
    """
    # Pattern: RT @username: text
    match = re.match(r'RT @(\w+):\s*(.*)', text)
    if match:
        retweeter = match.group(1)
        rest = match.group(2)
        
        # Try to find if there's original user mentioned
        original_match = re.search(r'@(\w+)', rest)
        if original_match:
            original_user = original_match.group(1)
            original_text = rest
            return True, retweeter, original_text, original_user
        
        return True, retweeter, rest, "unknown"
    
    return False, None, text, None


def format_retweet(retweeter, original_user, original_text, emoji_prefix):
    """Format retweet with separator"""
    separator = "~~~~~~~~~~~~~~~~~~~~~~~~"
    
    formatted = (
        emoji_prefix + "\n\n"
        "🔄 Retweeted by @" + retweeter + "\n\n"
        + separator + "\n\n"
        "@" + original_user + ":\n\n"
        + original_text + "\n\n"
        "— @Tweet1fy_bot"
    )
    return formatted


def format_normal_tweet(text, username, emoji_prefix):
    """Format normal tweet"""
    return (
        emoji_prefix + "\n\n"
        + text + "\n\n"
        "@" + username + "\n"
        "— @Tweet1fy_bot"
    )


def get_translation_buttons(tweet_text):
    """Create translation buttons"""
    short = tweet_text[:20]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇬🇧 English", callback_data=f"translate_en:{short}"),
            InlineKeyboardButton("🇮🇷 فارسی", callback_data=f"translate_fa:{short}"),
        ]
    ])


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
    """Download media file - skip if it's too small (likely thumbnail)"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            # Check file size - if < 100KB, it's probably just a thumbnail
            if len(resp.content) > 102400:  # 100KB minimum for real video
                return io.BytesIO(resp.content)
            elif url.lower().endswith((".jpg", ".jpeg", ".png")):
                # Images are OK to be small
                return io.BytesIO(resp.content)
    except Exception as e:
        log.warning("Media download failed: %s", e)
    return None


async def send_tweet_text(bot, tweet, emoji_prefix):
    """Send tweet as text with translation buttons"""
    # Check if it's a retweet
    is_rt, retweeter, original_text, original_user = detect_retweet(tweet["text"])
    
    if is_rt:
        text = format_retweet(retweeter, original_user, original_text, emoji_prefix)
    else:
        text = format_normal_tweet(tweet["text"], tweet["username"], emoji_prefix)
    
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
    # Check if it's a retweet
    is_rt, retweeter, original_text, original_user = detect_retweet(tweet["text"])
    
    if is_rt:
        caption = format_retweet(retweeter, original_user, original_text, emoji_prefix)
    else:
        caption = format_normal_tweet(tweet["text"], tweet["username"], emoji_prefix)
    
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
    emoji = IRAN_EMOJI  # ☀️☀️🦁☀️☀️
    
    if tweet.get("media"):
        await send_tweet_media(bot, tweet, emoji, tweet["media"][0])
    else:
        await send_tweet_text(bot, tweet, emoji)
    
    seen_ids.add(tweet["id"])
    save_seen_ids(seen_ids)
    log.info("Posted Iran tweet from @%s", account)


async def handle_translation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle translation button clicks"""
    query = update.callback_query
    
    try:
        await query.answer(text="Translating...", show_alert=False)
        
        data = query.data
        original_text = query.message.text
        
        # Extract tweet text (skip emojis, signatures, etc)
        lines = original_text.split("\n")
        tweet_text = ""
        for line in lines:
            if line and not line.startswith("—") and not line.startswith("@") and not line.startswith("🔄"):
                if not any(c in line for c in ["~~~~", "----"]):
                    tweet_text += line + " "
        tweet_text = tweet_text.strip()[:300]
        
        if not tweet_text:
            await query.answer(text="No text to translate", show_alert=True)
            return
        
        response = ""
        
        if "translate_fa" in data:
            # Translate to Persian
            log.info("Translating to Persian: %s", tweet_text[:50])
            translated = translate_to_persian(tweet_text)
            response = "\n\n🇮🇷 *فارسی ترجمه:*\n\n" + translated
            
        elif "translate_en" in data:
            # Translate to English
            log.info("Translating to English: %s", tweet_text[:50])
            translated = translate_to_english(tweet_text)
            response = "\n\n🇬🇧 *English Translation:*\n\n" + translated
        
        if response:
            new_text = original_text + response
            await query.edit_message_text(text=new_text)
            await query.answer(text="Done!", show_alert=False)
    
    except Exception as e:
        log.error("Translation callback error: %s", e)
        await query.answer(text="Translation failed: " + str(e)[:50], show_alert=True)


async def run_posting_cycle(bot, seen_ids):
    """Run the posting cycle in background"""
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
            log.exception("Posting cycle error: %s", e)
            await asyncio.sleep(30)


async def main():
    missing = []
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CHAT_IDS:
        missing.append("TELEGRAM_CHAT_IDS")
    if missing:
        log.error("Missing: %s", ", ".join(missing))
        return

    # Create application for handling callbacks
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add callback handler for translations
    app.add_handler(CallbackQueryHandler(handle_translation))
    
    bot = app.bot
    seen_ids = load_seen_ids()
    log.info("Bot started - Retweet edition with Iran emojis + Translation")
    
    # Start the application
    async with app:
        await app.start()
        
        # Run posting cycle concurrently
        try:
            await run_posting_cycle(bot, seen_ids)
        finally:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
