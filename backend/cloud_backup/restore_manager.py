"""
Download encrypted snapshots from Supabase and restore/replace local DB.

Compatibility: refuses restore when backup schema_version > current, or when
backup mbt_version is newer than a hard min (current app too old).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import Callable, Optional

from mbt_paths import configure_sqlite_connection, get_data_dir, get_db_path

from backend.cloud_backup import SCHEMA_VERSION
from backend.cloud_backup.device_manager import get_or_create_device_id
from backend.cloud_backup.encryption import (
    EncryptionError,
    decrypt_file,
    derive_candidate_keys,
    ensure_identity_key_material,
)
from backend.cloud_backup.paths import load_identity, save_identity
from backend.cloud_backup.supabase_client import SupabaseClient, SupabaseError

logger = logging.getLogger('cloud_backup.restore')


class RestoreError(Exception):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_version(v: str) -> tuple:
    parts = []
    for p in str(v or '0').split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def _app_version() -> str:
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, 'version.json'), encoding='utf-8-sig') as f:
            return str(json.load(f).get('version') or '0')
    except Exception:
        return '0'


def check_compatibility(backup_meta: dict) -> tuple[bool, str]:
    """
    Returns (ok, message). Refuse if current app is too old for the backup.
    """
    bak_schema = int(backup_meta.get('schema_version') or 0)
    bak_ver = str(backup_meta.get('mbt_version') or '0')
    cur_ver = _app_version()

    if bak_schema > SCHEMA_VERSION:
        return False, (
            f'This backup requires schema v{bak_schema}, but this app supports '
            f'v{SCHEMA_VERSION}. Update MBT POS before restoring.'
        )
    # If backup was made with a much newer app (major.minor ahead), warn/refuse
    bv, cv = _parse_version(bak_ver), _parse_version(cur_ver)
    if bv[:2] > cv[:2]:
        return False, (
            f'This backup was created with MBT POS {bak_ver}. '
            f'You are running {cur_ver}. Update MBT POS before restoring.'
        )
    if bak_schema < SCHEMA_VERSION:
        return True, (
            f'Backup schema v{bak_schema} is older than current v{SCHEMA_VERSION}; '
            'restore will run local migrations after replace.'
        )
    return True, 'Compatible'


class RestoreManager:
    def __init__(self):
        self._progress_cb: Optional[Callable[[str, float], None]] = None

    def set_progress_callback(self, cb: Callable[[str, float], None] | None):
        self._progress_cb = cb

    def _emit(self, msg: str, pct: float = -1):
        if self._progress_cb:
            try:
                self._progress_cb(msg, pct)
            except Exception:
                pass

    def list_available_backups(self, limit: int = 30) -> list:
        ident = load_identity()
        biz = ident.get('business_id') or ''
        if not biz:
            return []
        client = SupabaseClient()
        return client.list_backups(biz, limit=limit)

    def latest_backup(self) -> dict | None:
        rows = self.list_available_backups(limit=30)
        if not rows:
            return None
        # Prefer a real snapshot over empty post-wipe backups that sort newer.
        # Tiny encrypted envelopes (~<50KB) are almost always empty DBs.
        substantial = [
            r for r in rows
            if int(r.get('size_bytes') or 0) >= 50_000
        ]
        pool = substantial or rows
        return max(pool, key=lambda r: int(r.get('size_bytes') or 0))

    def restore_from_meta(
        self,
        backup_row: dict,
        password: str = '',
        replace: bool = True,
    ) -> dict:
        """
        Download → decrypt → unzip → replace live DB (with .pre_restore backup).
        """
        ok, msg = check_compatibility(backup_row)
        if not ok:
            raise RestoreError(msg)

        storage_path = backup_row.get('storage_path') or ''
        if not storage_path:
            raise RestoreError('Backup has no storage_path')

        tmp = tempfile.mkdtemp(prefix='mbt_cloud_restore_')
        try:
            enc_path = os.path.join(tmp, 'backup.mbtenc')
            self._emit('Downloading backup…', 15)
            client = SupabaseClient()
            client.download_file(storage_path, enc_path)

            ident = load_identity()
            _key, ident = ensure_identity_key_material(ident, password=password)
            save_identity(ident)

            zip_path = os.path.join(tmp, 'backup.zip')
            self._emit('Decrypting…', 40)
            candidates = derive_candidate_keys(ident, password=password)
            if not candidates:
                raise RestoreError('No decryption key material available for this account')
            last_err: Optional[Exception] = None
            decrypted = False
            for cand in candidates:
                try:
                    decrypt_file(enc_path, zip_path, cand)
                    decrypted = True
                    break
                except EncryptionError as e:
                    last_err = e
                    continue
            if not decrypted:
                raise RestoreError(
                    'Decryption failed — wrong key/password for this account '
                    f'({last_err})'
                ) from last_err

            self._emit('Extracting database…', 60)
            extract_dir = os.path.join(tmp, 'out')
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
                # Prefer meta from zip if present
                if 'backup_meta.json' in zf.namelist():
                    try:
                        zip_meta = json.loads(zf.read('backup_meta.json'))
                        ok2, msg2 = check_compatibility({**backup_row, **zip_meta})
                        if not ok2:
                            raise RestoreError(msg2)
                    except RestoreError:
                        raise
                    except Exception:
                        pass

            snap = os.path.join(extract_dir, 'mbt_pos.db')
            if not os.path.isfile(snap):
                # search
                for root, _dirs, files in os.walk(extract_dir):
                    if 'mbt_pos.db' in files:
                        snap = os.path.join(root, 'mbt_pos.db')
                        break
            if not os.path.isfile(snap):
                raise RestoreError('Backup archive missing mbt_pos.db')

            # Sanity: open SQLite
            conn = sqlite3.connect(snap)
            try:
                configure_sqlite_connection(conn)
                conn.execute('SELECT count(*) FROM sqlite_master').fetchone()
            finally:
                conn.close()

            live = get_db_path()
            data_dir = get_data_dir()
            os.makedirs(data_dir, exist_ok=True)

            if replace:
                self._emit('Replacing local database…', 80)
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                if os.path.isfile(live):
                    pre = os.path.join(data_dir, f'mbt_pos.pre_restore_{stamp}.db')
                    shutil.copy2(live, pre)
                    # Also copy WAL/SHM aside if present
                    for suffix in ('-wal', '-shm'):
                        side = live + suffix
                        if os.path.isfile(side):
                            try:
                                shutil.copy2(side, pre + suffix)
                            except Exception:
                                pass
                # Remove WAL so we don't mix journals
                for suffix in ('-wal', '-shm'):
                    side = live + suffix
                    if os.path.isfile(side):
                        try:
                            os.remove(side)
                        except OSError:
                            pass
                shutil.copy2(snap, live)

            try:
                client.log_restore({
                    'business_id': backup_row.get('business_id') or load_identity().get('business_id'),
                    'device_id': get_or_create_device_id(),
                    'backup_id': backup_row.get('id'),
                    'status': 'ok',
                    'message': msg,
                    'restored_at': _utc_now(),
                })
            except Exception:
                pass

            self._emit('Restore complete — restart recommended', 100)
            return {
                'ok': True,
                'message': msg,
                'db_path': live,
                'compatibility': msg,
            }
        except (RestoreError, SupabaseError):
            raise
        except Exception as e:
            logger.exception('Restore failed')
            raise RestoreError(str(e)) from e
        finally:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

    def restore_latest(self, password: str = '') -> dict:
        latest = self.latest_backup()
        if not latest:
            raise RestoreError('No cloud backups found for this business')
        return self.restore_from_meta(latest, password=password)
