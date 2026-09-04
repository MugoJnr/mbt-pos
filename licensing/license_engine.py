"""
MBT POS — License Engine (Core)
MugoByte Technologies | mugobyte.com

Offline-first license validation with:
  • Hardware device binding (CPU/board/disk serials)
  • Time-rollback detection (local + remote anchor)
  • Anti-copy: token is cryptographically bound to THIS device's fingerprint
  • Tamper → immediate lock on first confirmed attack
  • Remote activation / revoke / extend via Portal command center
"""
import os, sys, json, time, uuid, hashlib, hmac, base64, shutil
import sqlite3, platform, threading, logging, requests
import glob
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple
logger = logging.getLogger('license_engine')

# Local license crypto secret — lazy-loaded; co-located with lc.db (see below).
_MASTER_SECRET_CACHE: bytes | None = None
_LEGACY_SECRET_CANDIDATES: list[bytes] | None = None


def _legacy_roaming_lic_dir() -> str:
    """Old license folder under %APPDATA% (Roaming) — may not persist on shop PCs."""
    if platform.system() == 'Windows':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        return os.path.join(base, 'MugoByte', '.mbt_lic')
    if platform.system() == 'Darwin':
        return os.path.expanduser('~/Library/Application Support/MugoByte/.mbt_lic')
    return os.path.expanduser('~/.config/mugobyte/.mbt_lic')


def _legacy_local_lic_dir() -> str:
    """Per-user store used by v3.0.71 and earlier Windows builds."""
    base = (
        os.environ.get('LOCALAPPDATA')
        or os.environ.get('APPDATA')
        or os.path.expanduser('~')
    )
    return os.path.join(base, 'MugoByte', '.mbt_lic')


def _program_data_lic_dir() -> str:
    """Machine-wide Windows store shared by installer/admin/cashier contexts."""
    base = (os.environ.get('PROGRAMDATA') or '').strip()
    if not base:
        return ''
    return os.path.join(base, 'MugoByte', 'MBT POS', 'license')


def _store_has_license_token(db_path: str) -> bool:
    """True when lc.db contains a non-empty license_token row."""
    if not os.path.isfile(db_path):
        return False
    try:
        db = sqlite3.connect(db_path)
        row = db.execute(
            "SELECT value FROM license_data WHERE key='license_token' LIMIT 1"
        ).fetchone()
        db.close()
        return bool(row and str(row[0] or '').strip())
    except Exception:
        return False


def _migrate_legacy_lic_store(canonical_dir: str, legacy_dir: str) -> None:
    """Copy a populated older store when the canonical store has no license.

    Do not use file size — an empty schema lc.db is ~20KB and would block
    migration forever, leaving shops stuck on the activation screen after restart.
    """
    try:
        if os.path.normcase(os.path.abspath(canonical_dir)) == os.path.normcase(
            os.path.abspath(legacy_dir)
        ):
            return
        canon_db = os.path.join(canonical_dir, 'lc.db')
        legacy_db = os.path.join(legacy_dir, 'lc.db')
        if _store_has_license_token(canon_db):
            return
        if not os.path.isfile(legacy_db):
            return
        if not _store_has_license_token(legacy_db):
            return
        os.makedirs(canonical_dir, exist_ok=True)
        for name in os.listdir(legacy_dir):
            src = os.path.join(legacy_dir, name)
            dst = os.path.join(canonical_dir, name)
            if not os.path.isfile(src):
                continue
            if name == 'lc.db':
                shutil.copy2(src, dst)
            elif not os.path.exists(dst):
                shutil.copy2(src, dst)
        logger.info('Migrated license store %s → %s', legacy_dir, canonical_dir)
    except Exception as e:
        logger.warning('License store migration skipped: %s', e)


def _all_windows_user_license_dirs() -> list[str]:
    """License stores that may belong to the installing admin or a cashier."""
    if platform.system() != 'Windows':
        return []
    out: list[str] = []

    def _add(path: str) -> None:
        if path and path not in out:
            out.append(path)

    _add(_legacy_local_lic_dir())
    _add(_legacy_roaming_lic_dir())
    system_drive = (os.environ.get('SystemDrive') or 'C:').rstrip('\\/')
    users_root = os.path.join(system_drive + os.sep, 'Users')
    for pattern in (
        os.path.join(users_root, '*', 'AppData', 'Local', 'MugoByte', '.mbt_lic'),
        os.path.join(users_root, '*', 'AppData', 'Roaming', 'MugoByte', '.mbt_lic'),
    ):
        for path in glob.glob(pattern):
            _add(path)
    return out


def repair_machine_license_store(candidate_dirs: list[str] | None = None) -> dict:
    """Elevated installer repair for licenses activated under another user.

    v3.0.71 and older used ``%LOCALAPPDATA%``.  An installer launched with
    alternate administrator credentials could therefore save activation under
    the administrator profile, while the cashier's next launch saw an empty
    store.  Move the newest populated store into ProgramData.
    """
    target = _program_data_lic_dir()
    if platform.system() != 'Windows' or not target:
        return {'ok': True, 'changed': False, 'reason': 'not_windows'}
    target_db = os.path.join(target, 'lc.db')
    if _store_has_license_token(target_db):
        return {'ok': True, 'changed': False, 'reason': 'already_machine_wide'}

    candidates = []
    for path in candidate_dirs if candidate_dirs is not None else _all_windows_user_license_dirs():
        try:
            db_path = os.path.join(path, 'lc.db')
            if _store_has_license_token(db_path):
                candidates.append((os.path.getmtime(db_path), path))
        except Exception:
            continue
    candidates.sort(reverse=True)
    if not candidates:
        return {'ok': False, 'changed': False, 'reason': 'no_populated_store'}

    try:
        os.makedirs(target, exist_ok=True)
        source = candidates[0][1]
        for name in os.listdir(source):
            src = os.path.join(source, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(target, name))
        if not _store_has_license_token(target_db):
            return {'ok': False, 'changed': False, 'reason': 'copy_failed'}
        logger.info('Recovered machine-wide license store from %s', source)
        return {
            'ok': True,
            'changed': True,
            'reason': 'migrated',
            'source': source,
            'target': target,
        }
    except Exception as e:
        logger.warning('Machine-wide license repair failed: %s', e)
        return {'ok': False, 'changed': False, 'reason': str(e)}


