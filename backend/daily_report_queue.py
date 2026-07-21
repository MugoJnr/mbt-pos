"""
MBT POS — Daily report delivery queue + idempotency store

Statuses: PENDING → SENDING → SENT | FAILED | RETRYING

One SENT row per (business_key, report_date, report_type) prevents duplicate
Portal / email report delivery across restarts and duplicate scheduler instances.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from mbt_paths import configure_sqlite_connection, get_data_dir

logger = logging.getLogger('daily_report_queue')

STATUS_PENDING = 'PENDING'
STATUS_SENDING = 'SENDING'
STATUS_SENT = 'SENT'
STATUS_FAILED = 'FAILED'
STATUS_RETRYING = 'RETRYING'

TYPE_DAILY = 'daily'
TYPE_WEEKLY = 'weekly'

MAX_ATTEMPTS = 8
CATCHUP_DAYS = 7

_db_lock = threading.RLock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_key TEXT NOT NULL,
    report_date TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'daily',
    status TEXT NOT NULL,
    file_path TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE(business_key, report_date, report_type)
);
CREATE INDEX IF NOT EXISTS idx_report_status ON report_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_report_date ON report_deliveries(report_date);
"""


def _db_path() -> str:
    d = get_data_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'report_delivery.db')


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    configure_sqlite_connection(conn)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db_lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def business_key_from_cfg(cfg: dict | None) -> str:
    """Stable per-shop key for idempotency."""
    cfg = cfg or {}
    try:
        from backend.cloud_backup.paths import load_identity
        ident = load_identity() or {}
        bid = (ident.get('business_id') or '').strip()
        if bid:
            return f'biz:{bid}'
    except Exception:
        pass
    shop = (cfg.get('shop_name') or '').strip().lower()
    if shop:
        return f'shop:{shop}'
    return 'default'


