"""
MBT POS - Telegram Setup Tool
MugoByte Technologies | mugobyte.com

Run this script ONCE to find your Telegram Chat ID.
Then it auto-saves the Chat ID into your MBT POS settings.

HOW TO USE:
1. Open Telegram
2. Search for your bot: @MBT_edmus_shop_bot
3. Send it any message (e.g. "hello")
4. Run this script
5. Your Chat ID will be found and saved automatically
"""
import sys
import os
import json
import sqlite3
import time
import requests
from datetime import datetime

# Pre-configured for @mbt_admin1_bot
try:
    from config.deploy import load_deploy_config
    _cfg = load_deploy_config()
    BOT_TOKEN = (_cfg.get("telegram_bot_token") or "").strip()
    BOT_NAME = "@" + (_cfg.get("telegram_bot_username") or "mbt_admin1_bot").lstrip("@")
except Exception:
    BOT_TOKEN = ""
    BOT_NAME = "@mbt_admin1_bot"
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Path to settings DB (relative to this file = project root)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(SCRIPT_DIR, 'data', 'mbt_pos.db')


def print_banner():
    print()
    print("=" * 55)
    print("  MBT POS — Telegram Setup Tool")
    print("  MugoByte Technologies | mugobyte.com")
    print("=" * 55)
    print()


def check_bot():
    print(f"  Checking bot: {BOT_NAME} …", end=' ', flush=True)
    try:
        r = requests.get(f"{BASE_URL}/getMe", timeout=10)
        data = r.json()
        if data.get('ok'):
            bot = data['result']
            print(f"✓  Connected!")
            print(f"  Bot name:  {bot.get('first_name')}")
            print(f"  Username:  @{bot.get('username')}")
            return True
        else:
            print(f"✗  Error: {data.get('description')}")
            return False
    except Exception as e:
        print(f"✗  {e}")
        return False


def get_chat_id():
    print()
    print("  Waiting for a message from you…")
    print(f"  ➜  Open Telegram and send ANY message to {BOT_NAME}")
    print()

    seen = set()
    for attempt in range(60):   # wait up to 60 seconds
        try:
            r = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"timeout": 2, "allowed_updates": ["message"]},
                timeout=10
            )
            data = r.json()
            if not data.get('ok'):
                time.sleep(1)
                continue

            for update in data.get('result', []):
                uid = update.get('update_id')
                if uid in seen:
                    continue
                seen.add(uid)

                msg = update.get('message', {})
                chat = msg.get('chat', {})
                chat_id = chat.get('id')
                name = (chat.get('first_name', '') + ' ' + chat.get('last_name', '')).strip()
                username = chat.get('username', '')
                text = msg.get('text', '')

                if chat_id:
                    print(f"  ✓  Message received from: {name} (@{username})")
                    print(f"  ✓  Chat ID found: {chat_id}")
                    return str(chat_id)

            # Show waiting dots
            dots = '.' * ((attempt % 3) + 1) + '   '
            print(f"\r  Waiting{dots}", end='', flush=True)
            time.sleep(1)

        except KeyboardInterrupt:
            print()
            print("  Cancelled.")
            return None
        except Exception as e:
            time.sleep(1)

    print()
    print("  ✗  Timed out. Did you send a message to the bot?")
    return None


def save_to_db(chat_id):
    if not os.path.exists(DB_PATH):
        print(f"  ⚠  Database not found at: {DB_PATH}")
        print(f"     Run the MBT POS system first, then run this tool again.")
        return False

    try:
        db = sqlite3.connect(DB_PATH)
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ('telegram_chat_id', chat_id, datetime.now().isoformat())
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ('telegram_bot_token', BOT_TOKEN, datetime.now().isoformat())
        )
        db.commit()
        db.close()
        print(f"  ✓  Chat ID saved to database.")
        return True
    except Exception as e:
        print(f"  ✗  Could not save to DB: {e}")
        return False


def send_welcome(chat_id):
    print()
    print("  Sending welcome message…", end=' ', flush=True)
    try:
        msg = (
            "🎉 <b>MBT POS Connected!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Telegram integration is now active.\n\n"
            "You will receive:\n"
            "  🛒 Every new sale notification\n"
            "  ⚠️ System error alerts\n"
            "  🔄 Sync status updates\n\n"
            "<b>MugoByte Technologies</b>\n"
            "<i>mugobyte.com</i>"
        )
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        if r.json().get('ok'):
            print("✓  Welcome message sent!")
        else:
            print(f"  ✗  {r.json().get('description')}")
    except Exception as e:
        print(f"  ✗  {e}")


def print_summary(chat_id):
    print()
    print("=" * 55)
    print("  SETUP COMPLETE")
    print("=" * 55)
    print(f"  Bot Token : {BOT_TOKEN[:20]}…")
    print(f"  Chat ID   : {chat_id}")
    print()
    print("  These are already saved to your MBT POS.")
    print("  You can also verify them in:")
    print("  Settings ➜ Telegram Bot Integration")
    print()
    print("  Powered by MugoByte Technologies | mugobyte.com")
    print("=" * 55)
    print()


def main():
    global BOT_TOKEN, BOT_NAME, BASE_URL
    print_banner()

    print("  To start, you need a Telegram Bot Token from @BotFather.")
    BOT_TOKEN = input("  ➜  Enter Bot Token: ").strip()
    if not BOT_TOKEN:
        print("  ✗  Error: Bot Token is required.")
        return

    BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # Get bot info
    try:
        r = requests.get(f"{BASE_URL}/getMe", timeout=10).json()
        if r.get('ok'):
            BOT_NAME = "@" + r['result']['username']
        else:
            print(f"  ✗  Error: {r.get('description')}")
            return
    except Exception as e:
        print(f"  ✗  Connection error: {e}")
        return

    if not check_bot():
        print()
        print("  Check your internet connection and try again.")
        input("  Press Enter to exit…")
        sys.exit(1)

    chat_id = get_chat_id()
    if not chat_id:
        input("  Press Enter to exit…")
        sys.exit(1)

    saved = save_to_db(chat_id)
    send_welcome(chat_id)
    print_summary(chat_id)

    if not saved:
        print(f"  ➜  Manually enter this in Settings > Telegram Chat ID:")
        print(f"     {chat_id}")
        print()

    input("  Press Enter to close…")


if __name__ == '__main__':
    main()
