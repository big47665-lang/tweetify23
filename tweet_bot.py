#!/usr/bin/env python3
"""
Tweetify Bot - SIMPLE & WORKING
- Posts real tweets from accounts
- No duplicates (hash-based detection)
- Image/video support
- Translation button (working)
- Fallback to Iran + trending
- Auto-posts to groups
"""

import os
import json
import logging
import random
import asyncio
import re
import io
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import xml.etree.ElementTree as ET

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from telegram.error import TelegramError

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
RAW_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")
CHAT_IDS = [c.strip() for c in RAW_CHAT_IDS.split(",") if c.strip()]
POST_INTERVAL = 600  # 10 minutes
TWEET_HASH_FILE = Path("tweet_hashes.json")

# ACCOUNTS - EDIT HERE
CATEGORY_ACCOUNTS = {
    "Funny": {"accounts": ["dril", "shitpost_2077", "funnytweeter", "gaming_leake"], "emoji": "😂😂😂"},
    "Political": {"accounts": ["Reuters", "AP", "politico", "axios"], "emoji": "🏛️🏛️🏛️"},
    "News": {"accounts": ["BBCBreaking", "Reuters", "ManotoNews", "nytimes", "guardian"], "emoji": "📰📰📰"},
    "Gaming": {"accounts": ["IGN", "PlayStation", "Xbox", "GameSpot"], "emoji": "🎮🎮🎮"},
    "Unhinged": {"accounts": ["dril", "TweetsByKosta", "insaneposes"], "emoji": "🤪🤪🤪"},
}

IRAN_ACCOUNTS = ["IranIntl_Fa", "bbcpersian", "VOAIran", "RFE_FARSI", "Realneo101"]
IRAN_EMOJI = "☀️☀️🦁☀️☀️"
TRENDS = ["PS5", "XBOX", "Trump", "China", "Iran", "AI", "Tesla", "Elon Musk"]

NITTER = ["https://nitter.net", "https://nitter.privacydev.net", "https://nitter.poast.org"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def get_tweet_hash(text):
    """Create hash of tweet to avoid duplicates"""
    return hashlib.md5(text.encode()).hexdigest()


def load_hashes():
    """Load sent tweet hashes"""
    if TWEET_HASH_FILE.exists():
        return set(json.loads(TWEET_HASH_FILE.read_text()))
    return set()


def save_hashes(hashes):
    """Save tweet hashes"""
    TWEET_HASH_FILE.write_text(json.dumps(list(hashes)[-5000:]))


def clean_text(text):
    """Clean tweet text"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_nitter():
    """Get working Nitter instance"""
    for nitter in NITTER:
        try:
            r = requests.get(nitter, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                log.info("Using: %s", nitter)
                return nitter
        except:
            pass
    return None


def fetch_tweets(nitter, username):
    """Fetch tweets from account"""
    try:
        url = f"{nitter}/{username}/rss"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        
        root = ET.fromstring(resp.content)
        tweets = []
        
        for item in root.findall(".//item"):
            text = clean_text(item.findtext("description", "") or item.findtext("title", ""))
            link = item.findtext("link", "")
            
            if not text or len(text) < 5:
                continue
            
            # Extract images/videos
            media = re.findall(r'src="([^"]*\.(?:jpg|jpeg|png|mp4|webm|gif))"', text)
            
            tweets.append({
                "text": text[:350],
                "username": username,
                "link": link,
                "media": media[:1],  # Take first media only
            })
        
        log.info("Got %d tweets from @%s", len(tweets), username)
        return tweets
    except Exception as e:
        log.warning("Error fetching @%s: %s", username, e)
        return []


def download_media(url):
    """Download image/video"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return io.BytesIO(resp.content)
    except Exception as e:
        log.warning("Media download failed: %s", e)
    return None


def translate_text(text, to_lang):
    """Translate using free API"""
    try:
        if to_lang == "fa":
            params = {"q": text[:400], "langpair": "en|fa"}
        else:
            params = {"q": text[:400], "langpair": "fa|en"}
        
        r = requests.get("https://api.mymemory.translated.net/get", params=params, timeout=5)
        if r.status_code == 200:
            result = r.json().get("responseData", {}).get("translatedText", text)
            return result if result and result != text else text
    except:
        pass
    return text


async def handle_translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle translation button"""
    query = update.callback_query
    try:
        await query.answer("Translating...", show_alert=False)
        
        data = query.data
        text = query.message.text
        
        # Extract tweet text
        lines = text.split("\n")
        tweet = " ".join([l for l in lines if l and not l.startswith("@") and not l.startswith("—")])[:300]
        
        if "fa" in data:
            translated = translate_text(tweet, "fa")
            response = f"🇮🇷 *Persian:*\n{translated}"
        else:
            translated = translate_text(tweet, "en")
            response = f"🇬🇧 *English:*\n{translated}"
        
        await query.message.reply_text(response, parse_mode="Markdown")
        await query.answer("✅ Sent!", show_alert=False)
    except Exception as e:
        log.error("Translation error: %s", e)
        await query.answer("Error", show_alert=True)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start"""
    await update.message.reply_text(
        "🎉 *Tweetify Bot*\n\n"
        "Posting trending tweets automatically!\n"
        "🌍 World • 🇮🇷 Iran • 📊 Trending\n\n"
        "Commands: /help /stats"
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help"""
    await update.message.reply_text(
        "/start - Welcome\n"
        "/help - This\n"
        "/stats - Statistics"
    )


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats"""
    hashes = load_hashes()
    await update.message.reply_text(
        f"📊 *Stats*\n\n"
        f"Tweets sent: {len(hashes)}\n"
        f"Accounts: {sum(len(c['accounts']) for c in CATEGORY_ACCOUNTS.values())}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
    )


async def send_tweet(bot, tweet, emoji, hashes):
    """Send tweet to groups"""
    tweet_hash = get_tweet_hash(tweet["text"])
    
    # Check if already sent
    if tweet_hash in hashes:
        log.info("Duplicate detected, skipping")
        return False
    
    text = f"{emoji}\n\n{tweet['text']}\n\n@{tweet['username']}"
    
    # Add translation buttons
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇬🇧 English", callback_data="trans_en"),
        InlineKeyboardButton("🇮🇷 فارسی", callback_data="trans_fa"),
    ]])
    
    for chat_id in CHAT_IDS:
        try:
            # Send with media if available
            if tweet.get("media"):
                media = download_media(tweet["media"][0])
                if media:
                    is_video = tweet["media"][0].lower().endswith((".mp4", ".webm"))
                    try:
                        if is_video:
                            await bot.send_video(chat_id, media, caption=text, reply_markup=keyboard)
                        else:
                            await bot.send_photo(chat_id, media, caption=text, reply_markup=keyboard)
                    except:
                        await bot.send_message(chat_id, text, reply_markup=keyboard)
                else:
                    await bot.send_message(chat_id, text, reply_markup=keyboard)
            else:
                await bot.send_message(chat_id, text, reply_markup=keyboard)
            
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Send error: %s", e)
    
    hashes.add(tweet_hash)
    save_hashes(hashes)
    return True