def enqueue(
    business_key: str,
    report_date: str,
    report_type: str = TYPE_DAILY,
    reason: str = '',
) -> Optional[dict]:
    """
    Ensure a delivery row exists. Does not overwrite SENT.
    Returns the row dict, or None on error.
    """
    init_db()
    now = datetime.now().isoformat(timespec='seconds')
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                """SELECT * FROM report_deliveries
                   WHERE business_key=? AND report_date=? AND report_type=?""",
                (business_key, report_date, report_type),
            ).fetchone()
            if row:
                d = dict(row)
                if d['status'] == STATUS_SENT:
                    logger.debug(
                        'report already SENT %s %s %s — skip enqueue',
                        business_key, report_date, report_type,
                    )
                    return d
                if reason and not d.get('reason'):
                    conn.execute(
                        'UPDATE report_deliveries SET reason=?, updated_at=? WHERE id=?',
                        (reason, now, d['id']),
                    )
                    conn.commit()
                    d['reason'] = reason
                return d

            conn.execute(
                """INSERT INTO report_deliveries
                   (business_key, report_date, report_type, status, reason,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    business_key, report_date, report_type, STATUS_PENDING,
                    reason or '', now, now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """SELECT * FROM report_deliveries
                   WHERE business_key=? AND report_date=? AND report_type=?""",
                (business_key, report_date, report_type),
            ).fetchone()
            logger.info(
                'Enqueued %s report %s for %s (%s)',
                report_type, report_date, business_key, reason or 'schedule',
            )
            return dict(row) if row else None
        except Exception as e:
            logger.error('enqueue failed: %s', e)
            return None
        finally:
            conn.close()


def enqueue_catchup(
    business_key: str,
    *,
    days: int = CATCHUP_DAYS,
    include_today: bool = True,
    reason: str = 'catchup',
) -> list[dict]:
    """Enqueue missing daily reports for the last N calendar days."""
    out: list[dict] = []
    today = date.today()
    start_offset = 0 if include_today else 1
    for i in range(start_offset, days + start_offset):
        d = str(today - timedelta(days=i))
        row = enqueue(business_key, d, TYPE_DAILY, reason=reason)
        if row and row.get('status') != STATUS_SENT:
            out.append(row)
    return out


def claim_next(
    business_key: str,
    report_type: str | None = None,
) -> Optional[dict]:
    """
    Atomically claim the oldest PENDING/RETRYING row → SENDING.
    Skips SENT and exhausted FAILED rows.
    """
    init_db()
    now = datetime.now().isoformat(timespec='seconds')
    with _db_lock:
        conn = _connect()
        try:
            if report_type:
                row = conn.execute(
                    """SELECT * FROM report_deliveries
                       WHERE business_key=? AND report_type=?
                         AND status IN (?, ?)
                         AND attempts < ?
                       ORDER BY report_date ASC, id ASC LIMIT 1""",
                    (
                        business_key, report_type,
                        STATUS_PENDING, STATUS_RETRYING, MAX_ATTEMPTS,
                    ),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM report_deliveries
                       WHERE business_key=?
                         AND status IN (?, ?)
                         AND attempts < ?
                       ORDER BY report_date ASC, id ASC LIMIT 1""",
                    (
                        business_key, STATUS_PENDING, STATUS_RETRYING,
                        MAX_ATTEMPTS,
                    ),
                ).fetchone()
            if not row:
                return None
            rid = row['id']
            cur = conn.execute(
                """UPDATE report_deliveries
                   SET status=?, attempts=attempts+1, updated_at=?
                   WHERE id=? AND status IN (?, ?)""",
                (
                    STATUS_SENDING, now, rid,
                    STATUS_PENDING, STATUS_RETRYING,
                ),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            claimed = conn.execute(
                'SELECT * FROM report_deliveries WHERE id=?', (rid,)
            ).fetchone()
            logger.info(
                'Claimed report id=%s date=%s type=%s attempt=%s',
                rid, claimed['report_date'], claimed['report_type'],
                claimed['attempts'],
            )
            return dict(claimed)
        except Exception as e:
            logger.error('claim_next failed: %s', e)
            return None
        finally:
            conn.close()


def begin_send(row_id: int) -> Optional[dict]:
    """Mark a specific row SENDING (manual / targeted send)."""
    now = datetime.now().isoformat(timespec='seconds')
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """UPDATE report_deliveries
                   SET status=?, attempts=attempts+1, updated_at=?
                   WHERE id=? AND status != ?""",
                (STATUS_SENDING, now, row_id, STATUS_SENDING),
            )
            if cur.rowcount != 1:
                # Already SENDING — still return row
                row = conn.execute(
                    'SELECT * FROM report_deliveries WHERE id=?', (row_id,)
                ).fetchone()
                return dict(row) if row else None
            conn.commit()
            row = conn.execute(
                'SELECT * FROM report_deliveries WHERE id=?', (row_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def mark_sent(row_id: int, file_path: str = '') -> None:
    now = datetime.now().isoformat(timespec='seconds')
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """UPDATE report_deliveries
                   SET status=?, file_path=?, last_error='',
                       sent_at=?, updated_at=?
                   WHERE id=?""",
                (STATUS_SENT, file_path or '', now, now, row_id),
            )
            conn.commit()
            logger.info('Report id=%s marked SENT', row_id)
        finally:
            conn.close()


def mark_failed(row_id: int, error: str, *, retry: bool = True) -> str:
    """Mark FAILED or RETRYING. Returns new status."""
    now = datetime.now().isoformat(timespec='seconds')
    err = (error or '')[:500]
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                'SELECT attempts FROM report_deliveries WHERE id=?', (row_id,)
            ).fetchone()
            attempts = int(row['attempts']) if row else MAX_ATTEMPTS
            if retry and attempts < MAX_ATTEMPTS:
                status = STATUS_RETRYING
            else:
                status = STATUS_FAILED
            conn.execute(
                """UPDATE report_deliveries
                   SET status=?, last_error=?, updated_at=?
                   WHERE id=?""",
                (status, err, now, row_id),
            )
            conn.commit()
            logger.warning(
                'Report id=%s → %s (attempt %s): %s',
                row_id, status, attempts, err[:120],
            )
            return status
        finally:
            conn.close()


