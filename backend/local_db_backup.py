"""
Local automatic SQLite backups (filesystem) — no Telegram/cloud required.

Stores rotating zip snapshots under %LOCALAPPDATA%\\MugoByte\\MBT POS\\backups\\
and records last_local_backup_at in system_settings when an API is available.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime
from typing import Optional

from mbt_paths import ensure_data_dirs, get_project_root

logger = logging.getLogger('local_db_backup')

DEFAULT_INTERVAL_HRS = 6
KEEP_COUNT = 14
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_last_status = ''
_last_path = ''
_last_error = ''
_last_at = ''


def get_local_backup_dir() -> str:
    root = ensure_data_dirs(get_project_root())
    path = os.path.join(root, 'backups')
    os.makedirs(path, exist_ok=True)
    return path


def local_backup_status() -> dict:
    return {
        'last_status': _last_status,
        'last_path': _last_path,
        'last_error': _last_error,
        'last_at': _last_at,
        'backup_dir': get_local_backup_dir(),
        'running': bool(_thread and _thread.is_alive()),
    }


def create_local_backup(reason: str = 'manual') -> dict:
    """Create a local zip snapshot and prune old ones. Returns status dict."""
    global _last_status, _last_path, _last_error, _last_at
    from backend.db_backup import create_db_backup_zip

    with _lock:
        zip_path = None
        try:
            zip_path, size, content_hash = create_db_backup_zip()
            dest_dir = get_local_backup_dir()
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            dest = os.path.join(dest_dir, f'MBT_POS_DB_local_{stamp}.zip')
            shutil.move(zip_path, dest)
            zip_path = None
            _prune(dest_dir)
            _last_at = datetime.now().isoformat(timespec='seconds')
            _last_path = dest
            _last_error = ''
            _last_status = f'OK ({reason}) {size / 1024:.0f} KB hash={content_hash}'
            logger.info('Local DB backup saved: %s (%s)', dest, _last_status)
            return {
                'ok': True,
                'path': dest,
                'size': size,
                'hash': content_hash,
                'at': _last_at,
                'reason': reason,
            }
        except Exception as e:
            _last_error = str(e)
            _last_status = f'FAIL: {e}'
            logger.error('Local DB backup failed: %s', e, exc_info=True)
            return {'ok': False, 'error': str(e), 'reason': reason}
        finally:
            if zip_path and os.path.isfile(zip_path):
                try:
                    os.remove(zip_path)
                    parent = os.path.dirname(zip_path)
                    if parent and os.path.basename(parent).startswith('mbt_db_bak_'):
                        os.rmdir(parent)
                except OSError:
                    pass


def _prune(dest_dir: str) -> None:
    files = [
        os.path.join(dest_dir, f)
        for f in os.listdir(dest_dir)
        if f.startswith('MBT_POS_DB_local_') and f.endswith('.zip')
    ]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for old in files[KEEP_COUNT:]:
        try:
            os.remove(old)
        except OSError:
            pass


def _interval_seconds(config_getter) -> int:
    hrs = DEFAULT_INTERVAL_HRS
    try:
        cfg = config_getter() if config_getter else {}
        raw = cfg.get('auto_local_db_backup_interval_hours') or cfg.get(
            'auto_db_backup_interval_hours') or DEFAULT_INTERVAL_HRS
        hrs = float(raw)
        hrs = max(1.0, min(hrs, 168.0))
    except Exception:
        hrs = DEFAULT_INTERVAL_HRS
    return int(hrs * 3600)


def _enabled(config_getter) -> bool:
    try:
        cfg = config_getter() if config_getter else {}
        # Default ON — local backups need no shop Telegram setup
        return str(cfg.get('auto_local_db_backup', '1')) != '0'
    except Exception:
        return True


def start_local_backup_scheduler(config_getter=None, api=None) -> None:
    """Daemon loop: local zip every N hours (default 6). Runs without Telegram."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def _loop():
        # Let POS finish boot; then take an immediate backup if none today
        _stop.wait(45)
        while not _stop.is_set():
            try:
                if _enabled(config_getter):
                    due = True
                    if _last_at:
                        try:
                            age = (datetime.now() - datetime.fromisoformat(_last_at)).total_seconds()
                            due = age >= _interval_seconds(config_getter)
                        except Exception:
                            due = True
                    if due:
                        result = create_local_backup(reason='scheduled')
                        if result.get('ok') and api is not None:
                            try:
                                # Persist marker for Settings visibility
                                if hasattr(api, 'update_settings'):
                                    api.update_settings({
                                        'last_local_backup_at': result['at'],
                                        'last_local_backup_path': result['path'],
                                    })
                                elif hasattr(api, 'set_setting'):
                                    api.set_setting('last_local_backup_at', result['at'])
                            except Exception as e:
                                logger.debug('persist local backup marker: %s', e)
            except Exception as e:
                logger.warning('local backup loop: %s', e)
            _stop.wait(_interval_seconds(config_getter))

    _thread = threading.Thread(target=_loop, name='MBT-LocalDbBackup', daemon=True)
    _thread.start()
    logger.info('Local DB backup scheduler started')


def stop_local_backup_scheduler() -> None:
    _stop.set()