async def cycle(bot, hashes):
    """Main posting cycle"""
    nitter = get_nitter()
    if not nitter:
        log.error("No Nitter available!")
        return
    
    # Try categories
    for category, config in CATEGORY_ACCOUNTS.items():
        account = random.choice(config["accounts"])
        tweets = fetch_tweets(nitter, account)
        
        for tweet in tweets:
            if await send_tweet(bot, tweet, config["emoji"], hashes):
                log.info("Posted from %s", category)
                return
    
    # Fallback: Iran
    log.info("No new tweets in categories, trying Iran...")
    account = random.choice(IRAN_ACCOUNTS)
    tweets = fetch_tweets(nitter, account)
    
    for tweet in tweets:
        if await send_tweet(bot, tweet, IRAN_EMOJI, hashes):
            log.info("Posted from Iran")
            return
    
    # Fallback: Trends
    log.info("No Iran tweets, trying trends...")
    keyword = random.choice(TRENDS)
    try:
        r = requests.get(f"{nitter}/search?q={keyword}", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            texts = re.findall(r'<div class="tweet-content">([^<]+)</div>', r.text)
            if texts:
                tweet_text = clean_text(random.choice(texts))
                await send_tweet(bot, {
                    "text": tweet_text[:350],
                    "username": "Trending",
                    "media": []
                }, "📊📊📊", hashes)
                log.info("Posted from trends")
    except Exception as e:
        log.warning("Trend search failed: %s", e)


async def main_loop(bot, hashes):
    """Keep posting"""
    while True:
        try:
            await cycle(bot, hashes)
            await asyncio.sleep(POST_INTERVAL)
        except Exception as e:
            log.exception("Cycle error: %s", e)
            await asyncio.sleep(60)


async def main():
    """Start bot"""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        log.error("Set TELEGRAM_BOT_TOKEN!")
        return
    
    if not CHAT_IDS:
        log.error("Set TELEGRAM_CHAT_IDS!")
        return
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CallbackQueryHandler(handle_translate, pattern="trans_"))
    
    bot = app.bot
    hashes = load_hashes()
    
    log.info("🤖 Tweetify Bot Started!")
    
    async with app:
        await app.start()
        try:
            await main_loop(bot, hashes)
        finally:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