def release_stale_sending(max_age_minutes: int = 30) -> int:
    """Recover rows stuck in SENDING after crash."""
    init_db()
    cutoff = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat(
        timespec='seconds'
    )
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                """UPDATE report_deliveries
                   SET status=?, updated_at=?
                   WHERE status=? AND updated_at < ?""",
                (
                    STATUS_RETRYING,
                    datetime.now().isoformat(timespec='seconds'),
                    STATUS_SENDING,
                    cutoff,
                ),
            )
            conn.commit()
            n = cur.rowcount or 0
            if n:
                logger.warning('Released %s stale SENDING report(s)', n)
            return n
        finally:
            conn.close()


def is_sent(business_key: str, report_date: str,
            report_type: str = TYPE_DAILY) -> bool:
    init_db()
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                """SELECT status FROM report_deliveries
                   WHERE business_key=? AND report_date=? AND report_type=?""",
                (business_key, report_date, report_type),
            ).fetchone()
            return bool(row and row['status'] == STATUS_SENT)
        finally:
            conn.close()


def get_row(
    business_key: str,
    report_date: str,
    report_type: str = TYPE_DAILY,
) -> Optional[dict]:
    init_db()
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                """SELECT * FROM report_deliveries
                   WHERE business_key=? AND report_date=? AND report_type=?""",
                (business_key, report_date, report_type),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def get_health(business_key: str) -> dict:
    """Aggregate status for Settings health UI (no secrets)."""
    init_db()
    with _db_lock:
        conn = _connect()
        try:
            counts = {
                STATUS_PENDING: 0,
                STATUS_SENDING: 0,
                STATUS_SENT: 0,
                STATUS_FAILED: 0,
                STATUS_RETRYING: 0,
            }
            for r in conn.execute(
                """SELECT status, COUNT(*) AS n FROM report_deliveries
                   WHERE business_key=? GROUP BY status""",
                (business_key,),
            ):
                counts[r['status']] = r['n']

            last = conn.execute(
                """SELECT * FROM report_deliveries
                   WHERE business_key=? AND status=?
                   ORDER BY sent_at DESC, id DESC LIMIT 1""",
                (business_key, STATUS_SENT),
            ).fetchone()

            last_any = conn.execute(
                """SELECT * FROM report_deliveries
                   WHERE business_key=?
                   ORDER BY updated_at DESC, id DESC LIMIT 1""",
                (business_key,),
            ).fetchone()

            fail_attempts = conn.execute(
                """SELECT COALESCE(SUM(attempts),0) AS n FROM report_deliveries
                   WHERE business_key=? AND status IN (?, ?)""",
                (business_key, STATUS_FAILED, STATUS_RETRYING),
            ).fetchone()['n']

            return {
                'business_key': business_key,
                'counts': counts,
                'pending': counts[STATUS_PENDING] + counts[STATUS_RETRYING],
                'failed': counts[STATUS_FAILED],
                'failed_attempts': int(fail_attempts or 0),
                'last_sent': dict(last) if last else None,
                'last_any': dict(last_any) if last_any else None,
            }
        finally:
            conn.close()


def reset_for_manual_resend(
    business_key: str,
    report_date: str,
    report_type: str = TYPE_DAILY,
) -> dict:
    """
    Manual 'Send Now' path: allow a fresh send even if already SENT.
    Resets to PENDING (attempts cleared).
    """
    init_db()
    now = datetime.now().isoformat(timespec='seconds')
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO report_deliveries
                   (business_key, report_date, report_type, status, reason,
                    attempts, created_at, updated_at)
                   VALUES (?,?,?,?,?,0,?,?)
                   ON CONFLICT(business_key, report_date, report_type) DO UPDATE SET
                     status=excluded.status,
                     reason=excluded.reason,
                     attempts=0,
                     last_error='',
                     sent_at=NULL,
                     updated_at=excluded.updated_at""",
                (
                    business_key, report_date, report_type, STATUS_PENDING,
                    'manual', now, now,
                ),
            )
            conn.commit()
            row = conn.execute(
                """SELECT * FROM report_deliveries
                   WHERE business_key=? AND report_date=? AND report_type=?""",
                (business_key, report_date, report_type),
            ).fetchone()
            return dict(row)
        finally:
            conn.close()
