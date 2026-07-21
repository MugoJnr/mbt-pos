"""
MBT POS — single source of truth for where data is stored.

All shop data (database, settings, setup flag, exports) must use these helpers
so the app never "resets" because it was started from a different folder.
"""
import logging
import os
import shutil
import sqlite3
import sys

logger = logging.getLogger('mbt_paths')

_BRAND_PARTS = ('MugoByte', 'MBT POS')


def _user_data_root() -> str:
    """Permanent writable folder for installed / portable .exe runs."""
    base = (
        os.environ.get('LOCALAPPDATA')
        or os.environ.get('APPDATA')
        or os.path.expanduser('~')
    )
    return os.path.join(base, *_BRAND_PARTS)


def get_project_root() -> str:
    """
    Return the folder that contains data/, logs/, config/, exports/.

    - MBT_DATA_ROOT env: cloud server / container data dir (e.g. /data)
    - Frozen (.exe): ALWAYS %LOCALAPPDATA%\\MugoByte\\MBT POS
    - Development: folder containing this file (extracted/mbt_pos).
    """
    override = os.environ.get('MBT_DATA_ROOT', '').strip()
    if override:
        _migrate_legacy_data(override)
        return ensure_data_dirs(override)
    if getattr(sys, 'frozen', False):
        root = _user_data_root()
        _migrate_legacy_data(root)
        return root
    # Development: use the same AppData store as the installed app when present,
    # so Cloudflare, notification, and DB paths are not split between the repo
    # and %LOCALAPPDATA%.
    appdata = _user_data_root()
    appdata_db = os.path.join(appdata, 'data', 'mbt_pos.db')
    if _db_has_shop_data(appdata_db):
        return ensure_data_dirs(appdata)
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    return os.path.join(get_project_root(), 'data')


def get_db_path() -> str:
    return os.path.join(get_data_dir(), 'mbt_pos.db')


def configure_sqlite_connection(conn: sqlite3.Connection) -> None:
    """Standard PRAGMAs for all MBT POS database connections."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")


def get_init_flag_path() -> str:
    return os.path.join(get_data_dir(), '.initialized')


def ensure_data_dirs(root: str = None) -> str:
    root = root or get_project_root()
    for name in ('logs', 'data', 'config', 'exports', 'backups'):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    _write_path_marker(root)
    return root


def _write_path_marker(root: str):
    """Help support find the live database path."""
    try:
        marker = os.path.join(root, 'data', 'DATA_LOCATION.txt')
        db_path = os.path.join(root, 'data', 'mbt_pos.db')
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(
                'MBT POS stores all shop data here.\n'
                f'Database: {db_path}\n'
                f'Root: {root}\n'
            )
    except Exception:
        pass


def _db_has_shop_data(db_path: str) -> bool:
    if not os.path.exists(db_path) or os.path.getsize(db_path) < 100:
        return False
    try:
        conn = sqlite3.connect(db_path)
        configure_sqlite_connection(conn)
        try:
            users = conn.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
            products = conn.execute(
                "SELECT COUNT(*) FROM products"
            ).fetchone()[0]
            sales = conn.execute(
                "SELECT COUNT(*) FROM sales"
            ).fetchone()[0]
            return (users + products + sales) > 0
        except sqlite3.OperationalError:
            return os.path.getsize(db_path) > 16384
        finally:
            conn.close()
    except Exception:
        return False


def _copy_tree_files(src_dir: str, dst_dir: str):
    if not os.path.isdir(src_dir):
        return
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def _migrate_legacy_data(canonical_root: str):
    """If canonical store is empty, import data from old portable exe folders."""
    canonical_db = os.path.join(canonical_root, 'data', 'mbt_pos.db')
    if _db_has_shop_data(canonical_db):
        return

    exe_dir = os.path.dirname(sys.executable)
    legacy_roots = []

    if exe_dir and exe_dir not in legacy_roots:
        legacy_roots.append(exe_dir)

    roaming = os.path.join(
        os.environ.get('APPDATA', os.path.expanduser('~')), *_BRAND_PARTS)
    if roaming not in legacy_roots and roaming != canonical_root:
        legacy_roots.append(roaming)

    for leg_root in legacy_roots:
        if os.path.normcase(leg_root) == os.path.normcase(canonical_root):
            continue
        leg_db = os.path.join(leg_root, 'data', 'mbt_pos.db')
        if not _db_has_shop_data(leg_db):
            continue
        logger.info('Migrating MBT POS data: %s -> %s', leg_root, canonical_root)
        try:
            for sub in ('data', 'config', 'exports'):
                _copy_tree_files(
                    os.path.join(leg_root, sub),
                    os.path.join(canonical_root, sub),
                )
            return
        except Exception as e:
            logger.warning('Data migration failed from %s: %s', leg_root, e)
