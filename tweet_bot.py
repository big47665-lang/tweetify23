#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Sends tweets as screenshots (images)
- Only shows @username
- Easy to customize accounts at the top of the file
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
from PIL import Image, ImageDraw, ImageFont
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

# ═══════════════════════════════════════════════════════════════
#   CUSTOMIZE YOUR ACCOUNTS HERE
#   Add or remove any Twitter/X username you want per category
# ═══════════════════════════════════════════════════════════════

CATEGORY_ACCOUNTS = {
    "😂 Funny": [
        "dril",
        "dadsaysjokes",
        "funnytweeter",
        "thedad",
        "middleclassfancy",
    ],
    "🏛️ Political": [
        "Reuters",
        "AP",
        "BBCWorld",
        "politico",
        "axios",
    ],
    "📰 News": [
        "BBCBreaking",
        "Reuters",
        "AP",
        "nytimes",
        "guardian",
    ],
    "🎮 Gaming": [
        "IGN",
        "PlayStation",
        "Xbox",
        "NintendoAmerica",
        "GameSpot",
    ],
    "🤦 Unhinged": [
        "dril",
        "NotGaryBusey",
        "TweetsByKosta",
        "middleclassfancy",
    ],
    "🇮🇷 Persian": [
        "IranIntl_Fa",
        "bbcpersian",
        "VOAIran",
        "manototv",
        "IranWire",
    ],
}

# ═══════════════════════════════════════════════════════════════

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.1d4.us",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSS reader)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}


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
        items = root.findall(".//item")
        tweets = []

        for item in items:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            guid = item.findtext("guid", link).strip()

            clean = re.sub(r"<[^>]+>", "", desc).strip()
            text = clean if clean else title
            if not text or len(text) < 5:
                continue

            tweet_id = link.rstrip("/").split("/")[-1].replace("#m", "")

            tweets.append({
                "id": tweet_id if tweet_id.isdigit() else guid,
                "text": text[:400],
                "username": username,
                "url": "https://twitter.com/" + username,
            })

        log.info("Got %d tweets from @%s", len(tweets), username)
        return tweets

    except Exception as e:
        log.warning("RSS error for @%s: %s", username, e)
        return []


def make_tweet_image(text, username, category):
    # Card size
    width = 800
    padding = 40
    avatar_size = 60

    # Colors — dark Twitter-like theme
    bg_color = (21, 32, 43)
    card_color = (25, 39, 52)
    text_color = (255, 255, 255)
    handle_color = (110, 118, 125)
    accent_color = (29, 161, 242)
    border_color = (56, 68, 77)

    # Try to load a font, fall back to default
    try:
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        font_handle = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        font_category = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except Exception:
        font_text = ImageFont.load_default()
        font_handle = font_text
        font_category = font_text

    # Wrap text
    def wrap_text(txt, font, max_width, draw):
        words = txt.split()
        lines = []
        current = ""
        for word in words:
            test = (current + " " + word).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    # First pass to calculate height
    dummy = Image.new("RGB", (width, 100))
    draw = ImageDraw.Draw(dummy)
    max_text_width = width - padding * 2 - avatar_size - 20
    lines = wrap_text(text, font_text, max_text_width, draw)
    line_height = 30
    text_block_height = len(lines) * line_height

    total_height = padding + avatar_size + 20 + text_block_height + 60 + padding

    # Create real image
    img = Image.new("RGB", (width, total_height), bg_color)
    draw = ImageDraw.Draw(img)

    # Card background with rounded feel (border)
    draw.rectangle([(10, 10), (width - 10, total_height - 10)], fill=card_color, outline=border_color, width=1)

    # Category badge
    cat_x = padding
    cat_y = padding - 5
    draw.text((cat_x, cat_y), category, font=font_category, fill=accent_color)

    # Avatar circle placeholder
    av_x = padding
    av_y = padding + 30
    draw.ellipse([(av_x, av_y), (av_x + avatar_size, av_y + avatar_size)], fill=accent_color)
    initial = username[0].upper() if username else "T"
    draw.text((av_x + 18, av_y + 14), initial, font=font_category, fill=(255, 255, 255))

    # Username @handle
    handle_x = av_x + avatar_size + 15
    handle_y = av_y + 10
    draw.text((handle_x, handle_y), "@" + username, font=font_handle, fill=handle_color)

    # Blue verified-style dot
    dot_x = handle_x + draw.textbbox((0, 0), "@" + username, font=font_handle)[2] + 8
    draw.ellipse([(dot_x, handle_y + 5), (dot_x + 12, handle_y + 17)], fill=accent_color)

    # Tweet text
    text_y = av_y + avatar_size + 20
    for line in lines:
        draw.text((padding, text_y), line, font=font_text, fill=text_color)
        text_y += line_height

    # Twitter/X logo watermark bottom right
    draw.text((width - padding - 20, total_height - padding - 10), "𝕏", font=font_category, fill=handle_color)

    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes


async def post_tweet_image(bot, tweet, category):
    try:
        img = make_tweet_image(tweet["text"], tweet["username"], category)
        caption = "@" + tweet["username"] + "\n🔗 " + tweet["url"]
        for chat_id in CHAT_IDS:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=img,
                    caption=caption,
                )
                img.seek(0)
                log.info("Sent image to %s", chat_id)
                await asyncio.sleep(1)
            except TelegramError as e:
                log.error("Telegram error %s: %s", chat_id, e)
    except Exception as e:
        log.error("Image creation failed: %s", e)
        # Fallback to text
        text = category + "\n\n" + tweet["text"] + "\n\n@" + tweet["username"] + "\n" + tweet["url"]
        for chat_id in CHAT_IDS:
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except TelegramError as te:
                log.error("Fallback text error %s: %s", chat_id, te)


async def run_cycle(bot, seen_ids):
    log.info("=== Cycle started %s ===", datetime.now(timezone.utc).isoformat())

    instance = get_working_instance()
    if not instance:
        log.error("All Nitter instances down!")
        return

    posted = 0

    for category, accounts in CATEGORY_ACCOUNTS.items():
        account = random.choice(accounts)
        tweets = fetch_rss(instance, account)
        new_tweets = [t for t in tweets if t["id"] not in seen_ids]

        if not new_tweets:
            log.info("No new tweets from @%s", account)
            continue

        tweet = random.choice(new_tweets)
        await post_tweet_image(bot, tweet, category)
        seen_ids.add(tweet["id"])
        save_seen_ids(seen_ids)
        log.info("Posted [%s] from @%s", category, account)
        posted += 1
        await asyncio.sleep(5)

    log.info("=== Done. Posted %d. Next in %ds ===", posted, POST_INTERVAL)


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
    log.info("Bot started. Posting every %ds", POST_INTERVAL)

    while True:
        try:
            await run_cycle(bot, seen_ids)
        except Exception as e:
            log.exception("Error: %s", e)
        await asyncio.sleep(POST_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
