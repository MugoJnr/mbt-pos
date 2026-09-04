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
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        # Read-only URI connections (e.g. backup snapshot source) cannot set WAL.
        pass
    try:
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError:
        pass
    try:
        # Busy shops can hold short write transactions during reports/backups.
        conn.execute("PRAGMA busy_timeout=10000")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass


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


JWT_SECRET_NAME = '.jwt_secret'
CLOUD_IDENTITY_NAME = 'cloud_identity.json'


def _read_text(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ''


def _config_migration_exclusions(src_dir: str, dst_dir: str) -> tuple:
    """Names to skip when importing a legacy ``config`` directory.

    ``cloud_identity.json`` holds Fernet ciphertext derived from that root's
    ``config/.jwt_secret``. Copying the identity into a root that already has
    a different secret produces an identity nothing can ever decrypt, which
    then reads as "signed in with an empty token". Leave it behind so the shop
    simply signs in again.
    """
    src_secret = _read_text(os.path.join(src_dir, JWT_SECRET_NAME))
    dst_secret = _read_text(os.path.join(dst_dir, JWT_SECRET_NAME))
    if not dst_secret or dst_secret == src_secret:
        return ()
    logger.warning(
        'Skipping %s during data migration: destination %s differs, so the '
        'sealed cloud tokens could never be decrypted. Sign in to '
        'portal.mugobyte.com again to resume cloud backup.',
        CLOUD_IDENTITY_NAME, JWT_SECRET_NAME,
    )
    return (CLOUD_IDENTITY_NAME,)


def _copy_tree_files(src_dir: str, dst_dir: str, excluded=()):
    if not os.path.isdir(src_dir):
        return
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        if name in excluded:
            continue
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def _copy_sqlite_snapshot(src_path: str, dst_path: str) -> None:
    """Copy a live WAL database as one consistent SQLite snapshot."""
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    src = sqlite3.connect(src_path, timeout=10)
    dst = sqlite3.connect(dst_path, timeout=10)
    try:
        src.execute("PRAGMA busy_timeout=10000")
        dst.execute("PRAGMA busy_timeout=10000")
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != 'ok':
            raise sqlite3.DatabaseError(f'migrated database integrity check failed: {result}')
    finally:
        dst.close()
        src.close()


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
            src_data = os.path.join(leg_root, 'data')
            dst_data = os.path.join(canonical_root, 'data')
            _copy_sqlite_snapshot(leg_db, canonical_db)
            # backup() incorporates committed WAL content. Never transplant
            # live -wal/-shm sidecars into the new data directory.
            _copy_tree_files(
                src_data,
                dst_data,
                excluded=('mbt_pos.db', 'mbt_pos.db-wal', 'mbt_pos.db-shm'),
            )
            for sub in ('config', 'exports'):
                src_sub = os.path.join(leg_root, sub)
                dst_sub = os.path.join(canonical_root, sub)
                excluded = (
                    _config_migration_exclusions(src_sub, dst_sub)
                    if sub == 'config' else ()
                )
                _copy_tree_files(src_sub, dst_sub, excluded=excluded)
            return
        except Exception as e:
            logger.warning('Data migration failed from %s: %s', leg_root, e)