def _store_is_writable(path: str) -> bool:
    """True when the store folder exists and this account can write in it.

    ``os.makedirs(exist_ok=True)`` succeeds on an existing read-only folder, so
    an explicit write probe is required.  Without it a locked-down ProgramData
    ACL would be selected and every LicenseStore write would raise.
    """
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return False
    probe = os.path.join(
        path,
        f'.write_probe_{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex}',
    )
    try:
        with open(probe, 'w', encoding='utf-8') as handle:
            handle.write('ok')
        return True
    except OSError:
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def collect_activation_diagnostics() -> dict:
    """Read-only snapshot of every license store and its audit trail.

    When a shop is stuck on the activation screen the audit log names the exact
    cause — REVOKED, TAMPER_DETECT, DEVICE_MISMATCH, CLOUD_VALIDATE_FAIL,
    TIME_ROLLBACK — which is otherwise invisible from the cloud side.
    """
    machine = _program_data_lic_dir()
    report: dict = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'platform': platform.system(),
        'machine_store': machine,
        'machine_store_exists': bool(machine) and os.path.isdir(machine),
        'machine_store_writable': bool(machine) and os.path.isdir(machine)
                                  and os.access(machine, os.W_OK),
        'stores': [],
    }
    seen: set[str] = set()
    candidates = ([machine] if machine else []) + _all_windows_user_license_dirs()
    for path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        db_path = os.path.join(path, 'lc.db')
        entry: dict = {
            'path': path,
            'lc_db_exists': os.path.isfile(db_path),
            'has_license_token': _store_has_license_token(db_path),
            'has_crypto_secret': os.path.isfile(
                os.path.join(path, 'crypto.secret')),
            'has_device_id': os.path.isfile(os.path.join(path, 'device.id')),
            'events': [],
        }
        if entry['lc_db_exists']:
            try:
                entry['modified'] = datetime.fromtimestamp(
                    os.path.getmtime(db_path), timezone.utc).isoformat()
            except OSError:
                entry['modified'] = ''
            try:
                db = sqlite3.connect(db_path)
                rows = db.execute(
                    'SELECT ts, event, detail FROM license_log '
                    'ORDER BY id DESC LIMIT 80'
                ).fetchall()
                db.close()
                for ts, event, detail in rows:
                    try:
                        stamp = datetime.fromtimestamp(
                            int(ts or 0), timezone.utc).isoformat()
                    except Exception:
                        stamp = str(ts)
                    entry['events'].append({
                        'at': stamp,
                        'event': event,
                        'detail': detail or '',
                    })
            except Exception as e:
                entry['events_error'] = str(e)
        report['stores'].append(entry)
    return report


def _lic_store_dir() -> str:
    if platform.system() == 'Windows':
        machine = _program_data_lic_dir()
        per_user = _legacy_local_lic_dir()
        if machine and _store_is_writable(machine):
            for older in (per_user, _legacy_roaming_lic_dir()):
                _migrate_legacy_lic_store(machine, older)
            return machine
        if machine:
            # Read-only/unavailable ProgramData must never re-prompt activation:
            # seed the per-user store from the machine store before falling back.
            logger.warning(
                'Machine license store not writable — falling back to per-user store'
            )
            _migrate_legacy_lic_store(per_user, machine)
        _migrate_legacy_lic_store(per_user, _legacy_roaming_lic_dir())
        d = per_user
    elif platform.system() == 'Darwin':
        d = os.path.expanduser('~/Library/Application Support/MugoByte/.mbt_lic')
    else:
        d = os.path.expanduser('~/.config/mugobyte/.mbt_lic')
    os.makedirs(d, exist_ok=True)
    return d


def _license_crypto_secret_path() -> str:
    return os.path.join(os.path.dirname(_hidden_db_path()), 'crypto.secret')


def _legacy_config_secret_path() -> str:
    try:
        from mbt_paths import get_project_root
        return os.path.join(get_project_root(), 'config', '.activation_hmac_secret')
    except Exception:
        return ''


def _license_db_has_token() -> bool:
    try:
        db = sqlite3.connect(_hidden_db_path())
        row = db.execute(
            "SELECT 1 FROM license_data WHERE key='license_token' LIMIT 1"
        ).fetchone()
        db.close()
        return bool(row)
    except Exception:
        return False


def _read_secret_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            val = f.read().strip()
        return val if len(val) >= 32 else ''
    except Exception:
        return ''


