#!/usr/bin/env python3
"""
Tweet Sharing Bot - Clean Interactive Version
- Bot commands: /start, /help, /stats, /refresh
- Interactive Telegram bot
- Mini app dashboard support
"""

import os
import json
import logging
import random
import asyncio
import re
import io
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
POST_INTERVAL = int(os.environ.get("POST_INTERVAL_SECONDS", 600))
NEWS_INTERVAL = int(os.environ.get("NEWS_INTERVAL_SECONDS", 900))
SEEN_IDS_FILE = Path("seen_tweet_ids.json")
TWEET_AGE_HOURS = 12

# ═══════════════════════════════════════════════════════════════
#   CUSTOMIZE YOUR ACCOUNTS HERE
# ═══════════════════════════════════════════════════════════════

CATEGORY_ACCOUNTS = {
    "Funny": {
        "accounts": ["dril", "shitpost_2077", "funnytweeter", "gaming_leake"],
        "emoji": "😂😂😂",
    },
    "Political": {
        "accounts": ["Reuters", "AP", "politico", "axios"],
        "emoji": "🏛️🏛️🏛️",
    },
    "News": {
        "accounts": ["BBCBreaking", "Reuters", "ManotoNews", "nytimes", "guardian", "DiscussingFilm"],
        "emoji": "📰📰📰",
    },
    "Gaming": {
        "accounts": ["IGN", "PlayStation", "Xbox", "GameSpot", "Dexerto", "InternetH0F"],
        "emoji": "🎮🎮🎮",
    },
    "Unhinged": {
        "accounts": ["dril", "TweetsByKosta", "insaneposes", "middleclassfancy", "LocalBateman"],
        "emoji": "🤪🤪🤪",
    },
}

IRAN_ACCOUNTS = [
    "IranIntl_Fa", "BhFak46419", "MatinSenPai", "RFE_FARSI", 
    "Realneo101", "thetwelfth_Imam", "PahlaviReza", "SAVAK071",
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
    "PS5", "XBOX", "Trump", "China", "AI", "Elon Musk", 
    "SpaceX", "Tesla", "Iran", "Israel", "GTA VI", "GTA 6", "War",
]

IRAN_TRENDS = [
    "ایران", "خامنه ای", "دولت", "سیاست", "خبر", "اقتصاد", "جاوید شاه",
]

