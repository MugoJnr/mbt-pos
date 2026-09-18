"""
MBT POS - Internet Monitor & Cloud Sync Service
Runs as background thread; monitors connectivity and syncs queued data
via the centralized Notification Engine (replaces Telegram).

v3.0.93: fail-fast sockets, circuit breaker / backoff when offline so the
monitor cannot burn CPU or stall callers with multi-host 3s timeouts.
"""
import threading
import time
import socket
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Two IP probes, short connect — never hostname DNS here.
CHECK_HOSTS = [("1.1.1.1", 53), ("8.8.8.8", 53)]
CONNECT_TIMEOUT = 1.0
CHECK_INTERVAL_ONLINE = 30
CHECK_INTERVAL_OFFLINE_MIN = 15


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
        self._breaker = None

    def _get_breaker(self):
        if self._breaker is None:
            try:
                from backend.cloud.circuit_breaker import get_breaker
                self._breaker = get_breaker('internet_monitor')
            except Exception:
                self._breaker = None
        return self._breaker

    def stop(self):
        self._stop_event.set()

    def check_connection(self) -> bool:
        br = self._get_breaker()
        if br is not None and not br.allow():
            return False
        for host, port in CHECK_HOSTS:
            try:
                s = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
                s.close()
                if br is not None:
                    br.record_success()
                return True
            except OSError:
                continue
        if br is not None:
            wait = br.record_failure()
            logger.debug('InternetMonitor offline; next probe in %.0fs', wait)
        return False

    def run(self):
        while not self._stop_event.is_set():
            connected = self.check_connection()
            self.last_checked = datetime.now()

            if connected != self.is_connected:
                self.is_connected = connected
                logger.info(
                    "Connection status changed: %s",
                    'ONLINE' if connected else 'OFFLINE',
                )
                if self.status_callback:
                    try:
                        self.status_callback(connected)
                    except Exception as e:
                        logger.error("Status callback error: %s", e)
                if connected:
                    self._do_sync()
            elif connected:
                self._do_sync()

            if connected:
                wait = CHECK_INTERVAL_ONLINE
            else:
                br = self._get_breaker()
                wait = max(
                    CHECK_INTERVAL_OFFLINE_MIN,
                    (br.seconds_until_retry() if br else CHECK_INTERVAL_OFFLINE_MIN),
                )
            self._stop_event.wait(wait)

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
                        engine.publish_error(
                            shop,
                            payload.get('module', 'unknown'),
                            payload.get('message', ''),
                        )
                    else:
                        engine.publish(
                            action_type,
                            f'{shop} — {action_type}',
                            json.dumps(payload),
                        )

                    sent_ids.append(row['id'])
                except Exception as e:
                    logger.warning("Sync item %s failed: %s", row['id'], e)
                    db.execute(
                        "UPDATE sync_queue SET status='failed', "
                        "last_error=?, attempts=attempts+1 WHERE id=?",
                        (str(e)[:200], row['id']),
                    )

            if sent_ids:
                placeholders = ','.join('?' for _ in sent_ids)
                db.execute(
                    f"UPDATE sync_queue SET status='synced', "
                    f"synced_at=? WHERE id IN ({placeholders})",
                    [datetime.now().isoformat(), *sent_ids],
                )
            db.commit()
            db.close()
            self.sync_status = "synced" if sent_ids else "idle"
        except Exception as e:
            self.sync_status = "failed"
            logger.error("Sync error: %s", e)
        finally:
            self._sync_lock.release()
