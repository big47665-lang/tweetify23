#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Sends tweets as realistic tweet screenshots
- Zero caption - just the image, like a real screenshot
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

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
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
                "text": text[:350],
                "username": username,
                "url": "https://twitter.com/" + username,
            })
        log.info("Got %d tweets from @%s", len(tweets), username)
        return tweets
    except Exception as e:
        log.warning("RSS error for @%s: %s", username, e)
        return []


def make_tweet_screenshot(text, username, category):
    """
    Renders a card that looks like a real tweet screenshot:
    - White background
    - Avatar circle with initial
    - Bold display name + @handle + verified badge
    - Tweet text in black
    - Like/retweet/reply icons row
    - Subtle top label showing category
    """
    W = 900
    PAD = 28
    AVATAR = 56
    BG = (255, 255, 255)
    TEXT_BLACK = (15, 20, 25)
    GRAY = (83, 100, 113)
    LIGHT_GRAY = (239, 243, 244)
    BLUE = (29, 155, 240)
    BORDER = (207, 217, 222)

    # Fonts
    def load_font(bold=False, size=20):
        bold_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        reg_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        paths = bold_paths if bold else reg_paths
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    f_name     = load_font(bold=True,  size=22)
    f_handle   = load_font(bold=False, size=19)
    f_text     = load_font(bold=False, size=26)
    f_stats    = load_font(bold=False, size=18)
    f_category = load_font(bold=True,  size=17)

    # Wrap tweet text
    def wrap(txt, font, max_w, draw):
        words = txt.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    dummy = Image.new("RGB", (W, 100), BG)
    ddraw = ImageDraw.Draw(dummy)
    max_tw = W - PAD * 2
    lines = wrap(text, f_text, max_tw, ddraw)
    line_h = 38

    # Heights of sections
    CAT_H    = 38   # top category strip
    HEAD_H   = 76   # avatar + name row
    TEXT_H   = len(lines) * line_h + 24
    STATS_H  = 52   # icons row
    TOTAL_H  = CAT_H + HEAD_H + TEXT_H + STATS_H + 8

    img = Image.new("RGB", (W, TOTAL_H), BG)
    draw = ImageDraw.Draw(img)

    # ── Category strip at top ─────────────────────────────────────
    draw.rectangle([(0, 0), (W, CAT_H)], fill=LIGHT_GRAY)
    cat_text = category + "  •  shared by bot"
    draw.text((PAD, 10), cat_text, font=f_category, fill=GRAY)

    # ── Header row ────────────────────────────────────────────────
    hy = CAT_H + 12
    # Avatar circle
    av_x, av_y = PAD, hy
    draw.ellipse([av_x, av_y, av_x + AVATAR, av_y + AVATAR], fill=BLUE)
    init = username[0].upper()
    ib = draw.textbbox((0, 0), init, font=f_name)
    draw.text(
        (av_x + (AVATAR - ib[2]) // 2, av_y + (AVATAR - ib[3]) // 2 - 2),
        init, font=f_name, fill=(255, 255, 255)
    )

    # Display name
    name_x = av_x + AVATAR + 14
    name_y = hy + 4
    draw.text((name_x, name_y), username, font=f_name, fill=TEXT_BLACK)

    # Blue verified checkmark circle
    nw = draw.textbbox((0, 0), username, font=f_name)[2]
    cx = name_x + nw + 6
    cy = name_y + 3
    draw.ellipse([cx, cy, cx + 20, cy + 20], fill=BLUE)
    draw.text((cx + 4, cy + 1), "✓", font=f_stats, fill=(255, 255, 255))

    # @handle underneath name
    draw.text((name_x, name_y + 28), "@" + username, font=f_handle, fill=GRAY)

    # Time ago (fake but realistic)
    time_str = str(random.randint(1, 23)) + "h"
    tw = draw.textbbox((0, 0), time_str, font=f_handle)[2]
    draw.text((W - PAD - tw, name_y + 4), time_str, font=f_handle, fill=GRAY)

    # Separator line under header
    sep_y = CAT_H + HEAD_H
    draw.line([(PAD, sep_y), (W - PAD, sep_y)], fill=BORDER, width=1)

    # ── Tweet text ────────────────────────────────────────────────
    ty = sep_y + 16
    for line in lines:
        draw.text((PAD, ty), line, font=f_text, fill=TEXT_BLACK)
        ty += line_h

    # ── Stats / icons row ─────────────────────────────────────────
    stats_y = TOTAL_H - STATS_H
    draw.line([(PAD, stats_y), (W - PAD, stats_y)], fill=BORDER, width=1)

    # Fake but plausible stats
    replies  = str(random.randint(10, 999))
    retweets = str(random.randint(50, 9999))
    likes    = str(random.randint(100, 99999))

    icons = [
        ("💬", replies),
        ("🔁", retweets),
        ("❤️", likes),
        ("📊", str(random.randint(1000, 500000))),
    ]

    sx = PAD
    for icon, val in icons:
        draw.text((sx, stats_y + 14), icon + " " + val, font=f_stats, fill=GRAY)
        sx += 180

    # X watermark bottom right
    draw.text((W - PAD - 16, stats_y + 14), "𝕏", font=f_stats, fill=LIGHT_GRAY)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


async def post_tweet(bot, tweet, category):
    try:
        img = make_tweet_screenshot(tweet["text"], tweet["username"], category)
        for chat_id in CHAT_IDS:
            try:
                # NO caption — just the image, like a real screenshot
                await bot.send_photo(chat_id=chat_id, photo=img)
                img.seek(0)
                await asyncio.sleep(1)
            except TelegramError as e:
                log.error("Telegram error %s: %s", chat_id, e)
    except Exception as e:
        log.error("Image error: %s", e)
        # Fallback: plain text only
        fallback = tweet["text"][:300] + "\n\n— @" + tweet["username"]
        for chat_id in CHAT_IDS:
            try:
                await bot.send_message(chat_id=chat_id, text=fallback)
            except TelegramError as te:
                log.error("Fallback error %s: %s", chat_id, te)


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
        await post_tweet(bot, tweet, category)
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
