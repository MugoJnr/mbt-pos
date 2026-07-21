"""
MBT Cloud — Centralized Notification & Reports Engine.
Replaces all Telegram notification delivery.

Every important event becomes a notification stored locally and synced to cloud.
Delivery channels: dashboard, email (future), mobile push (future).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger('cloud.notifications')

# Event types that trigger notifications
EVENT_TYPES = {
    'daily_report': 'Daily Report',
    'weekly_report': 'Weekly Report',
    'monthly_report': 'Monthly Report',
    'low_stock': 'Low Stock Alert',
    'backup_completed': 'Backup Completed',
    'backup_failed': 'Backup Failed',
    'refund': 'Refund Processed',
    'void_sale': 'Sale Voided',
    'large_sale': 'Large Sale',
    'device_offline': 'Device Offline',
    'license_expiring': 'License Expiring',
    'new_device': 'New Device Activated',
    'update_available': 'Software Update Available',
    'failed_login': 'Failed Login Attempt',
    'database_issue': 'Database Issue',
    'sale': 'New Sale',
    'error': 'System Error',
    'sync': 'Sync Event',
    'command_result': 'Remote Command Result',
    'security': 'Security Alert',
    'tamper': 'License Tamper',
}

SEVERITY_MAP = {
    'daily_report': 'info',
    'weekly_report': 'info',
    'monthly_report': 'info',
    'low_stock': 'warning',
    'backup_completed': 'success',
    'backup_failed': 'error',
    'refund': 'warning',
    'void_sale': 'warning',
    'security': 'warning',
    'tamper': 'error',
    'large_sale': 'info',
    'device_offline': 'warning',
    'license_expiring': 'warning',
    'new_device': 'success',
    'update_available': 'info',
    'failed_login': 'error',
    'database_issue': 'error',
    'sale': 'info',
    'error': 'error',
    'sync': 'info',
    'command_result': 'info',
}


def ensure_notification_schema(db: sqlite3.Connection):
    db.execute("""
        CREATE TABLE IF NOT EXISTS cc_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL DEFAULT 'info',
            title TEXT NOT NULL,
            body TEXT,
            severity TEXT NOT NULL DEFAULT 'info',
            is_read INTEGER NOT NULL DEFAULT 0,
            link TEXT,
            meta_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL UNIQUE,
            dashboard INTEGER NOT NULL DEFAULT 1,
            email INTEGER NOT NULL DEFAULT 0,
            push INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS report_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_type TEXT NOT NULL,
            period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            sent_at TEXT,
            UNIQUE(report_type, period_key)
        )
    """)
    for event_type in EVENT_TYPES:
        db.execute(
            "INSERT OR IGNORE INTO notification_preferences (event_type) VALUES (?)",
            (event_type,),
        )
    db.commit()


class NotificationEngine:
    """Central notification dispatcher — replaces Telegram delivery."""

    def __init__(self, db_path: str, config_getter: Callable[[], dict] | None = None):
        self.db_path = db_path
        self.config_getter = config_getter or (lambda: {})
        self._lock = threading.Lock()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    def publish(
        self,
        event_type: str,
        title: str,
        body: str = '',
        severity: str | None = None,
        link: str | None = None,
        meta: dict | None = None,
    ) -> int | None:
        """Create a notification. Returns notification id."""
        if not self._is_enabled(event_type, 'dashboard'):
            return None
        sev = severity or SEVERITY_MAP.get(event_type, 'info')
        with self._lock:
            db = self._db()
            try:
                ensure_notification_schema(db)
                cur = db.execute(
                    """INSERT INTO cc_notifications
                       (type, title, body, severity, link, meta_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_type,
                        title,
                        body,
                        sev,
                        link,
                        json.dumps(meta or {}),
                        datetime.now().isoformat(),
                    ),
                )
                db.commit()
                nid = cur.lastrowid
                logger.info('Notification [%s] %s: %s', event_type, title, body[:80])
                self._sync_to_cloud(event_type, title, body, sev, meta)
                return nid
            finally:
                db.close()

    def publish_sale(self, shop: str, payload: dict) -> int | None:
        total = payload.get('total', 0)
        receipt = payload.get('receipt_number', 'N/A')
        cashier = payload.get('cashier', 'N/A')
        title = f'New Sale — {shop}'
        body = f'Receipt {receipt} · {total:,.2f} · Cashier: {cashier}'
        meta = {'receipt_number': receipt, 'total': total, 'cashier': cashier}
        if total >= 50000:
            self.publish('large_sale', f'Large Sale — {shop}', body, 'warning', meta=meta)
        return self.publish('sale', title, body, meta=meta)

    def publish_error(self, shop: str, module: str, message: str) -> int | None:
        return self.publish(
            'error',
            f'System Error — {shop}',
            f'{module}: {message}',
            'error',
            meta={'module': module, 'message': message},
        )

    def publish_backup(self, success: bool, detail: str) -> int | None:
        event = 'backup_completed' if success else 'backup_failed'
        title = 'Backup Completed' if success else 'Backup Failed'
        return self.publish(event, title, detail, SEVERITY_MAP[event])

    def publish_license_warning(self, days_remaining: int, plan: str) -> int | None:
        return self.publish(
            'license_expiring',
            f'License Expiring in {days_remaining} days',
            f'Your {plan} license expires soon. Renew to avoid interruption.',
            'warning',
            link='/license',
            meta={'days_remaining': days_remaining, 'plan': plan},
        )

    def list_notifications(self, limit: int = 100, unread_only: bool = False) -> list[dict]:
        db = self._db()
        try:
            ensure_notification_schema(db)
            q = "SELECT * FROM cc_notifications"
            if unread_only:
                q += " WHERE is_read=0"
            q += " ORDER BY created_at DESC LIMIT ?"
            rows = db.execute(q, (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    def unread_count(self) -> int:
        db = self._db()
        try:
            ensure_notification_schema(db)
            return db.execute(
                "SELECT COUNT(*) FROM cc_notifications WHERE is_read=0"
            ).fetchone()[0]
        finally:
            db.close()

    def mark_read(self, notification_id: int) -> bool:
        db = self._db()
        try:
            db.execute(
                "UPDATE cc_notifications SET is_read=1 WHERE id=?",
                (notification_id,),
            )
            db.commit()
            return True
        finally:
            db.close()

    def mark_all_read(self) -> int:
        db = self._db()
        try:
            cur = db.execute("UPDATE cc_notifications SET is_read=1 WHERE is_read=0")
            db.commit()
            return cur.rowcount
        finally:
            db.close()

    def get_preferences(self) -> list[dict]:
        db = self._db()
        try:
            ensure_notification_schema(db)
            rows = db.execute("SELECT * FROM notification_preferences ORDER BY event_type").fetchall()
            return [dict(r) for r in rows]
        finally:
            db.close()

    def update_preference(self, event_type: str, channel: str, enabled: bool) -> bool:
        if channel not in ('dashboard', 'email', 'push'):
            return False
        db = self._db()
        try:
            ensure_notification_schema(db)
            db.execute(
                f"UPDATE notification_preferences SET {channel}=? WHERE event_type=?",
                (1 if enabled else 0, event_type),
            )
            db.commit()
            return True
        finally:
            db.close()

    def _is_enabled(self, event_type: str, channel: str) -> bool:
        db = self._db()
        try:
            ensure_notification_schema(db)
            row = db.execute(
                f"SELECT {channel} FROM notification_preferences WHERE event_type=?",
                (event_type,),
            ).fetchone()
            return bool(row[channel]) if row else True
        except Exception:
            return True
        finally:
            db.close()

    def _sync_to_cloud(self, event_type: str, title: str, body: str, severity: str, meta: dict | None):
        """Push notification to Supabase cloud when configured."""
        try:
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                return
            from backend.cloud_backup.supabase_client import SupabaseClient
            from backend.cloud_backup.paths import load_identity
            ident = load_identity()
            org_id = ident.get('business_id') or ident.get('org_id')
            if not org_id:
                return
            client = SupabaseClient()
            token = ident.get('access_token') or ''
            client.rest_insert('notifications', {
                'org_id': org_id,
                'type': event_type,
                'title': title,
                'body': body,
                'severity': severity,
                'channel': 'dashboard',
                'meta': meta or {},
            })
        except Exception as e:
            logger.debug('Cloud notification sync skipped: %s', e)


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: NotificationEngine | None = None


def get_notification_engine(db_path: str | None = None, config_getter=None) -> NotificationEngine:
    global _engine
    if _engine is None:
        if db_path is None:
            from mbt_paths import get_db_path
            db_path = get_db_path()
        _engine = NotificationEngine(db_path, config_getter)
    return _engine
