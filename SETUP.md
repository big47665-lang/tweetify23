# 🤖 Tweet Sharing Telegram Bot — Setup Guide

A bot that automatically fetches tweets (Funny, Political, News, Gaming, Unhinged)
in **Persian 🇮🇷** and **English 🇬🇧** and posts them to your Telegram groups.

---

## 📦 Step 1 — Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 🔑 Step 2 — Get Your API Keys

### Telegram Bot Token
1. Open Telegram → message **@BotFather**
2. Send `/newbot` and follow the steps
3. Copy the token (looks like `123456789:ABCDefgh...`)

### Make Bot an Admin in Your Group
1. Add the bot to your Telegram group/channel
2. Go to group settings → Administrators → Add Admin → select your bot
3. Give it permission to **Send Messages**

### Get the Group Chat ID
1. Add **@userinfobot** to your group temporarily
2. It will send the chat ID (like `-1001234567890`)
3. Remove it after

### Twitter/X Bearer Token (Free Tier)
1. Go to https://developer.twitter.com
2. Sign up for a **Free** developer account
3. Create a new App → copy the **Bearer Token**
4. Free tier: 500,000 tweet reads/month (plenty for this bot)

---

## ▶️ Step 3 — Run the Bot

```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCDefgh..."
export TWITTER_BEARER_TOKEN="AAAAAAAAAAAAAAAAAAAAAxxxxxxxx..."
export TELEGRAM_CHAT_IDS="-1001234567890,-1009876543210"

python tweet_bot.py
```

You can post to **multiple groups** by separating chat IDs with commas.

---

## ⚙️ Optional Settings

| Variable | Default | Description |
|---|---|---|
| `POST_INTERVAL_SECONDS` | `900` | Seconds between posting cycles (900 = 15 min) |
| `TWEETS_PER_CATEGORY` | `10` | Tweets fetched per search query per cycle |

Example with custom interval (every 30 minutes):
```bash
export POST_INTERVAL_SECONDS=1800
```

---

## 📂 Files

| File | Purpose |
|---|---|
| `tweet_bot.py` | Main bot script |
| `requirements.txt` | Python dependencies |
| `seen_tweet_ids.json` | Auto-created — tracks posted tweets to avoid duplicates |

---

## 🗂️ Categories Posted

| Category | Search Languages |
|---|---|
| 😂 Funny | English + Persian |
| 🏛️ Political | English + Persian |
| 📰 News | English + Persian |
| 🎮 Gaming | English + Persian |
| 🤦 Unhinged | English + Persian |

---

## 🔁 Keep Running 24/7

### Option A — screen (simple)
```bash
screen -S tweetbot
python tweet_bot.py
# Press Ctrl+A then D to detach
```

### Option B — systemd service (recommended for VPS)
Create `/etc/systemd/system/tweetbot.service`:
```ini
[Unit]
Description=Tweet Sharing Telegram Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/tweet_bot.py
Environment=TELEGRAM_BOT_TOKEN=your_token
Environment=TWITTER_BEARER_TOKEN=your_bearer
Environment=TELEGRAM_CHAT_IDS=-1001234567890
Restart=always

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl enable tweetbot
sudo systemctl start tweetbot
```
