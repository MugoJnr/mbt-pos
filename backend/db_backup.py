"""
MBT POS — Telegram Database Backup
MugoByte Technologies | mugobyte.com

Creates a consistent SQLite snapshot (safe while POS is running),
compresses it, and sends to Telegram for disaster recovery.

Recipients (default):
  • Shop owner chat  (telegram_chat_id)
  • Developer chat   (developer_chat_id) — you keep a copy if the PC is lost

Telegram document limit ≈ 50 MB — backups over ~48 MB are skipped with a warning.
"""
import hashlib
import logging
import os
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime

from mbt_paths import configure_sqlite_connection, get_db_path, get_project_root

logger = logging.getLogger('db_backup')

TELEGRAM_MAX_BYTES = 48 * 1024 * 1024   # stay under Telegram's 50 MB cap
DEFAULT_INTERVAL_HRS = 24


def _backup_recipients(cfg: dict) -> list[tuple[str, str]]:
    """Unique chat IDs: (chat_id, label)."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for key, label in (
        ('telegram_chat_id', 'shop'),
        ('developer_chat_id', 'developer'),
    ):
        cid = str(cfg.get(key) or '').strip()
        if cid and cid not in seen:
            seen.add(cid)
            out.append((cid, label))
    return out


def create_db_backup_zip(db_path: str = None) -> tuple[str, int, str]:
    """
    Snapshot DB via SQLite backup API, zip it.
    Returns (zip_path, byte_size, content_hash).
    """
    db_path = db_path or get_db_path()
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f'Database not found: {db_path}')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    shop_safe = 'mbt_pos'
    tmp_dir = tempfile.mkdtemp(prefix='mbt_db_bak_')
    snap_db = os.path.join(tmp_dir, 'mbt_pos.db')
    zip_name = f'MBT_POS_DB_{shop_safe}_{stamp}.zip'
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


def _backup_caption(shop: str, size: int, device_hint: str, reason: str) -> str:
    mb = size / (1024 * 1024)
    return (
        f'💾 <b>Database Backup — {shop}</b>\n'
        f'When: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
        f'Size: {mb:.2f} MB\n'
        f'Trigger: {reason}\n'
        f'Device: <code>{device_hint}</code>\n'
        f'Unzip → place <code>mbt_pos.db</code> in AppData data folder.\n'
        f'<i>MugoByte Technologies · mugobyte.com</i>'
    )


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
    extra_chat_ids: list[str] = None,
    reason: str = 'manual',
) -> None:
    """Export + send DB backup in a background thread."""

    def _run():
        from backend.telegram_hub import resolve_bot_token
        from backend.telegram_reporter import _send_document, _send_message, _telegram_preflight

        cfg = config_getter() or {}
        token = resolve_bot_token(cfg)
        shop = cfg.get('shop_name', 'My Shop')

        recipients = list(_backup_recipients(cfg))
        if extra_chat_ids:
            seen = {c for c, _ in recipients}
            for cid in extra_chat_ids:
                cid = str(cid or '').strip()
                if cid and cid not in seen:
                    seen.add(cid)
                    recipients.append((cid, 'admin'))

        if not token:
            if on_done:
                on_done(False, 'Bot token not configured.')
            return
        if not recipients:
            if on_done:
                on_done(False, 'No Telegram chat configured. Connect Telegram in Settings.')
            return

        zip_path = ''
        try:
            if on_progress:
                on_progress('Creating database snapshot…')
            zip_path, size, digest = create_db_backup_zip()

            if size > TELEGRAM_MAX_BYTES:
                msg = (
                    f'⚠️ DB backup too large for Telegram ({size / (1024 * 1024):.1f} MB). '
                    f'Copy manually from:\n{get_db_path()}'
                )
                for cid, _ in recipients:
                    _send_message(token, cid, msg)
                if on_done:
                    on_done(False, msg)
                return

            caption = _backup_caption(shop, size, _device_hint(), reason)
            ok_any = False
            errors: list[str] = []

            for cid, label in recipients:
                if on_progress:
                    on_progress(f'Sending backup to {label}…')
                ok, pre_err = _telegram_preflight(token, cid)
                if not ok:
                    errors.append(f'{label}: {pre_err}')
                    continue
                ok, err = _send_document(token, cid, zip_path, caption, retries=3)
                if ok:
                    ok_any = True
                    logger.info('DB backup sent to %s (%s)', label, cid)
                else:
                    errors.append(f'{label}: {err}')

            if ok_any and api:
                try:
                    api.update_settings({
                        'last_db_backup_at': datetime.now().isoformat(timespec='seconds'),
                        'last_db_backup_hash': digest,
                    })
                except Exception as e:
                    logger.warning('Could not persist backup timestamp: %s', e)

            if ok_any:
                msg = f'Database backup sent ({size / (1024 * 1024):.2f} MB)'
                if errors:
                    msg += '\nPartial: ' + '; '.join(errors)
                if on_done:
                    on_done(True, msg)
            else:
                if on_done:
                    on_done(False, '; '.join(errors) or 'Send failed.')
        except Exception as e:
            logger.error('send_db_backup_now: %s', e, exc_info=True)
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
    if not _backup_recipients(cfg):
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
