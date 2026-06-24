#!/usr/bin/env python3
"""
Tweet Sharing Telegram Bot
- Beautiful tweet card images
- Only link shown in caption
- Easy account customization at the top
"""

import os
import json
import logging
import random
import asyncio
import re
import io
import math
from datetime import datetime, timezone
from pathlib import Path
import requests
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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
      "shitpost_2077",  
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
      "",  
      "GameSpot",  
      "Dexerto",  
  ],  
  "🤦 Unhinged": [  
      "dril",  
      "NotGaryBusey",  
      "TweetsByKosta",  
      "middleclassfancy",  
      "insaneposes",  
  ],  
  "🇮🇷 Persian": [  
      "IranIntl_Fa",  
      "MatinSenPai",  
      "BhFak46419",  
      "manototv",  
      "IranWire",  
      "Realneo101",  
      "thetwelfth_Imam"
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

# Category accent colors (R, G, B)
CATEGORY_COLORS = {
    "😂 Funny":      (255, 200, 0),
    "🏛️ Political":  (99, 179, 237),
    "📰 News":       (252, 129, 74),
    "🎮 Gaming":     (154, 117, 234),
    "🤦 Unhinged":   (252, 92, 125),
    "🇮🇷 Persian":   (71, 207, 132),
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


def draw_rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    x1, y1, x2, y2 = xy
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
    draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
    draw.ellipse([x1, y2 - radius * 2, x1 + radius * 2, y2], fill=fill)
    draw.ellipse([x2 - radius * 2, y2 - radius * 2, x2, y2], fill=fill)
    if outline:
        draw.arc([x1, y1, x1 + radius * 2, y1 + radius * 2], 180, 270, fill=outline, width=width)
        draw.arc([x2 - radius * 2, y1, x2, y1 + radius * 2], 270, 360, fill=outline, width=width)
        draw.arc([x1, y2 - radius * 2, x1 + radius * 2, y2], 90, 180, fill=outline, width=width)
        draw.arc([x2 - radius * 2, y2 - radius * 2, x2, y2], 0, 90, fill=outline, width=width)
        draw.line([x1 + radius, y1, x2 - radius, y1], fill=outline, width=width)
        draw.line([x1 + radius, y2, x2 - radius, y2], fill=outline, width=width)
        draw.line([x1, y1 + radius, x1, y2 - radius], fill=outline, width=width)
        draw.line([x2, y1 + radius, x2, y2 - radius], fill=outline, width=width)


def make_tweet_image(text, username, category):
    W = 900
    PAD = 48
    AVATAR = 64

    accent = CATEGORY_COLORS.get(category, (29, 161, 242))
    dark_accent = tuple(max(0, c - 60) for c in accent)

    # Fonts
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]

    def load_font(paths, size):
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    f_text    = load_font(font_paths, 26)
    f_handle  = load_font(font_paths, 20)
    f_cat     = load_font(bold_paths, 21)
    f_small   = load_font(font_paths, 17)

    # Wrap text
    def wrap(txt, font, max_w, draw):
        words = txt.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textbbox((0,0), test, font=font)[2] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    dummy_img = Image.new("RGB", (W, 100))
    dummy_draw = ImageDraw.Draw(dummy_img)
    text_w = W - PAD * 2
    lines = wrap(text, f_text, text_w, dummy_draw)
    line_h = 36
    text_h = len(lines) * line_h

    # Layout heights
    TOP_BAR    = 56   # category stripe
    HEADER_H   = 90   # avatar + name row
    TEXT_H     = text_h + 20
    FOOTER_H   = 54
    TOTAL_H    = TOP_BAR + HEADER_H + TEXT_H + FOOTER_H + 20

    img = Image.new("RGB", (W, TOTAL_H), (10, 14, 20))
    draw = ImageDraw.Draw(img)

    # ── Gradient-ish background strips ───────────────────────────
    for y in range(TOTAL_H):
        ratio = y / TOTAL_H
        r = int(10 + ratio * 8)
        g = int(14 + ratio * 10)
        b = int(20 + ratio * 18)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # ── Top accent bar ────────────────────────────────────────────
    for x in range(W):
        ratio = x / W
        r = int(accent[0] * (1 - ratio * 0.4) + dark_accent[0] * ratio * 0.4)
        g = int(accent[1] * (1 - ratio * 0.4) + dark_accent[1] * ratio * 0.4)
        b = int(accent[2] * (1 - ratio * 0.4) + dark_accent[2] * ratio * 0.4)
        draw.line([(x, 0), (x, TOP_BAR)], fill=(r, g, b))

    # Category label on bar
    cat_bbox = draw.textbbox((0,0), category, font=f_cat)
    cat_w = cat_bbox[2]
    draw.text(((W - cat_w) // 2, (TOP_BAR - cat_bbox[3]) // 2), category, font=f_cat, fill=(255,255,255))

    # ── Card body ─────────────────────────────────────────────────
    card_y = TOP_BAR + 10
    card_h = TOTAL_H - TOP_BAR - 10
    draw_rounded_rect(draw, (12, card_y, W - 12, TOTAL_H - 8), 18,
                      fill=(18, 24, 34), outline=(40, 52, 68), width=1)

    # ── Avatar circle ─────────────────────────────────────────────
    av_x = PAD
    av_y = card_y + 18
    # Glow
    for r in range(6, 0, -1):
        alpha = 30 + r * 8
        glow = tuple(min(255, c + 40) for c in accent)
        draw.ellipse([av_x - r, av_y - r, av_x + AVATAR + r, av_y + AVATAR + r],
                     fill=(*glow, alpha) if False else glow)
    draw.ellipse([av_x, av_y, av_x + AVATAR, av_y + AVATAR], fill=accent)
    initial = username[0].upper()
    ib = draw.textbbox((0,0), initial, font=f_cat)
    draw.text((av_x + (AVATAR - ib[2]) // 2, av_y + (AVATAR - ib[3]) // 2 - 2),
              initial, font=f_cat, fill=(255,255,255))

    # ── Name + handle ─────────────────────────────────────────────
    name_x = av_x + AVATAR + 16
    name_y = av_y + 8
    draw.text((name_x, name_y), username, font=f_cat, fill=(240,240,240))
    # Blue checkmark style badge
    check_x = name_x + draw.textbbox((0,0), username, font=f_cat)[2] + 8
    draw.ellipse([check_x, name_y + 3, check_x + 18, name_y + 21], fill=accent)
    draw.text((check_x + 3, name_y + 2), "✓", font=f_small, fill=(255,255,255))
    draw.text((name_x, name_y + 30), "@" + username, font=f_handle, fill=(100, 116, 135))

    # ── Divider ───────────────────────────────────────────────────
    div_y = card_y + HEADER_H
    draw.line([(PAD, div_y), (W - PAD, div_y)], fill=(35, 46, 62), width=1)

    # ── Tweet text ────────────────────────────────────────────────
    ty = div_y + 18
    for line in lines:
        draw.text((PAD, ty), line, font=f_text, fill=(225, 232, 240))
        ty += line_h

    # ── Footer ────────────────────────────────────────────────────
    footer_y = TOTAL_H - FOOTER_H
    draw.line([(PAD, footer_y), (W - PAD, footer_y)], fill=(35, 46, 62), width=1)

    # X logo + "View on X"
    draw.text((PAD, footer_y + 14), "𝕏  View on X", font=f_small, fill=(100, 116, 135))

    # Timestamp
    ts = datetime.now(timezone.utc).strftime("%H:%M · %b %d, %Y")
    ts_w = draw.textbbox((0,0), ts, font=f_small)[2]
    draw.text((W - PAD - ts_w, footer_y + 14), ts, font=f_small, fill=(70, 88, 108))

    # ── Thin accent line at very bottom ──────────────────────────
    for x in range(W):
        ratio = x / W
        r = int(accent[0] * (1 - ratio) + dark_accent[0] * ratio)
        g = int(accent[1] * (1 - ratio) + dark_accent[1] * ratio)
        b = int(accent[2] * (1 - ratio) + dark_accent[2] * ratio)
        draw.point((x, TOTAL_H - 1), fill=(r, g, b))

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


async def post_tweet_image(bot, tweet, category):
    try:
        img = make_tweet_image(tweet["text"], tweet["username"], category)
        # Clean caption: just the link
        caption = "🔗 " + tweet["url"]
        for chat_id in CHAT_IDS:
            try:
                await bot.send_photo(chat_id=chat_id, photo=img, caption=caption)
                img.seek(0)
                await asyncio.sleep(1)
            except TelegramError as e:
                log.error("Telegram error %s: %s", chat_id, e)
    except Exception as e:
        log.error("Image error: %s", e)
        # Text fallback
        fallback = category + "\n\n" + tweet["text"][:300] + "\n\n🔗 " + tweet["url"]
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
