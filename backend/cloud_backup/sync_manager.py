"""
Background cloud backup: encrypted SQLite snapshots on a schedule + Backup Now.

Also maintains a lightweight local change_log for products/sales/customers
(architecture hook for future incremental sync). Offline queue retries when
connectivity returns.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Callable, Optional

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


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
        return {
            'enabled': bool(cfg.get('enabled')),
            'configured': is_cloud_configured(),
            'logged_in': is_logged_in(),
            'cloud_skipped': bool(ident.get('cloud_skipped')),
            'device_id': get_or_create_device_id(),
            'business_id': ident.get('business_id') or '',
            'business_name': ident.get('business_name') or '',
            'email': ident.get('email') or '',
            'interval_minutes': int(cfg.get('backup_interval_minutes') or DEFAULT_INTERVAL_MIN),
            'last_backup_at': state.get('last_backup_at') or '',
            'last_backup_size': state.get('last_backup_size') or 0,
            'last_backup_id': state.get('last_backup_id') or '',
            'last_error': self._last_error or state.get('last_error') or '',
            'status': self._last_status,
            'queue_depth': len(load_json(offline_queue_path(), {'items': []}).get('items') or []),
            'mbt_version': _app_version(),
            'schema_version': SCHEMA_VERSION,
        }

    def _loop(self):
        # Initial delay so POS UI can finish booting
        self._stop.wait(20)
        while not self._stop.is_set():
            cfg = load_cloud_config()
            interval_min = max(1, int(cfg.get('backup_interval_minutes') or DEFAULT_INTERVAL_MIN))
            try:
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
                return {'ok': False, 'error': 'Not signed in to MBT Cloud'}

            self._emit('Creating database snapshot…', 10)
            zip_path, tmp_dir = create_sqlite_snapshot()
            size_plain = os.path.getsize(zip_path)

            ident = load_identity()
            key, ident = ensure_identity_key_material(ident, password=password)
            save_identity(ident)

            enc_path = zip_path + '.mbtenc'
            self._emit('Encrypting backup…', 35)
            enc_size = encrypt_file(zip_path, enc_path, key)
            content_hash = sha256_file(enc_path)

            device = get_device_info()
            business_id = ident.get('business_id') or ''
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            object_path = f'{business_id}/{device["device_id"]}/{stamp}.mbtenc'

            client = SupabaseClient()
            self._emit('Uploading to MBT Cloud…', 55)
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
            state = {
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

