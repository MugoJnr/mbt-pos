"""
Background cloud backup: encrypted SQLite snapshots on a schedule + Backup Now.

Also maintains a lightweight local change_log for products/sales/customers
(architecture hook for future incremental sync). Offline queue retries when
connectivity returns.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import quote
import requests

from mbt_paths import configure_sqlite_connection, get_db_path

from backend.cloud_backup import SCHEMA_VERSION
from backend.cloud_backup.device_manager import get_device_info, get_or_create_device_id
from backend.cloud_backup.encryption import (
    EncryptionError,
    encrypt_file,
    ensure_identity_key_material,
    sha256_file,
)
from backend.cloud_backup.paths import (
    backup_state_path,
    is_cloud_configured,
    is_logged_in,
    load_cloud_config,
    load_identity,
    load_json,
    offline_queue_path,
    save_identity,
    save_json,
)
from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError

logger = logging.getLogger('cloud_backup.sync')

DEFAULT_INTERVAL_MIN = 5
BACKFILL_BATCH_SIZE = 200

# Local table → cloud entity_type for outbox flush / historical backfill.
ENTITY_TABLE_MAP = {
    'product': 'products',
    'sale': 'sales',
    'sale_item': 'sale_items',
    'customer': 'customers',
    'supplier': 'suppliers',
    'expense': 'expenses',
    'purchase': 'purchases',
    'purchase_item': 'purchase_items',
    'employee': 'employees',
    'user': 'users',
    'branch': 'branches',
    'audit_log': 'audit_log',
    'setting': 'system_settings',
    'debt_invoice': 'debt_invoices',
    'debt_payment': 'debt_payments',
    'stock_movement': 'stock_movements',
}

# Historical backfill covers analytics-required entities only.
BACKFILL_ENTITY_TYPES = (
    'product',
    'customer',
    'sale',
    'sale_item',
    'debt_invoice',
    'debt_payment',
    'stock_movement',
)

# Allowlisted fields per entity — never sync secrets / sensitive free text / raw refs.
ENTITY_FIELD_ALLOWLIST = {
    'product': {
        'id', 'name', 'sku', 'category', 'price', 'cost_price', 'stock',
        'min_stock', 'unit', 'barcode', 'is_active', 'created_at', 'updated_at',
    },
    'sale': {
        'id', 'receipt_number', 'cashier_id', 'cashier_name', 'subtotal',
        'discount', 'tax', 'total', 'payment_method', 'amount_paid',
        'change_amount', 'status', 'customer_id', 'credit_applied',
        'electronic_paid', 'original_total', 'cash_rounding_adj',
        'variance_handling', 'created_at', 'updated_at',
    },
    'sale_item': {
        'id', 'sale_id', 'product_id', 'product_name', 'sku', 'category',
        'quantity', 'unit_price', 'unit_cost', 'discount', 'total',
        'created_at', 'updated_at',
    },
    'customer': {
        'id', 'name', 'phone', 'email', 'credit_limit', 'customer_type',
        'is_active', 'created_at', 'updated_at',
    },
    'debt_invoice': {
        'id', 'invoice_number', 'sale_id', 'receipt_number', 'customer_id',
        'customer_name', 'customer_phone', 'total_amount', 'amount_paid',
        'balance', 'status', 'due_date', 'cashier_id', 'cashier_name',
        'created_at', 'updated_at',
    },
    'debt_payment': {
        'id', 'payment_receipt', 'invoice_id', 'customer_id', 'amount',
        'payment_method', 'balance_before', 'balance_after', 'cashier_id',
        'cashier_name', 'created_at', 'updated_at',
    },
    'stock_movement': {
        'id', 'product_id', 'product_name', 'movement_type', 'qty_before',
        'qty_change', 'qty_after', 'reference', 'reason', 'user_id',
        'username', 'device_id', 'created_at',
    },
    'user': {
        'id', 'username', 'role', 'full_name', 'email', 'is_active',
        'tab_permissions', 'created_at', 'updated_at',
    },
    'supplier': {
        'id', 'name', 'phone', 'email', 'address', 'is_active',
        'created_at', 'updated_at',
    },
    'expense': {
        'id', 'category', 'amount', 'description', 'payment_method',
        'cashier_id', 'cashier_name', 'created_at', 'updated_at',
    },
    'purchase': {
        'id', 'supplier_id', 'reference', 'total', 'status',
        'created_at', 'updated_at',
    },
    'purchase_item': {
        'id', 'purchase_id', 'product_id', 'product_name', 'quantity',
        'unit_cost', 'total', 'created_at', 'updated_at',
    },
    'employee': {
        'id', 'name', 'phone', 'role', 'is_active', 'created_at', 'updated_at',
    },
    'branch': {
        'id', 'name', 'code', 'address', 'is_active', 'created_at', 'updated_at',
    },
    'audit_log': {
        'id', 'user_id', 'username', 'action', 'module', 'created_at',
    },
}

# Absolute denylist — applied even when an allowlist is absent.
ENTITY_FIELD_DENYLIST = {
    'password', 'password_hash', 'national_id', 'mpesa_ref',
    'payment_reference', 'notes', 'address', 'details', 'content',
}

SETTING_SECRET_KEY_FRAGMENTS = (
    'secret', 'token', 'password', 'passkey', 'api_key', 'apikey',
    'credential', 'private', 'consumer_key', 'consumer_secret',
)
SETTING_SECRET_KEYS = {
    'telegram_bot_token', 'telegram_chat_id', 'developer_chat_id',
    'openai_api_key', 'jwt_secret', 'activation_token',
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _is_secret_setting_key(key: str) -> bool:
    k = (key or '').strip().lower()
    if not k:
        return True
    if k in SETTING_SECRET_KEYS:
        return True
    return any(frag in k for frag in SETTING_SECRET_KEY_FRAGMENTS)


def serialize_entity_payload(entity_type: str, row: dict | None) -> dict:
    """Return a redacted/allowlisted payload safe for cloud analytics sync."""
    if not row:
        return {}
    raw = dict(row)
    if entity_type == 'setting':
        key = str(raw.get('key') or '')
        if _is_secret_setting_key(key):
            return {'key': key, 'redacted': True}
        out = {'key': key, 'value': raw.get('value')}
        if raw.get('updated_at') is not None:
            out['updated_at'] = raw.get('updated_at')
        return out

    allow = ENTITY_FIELD_ALLOWLIST.get(entity_type)
    out: dict = {}
    if allow is not None:
        for field in allow:
            if field in raw and raw[field] is not None:
                out[field] = raw[field]
    else:
        for field, value in raw.items():
            fl = str(field).lower()
            if fl in ENTITY_FIELD_DENYLIST or any(
                d in fl for d in ('password', 'secret', 'token', 'national_id')
            ):
                continue
            out[field] = value

    # Hard strip sensitive fields regardless of allowlist mistakes.
    for denied in ENTITY_FIELD_DENYLIST:
        out.pop(denied, None)
    out.pop('password_hash', None)
    out.pop('national_id', None)
    out.pop('mpesa_ref', None)
    out.pop('payment_reference', None)
    return out


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _app_version() -> str:
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        vpath = os.path.join(root, 'version.json')
        with open(vpath, encoding='utf-8-sig') as f:
            return str(json.load(f).get('version') or '0')
    except Exception:
        return '0'


def create_sqlite_snapshot(db_path: str | None = None) -> tuple[str, str]:
    """
    Consistent SQLite snapshot → zip. Returns (zip_path, tmp_dir).
    Caller must clean up tmp_dir.
    """
    db_path = db_path or get_db_path()
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f'Database not found: {db_path}')

    tmp_dir = tempfile.mkdtemp(prefix='mbt_cloud_bak_')
    snap_db = os.path.join(tmp_dir, 'mbt_pos.db')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_path = os.path.join(tmp_dir, f'mbt_pos_{stamp}.zip')

    src = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    dst = sqlite3.connect(snap_db)
    try:
        configure_sqlite_connection(src)
        configure_sqlite_connection(dst)
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    meta = {
        'mbt_version': _app_version(),
        'schema_version': SCHEMA_VERSION,
        'created_at': _utc_now(),
        'device_id': get_or_create_device_id(),
    }
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(snap_db, arcname='mbt_pos.db')
        zf.writestr('backup_meta.json', json.dumps(meta, indent=2))

    try:
        os.remove(snap_db)
    except OSError:
        pass
    return zip_path, tmp_dir


def ensure_change_log_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS cloud_change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL,
        row_id INTEGER,
        op TEXT NOT NULL,
        payload TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        synced INTEGER DEFAULT 0
    )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cloud_change_log_synced "
        "ON cloud_change_log(synced, id)"
    )


def record_change(table_name: str, row_id: int, op: str, payload: dict | None = None) -> None:
    """Hook for future incremental sync — safe no-op on failure."""
    try:
        db = get_db_path()
        conn = sqlite3.connect(db, timeout=5)
        configure_sqlite_connection(conn)
        ensure_change_log_table(conn)
        conn.execute(
            "INSERT INTO cloud_change_log (table_name, row_id, op, payload) VALUES (?,?,?,?)",
            (table_name, row_id, op, json.dumps(payload or {})),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug('change_log skip: %s', e)


class SyncManager:
    _instance: Optional['SyncManager'] = None
    _lock = threading.Lock()

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._last_error = ''
        self._last_status = 'idle'
        self._progress_cb: Optional[Callable[[str, float], None]] = None
        self._started = False

    @classmethod
    def instance(cls) -> 'SyncManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start(self, progress_callback: Callable | None = None, **_kwargs) -> 'SyncManager':
        if progress_callback:
            self._progress_cb = progress_callback
        if self._started and self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._started = True
        self._thread = threading.Thread(
            target=self._loop, name='MBT-CloudBackup', daemon=True)
        self._thread.start()
        logger.info('Cloud backup service started')
        return self

    def stop(self):
        self._stop.set()
        self._started = False

    def set_progress_callback(self, cb: Callable[[str, float], None] | None):
        self._progress_cb = cb

    def _emit(self, msg: str, pct: float = -1):
        self._last_status = msg
        cb = self._progress_cb
        if cb:
            try:
                cb(msg, pct)
            except Exception:
                pass

    def status(self) -> dict:
        state = load_json(backup_state_path(), {})
        cfg = load_cloud_config()
        ident = load_identity()
        backfill = state.get('analytics_backfill') or {}
        return {
            'enabled': bool(cfg.get('enabled')),
            'configured': is_cloud_configured(),
            'logged_in': is_logged_in(),
            'cloud_skipped': bool(ident.get('cloud_skipped')),
            'device_id': get_or_create_device_id(),
            'business_id': ident.get('business_id') or '',
            'business_name': ident.get('business_name') or '',
            'email': ident.get('email') or '',
            'org_id': ident.get('org_id') or '',
            'interval_minutes': int(cfg.get('backup_interval_minutes') or DEFAULT_INTERVAL_MIN),
            'last_backup_at': state.get('last_backup_at') or '',
            'last_backup_size': state.get('last_backup_size') or 0,
            'last_backup_id': state.get('last_backup_id') or '',
            'last_error': self._last_error or state.get('last_error') or '',
            'status': self._last_status,
            'queue_depth': len(load_json(offline_queue_path(), {'items': []}).get('items') or []),
            'mbt_version': _app_version(),
            'schema_version': SCHEMA_VERSION,
            'analytics_backfill_complete': bool(backfill.get('completed_at')),
        }

    def _loop(self):
        # Initial delay so POS UI can finish booting
        self._stop.wait(20)
        while not self._stop.is_set():
            cfg = load_cloud_config()
            interval_min = max(1, int(cfg.get('backup_interval_minutes') or DEFAULT_INTERVAL_MIN))
            try:
                if is_logged_in() and is_cloud_configured():
                    self.ensure_historical_backfill()
                    self.flush_entity_outbox()
                self.flush_offline_queue()
                if cfg.get('enabled') and is_logged_in() and is_cloud_configured():
                    state = load_json(backup_state_path(), {})
                    last = state.get('last_backup_at') or ''
                    due = True
                    if last:
                        try:
                            # Compare naive ISO
                            last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
                            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                            due = age >= interval_min * 60
                        except Exception:
                            due = True
                    if due:
                        self.run_backup(reason='scheduled')
            except Exception as e:
                logger.warning('Cloud backup loop: %s', e)
                self._last_error = str(e)
            self._stop.wait(min(60, interval_min * 60))

    def _post_entity_sync_batch(
        self,
        portal_url: str,
        token: str,
        batch_key: str,
        org_id: str,
        device_id: str,
        entities: list[dict],
    ):
        """POST sync batch; refresh access token once on 401/403 and retry."""
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-Request-ID': batch_key[:24],
        }
        body = {
            'org_id': org_id,
            'device_id': device_id,
            'idempotency_key': batch_key,
            'entities': entities,
        }
        url = f'{portal_url}/api/cloud/sync/batch'
        response = requests.post(url, headers=headers, json=body, timeout=60)
        if response.status_code not in (401, 403):
            return response
        try:
            SupabaseClient().refresh_session()
        except Exception as refresh_error:
            logger.warning('Entity sync token refresh failed: %s', refresh_error)
            return response
        new_token = str(load_identity().get('access_token') or '')
        if not new_token or new_token == token:
            return response
        headers['Authorization'] = f'Bearer {new_token}'
        return requests.post(url, headers=headers, json=body, timeout=60)

    def ensure_historical_backfill(self, batch_size: int = BACKFILL_BATCH_SIZE) -> int:
        """
        Resumable, idempotent enqueue of existing analytics rows into sync_outbox.
        Runs automatically once org/device cloud identity is available.
        """
        ident = load_identity()
        org_id = str(ident.get('org_id') or '')
        if not org_id or not is_logged_in():
            return 0
        # Device registry identity must exist before cloud ingest will accept batches.
        device_id = get_or_create_device_id()
        if not device_id:
            return 0

        state = load_json(backup_state_path(), {})
        backfill = dict(state.get('analytics_backfill') or {})
        if backfill.get('completed_at') and all(
            (backfill.get(et) or {}).get('done') for et in BACKFILL_ENTITY_TYPES
        ):
            return 0

        conn = sqlite3.connect(get_db_path(), timeout=10)
        configure_sqlite_connection(conn)
        enqueued = 0
        try:
            existing_tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            limit = max(1, min(int(batch_size or BACKFILL_BATCH_SIZE), 500))
            for entity_type in BACKFILL_ENTITY_TYPES:
                progress = dict(backfill.get(entity_type) or {})
                if progress.get('done'):
                    continue
                table = ENTITY_TABLE_MAP.get(entity_type)
                if not table or table not in existing_tables:
                    progress['done'] = True
                    progress['last_id'] = int(progress.get('last_id') or 0)
                    backfill[entity_type] = progress
                    continue
                columns = {
                    row[1] for row in conn.execute(
                        f'PRAGMA table_info("{table}")'
                    ).fetchall()
                }
                if 'id' not in columns:
                    progress['done'] = True
                    backfill[entity_type] = progress
                    continue

                last_id = int(progress.get('last_id') or 0)
                rows = conn.execute(
                    f'SELECT id FROM "{table}" WHERE id > ? ORDER BY id ASC LIMIT ?',
                    (last_id, limit),
                ).fetchall()
                if not rows:
                    progress['done'] = True
                    progress['last_id'] = last_id
                    backfill[entity_type] = progress
                    continue

                for (row_id,) in rows:
                    source_id = str(row_id)
                    pending = conn.execute(
                        "SELECT 1 FROM sync_outbox "
                        "WHERE entity_type=? AND row_id=? AND processed_at IS NULL "
                        "LIMIT 1",
                        (entity_type, source_id),
                    ).fetchone()
                    if pending:
                        last_id = int(row_id)
                        continue
                    event_id = (
                        f"bf-{entity_type}-{source_id}-"
                        f"{hashlib.sha1(f'{org_id}:{device_id}:{entity_type}:{source_id}'.encode()).hexdigest()[:16]}"
                    )
                    try:
                        conn.execute(
                            "INSERT INTO sync_outbox("
                            "event_id, entity_type, row_id, operation"
                            ") VALUES (?,?,?,?)",
                            (event_id, entity_type, source_id, 'upsert'),
                        )
                        enqueued += 1
                    except sqlite3.IntegrityError:
                        # Deterministic backfill event already exists (processed or pending).
                        pass
                    last_id = int(row_id)

                progress['last_id'] = last_id
                progress['done'] = len(rows) < limit
                progress['updated_at'] = _utc_now()
                backfill[entity_type] = progress

            if all((backfill.get(et) or {}).get('done') for et in BACKFILL_ENTITY_TYPES):
                backfill['completed_at'] = _utc_now()
            # Commit outbox inserts first so a failed commit cannot leave a
            # checkpoint that skips rows. Deterministic event IDs make a later
            # checkpoint save failure safe (replay is idempotent).
            conn.commit()
            state['analytics_backfill'] = backfill
            save_json(backup_state_path(), state)
            if enqueued:
                self._last_status = f'Backfilled {enqueued} historical rows'
                logger.info('Historical analytics backfill enqueued %s rows', enqueued)
            return enqueued
        except Exception as error:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning('Historical backfill deferred: %s', error)
            self._last_error = str(error)
            return 0
        finally:
            conn.close()

    def clear_device_approval_backoff(self) -> int:
        """
        After successful device registration/approval, make outbox rows that were
        deferred for approval/auth reasons immediately eligible again.

        Preserves last_error text for unrelated failures so operators still see
        the prior diagnostic until a successful flush clears it.
        """
        conn = sqlite3.connect(get_db_path(), timeout=10)
        configure_sqlite_connection(conn)
        try:
            # Match common Portal/auth denial messages without touching rows that
            # failed for unrelated reasons (network, validation, etc.).
            cur = conn.execute(
                "UPDATE sync_outbox "
                "SET available_at=CURRENT_TIMESTAMP, attempts=0 "
                "WHERE processed_at IS NULL "
                "AND ("
                "  last_error LIKE '%not approved%' "
                "  OR last_error LIKE '%Device is not approved%' "
                "  OR last_error LIKE '%approval%' "
                "  OR last_error LIKE '%Organization access%' "
                "  OR last_error LIKE '%403%' "
                "  OR last_error LIKE '%Forbidden%' "
                "  OR last_error LIKE '%forbidden%' "
                ")"
            )
            cleared = int(cur.rowcount or 0)
            conn.commit()
            if cleared:
                self._last_status = f'Ready to retry {cleared} deferred sync row(s)'
            return cleared
        except Exception as error:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.debug('Approval backoff clear skipped: %s', error)
            return 0
        finally:
            conn.close()

    def flush_entity_outbox(self, limit: int = 100) -> int:
        """Push one transactional, idempotent entity batch to the Portal API."""
        ident = load_identity()
        org_id = str(ident.get('org_id') or '')
        token = str(ident.get('access_token') or '')
        device_id = get_or_create_device_id()
        if not org_id or not token:
            return 0

        conn = sqlite3.connect(get_db_path(), timeout=10)
        configure_sqlite_connection(conn)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM sync_outbox "
                "WHERE processed_at IS NULL AND available_at <= CURRENT_TIMESTAMP "
                "ORDER BY id LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
            if not rows:
                return 0

            entities = []
            event_ids = []
            for event in rows:
                event_ids.append(event['event_id'])
                entity_type = event['entity_type']
                table = ENTITY_TABLE_MAP.get(entity_type)
                payload = {}
                deleted = event['operation'] == 'delete'
                if table and not deleted:
                    key_column = 'key' if table == 'system_settings' else 'id'
                    current = conn.execute(
                        f'SELECT * FROM "{table}" WHERE "{key_column}"=?',
                        (event['row_id'],),
                    ).fetchone()
                    if current:
                        payload = serialize_entity_payload(
                            entity_type, dict(current)
                        )
                    else:
                        deleted = True
                elif deleted:
                    payload = serialize_entity_payload(entity_type, {})

                entities.append({
                    'branch_id': ident.get('branch_id') or '',
                    'entity_type': entity_type,
                    'source_id': str(event['row_id']),
                    'source_version': int(event['id']),
                    'source_updated_at': (
                        payload.get('updated_at')
                        or payload.get('created_at')
                        or event['created_at']
                    ),
                    'payload': payload,
                    'payload_hash': _payload_hash(payload),
                    'deleted': deleted,
                })

            batch_key = hashlib.sha256(
                f"{org_id}:{device_id}:{','.join(event_ids)}".encode()
            ).hexdigest()
            portal_url = os.environ.get(
                'MBT_PORTAL_URL',
                'https://portal.mugobyte.com',
            ).rstrip('/')
            response = self._post_entity_sync_batch(
                portal_url=portal_url,
                token=token,
                batch_key=batch_key,
                org_id=org_id,
                device_id=device_id,
                entities=entities,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f'Entity sync failed ({response.status_code}): '
                    f'{response.text[:200]}'
                )
            placeholders = ','.join('?' for _ in event_ids)
            conn.execute(
                f"UPDATE sync_outbox SET processed_at=CURRENT_TIMESTAMP, "
                f"last_error=NULL WHERE event_id IN ({placeholders})",
                event_ids,
            )
            conn.commit()
            self._last_status = f'Synced {len(event_ids)} changes'
            return len(event_ids)
        except Exception as error:
            if 'rows' in locals() and rows:
                retry_at = datetime.now() + timedelta(
                    seconds=min(3600, 30 * (2 ** min(int(rows[0]['attempts']), 7)))
                )
                ids = [row['id'] for row in rows]
                placeholders = ','.join('?' for _ in ids)
                conn.execute(
                    f"UPDATE sync_outbox SET attempts=attempts+1, last_error=?, "
                    f"available_at=? WHERE id IN ({placeholders})",
                    [str(error)[:500], retry_at.strftime('%Y-%m-%d %H:%M:%S'), *ids],
                )
                conn.commit()
            self._last_error = str(error)
            logger.warning('Entity outbox sync deferred: %s', error)
            return 0
        finally:
            conn.close()

    def enqueue_offline(self, item: dict) -> None:
        q = load_json(offline_queue_path(), {'items': []})
        items = q.get('items') or []
        items.append({**item, 'enqueued_at': _utc_now()})
        q['items'] = items[-50:]  # cap
        save_json(offline_queue_path(), q)

    def flush_offline_queue(self) -> int:
        if not (is_logged_in() and is_cloud_configured()):
            return 0
        q = load_json(offline_queue_path(), {'items': []})
        items = q.get('items') or []
        if not items:
            return 0
        remaining = []
        done = 0
        for item in items:
            try:
                if item.get('type') == 'backup_meta' and item.get('local_enc_path'):
                    # Re-attempt upload if file still exists
                    path = item['local_enc_path']
                    if os.path.isfile(path):
                        client = SupabaseClient()
                        obj = item.get('storage_path') or ''
                        client.upload_file(obj, path)
                        client.insert_backup_meta(item.get('meta') or {})
                        done += 1
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                    else:
                        remaining.append(item)
                else:
                    remaining.append(item)
            except Exception as e:
                logger.info('Offline queue item deferred: %s', e)
                remaining.append(item)
        save_json(offline_queue_path(), {'items': remaining})
        return done

    def run_backup(self, reason: str = 'manual', password: str = '') -> dict:
        """
        Create encrypted snapshot, upload to Supabase Storage, insert metadata.
        Returns status dict. Safe to call from UI thread via worker.
        """
        if not self._busy.acquire(blocking=False):
            return {'ok': False, 'error': 'Backup already in progress'}
        tmp_dir = None
        try:
            if not is_cloud_configured():
                return {'ok': False, 'error': 'Cloud not configured (cloud_config.json)'}
            if not is_logged_in():
                return {'ok': False, 'error': 'Not signed in to MugoByte Platform'}

            self._emit('Creating database snapshot…', 10)
            zip_path, tmp_dir = create_sqlite_snapshot()
            size_plain = os.path.getsize(zip_path)

            ident = load_identity()
            key, ident = ensure_identity_key_material(ident, password=password)
            # Heal stale identity: business_id must belong to the signed-in user
            # or RLS blocks backup metadata inserts.
            try:
                client = SupabaseClient()
                uid = ident.get('user_id') or ''
                bid = ident.get('business_id') or ''
                if uid:
                    owned = client.rest_select(
                        'businesses',
                        f'owner_user_id=eq.{quote(uid, safe="")}'
                        f'&select=id,name,org_id&limit=5',
                    ) or []
                    owned_ids = {str(b.get('id')) for b in owned if b.get('id')}
                    if bid and bid not in owned_ids and owned:
                        bid = str(owned[0]['id'])
                        ident['business_id'] = bid
                        if owned[0].get('org_id'):
                            ident['org_id'] = owned[0]['org_id']
                        logger.warning('Repaired cloud identity business_id → %s', bid)
                    elif not bid:
                        biz = client.ensure_business(
                            uid,
                            (ident.get('email') or 'My Business').split('@')[0],
                        )
                        bid = str((biz or {}).get('id') or '')
                        ident['business_id'] = bid
                        if (biz or {}).get('org_id'):
                            ident['org_id'] = biz['org_id']
            except Exception as e:
                logger.warning('business identity repair skipped: %s', e)
            save_identity(ident)

            enc_path = zip_path + '.mbtenc'
            self._emit('Encrypting backup…', 35)
            enc_size = encrypt_file(zip_path, enc_path, key)
            content_hash = sha256_file(enc_path)

            device = get_device_info()
            business_id = ident.get('business_id') or ''
            if not business_id:
                return {'ok': False, 'error': 'No business linked to this cloud account'}
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            object_path = f'{business_id}/{device["device_id"]}/{stamp}.mbtenc'

            client = SupabaseClient()
            self._emit('Uploading to MugoByte Platform…', 55)
            try:
                client.upload_file(object_path, enc_path, content_type='application/octet-stream')
            except (SupabaseError, OSError, ConnectionError) as e:
                # Queue for retry when offline / upload fails
                hold = os.path.join(
                    os.path.dirname(backup_state_path()),
                    f'pending_{stamp}.mbtenc',
                )
                try:
                    shutil.copy2(enc_path, hold)
                except Exception:
                    hold = enc_path
                    tmp_dir = None  # don't delete yet
                meta = self._build_meta(
                    business_id, device, object_path, enc_size, content_hash, reason)
                self.enqueue_offline({
                    'type': 'backup_meta',
                    'local_enc_path': hold,
                    'storage_path': object_path,
                    'meta': meta,
                })
                self._last_error = str(e)
                save_json(backup_state_path(), {
                    **load_json(backup_state_path(), {}),
                    'last_error': str(e),
                    'last_attempt_at': _utc_now(),
                })
                self._emit(f'Offline — queued ({e})', -1)
                return {'ok': False, 'queued': True, 'error': str(e)}
            except Exception as e:
                # requests HTTPError / generic network
                hold = os.path.join(
                    os.path.dirname(backup_state_path()),
                    f'pending_{stamp}.mbtenc',
                )
                try:
                    shutil.copy2(enc_path, hold)
                except Exception:
                    hold = enc_path
                    tmp_dir = None
                meta = self._build_meta(
                    business_id, device, object_path, enc_size, content_hash, reason)
                self.enqueue_offline({
                    'type': 'backup_meta',
                    'local_enc_path': hold,
                    'storage_path': object_path,
                    'meta': meta,
                })
                self._last_error = str(e)
                self._emit(f'Offline — queued ({e})', -1)
                return {'ok': False, 'queued': True, 'error': str(e)}

            meta = self._build_meta(
                business_id, device, object_path, enc_size, content_hash, reason)
            self._emit('Saving backup metadata…', 85)
            row = client.insert_backup_meta(meta)
            client.log_sync({
                'business_id': business_id,
                'device_id': device['device_id'],
                'event_type': 'backup',
                'status': 'ok',
                'message': reason,
                'detail': json.dumps({'size': enc_size, 'hash': content_hash}),
            })

            # Touch device last_seen
            try:
                client.register_device(
                    business_id,
                    device['device_id'],
                    hostname=device.get('hostname') or '',
                    platform_str=device.get('platform') or '',
                    mbt_version=_app_version(),
                )
            except Exception:
                pass

            backup_id = (row or {}).get('id') if isinstance(row, dict) else ''
            # Merge into existing state so analytics_backfill / other checkpoints
            # survive every backup write.
            prev = load_json(backup_state_path(), {})
            state = {
                **prev,
                'last_backup_at': _utc_now(),
                'last_backup_size': enc_size,
                'last_backup_id': backup_id or '',
                'last_storage_path': object_path,
                'last_content_hash': content_hash,
                'last_plain_size': size_plain,
                'last_error': '',
                'last_reason': reason,
            }
            save_json(backup_state_path(), state)
            self._last_error = ''
            self._emit('Backup complete', 100)
            logger.info('Cloud backup OK: %s (%.1f KB)', object_path, enc_size / 1024)
            return {'ok': True, 'meta': meta, 'row': row, 'size': enc_size}
        except EncryptionError as e:
            self._last_error = str(e)
            self._emit(str(e), -1)
            return {'ok': False, 'error': str(e)}
        except Exception as e:
            logger.exception('Backup failed')
            self._last_error = str(e)
            self._emit(str(e), -1)
            return {'ok': False, 'error': str(e)}
        finally:
            self._busy.release()
            if tmp_dir and os.path.isdir(tmp_dir):
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception:
                    pass

    def _build_meta(self, business_id, device, object_path, enc_size, content_hash, reason):
        return {
            'business_id': business_id,
            'device_id': device['device_id'],
            'storage_path': object_path,
            'size_bytes': enc_size,
            'content_hash': content_hash,
            'mbt_version': _app_version(),
            'schema_version': SCHEMA_VERSION,
            'backup_type': 'full_snapshot',
            'reason': reason,
            'created_at': _utc_now(),
        }

