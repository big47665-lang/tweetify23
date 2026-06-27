#!/usr/bin/env python3
"""
Tweet Sharing Bot - Final Complete Version
- Proper command registration
- Bilingual announcements (Persian + English)
- Real tweet fetching
- API endpoint for mini app
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
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton, Update, BotCommand
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

CATEGORY_ACCOUNTS = {
    "Funny": {"accounts": ["dril", "shitpost_2077", "funnytweeter", "gaming_leake"], "emoji": "😂😂😂"},
    "Political": {"accounts": ["Reuters", "AP", "politico", "axios"], "emoji": "🏛️🏛️🏛️"},
    "News": {"accounts": ["BBCBreaking", "Reuters", "ManotoNews", "nytimes", "guardian", "DiscussingFilm"], "emoji": "📰📰📰"},
    "Gaming": {"accounts": ["IGN", "PlayStation", "Xbox", "GameSpot", "Dexerto", "InternetH0F"], "emoji": "🎮🎮🎮"},
    "Unhinged": {"accounts": ["dril", "TweetsByKosta", "insaneposes", "middleclassfancy", "LocalBateman"], "emoji": "🤪🤪🤪"},
}

IRAN_ACCOUNTS = ["IranIntl_Fa", "BhFak46419", "MatinSenPai", "RFE_FARSI", "Realneo101", "thetwelfth_Imam", "PahlaviReza", "SAVAK071"]
IRAN_EMOJI = "☀️☀️🦁☀️☀️"
BLOCKED_KEYWORDS = ["Islamic Republic", "gov.ir", "khamenei", "rouhani", "Revolutionary Guard"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.privacydev.net", "https://nitter.poast.org"]
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
TREND_KEYWORDS = ["PS5", "XBOX", "Trump", "China", "AI", "Elon Musk", "SpaceX", "Tesla", "Iran", "Israel", "GTA VI", "GTA 6", "War"]

# Store last tweets for API
last_tweets = {"worldTrending": [], "iranTimeline": [], "news": []}


def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-10000:]))


def clean_text(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"http[s]?://\S+", "", text).strip()
    return text


def detect_retweet(text):
    match = re.match(r'RT @(\w+):\s*(.*)', text)
    if match:
        retweeter = match.group(1)
        rest = match.group(2)
        original_match = re.search(r'@(\w+)', rest)
        if original_match:
            return True, retweeter, rest, original_match.group(1)
        return True, retweeter, rest, "unknown"
    return False, None, text, None


def get_working_instance():
    instances = NITTER_INSTANCES.copy()
    random.shuffle(instances)
    for instance in instances:
        try:
            r = requests.get(instance, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                return instance
        except:
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
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=TWEET_AGE_HOURS)
        
        for item in items:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub_date_str = item.findtext("pubDate", "").strip()
            
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                if pub_date < cutoff_time:
                    continue
            except:
                pass
            
            clean = clean_text(desc) or title
            if not clean or len(clean) < 5:
                continue
            
            tweet_id = link.rstrip("/").split("/")[-1].replace("#m", "")
            media_urls = re.findall(r'src="([^"]*\.(?:jpg|jpeg|png|mp4|webm))"', desc)
            
            tweets.append({
                "id": tweet_id if tweet_id.isdigit() else link,
                "text": clean[:400],
                "username": username,
                "media": media_urls,
                "time": pub_date_str[:10] if pub_date_str else "now",
            })
        
        return tweets
    except Exception as e:
        log.warning("RSS error for @%s: %s", username, e)
        return []


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    keyboard = [[InlineKeyboardButton("📱 Open Dashboard", url="https://your-vercel-url.vercel.app")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎉 *Welcome to Tweetify!*\n\n"
        "I post trending tweets automatically:\n"
        "🌍 World trends • 🇮🇷 Iran timeline\n\n"
        "خوش آمدید! من توییت های ترندی را برای شما ارسال می کنم 🎉\n\n"
        "Tap button → Choose your theme → See live tweets!",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "*Commands / فرمان‌ها*\n\n"
        "/start - Welcome\n"
        "/help - This message\n"
        "/stats - Statistics\n\n"
        "ارسال خودکار: هر 15 دقیقه\n"
        "Auto-posts: Every 15 minutes"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    seen_ids = load_seen_ids()
    stats = (
        "📊 *Bot Stats / آمار*\n\n"
        f"Tweets: {len(seen_ids)}\n"
        f"Categories: 5\n"
        f"Iran accounts: 8\n"
        f"Last update: {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
    )
    await update.message.reply_text(stats, parse_mode="Markdown")


async def announce_tweet(bot, tweet, emoji_prefix, title_en, title_fa):
    """Send bilingual announcement of new tweet"""
    is_rt, retweeter, original_text, original_user = detect_retweet(tweet["text"])
    
    if is_rt:
        text = (
            f"{emoji_prefix}\n\n"
            f"🔄 *Retweeted by* @{retweeter}\n\n"
            f"{'~'*25}\n\n"
            f"@{original_user}:\n\n"
            f"{original_text}\n\n"
            f"— @Tweetify_bot"
        )
    else:
        text = (
            f"{emoji_prefix}\n\n"
            f"**{title_en}** | **{title_fa}**\n\n"
            f"{tweet['text']}\n\n"
            f"@{tweet['username']}"
        )
    
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            await asyncio.sleep(1)
        except TelegramError as e:
            log.error("Error: %s", e)


async def run_category_cycle(bot, seen_ids):
    """Post from categories"""
    log.info("=== Category Cycle ===")
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
        
        # Store for API
        if len(last_tweets["worldTrending"]) < 10:
            last_tweets["worldTrending"].append(tweet)
        
        await announce_tweet(bot, tweet, emoji, f"{category} Tweets", f"توییت‌های {category}")
        
        seen_ids.add(tweet["id"])
        save_seen_ids(seen_ids)
        await asyncio.sleep(4)


async def run_iran_cycle(bot, seen_ids):
    """Post Iran content"""
    log.info("=== Iran Cycle ===")
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
    
    if len(last_tweets["iranTimeline"]) < 10:
        last_tweets["iranTimeline"].append(tweet)
    
    await announce_tweet(bot, tweet, emoji, "Iran News", "اخبار ایران")
    
    seen_ids.add(tweet["id"])
    save_seen_ids(seen_ids)


async def run_posting_cycle(bot, seen_ids):
    """Main posting loop"""
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
            log.exception("Error: %s", e)
            await asyncio.sleep(30)


async def set_commands(app):
    """Register commands with Telegram"""
    commands = [
        BotCommand("start", "🎉 Start the bot"),
        BotCommand("help", "❓ Show help"),
        BotCommand("stats", "📊 Show statistics"),
    ]
    await app.bot.set_my_commands(commands)
    log.info("Commands registered with Telegram")


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
    
    # Register commands
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("stats", handle_stats))
    
    bot = app.bot
    seen_ids = load_seen_ids()
    
    log.info("Bot started - Bilingual + Real tweets")
    
    async with app:
        await set_commands(app)
        await app.start()
        try:
            await run_posting_cycle(bot, seen_ids)
        finally:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
