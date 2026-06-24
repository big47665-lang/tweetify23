#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Realistic tweet screenshots, no emojis in image (uses text icons instead)
- Zero caption
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
# ═══════════════════════════════════════════════════════════════

CATEGORY_ACCOUNTS = {
    "Funny": [
        "dril",
        "dadsaysjokes",
        "funnytweeter",
        "thedad",
        "middleclassfancy",
    ],
    "Political": [
        "Reuters",
        "AP",
        "BBCWorld",
        "politico",
        "axios",
    ],
    "News": [
        "BBCBreaking",
        "Reuters",
        "AP",
        "nytimes",
        "guardian",
    ],
    "Gaming": [
        "IGN",
        "PlayStation",
        "Xbox",
        "NintendoAmerica",
        "GameSpot",
    ],
    "Unhinged": [
        "dril",
        "NotGaryBusey",
        "TweetsByKosta",
        "middleclassfancy",
    ],
    "Persian": [
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

CATEGORY_COLORS = {
    "Funny":    (234, 179, 8),
    "Political":(59, 130, 246),
    "News":     (239, 68, 68),
    "Gaming":   (139, 92, 246),
    "Unhinged": (236, 72, 153),
    "Persian":  (16, 185, 129),
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
            link  = item.findtext("link", "").strip()
            desc  = item.findtext("description", "").strip()
            guid  = item.findtext("guid", link).strip()
            clean = re.sub(r"<[^>]+>", "", desc).strip()
            # strip emoji from text so they don't appear as boxes
            clean = re.sub(r"[^\x00-\x7F\u0600-\u06FF\u0750-\u077F ]", "", clean).strip()
            text  = clean if clean else title
            if not text or len(text) < 5:
                continue
            tweet_id = link.rstrip("/").split("/")[-1].replace("#m", "")
            tweets.append({
                "id":       tweet_id if tweet_id.isdigit() else guid,
                "text":     text[:350],
                "username": username,
                "url":      "https://twitter.com/" + username,
            })
        log.info("Got %d tweets from @%s", len(tweets), username)
        return tweets
    except Exception as e:
        log.warning("RSS error for @%s: %s", username, e)
        return []


def load_font(bold=False, size=20):
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    reg_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in (bold_paths if bold else reg_paths):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_text(text, font, max_w, draw):
    words = text.split()
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


def make_tweet_screenshot(text, username, category):
    W       = 920
    PAD     = 32
    AVATAR  = 58
    BG      = (255, 255, 255)
    BLACK   = (15, 20, 25)
    GRAY    = (83, 100, 113)
    LGRAY   = (247, 249, 249)
    BORDER  = (207, 217, 222)
    BLUE    = (29, 155, 240)
    accent  = CATEGORY_COLORS.get(category, BLUE)

    f_name   = load_font(bold=True,  size=23)
    f_handle = load_font(bold=False, size=19)
    f_text   = load_font(bold=False, size=27)
    f_stats  = load_font(bold=False, size=18)
    f_cat    = load_font(bold=True,  size=17)

    dummy = Image.new("RGB", (W, 100), BG)
    ddraw = ImageDraw.Draw(dummy)
    lines  = wrap_text(text, f_text, W - PAD * 2, ddraw)
    line_h = 40

    CAT_H   = 40
    HEAD_H  = 80
    TEXT_H  = len(lines) * line_h + 28
    STATS_H = 52
    TOTAL_H = CAT_H + HEAD_H + TEXT_H + STATS_H + 4

    img  = Image.new("RGB", (W, TOTAL_H), BG)
    draw = ImageDraw.Draw(img)

    # ── Category bar ─────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, CAT_H)], fill=accent)
    cat_label = category.upper() + "  |  X / Twitter"
    draw.text((PAD, 10), cat_label, font=f_cat, fill=(255, 255, 255))

    # ── Avatar ───────────────────────────────────────────────────
    av_x = PAD
    av_y = CAT_H + 12
    draw.ellipse([av_x, av_y, av_x + AVATAR, av_y + AVATAR], fill=BLUE)
    init = username[0].upper()
    ib   = draw.textbbox((0, 0), init, font=f_name)
    draw.text(
        (av_x + (AVATAR - ib[2]) // 2, av_y + (AVATAR - ib[3]) // 2 - 2),
        init, font=f_name, fill=(255, 255, 255)
    )

    # ── Name + handle ─────────────────────────────────────────────
    nx = av_x + AVATAR + 14
    ny = av_y + 4
    draw.text((nx, ny), username, font=f_name, fill=BLACK)

    # Verified badge — solid blue circle with white "v"
    nw  = draw.textbbox((0, 0), username, font=f_name)[2]
    bx  = nx + nw + 7
    by  = ny + 2
    draw.ellipse([bx, by, bx + 20, by + 20], fill=BLUE)
    draw.text((bx + 5, by + 1), "v", font=f_stats, fill=(255, 255, 255))

    draw.text((nx, ny + 30), "@" + username, font=f_handle, fill=GRAY)

    # Time
    t_str = str(random.randint(1, 22)) + "h"
    tw    = draw.textbbox((0, 0), t_str, font=f_handle)[2]
    draw.text((W - PAD - tw, ny + 6), t_str, font=f_handle, fill=GRAY)
    draw.text((W - PAD - tw - 14, ny + 6), ".", font=f_handle, fill=GRAY)

    # ── Divider ───────────────────────────────────────────────────
    sep_y = CAT_H + HEAD_H
    draw.line([(PAD, sep_y), (W - PAD, sep_y)], fill=BORDER, width=1)

    # ── Tweet text ────────────────────────────────────────────────
    ty = sep_y + 16
    for line in lines:
        draw.text((PAD, ty), line, font=f_text, fill=BLACK)
        ty += line_h

    # ── Stats row ────────────────────────────────────────────────
    st_y = TOTAL_H - STATS_H
    draw.line([(PAD, st_y), (W - PAD, st_y)], fill=BORDER, width=1)
    draw.rectangle([(0, st_y), (W, TOTAL_H)], fill=LGRAY)
    draw.line([(PAD, st_y), (W - PAD, st_y)], fill=BORDER, width=1)

    def fmt(n):
        if n >= 1000000:
            return str(round(n / 1000000, 1)) + "M"
        if n >= 1000:
            return str(round(n / 1000, 1)) + "K"
        return str(n)

    stats = [
        ("Reply",    fmt(random.randint(10, 999))),
        ("Retweet",  fmt(random.randint(50, 9999))),
        ("Like",     fmt(random.randint(500, 99999))),
        ("Views",    fmt(random.randint(5000, 999999))),
    ]
    sx = PAD
    for label, val in stats:
        draw.text((sx, st_y + 16), val + " " + label, font=f_stats, fill=GRAY)
        sx += 190

    # X watermark
    xw = draw.textbbox((0, 0), "X", font=f_cat)[2]
    draw.text((W - PAD - xw, st_y + 14), "X", font=f_cat, fill=BLUE)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


async def post_tweet(bot, tweet, category):
    try:
        img = make_tweet_screenshot(tweet["text"], tweet["username"], category)
        for chat_id in CHAT_IDS:
            try:
                await bot.send_photo(chat_id=chat_id, photo=img)
                img.seek(0)
                await asyncio.sleep(1)
            except TelegramError as e:
                log.error("Telegram error %s: %s", chat_id, e)
    except Exception as e:
        log.error("Image error: %s", e)
        fallback = tweet["text"][:300] + "\n\n-- @" + tweet["username"]
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
        tweets  = fetch_rss(instance, account)
        new     = [t for t in tweets if t["id"] not in seen_ids]
        if not new:
            log.info("No new tweets from @%s", account)
            continue
        tweet = random.choice(new)
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

    bot      = Bot(token=TELEGRAM_BOT_TOKEN)
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
