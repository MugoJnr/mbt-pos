"""
MBT POS - Internet Monitor & Cloud Sync Service
Runs as background thread; monitors connectivity and syncs queued data
via the centralized Notification Engine (replaces Telegram).
"""
import threading
import time
import socket
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CHECK_HOSTS = [("8.8.8.8", 53), ("1.1.1.1", 53), ("8.8.4.4", 53)]
CHECK_INTERVAL = 10


class InternetMonitor(threading.Thread):
    """
    Continuously monitors internet connection.
    Fires callbacks on status change.
    Syncs pending queue items via Notification Engine when online.
    """

    def __init__(self, db_path, config_getter, status_callback=None):
        super().__init__(daemon=True, name="InternetMonitor")
        self.db_path = db_path
        self.config_getter = config_getter
        self.status_callback = status_callback
        self.is_connected = False
        self.last_checked = None
        self.sync_status = "idle"
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
                self._do_sync()

            self._stop_event.wait(CHECK_INTERVAL)

    def force_sync(self):
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
            return
        try:
            self.sync_status = "syncing"
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row
            pending = db.execute(
                "SELECT * FROM sync_queue WHERE status='pending' ORDER BY created_at LIMIT 50"
            ).fetchall()

            if not pending:
                self.sync_status = "idle"
                db.close()
                return

            cfg = self.config_getter()
            shop = cfg.get('shop_name', 'MBT POS')
            sent_ids = []

            from backend.cloud.notification_engine import get_notification_engine
            engine = get_notification_engine(self.db_path, self.config_getter)

            for row in pending:
                try:
                    payload = json.loads(row['payload'])
                    action_type = row['action_type']

                    if action_type == 'sale':
                        engine.publish_sale(shop, payload)
                    elif action_type == 'error':
                        engine.publish_error(shop, payload.get('module', 'unknown'), payload.get('message', ''))
                    else:
                        engine.publish(action_type, f'{shop} — {action_type}', json.dumps(payload))

                    sent_ids.append(row['id'])
                except Exception as e:
                    logger.warning(f"Sync item {row['id']} failed: {e}")

            if sent_ids:
                placeholders = ','.join('?' * len(sent_ids))
                db.execute(
                    f"UPDATE sync_queue SET status='sent', synced_at=? WHERE id IN ({placeholders})",
                    [datetime.now().isoformat()] + sent_ids,
                )
                db.commit()

            db.close()
            self.sync_status = "synced"
            logger.info(f"Sync complete: {len(sent_ids)} items processed via notification engine")

        except Exception as e:
            self.sync_status = "failed"
            logger.error(f"Sync error: {e}")
        finally:
            self._sync_lock.release()
