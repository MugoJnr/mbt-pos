"""Developer emergency recovery codes for the shop Super Admin password.

The portal and the shop share a per-device secret that stays with the
installation. The portal turns that secret into a short code. The till and
the Live Dashboard recompute it locally, with no network. A remote portal
cannot change the local password by itself.

The code a person types is 12 characters in three groups, for example
K7NP-4RWM-9QHD. No private signing key is shipped in the customer app.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone

logger = logging.getLogger('emergency_recovery')

OPERATION = 'superadmin_password_reset'
TOKEN_TTL_SECONDS = 30 * 60
WINDOW_STEP_SECONDS = 60
FUTURE_SKEW_SECONDS = 120
CLOCK_KEY = 'emergency_recovery_clock_floor'
LOCK_KEY = 'emergency_recovery_locked_until'
WRONG_LIMIT = 5
WRONG_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
# No 0/O and no 1/I/L. 31 symbols, shown as three groups of four.
ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
CODE_LENGTH = 12
EXPLANATION = (
    'A MugoByte developer can issue a one-time code for this shop and this '
    'computer. The code is 12 characters, in three groups. The portal does not '
    'change the password. This shop checks the code here, including when the '
    'computer is offline, then sets a new Super Admin password. The code works '
    'once, for 30 minutes, and only on this device. It does not reveal the old '
    'password, enable a disabled account, or change anyone\'s role.'
)

_SHOP_ROLES = frozenset({
    'admin', 'superadmin', 'manager', 'cashier', 'viewer', 'owner', 'member', 'staff',
})


class RecoveryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def password_policy_error(new_password: str, confirm_password: str) -> str:
    """Same rule as changing your own password: 6 characters, no surrounding space."""
    new_password = '' if new_password is None else str(new_password)
    confirm_password = '' if confirm_password is None else str(confirm_password)
    if confirm_password != new_password:
        return 'New password and confirmation do not match.'
    if len(new_password.strip()) < 6 or new_password != new_password.strip():
        return 'New password must be at least 6 characters.'
    return ''


def developer_recovery_decision(role: str, provider: str) -> dict:
    """Shop Admin and Super Admin are never developers. Backend gate, not a hidden button."""
    role = (role or '').strip().lower()
    provider = (provider or '').strip().lower()
    denied = {
        'allowed': False,
        'status': 403,
        'error': 'Developer emergency recovery is only available to MugoByte developers.',
    }
    if role in _SHOP_ROLES or role != 'platform_admin':
        return denied
    if provider == 'supabase':
        return {'allowed': True, 'status': 200, 'error': ''}
    test_ok = (
        provider == 'test-developer'
        and os.environ.get('MBT_TEST_INSTANCE') == '1'
        and os.environ.get('MBT_RECOVERY_TEST_AUTH') == '1'
    )
    if test_ok:
        return {'allowed': True, 'status': 200, 'error': ''}
    return denied


def _repo_root() -> str:
    return os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _live_shop_root() -> str:
    profile = os.environ.get('USERPROFILE') or ''
    if not profile:
        return ''
    return os.path.normcase(os.path.join(profile, 'AppData', 'Local', 'MugoByte', 'MBT POS'))


def _is_live_programdata(path: str) -> bool:
    live = os.path.normcase(r'C:\ProgramData')
    if not path:
        return True
    try:
        got = os.path.normcase(os.path.abspath(path))
    except Exception:
        return True
    return got == live or got.startswith(live + os.sep)


def recovery_data_root() -> str:
    """Shop data root. A test process must already be pointed away from the live shop."""
    override = (os.environ.get('MBT_DATA_ROOT') or '').strip()
    if os.environ.get('MBT_TEST_INSTANCE') == '1':
        if not override:
            raise PermissionError('Test recovery requires an isolated data root.')
        root = os.path.normcase(os.path.abspath(override))
        live = _live_shop_root()
        if live and (root == live or root.startswith(live + os.sep)):
            raise PermissionError('Test recovery must not use the live shop.')
        if _is_live_programdata(os.environ.get('PROGRAMDATA') or ''):
            raise PermissionError('Test recovery must not use the live licence store.')
        return root
    if override:
        return os.path.abspath(override)
    from mbt_paths import get_project_root
    return get_project_root()


def device_secret_path(root: str | None = None) -> str:
    """Secret file for this installation. Never a path inside the repository."""
    base = root or recovery_data_root()
    path = os.path.abspath(os.path.join(base, 'config', 'recovery_device_secret'))
    absolute = os.path.normcase(path)
    repo = _repo_root()
    if absolute == repo or absolute.startswith(repo + os.sep):
        raise RecoveryError('key', 'The device recovery secret must stay outside the application repository.')
    return path


def _restrict_secret(path: str) -> None:
    if os.name != 'nt':
        try:
            os.chmod(path, 0o600)
        except OSError:
            logger.debug('could not restrict recovery secret', exc_info=True)
        return
    user = os.environ.get('USERNAME') or ''
    if not user:
        return
    try:
        import subprocess
        subprocess.run(
            ['icacls', path, '/inheritance:r', '/grant:r', f'{user}:R'],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        logger.debug('could not restrict recovery secret acl', exc_info=True)


def get_or_create_device_secret(root: str | None = None) -> bytes:
    """32-byte secret stored with this shop installation. Created once."""
    path = device_secret_path(root)
    if os.path.isfile(path):
        with open(path, 'rb') as handle:
            data = handle.read()
        if len(data) != 32:
            raise RecoveryError('key', 'The device recovery secret could not be read.')
        return data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        with open(path, 'rb') as handle:
            data = handle.read()
        if len(data) != 32:
            raise RecoveryError('key', 'The device recovery secret could not be read.')
        return data
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    _restrict_secret(path)
    return data


def normalize_recovery_code(token: str) -> str:
    """Accept the grouped code with or without dashes, spaces, or letter case."""
    compact = ''.join(str(token or '').split()).upper().replace('-', '')
    if len(compact) != CODE_LENGTH or any(ch not in ALPHABET for ch in compact):
        raise RecoveryError('invalid', 'This recovery code is not valid.')
    return compact


def format_recovery_code(compact: str) -> str:
    return f'{compact[0:4]}-{compact[4:8]}-{compact[8:12]}'


def _binding_message(shop_id: str, device_id: str, user_id: int, window_start: int) -> bytes:
    return (
        f'v1|{shop_id}|{device_id}|{OPERATION}|{int(user_id)}|{int(window_start)}'
    ).encode('utf-8')


def _code_compact(secret: bytes, shop_id: str, device_id: str, user_id: int, window_start: int) -> str:
    digest = hmac.new(
        secret, _binding_message(shop_id, device_id, user_id, window_start), hashlib.sha256,
    ).digest()
    value = int.from_bytes(digest[:16], 'big') % (31 ** CODE_LENGTH)
    chars = []
    for _ in range(CODE_LENGTH):
        value, rem = divmod(value, 31)
        chars.append(ALPHABET[rem])
    return ''.join(reversed(chars))


def _token_id(secret: bytes, shop_id: str, device_id: str, user_id: int, window_start: int) -> str:
    """Non-typeable reference. This is not the recovery code."""
    digest = hmac.new(
        secret,
        b'id|' + _binding_message(shop_id, device_id, user_id, window_start),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def _aligned(moment: int) -> int:
    return (int(moment) // WINDOW_STEP_SECONDS) * WINDOW_STEP_SECONDS


def _windows_between(start_moment: int, end_moment: int) -> list[int]:
    earliest = _aligned(start_moment)
    latest = _aligned(end_moment)
    if earliest > latest:
        return []
    return list(range(earliest, latest + 1, WINDOW_STEP_SECONDS))


def issue_token(
    *,
    shop_id: str,
    device_id: str,
    user_id: int,
    username: str,
    secret: bytes | None = None,
    now: int | None = None,
    window_start: int | None = None,
) -> dict:
    shop_id = str(shop_id or '').strip()
    device_id = str(device_id or '').strip()
    username = str(username or '').strip()
    if not shop_id or not device_id or not username or int(user_id) <= 0:
        raise RecoveryError('target', 'A recovery code must name the shop, device, and Super Admin.')
    if secret is None:
        secret = get_or_create_device_secret()
    if not isinstance(secret, (bytes, bytearray)) or len(secret) != 32:
        raise RecoveryError('key', 'The device recovery secret could not be read.')
    issued = int(time.time() if now is None else now)
    start = _aligned(issued if window_start is None else window_start)
    compact = _code_compact(bytes(secret), shop_id, device_id, int(user_id), start)
    formatted = format_recovery_code(compact)
    return {
        'token': formatted,
        'code': formatted,
        'token_id': _token_id(bytes(secret), shop_id, device_id, int(user_id), start),
        'expires_at': start + TOKEN_TTL_SECONDS,
        'window_start': start,
        'shop_id': shop_id,
        'device_id': device_id,
        'username': username,
        'user_id': int(user_id),
    }


def verify_token(
    token: str,
    *,
    shop_id: str,
    device_id: str,
    user_id: int,
    username: str,
    secret: bytes | None = None,
    now: int | None = None,
    clock_floor: int = 0,
) -> dict:
    """Recompute the short code for this shop and device. No network."""
    compact = normalize_recovery_code(token)
    shop_id = str(shop_id or '').strip()
    device_id = str(device_id or '').strip()
    username = str(username or '').strip()
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        user_id = 0
    if not shop_id or not device_id or not username or user_id <= 0:
        raise RecoveryError('invalid', 'This recovery code is not valid.')
    if secret is None:
        secret = get_or_create_device_secret()
    if not isinstance(secret, (bytes, bytearray)) or len(secret) != 32:
        raise RecoveryError('key', 'The device recovery secret could not be read.')
    secret = bytes(secret)
    observed = int(time.time() if now is None else now)
    floor = max(int(clock_floor or 0), 0)
    effective = max(observed, floor)
    valid = _windows_between(effective - (TOKEN_TTL_SECONDS - 1), effective + FUTURE_SKEW_SECONDS)
    expired_windows = _windows_between(
        effective - (TOKEN_TTL_SECONDS * 2 - 1),
        effective - TOKEN_TTL_SECONDS,
    )
    if floor > observed:
        for start in _windows_between(observed - (TOKEN_TTL_SECONDS - 1), observed):
            if start + TOKEN_TTL_SECONDS <= floor and start not in expired_windows:
                expired_windows.append(start)

    def _matches(start: int) -> bool:
        expected = _code_compact(secret, shop_id, device_id, user_id, start)
        return hmac.compare_digest(expected, compact)

    for start in valid:
        if start + TOKEN_TTL_SECONDS <= effective:
            continue
        if _matches(start):
            return {
                'tid': _token_id(secret, shop_id, device_id, user_id, start),
                'uid': user_id,
                'user': username,
                'shop': shop_id,
                'device': device_id,
                'op': OPERATION,
                'iat': start,
                'exp': start + TOKEN_TTL_SECONDS,
            }
    for start in expired_windows:
        if _matches(start):
            raise RecoveryError('expired', 'This recovery code has expired.')
    raise RecoveryError('invalid', 'This recovery code is not valid for this shop and computer.')


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS emergency_recovery_uses (
            token_id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            used_at TEXT NOT NULL,
            used_via TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS emergency_recovery_issues (
            token_id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            issued_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS emergency_recovery_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempted_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            module TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def note_observed_time(conn: sqlite3.Connection, observed: int | None = None) -> int:
    """Raise the offline clock watermark to the latest time this shop has seen.

    A later rollback cannot make an already-expired code look fresh. A Windows
    administrator who can edit this database can still move the watermark.
    """
    ensure_tables(conn)
    seen = int(time.time() if observed is None else observed)
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key=?",
        (CLOCK_KEY,),
    ).fetchone()
    raw = row[0] if row else 0
    try:
        stored = int(raw or 0)
    except (TypeError, ValueError):
        stored = 0
    floor = max(stored, seen, 0)
    if floor != stored:
        conn.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (CLOCK_KEY, str(floor), datetime.now().isoformat(timespec='seconds')),
        )
        conn.commit()
    return floor


def _refuse_live_customer(profile: dict) -> None:
    parts = [
        profile.get('shop_name'), profile.get('org_name'), profile.get('hostname'),
    ]
    for admin in profile.get('superadmins') or []:
        parts.append(admin.get('username'))
        parts.append(admin.get('full_name'))
    blob = ' '.join(str(part or '') for part in parts).lower()
    if 'edmus' in blob:
        raise PermissionError('Refusing to issue a recovery code for this shop.')
    for key in ('data_root', 'db_path'):
        raw = str(profile.get(key) or '')
        if not raw:
            continue
        got = os.path.normcase(os.path.abspath(raw))
        live = _live_shop_root()
        live_db = os.path.normcase(os.path.join(live, 'data', 'mbt_pos.db')) if live else ''
        if live and (got == live or got.startswith(live + os.sep) or got == live_db):
            raise PermissionError('Refusing to issue a recovery code for the live shop database.')


def _licence_summary() -> dict:
    if os.environ.get('MBT_TEST_INSTANCE') == '1' and _is_live_programdata(os.environ.get('PROGRAMDATA') or ''):
        return {'state': 'not_opened', 'plan': ''}
    try:
        from licensing.license_engine import LicenseEngine
        info = LicenseEngine().get_status_dict()
    except Exception:
        logger.debug('licence summary unavailable', exc_info=True)
        return {'state': 'unknown', 'plan': ''}
    return {
        'state': str(info.get('state') or 'unknown'),
        'plan': str(info.get('plan_name') or info.get('plan') or ''),
    }


def local_recovery_profile() -> dict:
    root = recovery_data_root()
    db_path = os.path.join(root, 'data', 'mbt_pos.db')
    if not os.path.isfile(db_path):
        raise LookupError('This server does not have that shop database.')
    from backend.cloud_backup.device_manager import get_or_create_device_id
    device_id = get_or_create_device_id()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        shop_row = conn.execute(
            "SELECT value FROM system_settings WHERE key='shop_instance_id'"
        ).fetchone()
        name_row = conn.execute(
            "SELECT value FROM system_settings WHERE key='shop_name'"
        ).fetchone()
        admins = conn.execute(
            "SELECT id, username, full_name, is_active FROM users "
            "WHERE LOWER(role)='superadmin' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    shop_id = str(shop_row['value'] if shop_row else '') 
    if not shop_id:
        raise LookupError('This shop has no shop identity yet.')
    licence = _licence_summary()
    import platform
    profile = {
        'source': 'local',
        'shop_name': str(name_row['value'] if name_row else '') or 'This shop',
        'shop_id': shop_id,
        'device_id': device_id,
        'hostname': platform.node(),
        'licence_state': licence.get('state') or 'unknown',
        'licence_plan': licence.get('plan') or '',
        'superadmins': [
            {
                'id': int(row['id']),
                'username': row['username'] or '',
                'full_name': row['full_name'] or '',
                'active': int(row['is_active'] or 0) == 1,
            }
            for row in admins
        ],
        'product': 'mbt-pos',
        'data_root': root,
        'db_path': db_path,
    }
    _refuse_live_customer(profile)
    return profile


def cloud_recovery_profile(device_id: str, select=None) -> dict:
    """Read a cloud device by its real device identity. Does not write and does not invent an id."""
    device_id = str(device_id or '').strip()
    if select is None:
        from backend.cloud.platform_service import service_select as select
    from urllib.parse import quote
    rows = select(
        'devices',
        f'device_id=eq.{quote(device_id, safe="")}&select=*&limit=5',
    ) or []
    if not rows:
        raise LookupError('No device is registered with that identity.')
    device = rows[0]
    if str(device.get('device_id') or '') != device_id:
        raise LookupError('No device is registered with that identity.')
    org_id = str(device.get('org_id') or '')
    licences = []
    if org_id:
        licences = select(
            'licenses',
            f'org_id=eq.{quote(org_id, safe="")}&select=*&limit=20',
        ) or []
    def _product(row: dict) -> str:
        return str(row.get('product_id') or row.get('product') or 'mbt-pos').strip().lower()
    pos = [row for row in licences if _product(row) in ('', 'mbt-pos', 'mbt_pos')]
    if licences and not pos:
        raise PermissionError('That device is not an MBT POS shop.')
    licence = pos[0] if pos else {}
    username = str(device.get('superadmin_username') or device.get('owner_username') or '').strip()
    try:
        user_id = int(device.get('superadmin_user_id') or 0)
    except (TypeError, ValueError):
        user_id = 0
    admins = []
    if username and user_id > 0:
        admins.append({
            'id': user_id,
            'username': username,
            'full_name': str(device.get('superadmin_full_name') or username),
            'active': True,
        })
    return {
        'source': 'cloud',
        'shop_name': str(device.get('business_name') or device.get('computer_name') or 'Shop'),
        'org_name': str(device.get('org_name') or ''),
        'shop_id': str(device.get('shop_instance_id') or ''),
        'org_id': org_id,
        'device_id': device_id,
        'hostname': str(device.get('hostname') or device.get('computer_name') or ''),
        'licence_state': str(licence.get('status') or 'unknown'),
        'licence_plan': str(licence.get('plan') or ''),
        'superadmins': admins,
        'product': 'mbt-pos',
    }


def lookup_recovery_target(device_id: str, *, cloud_select=None) -> dict:
    device_id = str(device_id or '').strip()
    if not device_id:
        raise LookupError('Enter the device identity.')
    local = None
    try:
        local = local_recovery_profile()
    except PermissionError:
        raise
    except LookupError:
        local = None
    except Exception:
        logger.debug('local recovery profile unavailable', exc_info=True)
        local = None
    if local and str(local.get('device_id') or '') == device_id:
        return local
    if os.environ.get('MBT_TEST_INSTANCE') == '1' and cloud_select is None:
        raise LookupError('No shop on this server matches that device identity.')
    profile = cloud_recovery_profile(device_id, select=cloud_select)
    _refuse_live_customer(profile)
    if not profile.get('shop_id') or not profile.get('superadmins'):
        raise LookupError(
            'The device is registered, but this portal cannot see the shop id and Super Admin '
            'to bind a code. The portal still cannot change the shop password by itself.'
        )
    return profile


def public_recovery_profile(profile: dict, *, developer: bool = False) -> dict:
    admins = []
    for row in profile.get('superadmins') or []:
        item = {
            'username': row.get('username') or '',
            'full_name': row.get('full_name') or '',
            'active': bool(row.get('active', True)),
        }
        if developer:
            item['id'] = row.get('id')
        admins.append(item)
    return {
        'shop_name': profile.get('shop_name') or '',
        'shop_id': profile.get('shop_id') or '',
        'device_id': profile.get('device_id') or '',
        'hostname': profile.get('hostname') or '',
        'licence_state': profile.get('licence_state') or 'unknown',
        'licence_plan': profile.get('licence_plan') or '',
        'superadmins': admins,
        'product': 'mbt-pos',
        'portal_changes_password': False,
        'explanation': EXPLANATION,
    }


def _open_shop_db() -> sqlite3.Connection:
    root = recovery_data_root()
    db_path = os.path.join(root, 'data', 'mbt_pos.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _shop_binding(conn: sqlite3.Connection) -> tuple[str, str]:
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key='shop_instance_id'"
    ).fetchone()
    shop_id = str(row[0] if row else '')
    from backend.cloud_backup.device_manager import get_or_create_device_id
    return shop_id, get_or_create_device_id()


def _locked_until(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key=?",
        (LOCK_KEY,),
    ).fetchone()
    try:
        return int(row[0] if row else 0)
    except (TypeError, ValueError):
        return 0


def note_wrong_attempt(conn: sqlite3.Connection, now: int | None = None) -> None:
    """Persist a failed guess. Five wrong codes lock recovery for 15 minutes."""
    ensure_tables(conn)
    moment = int(time.time() if now is None else now)
    conn.execute(
        "INSERT INTO emergency_recovery_attempts (attempted_at) VALUES (?)",
        (moment,),
    )
    cutoff = moment - WRONG_WINDOW_SECONDS
    conn.execute(
        "DELETE FROM emergency_recovery_attempts WHERE attempted_at < ?",
        (cutoff,),
    )
    count = conn.execute(
        "SELECT COUNT(*) FROM emergency_recovery_attempts WHERE attempted_at >= ?",
        (cutoff,),
    ).fetchone()[0]
    if int(count) >= WRONG_LIMIT:
        conn.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (LOCK_KEY, str(moment + LOCKOUT_SECONDS), datetime.now().isoformat(timespec='seconds')),
        )
    conn.commit()


def _rate_limit_error(conn: sqlite3.Connection, now: int) -> str:
    if _locked_until(conn) > int(now):
        return 'Too many incorrect recovery codes. Wait about 15 minutes and try again.'
    return ''


def redeem_superadmin(
    conn: sqlite3.Connection,
    token: str,
    new_password: str,
    confirm_password: str,
    *,
    via: str,
    now: int | None = None,
) -> dict:
    """Verify locally, set the Super Admin password, and remember the code as used."""
    via = 'web' if str(via or '') == 'web' else 'till'
    policy = password_policy_error(new_password, confirm_password)
    if policy:
        return {'success': False, 'error': policy, 'code': 'policy'}
    ensure_tables(conn)
    moment = int(time.time() if now is None else now)
    floor = note_observed_time(conn, moment)
    limited = _rate_limit_error(conn, moment)
    if limited:
        return {'success': False, 'error': limited, 'code': 'rate_limited'}
    shop_id, device_id = _shop_binding(conn)
    secret = get_or_create_device_secret()
    admins = conn.execute(
        "SELECT id, username, role, is_active, password_hash FROM users "
        "WHERE LOWER(role)='superadmin' ORDER BY id"
    ).fetchall()
    claims = None
    expired = False
    for admin in admins:
        try:
            claims = verify_token(
                token,
                shop_id=shop_id,
                device_id=device_id,
                user_id=int(admin['id']),
                username=str(admin['username'] or ''),
                secret=secret,
                now=moment,
                clock_floor=floor,
            )
            break
        except RecoveryError as exc:
            if exc.code == 'expired':
                expired = True
            claims = None
    if claims is None:
        note_wrong_attempt(conn, moment)
        if expired:
            return {
                'success': False,
                'error': 'This recovery code has expired.',
                'code': 'expired',
            }
        return {
            'success': False,
            'error': 'This recovery code is not valid for this shop and computer.',
            'code': 'invalid',
        }
    token_id = str(claims['tid'])
    user = conn.execute(
        "SELECT id, username, role, is_active, password_hash FROM users WHERE id=?",
        (int(claims['uid']),),
    ).fetchone()
    if (
        not user
        or str(user['username'] or '') != str(claims['user'])
        or str(user['role'] or '').lower() != 'superadmin'
    ):
        return {
            'success': False,
            'error': 'This recovery code does not match the Super Admin on this shop.',
            'code': 'wrong_account',
        }
    if int(user['is_active'] or 0) != 1:
        return {
            'success': False,
            'error': 'That Super Admin account is disabled. Recovery does not enable it.',
            'code': 'disabled',
        }
    used = conn.execute(
        "SELECT token_id FROM emergency_recovery_uses WHERE token_id=?",
        (token_id,),
    ).fetchone()
    if used:
        return {
            'success': False,
            'error': 'This recovery code has already been used.',
            'code': 'replay',
        }
    from desktop.utils.api_client import _hash_pw
    from desktop.utils.account_sessions import invalidate_user_sessions
    try:
        conn.execute(
            "INSERT INTO emergency_recovery_uses (token_id, shop_id, device_id, user_id, used_at, used_via) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                token_id,
                shop_id,
                device_id,
                int(user['id']),
                datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                via,
            ),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        return {
            'success': False,
            'error': 'This recovery code has already been used.',
            'code': 'replay',
        }
    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=? AND role='superadmin' AND is_active=1",
        (_hash_pw(new_password), int(user['id'])),
    )
    invalidate_user_sessions(conn, int(user['id']))
    from desktop.utils.api_client import _audit
    _audit(
        int(user['id']),
        user['username'],
        'DEVELOPER_RECOVERY_RESET',
        'security',
        f"token_id={token_id} via={via} op={OPERATION}",
        conn=conn,
        source=via,
    )
    conn.commit()
    logger.info('Developer recovery reset token_id=%s via=%s', token_id, via)
    return {'success': True, 'username': user['username'], 'token_id': token_id}


def _profile_db_path(profile: dict) -> str:
    raw = str(profile.get('db_path') or '')
    if raw:
        return raw
    root = str(profile.get('data_root') or '')
    if root:
        return os.path.join(root, 'data', 'mbt_pos.db')
    return ''


def _secret_for_profile(profile: dict, secret: bytes | None) -> bytes:
    if isinstance(secret, (bytes, bytearray)) and len(secret) == 32:
        return bytes(secret)
    raw = profile.get('recovery_secret')
    if isinstance(raw, (bytes, bytearray)) and len(raw) == 32:
        return bytes(raw)
    if profile.get('source') == 'local' or profile.get('data_root'):
        return get_or_create_device_secret(profile.get('data_root') or None)
    raise RecoveryError(
        'secret',
        'This portal does not hold that computer\'s recovery secret, so it cannot issue a code. '
        'It still cannot change the shop password.',
    )


def _window_used(db_path: str, token_id: str) -> bool:
    if not db_path or not os.path.isfile(db_path):
        return False
    conn = sqlite3.connect(db_path)
    try:
        ensure_tables(conn)
        row = conn.execute(
            "SELECT token_id FROM emergency_recovery_uses WHERE token_id=?",
            (token_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _remember_issue(db_path: str, issued: dict) -> None:
    """Portal history stores the reference id, never the typeable code."""
    if not db_path or not os.path.isfile(db_path):
        return
    conn = sqlite3.connect(db_path)
    try:
        ensure_tables(conn)
        conn.execute(
            "INSERT OR REPLACE INTO emergency_recovery_issues "
            "(token_id, shop_id, device_id, user_id, expires_at, issued_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                issued['token_id'],
                issued['shop_id'],
                issued['device_id'],
                int(issued['user_id']),
                int(issued['expires_at']),
                datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def issue_for_target(
    profile: dict,
    user_id: int,
    *,
    secret: bytes | None = None,
    now: int | None = None,
) -> dict:
    _refuse_live_customer(profile)
    if str(profile.get('product') or '') != 'mbt-pos':
        raise RecoveryError('target', 'Recovery codes are issued only for MBT POS.')
    chosen = None
    for row in profile.get('superadmins') or []:
        if int(row.get('id') or 0) == int(user_id):
            chosen = row
            break
    if not chosen:
        raise RecoveryError('target', 'Choose the Super Admin shown for this shop.')
    if not chosen.get('active', True):
        raise RecoveryError('disabled', 'That Super Admin account is disabled. Recovery does not enable it.')
    if not profile.get('shop_id') or not profile.get('device_id'):
        raise RecoveryError('target', 'Search the shop and device before generating a code.')
    device_secret = _secret_for_profile(profile, secret)
    db_path = _profile_db_path(profile)
    issued_now = int(time.time() if now is None else now)
    start = _aligned(issued_now)
    issued = None
    for _ in range(3):
        candidate = issue_token(
            shop_id=profile['shop_id'],
            device_id=profile['device_id'],
            user_id=int(chosen['id']),
            username=str(chosen['username']),
            secret=device_secret,
            now=issued_now,
            window_start=start,
        )
        if not _window_used(db_path, candidate['token_id']):
            issued = candidate
            break
        start += WINDOW_STEP_SECONDS
    if issued is None:
        raise RecoveryError(
            'replay',
            'A recovery code for this shop and computer was already used. Wait a minute and generate another.',
        )
    _remember_issue(db_path, issued)
    issued['shop_name'] = profile.get('shop_name') or ''
    issued['licence_state'] = profile.get('licence_state') or ''
    issued['portal_changes_password'] = False
    return issued