def _write_secret_file(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(value)
    os.replace(tmp, path)


def _machine_guid_recovery_secret() -> str:
    """Deterministic per-PC secret when lc.db exists but crypto.secret was lost."""
    mg = _win_machine_guid()
    if not mg:
        return ''
    return hashlib.sha256(f'mbt-pos-local-v2:{mg}'.encode()).hexdigest()


def _resolve_local_license_secret() -> str:
    """Stable secret for encrypting the local license store.

    Stored next to lc.db so activation survives reinstalls and config wipes.
    Falls back to legacy config/.activation_hmac_secret, then MachineGuid
    recovery when a license row already exists on this PC.
    """
    env = (os.environ.get('MBT_ACTIVATION_HMAC_SECRET') or '').strip()
    if len(env) >= 32:
        return env

    canonical = _license_crypto_secret_path()
    val = _read_secret_file(canonical)
    if val:
        return val

    legacy_path = _legacy_config_secret_path()
    if legacy_path:
        val = _read_secret_file(legacy_path)
        if val:
            try:
                _write_secret_file(canonical, val)
                logger.info('Migrated license crypto secret into %s', _lic_store_dir())
            except Exception as e:
                logger.warning('Could not migrate license secret: %s', e)
            return val

    recovered = _machine_guid_recovery_secret()
    if recovered:
        # Windows: deterministic per-PC secret survives crypto.secret loss/reinstall.
        if _license_db_has_token():
            return recovered
        try:
            _write_secret_file(canonical, recovered)
        except Exception as e:
            logger.warning('Could not persist MachineGuid license secret: %s', e)
        return recovered

    import secrets
    val = secrets.token_urlsafe(48)
    try:
        _write_secret_file(canonical, val)
    except Exception as e:
        logger.warning('Could not persist license crypto secret: %s', e)
    return val


def _legacy_secret_candidates() -> list[bytes]:
    """Secrets that may have encrypted an older lc.db on this PC."""
    global _LEGACY_SECRET_CANDIDATES
    if _LEGACY_SECRET_CANDIDATES is not None:
        return _LEGACY_SECRET_CANDIDATES
    seen: list[bytes] = []

    def _add(raw: str):
        if raw and len(raw) >= 32:
            b = raw.encode('utf-8')
            if b not in seen:
                seen.append(b)

    _add(_resolve_local_license_secret())
    legacy_path = _legacy_config_secret_path()
    if legacy_path:
        _add(_read_secret_file(legacy_path))
    recovered = _machine_guid_recovery_secret()
    if recovered:
        _add(recovered)
    _LEGACY_SECRET_CANDIDATES = seen
    return seen


def _master_secret_bytes() -> bytes:
    global _MASTER_SECRET_CACHE
    if _MASTER_SECRET_CACHE is None:
        _MASTER_SECRET_CACHE = _resolve_local_license_secret().encode('utf-8')
    return _MASTER_SECRET_CACHE


def _with_secret(secret: bytes | None) -> bytes:
    return secret if secret is not None else _master_secret_bytes()

# ── Plans ─────────────────────────────────────────────────────────────────────
PLANS = {
    'trial':    {'name': 'Trial',        'days': 30,    'max_products': 50,  'max_users': 2},
    'basic':    {'name': 'Basic',        'days': 365,   'max_products': 500, 'max_users': 5},
    'pro':      {'name': 'Professional', 'days': 365,   'max_products': -1,  'max_users': 20},
    'lifetime': {'name': 'Lifetime',     'days': 36500, 'max_products': -1,  'max_users': -1},
}

STATE_ACTIVE      = 'active'
STATE_EXPIRING    = 'expiring'
STATE_WARNING     = 'warning'
STATE_CRITICAL    = 'critical'
STATE_EXPIRED     = 'expired'
STATE_INACTIVE    = 'inactive'
STATE_TAMPERED    = 'tampered'
STATE_UNACTIVATED = 'unactivated'


# ══════════════════════════════════════════════════════════════════════════════
# DEVICE FINGERPRINTING
# Combines CPU ID, motherboard serial, disk serial, machine-id.
# A different physical machine = different fingerprint = key rejected.
# ══════════════════════════════════════════════════════════════════════════════

def _win_machine_guid() -> str:
    """Stable Windows machine id (survives wmic failures on Win11)."""
    if platform.system() != 'Windows':
        return ''
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography')
        val, _ = winreg.QueryValueEx(key, 'MachineGuid')
        winreg.CloseKey(key)
        return str(val).strip()
    except Exception:
        return ''


def _collect_hardware_probe_parts() -> list:
    """Hardware probes used by legacy fingerprinting (wmic can be flaky on some PCs)."""
    parts = []
    parts.append(platform.node())
    parts.append(platform.processor() or platform.machine())
    parts.append(platform.system() + platform.version()[:20])

    if platform.system() == 'Windows':
        import subprocess
        for cmd, prefix in [
            (['wmic', 'cpu', 'get', 'ProcessorId', '/value'], 'ProcessorId='),
            (['wmic', 'baseboard', 'get', 'SerialNumber', '/value'], 'SerialNumber='),
            (['wmic', 'diskdrive', 'get', 'SerialNumber', '/value'], 'SerialNumber='),
        ]:
            try:
                out = subprocess.check_output(cmd, shell=False,
                                               stderr=subprocess.DEVNULL,
                                               timeout=5,
                                               creationflags=(
                                                   0x08000000
                                                   if sys.platform == 'win32'
                                                   else 0
                                               )).decode(errors='ignore')
                for line in out.splitlines():
                    if prefix in line:
                        val = line.split('=', 1)[-1].strip()
                        if val and val.lower() not in ('', 'none', 'to be filled by o.e.m.'):
                            parts.append(val)
                            break
            except Exception:
                pass

    if platform.system() == 'Linux':
        for p in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                with open(p) as f:
                    parts.append(f.read().strip())
                    break
            except Exception:
                pass

    if platform.system() == 'Darwin':
        try:
            import subprocess
            out = subprocess.check_output(
                ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                stderr=subprocess.DEVNULL, timeout=5).decode(errors='ignore')
            for line in out.splitlines():
                if 'IOPlatformSerialNumber' in line:
                    parts.append(line.split('"')[-2])
                    break
        except Exception:
            pass

    try:
        parts.append(hex(uuid.getnode()))
    except Exception:
        pass

    return parts


def _get_legacy_wmic_fingerprint() -> str:
    """Legacy ID from wmic/hardware probes — kept only for decrypting old licenses."""
    raw = '|'.join(str(p) for p in _collect_hardware_probe_parts() if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _get_device_fingerprint() -> str:
    mg = _win_machine_guid()
    if mg:
        # MachineGuid is stable on a Windows installation.
        # Use it as primary source so Hardware ID does not drift when
        # wmic/CPU/disk probes fail intermittently.
        return hashlib.sha256(f"mg:{mg}".encode()).hexdigest()[:40]

    raw = '|'.join(str(p) for p in _collect_hardware_probe_parts() if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _device_id_cache_path() -> str:
    return os.path.join(os.path.dirname(_hidden_db_path()), 'device.id')


def _read_cached_device_id() -> Optional[str]:
    try:
        with open(_device_id_cache_path(), 'r', encoding='utf-8') as f:
            did = f.read().strip()
            if len(did) == 40:
                return did
            # Older builds bound the local token to the cloud id (MBT-PC-XXXX).
            if did.startswith('MBT-PC-') and len(did) >= 10:
                return did
            return None
    except Exception:
        return None


def _write_cached_device_id(device_id: str):
    try:
        os.makedirs(os.path.dirname(_device_id_cache_path()), exist_ok=True)
        with open(_device_id_cache_path(), 'w', encoding='utf-8') as f:
            f.write(device_id)
    except Exception as e:
        logger.warning(f'Could not cache device id: {e}')


def _read_raw_license_token() -> Optional[str]:
    """Read encrypted license_token directly (no device key needed)."""
    try:
        db = sqlite3.connect(_hidden_db_path())
        row = db.execute(
            "SELECT value FROM license_data WHERE key='license_token'"
        ).fetchone()
        db.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _hmac_hex(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _decrypt_payload_with_secrets(
    token: str,
    device_id: str,
    secrets: list[bytes] | None = None,
) -> Optional[dict]:
    """Decrypt a store blob. HMAC may be the PBKDF2 key (legacy) or the secret."""
    try:
        b64, sig = token.rsplit('.', 1)
        enc = base64.b64decode(b64)
    except Exception:
        return None
    matched_secret: bytes | None = None
    payload = None
    for secret in secrets or _legacy_secret_candidates():
        try:
            key = _derive_key_cached(device_id, secret)
            if hmac.compare_digest(_hmac_hex(key, enc), sig) or hmac.compare_digest(
                _hmac_hex(secret, enc), sig
            ):
                payload = json.loads(_xor_encrypt(enc, key))
                matched_secret = secret
                break
        except Exception:
            continue
    if payload is None:
        return None
    if matched_secret is not None:
        try:
            canonical = _license_crypto_secret_path()
            if _read_secret_file(canonical) != matched_secret.decode('utf-8', errors='ignore'):
                _write_secret_file(canonical, matched_secret.decode('utf-8'))
                global _MASTER_SECRET_CACHE
                _MASTER_SECRET_CACHE = matched_secret
        except Exception:
            pass
    return payload


def _unwrap_license_blob(raw: str, device_id: str) -> Optional[str]:
    """Outer store wrapper → inner license token string."""
    outer = _decrypt_payload_with_secrets(raw, device_id)
    if not outer:
        return None
    if isinstance(outer.get('v'), str) and outer['v']:
        return outer['v']
    if outer.get('device_id') and outer.get('expires_at'):
        return raw
    return None


def _resolve_inner_license_token() -> tuple[Optional[str], Optional[str]]:
    """Return (inner_token, device_id) when lc.db holds a license."""
    raw = _read_raw_license_token()
    if not raw:
        return None, None
    # Normal installs are bound to one of these inexpensive identifiers. Do
    # not launch legacy WMIC probes unless none can decrypt the stored token.
    cheap = []
    for did in (
        _read_cached_device_id(),
        _get_device_fingerprint(),
        *_cloud_identity_device_ids(),
    ):
        if did and did not in cheap:
            cheap.append(did)
    for did in cheap:
        inner = _unwrap_license_blob(raw, did)
        if not inner:
            continue
        lic = _decrypt_payload_with_secrets(inner, did)
        if lic and lic.get('expires_at'):
            return inner, did
    legacy = _get_legacy_wmic_fingerprint()
    if legacy and legacy not in cheap:
        inner = _unwrap_license_blob(raw, legacy)
        if inner:
            lic = _decrypt_payload_with_secrets(inner, legacy)
            if lic and lic.get('expires_at'):
                return inner, legacy
    return None, None


def _cloud_identity_device_ids() -> list:
    """Cloud device id + fingerprint from identity (Edmus-style MBT-PC-XXXX)."""
    out = []
    try:
        from backend.cloud_backup.paths import load_identity
        ident = load_identity() or {}
    except Exception:
        return out
    for key in ('device_id', 'hardware_fingerprint'):
        val = str(ident.get(key) or '').strip()
        if val:
            out.append(val)
    return out


def _fingerprint_device_id_candidates() -> list:
    """Ids to try when matching an existing license (incl. migration)."""
    seen = []
    extra = []
    try:
        extra = _cloud_identity_device_ids()
    except Exception:
        extra = []
    for did in (
        _read_cached_device_id(),
        _get_device_fingerprint(),
        _get_legacy_wmic_fingerprint(),
        *extra,
    ):
        if did and did not in seen:
            seen.append(did)
    return seen


def resolve_device_id() -> str:
    """
    Pick the device id for this PC.
    Licensed PCs: use whichever id decrypts the stored token (legacy wmic OK).
    Unlicensed PCs: prefer stable MachineGuid fingerprint over stale cache.
    """
    _inner, did = _resolve_inner_license_token()
    if _inner and did:
        _write_cached_device_id(did)
        return did
    if _read_raw_license_token():
        logger.warning('License token present but could not decrypt with any device ID')

    canonical = _get_device_fingerprint()
    if _win_machine_guid():
        cached = _read_cached_device_id()
        if cached != canonical:
            if cached:
                logger.info('Device ID cache migrated to MachineGuid fingerprint')
            _write_cached_device_id(canonical)
        return canonical

    cached = _read_cached_device_id()
    if cached:
        return cached
    _write_cached_device_id(canonical)
    return canonical


def get_device_id() -> str:
    return resolve_device_id()


def __getattr__(name: str):
    # license_keygen / tests import _MASTER_SECRET at module level
    if name == '_MASTER_SECRET':
        return _master_secret_bytes()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


# ══════════════════════════════════════════════════════════════════════════════
# CRYPTOGRAPHIC HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _sign(data: bytes, secret: bytes | None = None) -> str:
    return hmac.new(_with_secret(secret), data, hashlib.sha256).hexdigest()

def _verify_sig(data: bytes, sig: str, secret: bytes | None = None) -> bool:
    if not sig:
        return False
    return hmac.compare_digest(_sign(data, secret), sig)

@lru_cache(maxsize=32)
def _derive_key_cached(device_id: str, secret: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        'sha256', device_id.encode(), secret,
        iterations=100_000, dklen=32)


def _derive_key(device_id: str, secret: bytes | None = None) -> bytes:
    """Derive once per process for each immutable device/secret pair.

    PBKDF2 deliberately costs CPU. Repeating it for every encrypted setting
    read made periodic license checks consume visible CPU while the POS was
    otherwise idle. The resolved secret bytes are part of the cache key, so a
    migrated or rotated local secret cannot reuse a stale derived key.
    """
    return _derive_key_cached(device_id, _with_secret(secret))

def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data)); kl = len(key)
    for i, b in enumerate(data): out[i] = b ^ key[i % kl]
    return bytes(out)

def encrypt_payload(payload: dict, device_id: str) -> str:
    key = _derive_key(device_id)
    raw = json.dumps(payload, separators=(',', ':')).encode()
    enc = _xor_encrypt(raw, key)
    # HMAC uses the derived key so existing shop tokens stay readable.
    return base64.b64encode(enc).decode() + '.' + _sign(enc, key)

def decrypt_payload(token: str, device_id: str) -> Optional[dict]:
    return _decrypt_payload_with_secrets(token, device_id)


# ══════════════════════════════════════════════════════════════════════════════
# LICENSE KEY GENERATION (developer side)
# ══════════════════════════════════════════════════════════════════════════════

def generate_license_key(device_id: str, plan: str = 'basic',
                         duration_days: int = 365,
                         issued_by: str = 'MugoByte Technologies') -> str:
    now = int(time.time())
    days = max(1, int(duration_days))
    payload = {
        'device_id':      device_id,
        'plan':           plan,
        'issued_at':      now,
        'expires_at':     now + days * 86400,  # hint / legacy; POS uses duration_days
        'duration_days':  days,                # authoritative allocation
        'issued_by':      issued_by,
        'version':        2,
    }
    raw = json.dumps(payload, separators=(',', ':')).encode()
    sig = _sign(raw)
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return b64 + '.' + sig

def decode_license_key(key_str: str) -> Optional[dict]:
    try:
        key_str = key_str.strip()
        if '.' not in key_str: return None
        b64_part, sig = key_str.rsplit('.', 1)
        pad = 4 - len(b64_part) % 4
        if pad != 4: b64_part += '=' * pad
        raw = base64.urlsafe_b64decode(b64_part)
        if not _verify_sig(raw, sig): return None
        return json.loads(raw)
    except Exception: return None


def _allocated_days_from_payload(data: dict) -> Optional[int]:
    """
    Resolve keygen-allocated days from the signed payload.
    Prefer explicit duration_days; else derive from expires_at - issued_at.
    Never invent a hardcoded plan default (365/30).
    """
    if not isinstance(data, dict):
        return None
    if 'duration_days' in data and data.get('duration_days') is not None:
        try:
            days = int(data['duration_days'])
            return days if days >= 1 else None
        except (TypeError, ValueError):
            return None
    issued = data.get('issued_at')
    expires = data.get('expires_at')
    if issued is not None and expires is not None:
        try:
            days = int((int(expires) - int(issued)) // 86400)
            return days if days >= 1 else None
        except (TypeError, ValueError):
            return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SECURE LICENSE STORE — hidden in system profile, survives app reinstall
# ══════════════════════════════════════════════════════════════════════════════

def _hidden_db_path() -> str:
    return os.path.join(_lic_store_dir(), 'lc.db')


def _sync_cloud_identity_fingerprint(device_id: str = '') -> None:
    """Keep cloud_identity hardware_fingerprint aligned with the stable local bind id."""
    try:
        from backend.cloud_backup.paths import load_identity, save_identity
        from backend.cloud_backup.device_manager import get_or_create_device_id

        ident = load_identity()
        fp = _get_device_fingerprint()
        changed = False
        if fp and str(ident.get('hardware_fingerprint') or '').strip() != fp:
            ident['hardware_fingerprint'] = fp
            changed = True
        if device_id and str(ident.get('device_id') or '').strip() != str(device_id).strip():
            ident['device_id'] = str(device_id).strip()
            changed = True
        if not str(ident.get('device_id') or '').strip().startswith('MBT-PC-'):
            get_or_create_device_id()
            ident = load_identity()
        if changed:
            save_identity(ident)
    except Exception as e:
        logger.debug('cloud identity fingerprint sync: %s', e)


def _verify_license_token_on_disk() -> bool:
    """True when lc.db contains a non-empty license_token row."""
    return _store_has_license_token(_hidden_db_path())


def ensure_license_store_ready() -> str:
    """Resolve canonical license dir and migrate legacy Roaming store if needed."""
    return _lic_store_dir()


class LicenseStore:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.db_path   = _hidden_db_path()
        self._init_db()

    def _init_db(self):
        db = sqlite3.connect(self.db_path)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS license_data (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, ts INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS license_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL, detail TEXT,
                ts INTEGER DEFAULT (strftime('%s','now')));
        """)
        db.commit(); db.close()

    def set(self, key: str, value):
        enc = encrypt_payload({'v': value}, self.device_id)
        db  = sqlite3.connect(self.db_path)
        db.execute("INSERT OR REPLACE INTO license_data (key,value,ts) VALUES (?,?,?)",
                   (key, enc, int(time.time())))
        db.commit()
        try:
            os.fsync(db.fileno())
        except Exception:
            pass
        db.close()

    def get(self, key: str, default=None):
        try:
            db  = sqlite3.connect(self.db_path)
            row = db.execute("SELECT value FROM license_data WHERE key=?", (key,)).fetchone()
            db.close()
            if row:
                dec = decrypt_payload(row[0], self.device_id)
                return dec['v'] if dec else default
        except Exception: pass
        return default

    def log(self, event: str, detail: str = ''):
        try:
            db = sqlite3.connect(self.db_path)
            db.execute("INSERT INTO license_log (event,detail) VALUES (?,?)", (event, detail))
            db.commit(); db.close()
        except Exception: pass

    def get_logs(self, limit=50):
        try:
            db   = sqlite3.connect(self.db_path)
            rows = db.execute(
                "SELECT ts,event,detail FROM license_log ORDER BY ts DESC LIMIT ?",
                (limit,)).fetchall()
            db.close()
            return [{'ts': r[0], 'event': r[1], 'detail': r[2]} for r in rows]
        except Exception: return []


# ══════════════════════════════════════════════════════════════════════════════
# TIME ANCHOR  —  fetch trusted time from internet to defeat clock rollback
# ══════════════════════════════════════════════════════════════════════════════

_TIME_SOURCES = [
    'https://worldtimeapi.org/api/timezone/Etc/UTC',
    'https://worldclockapi.com/api/json/utc/now',
]

# Session cache — never block POS startup on unreachable time APIs.
_TRUSTED_TIME_CACHE: dict = {
    'ts': None,          # Optional[int]
    'fetched_at': 0.0,   # monotonic-ish wall clock of last success
    'fail_until': 0.0,   # skip network until this wall time after failure
}
_TRUSTED_TIME_TTL_SEC = 3600.0
_TRUSTED_TIME_FAIL_TTL_SEC = 300.0
_TRUSTED_TIME_TIMEOUT = (1.0, 1.5)  # (connect, read) — fail open fast


def _cached_trusted_time() -> Optional[int]:
    """Return cached internet time only — never hits the network."""
    ts = _TRUSTED_TIME_CACHE.get('ts')
    if ts is None:
        return None
    age = time.time() - float(_TRUSTED_TIME_CACHE.get('fetched_at') or 0)
    if age > _TRUSTED_TIME_TTL_SEC:
        return None
    try:
        return int(ts)
    except Exception:
        return None


def _fetch_trusted_time(*, allow_network: bool = True) -> Optional[int]:
    """Return Unix timestamp from an internet time source, or None if offline.

    Startup / license evaluation must call with allow_network=False (or use
    ``_cached_trusted_time``) so unreachable DNS/HTTPS cannot hang the UI.
    """
    cached = _cached_trusted_time()
    if cached is not None:
        return cached
    if not allow_network:
        return None
    now = time.time()
    if now < float(_TRUSTED_TIME_CACHE.get('fail_until') or 0):
        return None
    for url in _TIME_SOURCES:
        try:
            r = requests.get(url, timeout=_TRUSTED_TIME_TIMEOUT)
            if not r.ok:
                continue
            data = r.json()
            # worldtimeapi
            if 'unixtime' in data:
                result = int(data['unixtime'])
            # worldclockapi  {'currentFileTime': 133...}
            elif 'currentFileTime' in data:
                # Windows FILETIME → Unix: subtract 116444736000000000, divide by 10M
                ft = int(data['currentFileTime'])
                result = (ft - 116444736000000000) // 10_000_000
            else:
                continue
            _TRUSTED_TIME_CACHE['ts'] = result
            _TRUSTED_TIME_CACHE['fetched_at'] = now
            _TRUSTED_TIME_CACHE['fail_until'] = 0.0
            return result
        except Exception:
            continue
    _TRUSTED_TIME_CACHE['fail_until'] = now + _TRUSTED_TIME_FAIL_TTL_SEC
    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LICENSE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class LicenseEngine:

    def __init__(self, project_root: str | None = None):
        if not project_root:
            from mbt_paths import get_project_root
            project_root = get_project_root()
        self.project_root  = project_root
        self.device_id     = resolve_device_id()
        self.store         = LicenseStore(self.device_id)
        self._state        = STATE_UNACTIVATED
        self._license_data = {}
        self._last_sync    = 0
        self._tamper_count = 0
        self._lock         = threading.Lock()
        self._load_from_store()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_from_store(self):
        inner, matched_did = _resolve_inner_license_token()
        if matched_did and matched_did != self.device_id:
            self.device_id = matched_did
            self.store = LicenseStore(self.device_id)
        token = inner or self.store.get('license_token')
        if not token:
            # Revoke must survive revalidate() — empty token alone looks
            # like "never activated" and would skip the revoked hard-lock UI.
            if self.store.get('revoked'):
                self._license_data = {}
                self._state = STATE_INACTIVE
            else:
                self._state = STATE_UNACTIVATED
            return

        data = decrypt_payload(token, self.device_id)
        if not data:
            # Token exists but cannot be decrypted with THIS device's key
            # → either tampered, or DB was copied from a different machine
            self._license_data = {}
            self._state = STATE_TAMPERED
            self.store.set('tampered', True)
            self.store.log('TAMPER_DETECT', 'Decryption failed — wrong device or tampered token')
            return

        # Hard device binding check — device_id baked into token
        if data.get('device_id') != self.device_id:
            self._license_data = {}
            self._state = STATE_TAMPERED
            self.store.set('tampered', True)
            self.store.log('DEVICE_MISMATCH',
                f"Token device={data.get('device_id','?')[:8]}… "
                f"Current={self.device_id[:8]}…")
            return

        self._license_data = data
        self._maybe_rebind_to_canonical_fingerprint(matched_did)
        self._maybe_clear_stale_tamper()
        self._maybe_clear_stale_cloud_lock()
        self._evaluate_state()

    def _maybe_rebind_to_canonical_fingerprint(self, matched_did: str | None):
        """Rewrite MBT-PC-* / legacy-wmic tokens onto the stable MachineGuid id."""
        canonical = _get_device_fingerprint()
        if not canonical or not self._license_data:
            return
        if matched_did == canonical:
            _write_cached_device_id(canonical)
            return
        allow = False
        if matched_did and str(matched_did).startswith('MBT-PC-'):
            allow = True
        elif matched_did and matched_did == _get_legacy_wmic_fingerprint():
            allow = True
        if not allow:
            return
        try:
            lic = dict(self._license_data)
            lic['device_id'] = canonical
            self.device_id = canonical
            self.store = LicenseStore(canonical)
            token = encrypt_payload(lic, canonical)
            self.store.set('license_token', token)
            self.store.set('tampered', False)
            self.store.set('revoked', False)
            self._license_data = lic
            _write_cached_device_id(canonical)
            self.store.log(
                'DEVICE_ID_MIGRATED',
                f'{str(matched_did)[:16]} → MachineGuid fingerprint',
            )
        except Exception as e:
            logger.warning('Could not migrate license device id: %s', e)

    def _maybe_clear_stale_tamper(self):
        """Clear false tamper flags when the license token is still valid."""
        if not self.store.get('tampered'):
            return
        if not self._license_data:
            return
        if self._license_data.get('device_id') != self.device_id:
            return
        local_now = int(time.time())
        expires = self._license_data.get('expires_at', 0)
        if expires and local_now > expires + 86400:
            return
        self.store.set('tampered', False)
        self.store.log('TAMPER_CLEARED', 'Valid license — removed stale tamper flag')

    def _maybe_clear_stale_cloud_lock(self):
        """Remove obsolete cloud-trial locks from a valid local signed license.

        Older builds could leave ``cloud_license_key`` and offline-grace flags
        behind after a shop activated a local lifetime key. Waiting for a
        background cloud cycle to repair that state made every fresh launch
        report CRITICAL despite the valid local token.
        """
        lic = self._license_data or {}
        is_cloud_license = bool(
            str(lic.get('license_key') or '').strip()
            or str(lic.get('source') or '').strip().lower() == 'mbt_cloud'
        )
        if not lic or is_cloud_license:
            return
        stale = bool(
            self.store.get('cloud_license_key')
            or self.store.get('requires_online')
            or self.store.get('offline_lock')
        )
        if not stale:
            return
        now = int(time.time())
        self.store.set('cloud_license_key', '')
        self.store.set('last_cloud_ok_ts', now)
        self.store.set('last_cloud_check_ts', now)
        self.store.set('requires_online', False)
        self.store.set('offline_lock', False)
        self.store.log(
            'LOCAL_LICENSE_CLOUD_STATE_CLEARED',
            'Removed stale cloud/offline flags from valid local license',
        )

    def _evaluate_state(self):
        if not self._license_data:
            self._state = STATE_INACTIVE if self.store.get('revoked') else STATE_UNACTIVATED
            return

        local_now  = int(time.time())
        last_local = self.store.get('last_checked_ts', 0)

        # Clock jumps after reboot (no NTP yet, CMOS lag) must NOT brick a
        # valid local license — that put Edmus back on the activation screen.
        if last_local and local_now < (last_local - 3600):
            self._tamper_count += 1
            self.store.log('TIME_ROLLBACK',
                f'Local clock went back: last={last_local} now={local_now} '
                f'delta={last_local - local_now}s (ignored — license kept)')

        highest = int(self.store.get('highest_ts_seen', 0) or 0)
        if highest and local_now < (highest - 3600):
            self.store.log('ROLLBACK_HIGHEST',
                f'now={local_now} highest_ever={highest} (ignored — license kept)')
            # Do not advance anchors while the clock is still catching up.
        elif local_now > highest:
            self.store.set('highest_ts_seen', local_now)
            self.store.set('last_checked_ts', local_now)
        else:
            self.store.set('last_checked_ts', local_now)

        # Never fetch internet time here — that blocked offline shop startup for
        # 10–30+ seconds (DNS/HTTPS hang). Use cache only; bg service may refresh.
        trusted = _cached_trusted_time()
        if trusted is not None:
            drift = abs(local_now - trusted)
            if drift > 3600:
                self.store.log('CLOCK_DRIFT',
                    f'Local={local_now} Trusted={trusted} Drift={drift}s (warning only)')

        # For expiry, use the later of local vs cached trusted so a slow clock
        # does not falsely expire; still use local for rollback anchors above.
        expiry_now = max(local_now, trusted) if trusted is not None else local_now

        expires   = self._license_data.get('expires_at', 0)
        days_left = max(0, (expires - expiry_now) // 86400)

        if expiry_now > expires:        self._state = STATE_EXPIRED
        elif days_left <= 3:            self._state = STATE_CRITICAL
        elif days_left <= 7:            self._state = STATE_WARNING
        elif days_left <= 14:           self._state = STATE_EXPIRING
        else:                           self._state = STATE_ACTIVE

    # ── Activation ────────────────────────────────────────────────────────────

    def activate(self, key_str: str) -> bool:
        """Backwards-compatible alias used by activation_ui.py."""
        ok, _ = self.activate_with_key(key_str)
        return ok

    def activate_with_key(self, key_str: str) -> Tuple[bool, str]:
        """Activate using a Portal / online key only (MBT-…).

        Locally signed keygen keys are rejected unless MBT_ALLOW_LOCAL_KEYS=1
        (developer/tests). Existing already-activated installs are unaffected.
        """
        key_str = (key_str or '').strip()
        if not key_str:
            return False, "Please enter a license key."

        # Preferred path: online Portal keys (MBT-PLAN-XXXX-…)
        if key_str.upper().startswith('MBT-') and key_str.count('-') >= 2:
            return self._activate_cloud_key(key_str)

        data = decode_license_key(key_str)
        if data:
            # Signed offline / license_keygen.py keys — disabled for production.
            allow_local = (os.environ.get('MBT_ALLOW_LOCAL_KEYS') or '').strip() in (
                '1', 'true', 'TRUE', 'yes', 'YES',
            )
            # Environment variables are customer-controlled on an installed PC.
            # Keep legacy key generation available only to source-based developer
            # and test runs; frozen production builds always require Portal keys.
            if not allow_local or getattr(sys, 'frozen', False):
                self.store.log('ACTIVATION_FAIL', 'Local keygen key rejected (online-only policy)')
                return False, (
                    "Local/offline keys are no longer accepted. "
                    "Sign in at portal.mugobyte.com and paste an online MBT-… license key."
                )
            return self._activate_local_signed_key(data)

        return False, (
            "Invalid license key. Use an online key from portal.mugobyte.com "
            "(format MBT-…)."
        )

    def _activate_local_signed_key(self, data: dict) -> Tuple[bool, str]:
        """Legacy keygen activation — only when MBT_ALLOW_LOCAL_KEYS is set."""
        key_device = data.get('device_id', '')
        if key_device and key_device != self.device_id:
            self.store.log('ACTIVATION_FAIL', 'Device ID mismatch')
            return False, "This license key is bound to a different device."

        local_now = int(time.time())
        allocated = _allocated_days_from_payload(data)
        if not allocated:
            return False, "License key has no valid duration_days allocation."

        expires_at = local_now + allocated * 86400
        lic = {
            'device_id':      self.device_id,
            'plan':           data.get('plan', 'basic'),
            'issued_at':      data.get('issued_at', local_now),
            'expires_at':     expires_at,
            'duration_days':  allocated,
            'activated_at':   local_now,
            'issued_by':      data.get('issued_by', 'MugoByte Technologies'),
            'version':        2,
        }
        with self._lock:
            _write_cached_device_id(self.device_id)
            token = encrypt_payload(lic, self.device_id)
            self.store.set('license_token', token)
            self.store.set('last_checked_ts', local_now)
            self.store.set('highest_ts_seen', local_now)
            self.store.set('tampered', False)
            self.store.set('revoked', False)
            self.store.set('cloud_license_key', '')
            self.store.set('last_cloud_ok_ts', local_now)
            self.store.set('last_cloud_check_ts', local_now)
            self.store.set('requires_online', False)
            self.store.set('offline_lock', False)
            self._license_data = lic
            self._tamper_count = 0
            self._evaluate_state()
            self.store.log('ACTIVATED',
                f"Plan={lic['plan']} Days={allocated} "
                f"Expires={datetime.fromtimestamp(lic['expires_at']).date()}")
        plan_name = PLANS.get(lic['plan'], {}).get('name', lic['plan'])
        return True, f"License activated! Plan: {plan_name} ({allocated} days)"

    def _activate_cloud_key(self, key_str: str) -> Tuple[bool, str]:
        """Validate + activate a MugoByte Platform license key, then mirror locally."""
        try:
            from backend.cloud.platform_service import activate_license_on_device
            from backend.cloud_backup.device_manager import get_or_create_device_id
            from backend.cloud_backup.paths import load_identity
            canonical_id = get_or_create_device_id() or self.device_id
            ident = load_identity()
            aliases = []
            for raw in (
                self.device_id,
                str(ident.get('hardware_fingerprint') or '').strip(),
            ):
                val = str(raw or '').strip()
                if val and val != canonical_id and val not in aliases:
                    aliases.append(val)
            actor_email = (ident.get('email') or '').strip()
            result = activate_license_on_device(
                key_str,
                canonical_id,
                actor_email=actor_email,
                actor_is_admin=False,
                device_aliases=aliases,
            )
            if result.get('ok'):
                lic = result.get('license') or {}
                activation = result.get('activation') or {}
                ok, message = self.activate_from_cloud(
                    plan=lic.get('plan') or activation.get('plan') or 'trial',
                    expires_at=(
                        lic.get('expires_at')
                        or activation.get('expires_at')
                    ),
                    license_key=key_str,
                    source='mbt_cloud',
                )
                if ok:
                    self._wire_cloud_backup_after_activation(result)
                    return True, message
                return False, message
            return False, result.get('message') or 'Cloud activation failed'
        except Exception as e:
            logger.warning('Cloud key activation failed: %s', e)
            return False, str(e)

    def _wire_cloud_backup_after_activation(self, result: dict) -> None:
        """Persist org linkage and kick off backup when a Portal session exists."""
        try:
            from backend.cloud_backup.paths import (
                is_logged_in,
                load_cloud_config,
                load_identity,
                save_cloud_config,
                save_identity,
            )
            from backend.cloud_backup.auth_service import _kickoff_backup_after_login

            lic = result.get('license') or {}
            org_id = str(lic.get('org_id') or '')
            ident = load_identity()
            if org_id and ident.get('org_id') != org_id:
                ident['org_id'] = org_id
                save_identity(ident)
            if is_logged_in():
                cfg = load_cloud_config()
                cfg['enabled'] = True
                save_cloud_config(cfg)
                _kickoff_backup_after_login()
        except Exception as e:
            logger.debug('Cloud backup wire after activation: %s', e)

    def activate_from_cloud(
        self,
        *,
        plan: str = 'trial',
        expires_at: str | None = None,
        license_key: str = '',
        duration_days: int | None = None,
        source: str = 'mbt_cloud',
    ) -> Tuple[bool, str]:
        """Mirror a server-validated cloud license onto this device (no local key signature)."""
        local_now = int(time.time())
        allocated = duration_days
        if not allocated and expires_at:
            try:
                exp = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
                allocated = max(1, int((exp.timestamp() - local_now) // 86400) + 1)
            except Exception:
                allocated = None
        if not allocated:
            allocated = int(PLANS.get(plan, {}).get('days') or 30)

        lic = {
            'device_id': self.device_id,
            'plan': plan or 'trial',
            'issued_at': local_now,
            'expires_at': local_now + allocated * 86400,
            'duration_days': allocated,
            'activated_at': local_now,
            'issued_by': 'MugoByte Platform',
            'license_key': license_key,
            'source': source,
            'version': 2,
        }
        with self._lock:
            try:
                from backend.cloud_backup.device_manager import get_or_create_device_id
                cloud_device_id = get_or_create_device_id() or self.device_id
            except Exception:
                cloud_device_id = self.device_id
            bind_id = _get_device_fingerprint() or self.device_id
            self.device_id = bind_id
            self.store = LicenseStore(bind_id)
            lic['device_id'] = bind_id
            _write_cached_device_id(bind_id)
            token = encrypt_payload(lic, bind_id)
            self.store.set('license_token', token)
            self.store.set('last_checked_ts', local_now)
            self.store.set('highest_ts_seen', local_now)
            self.store.set('tampered', False)
            self.store.set('revoked', False)
            if license_key:
                self.store.set('cloud_license_key', license_key)
            self._license_data = lic
            self._tamper_count = 0
            self._evaluate_state()
            self.store.log(
                'CLOUD_ACTIVATED',
                f"Plan={lic['plan']} Days={allocated} Key={license_key[:16]}…",
            )
            _sync_cloud_identity_fingerprint(cloud_device_id)
            if not _verify_license_token_on_disk():
                self._license_data = {}
                self._state = STATE_UNACTIVATED
                return False, 'Activation could not be saved on this PC — try again.'
        plan_name = PLANS.get(lic['plan'], {}).get('name', lic['plan'])
        return True, f"Cloud license activated! Plan: {plan_name} ({allocated} days)"

    def activate_from_remote(self, payload: dict) -> Tuple[bool, str]:
        """Activate via signed remote payload (legacy / command center)."""
        sig = payload.pop('sig', '')
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
        if not _verify_sig(raw, sig):
            self.store.log('REMOTE_ACTIVATION_FAIL', 'Bad signature')
            return False, "Invalid remote command signature."

        # Always bind to THIS device — prevents replay on other machines
        local_now = int(time.time())
        allocated = _allocated_days_from_payload(payload)
        if not allocated:
            return False, "Remote payload has no valid duration_days allocation."

        payload['device_id']      = self.device_id
        payload['activated_at']   = local_now
        payload['duration_days']  = allocated
        payload['expires_at']     = local_now + allocated * 86400

        with self._lock:
            _write_cached_device_id(self.device_id)
            token = encrypt_payload(payload, self.device_id)
            self.store.set('license_token', token)
            self.store.set('last_checked_ts', local_now)
            self.store.set('highest_ts_seen', local_now)
            self.store.set('tampered', False)
            self.store.set('revoked', False)
            self._license_data = payload
            self._tamper_count = 0
            self._evaluate_state()
            self.store.log('REMOTE_ACTIVATED',
                f"Plan={payload.get('plan')} Days={allocated} "
                f"Expires={payload.get('expires_at')}")
        return True, f"Remote activation successful ({allocated} days)."

    def revoke(self, sig: str) -> Tuple[bool, str]:
        raw = f"revoke:{self.device_id}".encode()
        if not _verify_sig(raw, sig):
            return False, "Invalid revocation signature."
        return self.revoke_from_cloud(reason='Revoked by administrator (signed)')

    def revoke_from_cloud(self, reason: str = 'Revoked by MugoByte Platform') -> Tuple[bool, str]:
        """Trusted cloud/admin revoke — no local signature required."""
        with self._lock:
            self.store.set('license_token', '')
            self.store.set('tampered', False)
            self.store.set('revoked', True)
            self.store.set('cloud_license_key', '')
            self._license_data = {}
            self._state = STATE_INACTIVE
            self.store.log('REVOKED', reason)
        return True, "License revoked."

    def extend(self, extra_days: int, sig: str) -> Tuple[bool, str]:
        raw = f"extend:{extra_days}:{self.device_id}".encode()
        if not _verify_sig(raw, sig):
            return False, "Invalid extension signature."
        return self.extend_from_cloud(extra_days, reason='Extended (signed)')

    def extend_from_cloud(self, extra_days: int, reason: str = 'Extended by MugoByte Platform',
                          expires_at: str | None = None) -> Tuple[bool, str]:
        """Trusted cloud extend — add days or set absolute expiry from server."""
        with self._lock:
            if not self._license_data and not expires_at:
                return False, "No active license to extend."
            local_now = int(time.time())
            if expires_at:
                try:
                    exp = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
                    new_exp = int(exp.timestamp())
                except Exception:
                    return False, "Invalid expires_at from cloud"
                if not self._license_data:
                    # Rebuild minimal license from cloud renew
                    self._license_data = {
                        'device_id': self.device_id,
                        'plan': 'basic',
                        'issued_at': local_now,
                        'activated_at': local_now,
                        'source': 'mbt_cloud',
                        'version': 2,
                    }
                self._license_data['expires_at'] = new_exp
                extra_days = max(1, (new_exp - local_now) // 86400)
            else:
                if not self._license_data:
                    return False, "No active license to extend."
                self._license_data['expires_at'] = int(self._license_data.get('expires_at') or local_now) + int(extra_days) * 86400
            self._license_data['duration_days'] = max(
                1, (int(self._license_data['expires_at']) - int(self._license_data.get('activated_at') or local_now)) // 86400
            )
            token = encrypt_payload(self._license_data, self.device_id)
            self.store.set('license_token', token)
            self.store.set('revoked', False)
            self.store.set('tampered', False)
            if local_now > self.store.get('highest_ts_seen', 0):
                self.store.set('highest_ts_seen', local_now)
            self._evaluate_state()
            self.store.log('EXTENDED', f"+{extra_days} days · {reason}")
        return True, f"License extended by {extra_days} days."

    def apply_cloud_validation(self, ok: bool, payload: dict | None = None, message: str = '') -> Tuple[bool, str]:
        """Apply result of CloudLicenseServer.validate / status check."""
        now = int(time.time())
        self.store.set('last_cloud_ok_ts', now if ok else self.store.get('last_cloud_ok_ts', 0))
        self.store.set('last_cloud_check_ts', now)
        if not ok:
            status = (payload or {}).get('status') or message
            msg_l = str(message or '').lower()
            st_l = str(status).lower()
            if st_l in ('revoked', 'suspended') or 'revoked' in msg_l or 'suspended' in msg_l:
                self.revoke_from_cloud(reason=f'Cloud validation failed: {message or status}')
                return False, message or 'License invalid on cloud'
            self.store.set('requires_online', True)
            self.store.log('CLOUD_VALIDATE_FAIL', message or str(status))
            return False, message or 'Cloud validation failed'
        # Sync expiry from cloud if provided
        if payload and payload.get('expires_at'):
            try:
                self.extend_from_cloud(0, reason='Cloud revalidation sync', expires_at=payload['expires_at'])
            except Exception:
                pass
        self.store.set('requires_online', False)
        self.store.set('offline_lock', False)
        self.store.log('CLOUD_VALIDATE_OK', message or 'Valid')
        return True, 'Valid'

    def enforce_offline_grace(self, grace_days: int = 7) -> Tuple[bool, str]:
        """
        Force online confirmation after grace_days without a successful cloud check.
        Returns (still_allowed, message).
        """
        last_ok = int(self.store.get('last_cloud_ok_ts') or 0)
        # First cloud sync: seed last_ok on first successful online path only
        if not last_ok:
            # Allow until first opportunity; stamp "activation" as baseline if licensed
            act = (self._license_data or {}).get('activated_at') or 0
            last_ok = int(act) if act else int(time.time())
            self.store.set('last_cloud_ok_ts', last_ok)
        now = int(time.time())
        offline_secs = now - last_ok
        grace_secs = max(1, int(grace_days)) * 86400
        if offline_secs <= grace_secs:
            self.store.set('offline_lock', False)
            return True, f'Offline OK ({offline_secs // 86400}d / {grace_days}d grace)'
        with self._lock:
            self.store.set('offline_lock', True)
            self.store.set('requires_online', True)
            self.store.log(
                'OFFLINE_GRACE_EXCEEDED',
                f'{offline_secs // 86400} days without cloud confirmation (limit {grace_days})',
            )
            # Soft-lock: mark inactive until online validate succeeds
            if self._state not in (STATE_TAMPERED, STATE_INACTIVE):
                self._state = STATE_CRITICAL
        return False, f'Must connect to internet — offline for {offline_secs // 86400} days (limit {grace_days})'

    # ── State ──────────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            # Stale clock-tamper flags must not override a decryptable license.
            if self.store.get('tampered') and not self._license_data:
                self._state = STATE_TAMPERED
                return STATE_TAMPERED
            if self.store.get('tampered') and self._license_data:
                self._maybe_clear_stale_tamper()
            if self.store.get('revoked') and not self._license_data:
                self._state = STATE_INACTIVE
                return STATE_INACTIVE
            if self.store.get('offline_lock'):
                # Soft lock: still honour real expiry / unactivated / revoke.
                self._evaluate_state()
                if self._state in (
                    STATE_EXPIRED, STATE_UNACTIVATED, STATE_INACTIVE, STATE_TAMPERED,
                ):
                    return self._state
                self._state = STATE_CRITICAL
                return STATE_CRITICAL
            self._evaluate_state()
            return self._state

    @property
    def is_valid(self) -> bool:
        """Local license usable for POS.

        Soft ``offline_lock`` (grace exceeded / cloud unreachable) must NOT brick
        an already-activated shop — that maps to STATE_CRITICAL and still opens.
        Hard blocks: tamper, revoke without token, expired, unactivated.
        """
        if self.store.get('tampered') and not self._license_data:
            return False
        if self.store.get('tampered') and self._license_data:
            self._maybe_clear_stale_tamper()
        if self.store.get('revoked') and not self._license_data:
            return False
        # Evaluate real license (ignores offline_lock short-circuit via property)
        with self._lock:
            self._evaluate_state()
            st = self._state
        if self.store.get('offline_lock') and st in (
            STATE_ACTIVE, STATE_EXPIRING, STATE_WARNING, STATE_CRITICAL,
        ):
            return True
        return st in (STATE_ACTIVE, STATE_EXPIRING, STATE_WARNING, STATE_CRITICAL)

    def has_local_license_payload(self) -> bool:
        """True when a decryptable license token exists for this device."""
        inner, _did = _resolve_inner_license_token()
        if inner:
            return True
        return bool(self._license_data and self._license_data.get('expires_at'))

    @property
    def days_remaining(self) -> int:
        exp = self._license_data.get('expires_at', 0)
        if not exp: return 0
        actual_now = _cached_trusted_time() or int(time.time())
        return max(0, (exp - actual_now) // 86400)

    @property
    def plan(self) -> str: return self._license_data.get('plan', 'unactivated')

    @property
    def plan_name(self) -> str:
        return PLANS.get(self.plan, {}).get('name', self.plan.title())

    @property
    def expiry_date(self) -> Optional[str]:
        exp = self._license_data.get('expires_at')
        return datetime.fromtimestamp(exp).strftime('%d %B %Y') if exp else None

    @property
    def activation_date(self) -> Optional[str]:
        act = self._license_data.get('activated_at')
        return datetime.fromtimestamp(act).strftime('%d %B %Y') if act else None

    @property
    def masked_device_id(self) -> str:
        did = self.device_id
        return did[:6] + '•' * 12 + did[-4:]

    def get_status_dict(self) -> dict:
        st = self.state
        lic = self._license_data or {}
        last_ok = int(self.store.get('last_cloud_ok_ts') or 0)
        last_check = int(self.store.get('last_cloud_check_ts') or 0)
        offline_days = max(0, (int(time.time()) - last_ok) // 86400) if last_ok else 0
        return {
            'state':           st,
            'is_valid':        self.is_valid,
            'plan':            self.plan,
            'plan_name':       self.plan_name,
            'days_remaining':  self.days_remaining,
            'expiry_date':     self.expiry_date,
            'activation_date': self.activation_date,
            'device_id':       self.masked_device_id,
            'last_sync':       self.store.get('last_sync_ts', 0),
            'tamper_count':    self._tamper_count,
            'source':          lic.get('source') or ('mbt_cloud' if lic.get('license_key') else 'license_engine'),
            'license_key':     lic.get('license_key') or self.store.get('cloud_license_key') or '',
            'revoked':         bool(self.store.get('revoked')),
            'tampered':        bool(self.store.get('tampered')),
            'requires_online': bool(self.store.get('requires_online') or self.store.get('offline_lock')),
            'offline_lock':    bool(self.store.get('offline_lock')),
            'last_cloud_ok':   last_ok,
            'last_cloud_check': last_check,
            'offline_days':    offline_days,
        }

    def revalidate(self):
        with self._lock:
            self._load_from_store()
            self._evaluate_state()
            return self._state