# ═══════════════════════════════════════════════════════════════


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
    """Translate English to Persian"""
    if not text or len(text) < 5:
        return text
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": text[:450], "langpair": "en|fa"}
        resp = requests.get(url, params=params, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("responseStatus") == 200:
                result = data.get("responseData", {}).get("translatedText", "")
                if result and result != text:
                    return result
    except Exception as e:
        log.warning("Translation failed: %s", e)
    return text


def translate_to_english(text):
    """Translate Persian to English"""
    if not text or len(text) < 5:
        return text
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": text[:450], "langpair": "fa|en"}
        resp = requests.get(url, params=params, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("responseStatus") == 200:
                result = data.get("responseData", {}).get("translatedText", "")
                if result and result != text:
                    return result
    except Exception as e:
        log.warning("Translation failed: %s", e)
    return text


def detect_retweet(text):
    """Detect if tweet is a retweet"""
    match = re.match(r'RT @(\w+):\s*(.*)', text)
    if match:
        retweeter = match.group(1)
        rest = match.group(2)
        original_match = re.search(r'@(\w+)', rest)
        if original_match:
            original_user = original_match.group(1)
            return True, retweeter, rest, original_user
        return True, retweeter, rest, "unknown"
    return False, None, text, None


def format_retweet(retweeter, original_user, original_text, emoji_prefix):
    """Format retweet"""
    separator = "~~~~~~~~~~~~~~~~~~~~~~~~"
    return (
        emoji_prefix + "\n\n"
        "🔄 Retweeted by @" + retweeter + "\n\n"
        + separator + "\n\n"
        "@" + original_user + ":\n\n"
        + original_text + "\n\n"
        "— @Tweet1fy_bot"
    )


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


async def handle_translation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle translation button clicks"""
    query = update.callback_query
    
    try:
        await query.answer(text="Translating...", show_alert=False)
        log.info("Translation request: %s", query.data)
        
        data = query.data
        original_text = query.message.text if query.message.text else ""
        
        # Extract tweet text
        lines = original_text.split("\n")
        tweet_text = ""
        for line in lines:
            line = line.strip()
            if (line and 
                not line.startswith("—") and 
                not line.startswith("@") and 
                not line.startswith("🔄") and
                len(line) > 3):
                tweet_text += line + " "
        
        tweet_text = tweet_text.strip()[:400]
        
        if not tweet_text:
            await query.answer(text="No text found", show_alert=True)
            return
        
        response = ""
        if "translate_fa" in data:
            translated = translate_to_persian(tweet_text)
            response = "🇮🇷 *فارسی ترجمه:*\n\n" + translated
        elif "translate_en" in data:
            translated = translate_to_english(tweet_text)
            response = "🇬🇧 *English Translation:*\n\n" + translated
        else:
            await query.answer(text="Unknown request", show_alert=True)
            return
        
        # Send as separate reply
        await query.message.reply_text(response, parse_mode="Markdown")
        await query.answer(text="✅ Sent!", show_alert=False)
        log.info("Translation sent successfully")
    
    except Exception as e:
        log.error("Translation error: %s", e, exc_info=True)
        try:
            await query.answer(text="Error occurred", show_alert=True)
        except:
            pass


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    keyboard = [[
        InlineKeyboardButton("📱 Open Dashboard", url="https://your-vercel-url.vercel.app"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎉 *Welcome to Tweet1fy Bot!*\n\n"
        "I automatically post trending tweets from:\n"
        "🌍 World trends • 🇮🇷 Iran timeline • 📰 Today's news\n\n"
        "Every 15 minutes in this chat!\n\n"
        "Tap the button below to see all tweets →",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "*Tweet1fy Commands*\n\n"
        "📍 */start* — Welcome message\n"
        "❓ */help* — Show this help\n"
        "📊 */stats* — Bot statistics\n"
        "🔄 */refresh* — Force refresh tweets now\n\n"
        "The bot posts automatically every 15 minutes."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    seen_ids = load_seen_ids()
    stats = (
        "📊 *Bot Statistics*\n\n"
        f"✅ Tweets tracked: {len(seen_ids)}\n"
        f"🌍 Categories: 5 (Funny, Political, News, Gaming, Unhinged)\n"
        f"🇮🇷 Iran accounts: 8\n"
        f"📰 Update cycle: Every 15 minutes\n"
        f"⏱️ Last check: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
    )
    await update.message.reply_text(stats, parse_mode="Markdown")


async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refresh command"""
    await update.message.reply_text("🔄 Refreshing tweets... checking all accounts now!")


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
    """Fetch RSS and filter by age"""
    url = instance + "/" + username + "/rss"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        tweets = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=TWEET_AGE_HOURS)
        
        for item in items:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            guid = item.findtext("guid", link).strip()
            pub_date_str = item.findtext("pubDate", "").strip()
            
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                if pub_date < cutoff_time:
                    continue
            except Exception:
                pass
            
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
        
        log.info("Got %d tweets from @%s (last %dh)", len(tweets), username, TWEET_AGE_HOURS)
        return tweets
    except Exception as e:
        log.warning("RSS error for @%s: %s", username, e)
        return []


def download_media(url):
    """Download media file"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, stream=True)
        if resp.status_code == 200:
            content = resp.content
            file_size = len(content)
            
            is_video = url.lower().endswith((".mp4", ".webm", ".mov", ".avi", ".mkv"))
            
            if is_video:
                log.info("Detected video: %s (%d bytes)", url[-50:], file_size)
                return io.BytesIO(content)
            elif url.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                log.info("Detected image: %s (%d bytes)", url[-50:], file_size)
                return io.BytesIO(content)
            else:
                if file_size > 10240:
                    return io.BytesIO(content)
    except Exception as e:
        log.warning("Media download failed: %s", e)
    return None


async def send_tweet_text(bot, tweet, emoji_prefix):
    """Send tweet as text"""
    is_rt, retweeter, original_text, original_user = detect_retweet(tweet["text"])
    
    if is_rt:
        text = format_retweet(retweeter, original_user, original_text, emoji_prefix)
    else:
        text = format_normal_tweet(tweet["text"], tweet["username"], emoji_prefix)
    
    keyboard = get_translation_buttons(tweet["text"])
    
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Telegram error %s: %s", chat_id, e)


async def send_tweet_media(bot, tweet, emoji_prefix, media_url):
    """Send tweet with media"""
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
                await bot.send_video(chat_id=chat_id, video=media_bytes, caption=caption, reply_markup=keyboard)
            else:
                await bot.send_photo(chat_id=chat_id, photo=media_bytes, caption=caption, reply_markup=keyboard)
            media_bytes.seek(0)
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Telegram media error %s: %s", chat_id, e)


async def run_category_cycle(bot, seen_ids):
    """Post from categories"""
    log.info("=== Category cycle ===")
    instance = get_working_instance()
    if not instance:
        return

    for category, config in CATEGORY_ACCOUNTS.items():
        account = random.choice(config["accounts"])
        tweets = fetch_rss(instance, account)
        new = [t for t in tweets if t["id"] not in seen_ids]
        
        if not new:
            continue
        
        tweet = random.choice(new)
        emoji = config["emoji"]
        
        if tweet.get("media"):
            await send_tweet_media(bot, tweet, emoji, tweet["media"][0])
        else:
            await send_tweet_text(bot, tweet, emoji)
        
        seen_ids.add(tweet["id"])
        save_seen_ids(seen_ids)
        log.info("Posted [%s]", category)
        await asyncio.sleep(4)


async def run_iran_cycle(bot, seen_ids):
    """Post Iran content"""
    log.info("=== Iran cycle ===")
    instance = get_working_instance()
    if not instance:
        return

    account = random.choice(IRAN_ACCOUNTS)
    tweets = fetch_rss(instance, account)
    new = [t for t in tweets if t["id"] not in seen_ids]
    
    if not new:
        return
    
    filtered = [t for t in new if not any(kw.lower() in t["username"].lower() for kw in BLOCKED_KEYWORDS)]
    if not filtered:
        return
    
    tweet = random.choice(filtered)
    emoji = IRAN_EMOJI
    
    if tweet.get("media"):
        await send_tweet_media(bot, tweet, emoji, tweet["media"][0])
    else:
        await send_tweet_text(bot, tweet, emoji)
    
    seen_ids.add(tweet["id"])
    save_seen_ids(seen_ids)


async def run_posting_cycle(bot, seen_ids):
    """Run posting cycle"""
    category_timer = 0
    iran_timer = 0

    while True:
        try:
            if category_timer <= 0:
                await run_category_cycle(bot, seen_ids)
                category_timer = POST_INTERVAL
            
            if iran_timer <= 0:
                await run_iran_cycle(bot, seen_ids)
                iran_timer = 600

            await asyncio.sleep(60)
            category_timer -= 60
            iran_timer -= 60

        except Exception as e:
            log.exception("Posting error: %s", e)
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

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(CommandHandler("refresh", handle_refresh))
    app.add_handler(CallbackQueryHandler(handle_translation))
    
    bot = app.bot
    seen_ids = load_seen_ids()
    log.info("Bot started - Interactive mode")
    
    async with app:
        await app.start()
        try:
            await run_posting_cycle(bot, seen_ids)
        finally:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
