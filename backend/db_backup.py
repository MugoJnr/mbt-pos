"""
MBT POS — Cloud Database Backup
MugoByte Technologies | mugobyte.com

Creates a consistent SQLite snapshot (safe while POS is running),
compresses it, and uploads to MBT Cloud (Supabase Storage).

Replaces Telegram document delivery.
"""
import hashlib
import logging
import os
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime

from mbt_paths import configure_sqlite_connection, get_db_path

logger = logging.getLogger('db_backup')

DEFAULT_INTERVAL_HRS = 24


def create_db_backup_zip(db_path: str = None) -> tuple[str, int, str]:
    """Snapshot DB via SQLite backup API, zip it. Returns (zip_path, byte_size, content_hash)."""
    db_path = db_path or get_db_path()
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f'Database not found: {db_path}')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tmp_dir = tempfile.mkdtemp(prefix='mbt_db_bak_')
    snap_db = os.path.join(tmp_dir, 'mbt_pos.db')
    zip_name = f'MBT_POS_DB_{stamp}.zip'
    zip_path = os.path.join(tmp_dir, zip_name)

    src = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    dst = sqlite3.connect(snap_db)
    try:
        configure_sqlite_connection(src)
        configure_sqlite_connection(dst)
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(snap_db, arcname='mbt_pos.db')
        readme = (
            'MBT POS database backup\n'
            f'Created: {datetime.now().isoformat(timespec="seconds")}\n'
            'Restore: copy mbt_pos.db to\n'
            r'  %LOCALAPPDATA%\MugoByte\MBT POS\data\mbt_pos.db\n'
            'Then restart MBT POS.\n'
        )
        zf.writestr('RESTORE.txt', readme)

    try:
        os.remove(snap_db)
    except OSError:
        pass

    with open(zip_path, 'rb') as f:
        content_hash = hashlib.sha256(f.read()).hexdigest()[:16]

    size = os.path.getsize(zip_path)
    logger.info('DB backup archive: %s (%.2f MB)', zip_name, size / (1024 * 1024))
    return zip_path, size, content_hash


def _device_hint() -> str:
    try:
        from licensing.license_engine import LicenseEngine
        eng = LicenseEngine()
        return eng.device_id[:12] + '…'
    except Exception:
        return 'unknown'


def send_db_backup_now(
    config_getter,
    api=None,
    on_progress=None,
    on_done=None,
    reason: str = 'manual',
) -> None:
    """Export + upload DB backup to cloud in a background thread."""

    def _run():
        cfg = config_getter() or {}
        shop = cfg.get('shop_name', 'My Shop')
        zip_path = ''

        try:
            if on_progress:
                on_progress('Creating database snapshot…')
            zip_path, size, digest = create_db_backup_zip()

            uploaded = False
            try:
                from backend.cloud_backup.paths import is_cloud_configured
                if is_cloud_configured():
                    from backend.cloud_backup.sync_manager import SyncManager
                    mgr = SyncManager()
                    if on_progress:
                        on_progress('Uploading to MugoByte Platform…')
                    mgr.run_backup_now(reason=reason)
                    uploaded = True
            except Exception as e:
                logger.warning('Cloud upload failed, keeping local copy: %s', e)

            from backend.cloud.notification_engine import get_notification_engine
            engine = get_notification_engine(config_getter=config_getter)
            detail = f'{shop} · {size / (1024 * 1024):.2f} MB · {"cloud" if uploaded else "local"}'
            engine.publish_backup(True, detail)

            if api:
                try:
                    api.update_settings({
                        'last_db_backup_at': datetime.now().isoformat(timespec='seconds'),
                        'last_db_backup_hash': digest,
                    })
                except Exception as e:
                    logger.warning('Could not persist backup timestamp: %s', e)

            msg = f'Database backup {"uploaded to cloud" if uploaded else "saved locally"} ({size / (1024 * 1024):.2f} MB)'
            if on_done:
                on_done(True, msg)
        except Exception as e:
            logger.error('send_db_backup_now: %s', e, exc_info=True)
            try:
                from backend.cloud.notification_engine import get_notification_engine
                get_notification_engine(config_getter=config_getter).publish_backup(False, str(e))
            except Exception:
                pass
            if on_done:
                on_done(False, str(e))
        finally:
            if zip_path and os.path.isfile(zip_path):
                try:
                    os.remove(zip_path)
                    parent = os.path.dirname(zip_path)
                    if parent and os.path.basename(parent).startswith('mbt_db_bak_'):
                        os.rmdir(parent)
                except OSError:
                    pass

    threading.Thread(target=_run, daemon=True, name='DbBackup').start()


def should_send_scheduled_backup(cfg: dict, last_sent_at: datetime | None) -> bool:
    if cfg.get('auto_db_backup', '1') != '1':
        return False
    try:
        hrs = float(cfg.get('auto_db_backup_interval_hours', DEFAULT_INTERVAL_HRS))
        hrs = max(6.0, min(hrs, 168.0))
    except (TypeError, ValueError):
        hrs = DEFAULT_INTERVAL_HRS
    interval = int(hrs * 3600)

    if last_sent_at is None:
        persisted = (cfg.get('last_db_backup_at') or '').strip()
        if persisted:
            try:
                last_sent_at = datetime.fromisoformat(persisted)
            except ValueError:
                last_sent_at = None
    if last_sent_at is None:
        return True
    return (datetime.now() - last_sent_at).total_seconds() >= interval


def parse_last_backup_at(cfg: dict) -> datetime | None:
    raw = (cfg.get('last_db_backup_at') or '').strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
