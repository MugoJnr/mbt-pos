import os
"""
MBT POS - Internet Monitor & Telegram Sync Service
Runs as background thread; monitors connectivity and syncs queued data
"""
import threading
import time
import socket
import requests
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

TELEGRAM_API     = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_DOC_API = "https://api.telegram.org/bot{token}/sendDocument"
CHECK_HOSTS = [("8.8.8.8", 53), ("1.1.1.1", 53), ("8.8.4.4", 53)]
CHECK_INTERVAL = 10   # seconds between checks


class InternetMonitor(threading.Thread):
    """
    Continuously monitors internet connection.
    Fires callbacks on status change.
    Handles Telegram sync when online.
    """

    def __init__(self, db_path, config_getter, status_callback=None):
        super().__init__(daemon=True, name="InternetMonitor")
        self.db_path = db_path
        self.config_getter = config_getter      # callable → dict of settings
        self.status_callback = status_callback  # called with (is_connected: bool)
        self.is_connected = False
        self.last_checked = None
        self.sync_status = "idle"               # idle / syncing / synced / failed
        self._stop_event = threading.Event()
        self._sync_lock = threading.Lock()

    def stop(self):
        self._stop_event.set()

    def check_connection(self):
        for host, port in CHECK_HOSTS:
            try:
                s = socket.create_connection((host, port), timeout=3)
                s.close()
                return True
            except OSError:
                continue
        return False

    def run(self):
        while not self._stop_event.is_set():
            connected = self.check_connection()
            self.last_checked = datetime.now()

            if connected != self.is_connected:
                self.is_connected = connected
                logger.info(f"Connection status changed: {'ONLINE' if connected else 'OFFLINE'}")
                if self.status_callback:
                    try:
                        self.status_callback(connected)
                    except Exception as e:
                        logger.error(f"Status callback error: {e}")

                if connected:
                    self._do_sync()

            elif connected:
                # Periodically sync even if already connected
                self._do_sync()

            self._stop_event.wait(CHECK_INTERVAL)

    def force_sync(self):
        """Called by manual refresh button."""
        connected = self.check_connection()
        self.last_checked = datetime.now()
        prev = self.is_connected
        self.is_connected = connected
        if self.status_callback and connected != prev:
            try:
                self.status_callback(connected)
            except Exception:
                pass
        if connected:
            self._do_sync()
        return connected

    def _do_sync(self):
        if not self._sync_lock.acquire(blocking=False):
            return  # already syncing
        try:
            self.sync_status = "syncing"
            self._notify_sync_status("syncing")
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            pending = db.execute(
                "SELECT * FROM sync_queue WHERE status='pending' ORDER BY created_at LIMIT 50"
            ).fetchall()

            if not pending:
                self.sync_status = "idle"
                self._notify_sync_status("idle")
                db.close()
                return

            cfg = self.config_getter()
            from backend.telegram_hub import resolve_bot_token
            bot_token = resolve_bot_token(cfg)
            chat_id = cfg.get('telegram_chat_id', '')
            shop = cfg.get('shop_name', 'MBT POS')
            sent_ids = []

            for row in pending:
                try:
                    payload = json.loads(row['payload'])
                    msg = self._format_telegram_message(shop, row['action_type'], payload)

                    if bot_token and chat_id:
                        resp = requests.post(
                            TELEGRAM_API.format(token=bot_token),
                            json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'},
                            timeout=10
                        )
                        if resp.ok:
                            sent_ids.append(row['id'])
                    else:
                        # No Telegram config — just mark as sent locally
                        sent_ids.append(row['id'])
                except Exception as e:
                    logger.warning(f"Sync item {row['id']} failed: {e}")

            if sent_ids:
                placeholders = ','.join('?' * len(sent_ids))
                db.execute(
                    f"UPDATE sync_queue SET status='sent', synced_at=? WHERE id IN ({placeholders})",
                    [datetime.now().isoformat()] + sent_ids
                )
                db.commit()

            db.close()
            self.sync_status = "synced"
            self._notify_sync_status("synced")
            logger.info(f"Sync complete: {len(sent_ids)} items sent")

        except Exception as e:
            self.sync_status = "failed"
            self._notify_sync_status("failed")
            logger.error(f"Sync error: {e}")
        finally:
            self._sync_lock.release()

    def _format_telegram_message(self, shop, action_type, payload):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if action_type == 'sale':
            return (
                f"🛒 <b>NEW SALE – {shop}</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📋 Receipt: <code>{payload.get('receipt_number', 'N/A')}</code>\n"
                f"💰 Total: <b>{payload.get('total', 0):,.2f}</b>\n"
                f"👤 Cashier: {payload.get('cashier', 'N/A')}\n"
                f"🕐 Time: {payload.get('created_at', now)[:19]}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"<i>Powered by MugoByte Technologies</i>"
            )
        elif action_type == 'error':
            return (
                f"⚠️ <b>SYSTEM ERROR – {shop}</b>\n"
                f"Module: {payload.get('module', 'unknown')}\n"
                f"Error: {payload.get('message', 'unknown error')}\n"
                f"Time: {now}"
            )
        elif action_type == 'sync':
            return (
                f"🔄 <b>SYSTEM SYNC – {shop}</b>\n"
                f"{payload.get('message', 'System synced')}\n"
                f"Time: {now}"
            )
        else:
            return f"📌 <b>{shop}</b>\n{action_type}: {json.dumps(payload)}\n{now}"

    def _notify_sync_status(self, status):
        """Override in subclass or bind callback."""
        pass


def send_telegram_message(bot_token, chat_id, message):
    """Standalone helper for ad-hoc messages."""
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=bot_token),
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
        return resp.ok
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def send_telegram_document(bot_token, chat_id, file_path, caption=''):
    """Send a file (Excel, PDF etc.) to a Telegram chat."""
    try:
        with open(file_path, 'rb') as f:
            resp = requests.post(
                TELEGRAM_DOC_API.format(token=bot_token),
                data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
                files={'document': (os.path.basename(file_path), f)},
                timeout=30,
            )
        return resp.ok
    except Exception as e:
        logger.error(f"Telegram document send error: {e}")
        return False


def send_activation_key_to_customer(bot_token, customer_chat_id, shop_name,
                                     plan, days, activation_msg):
    """
    Developer pushes an activation key / message directly to the customer's
    Telegram chat.  The customer's POS picks it up and auto-fills the key field.
    """
    try:
        msg = (
            f"\U0001f511 <b>MBT POS License Key — {shop_name}</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Plan:     <b>{plan}</b>\n"
            f"Duration: <b>{days} days</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<b>Your activation message:</b>\n"
            f"<code>{activation_msg}</code>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"<i>Open MBT POS → License tab → paste the key above and click Activate.</i>\n"
            f"<i>MugoByte Technologies  ·  mugobyte.com</i>"
        )
        resp = requests.post(
            TELEGRAM_API.format(token=bot_token),
            json={'chat_id': customer_chat_id, 'text': msg, 'parse_mode': 'HTML'},
            timeout=10,
        )
        return resp.ok
    except Exception as e:
        logger.error(f"send_activation_key error: {e}")
        return False

