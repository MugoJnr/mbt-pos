"""
MBT POS — License Engine (Core)
MugoByte Technologies | mugobyte.com

Offline-first license validation with:
  • Hardware device binding (CPU/board/disk serials)
  • Time-rollback detection (local + remote anchor)
  • Anti-copy: token is cryptographically bound to THIS device's fingerprint
  • Tamper → immediate lock on first confirmed attack
  • Remote activation / revoke / extend via signed Telegram commands
"""
import os, sys, json, time, uuid, hashlib, hmac, base64
import sqlite3, platform, threading, logging, requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

logger = logging.getLogger('license_engine')

# ── Master secret — baked at build time, never changes ────────────────────────
_MASTER_SECRET = b'MBT$MUGOBYTE$2024$LICENSE$ENGINE$SECRET$NEVER$EXPOSE$THIS$KEY!'

# Developer Telegram IDs allowed to send admin commands
ADMIN_TELEGRAM_IDS = {8293620725}

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
            ('wmic cpu get ProcessorId /value',        'ProcessorId='),
            ('wmic baseboard get SerialNumber /value', 'SerialNumber='),
            ('wmic diskdrive get SerialNumber /value', 'SerialNumber='),
        ]:
            try:
                out = subprocess.check_output(cmd, shell=True,
                                               stderr=subprocess.DEVNULL,
                                               timeout=5).decode(errors='ignore')
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
            return did if len(did) == 40 else None
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


def _fingerprint_device_id_candidates() -> list:
    """Ids to try when matching an existing license (incl. migration)."""
    seen = []
    for did in (
        _read_cached_device_id(),
        _get_device_fingerprint(),
        _get_legacy_wmic_fingerprint(),
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
    token = _read_raw_license_token()
    if token:
        for did in _fingerprint_device_id_candidates():
            if decrypt_payload(token, did):
                _write_cached_device_id(did)
                return did
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


# ══════════════════════════════════════════════════════════════════════════════
# CRYPTOGRAPHIC HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _sign(data: bytes, secret: bytes = _MASTER_SECRET) -> str:
    return hmac.new(secret, data, hashlib.sha256).hexdigest()

def _verify_sig(data: bytes, sig: str, secret: bytes = _MASTER_SECRET) -> bool:
    if not sig:
        return False
    return hmac.compare_digest(_sign(data, secret), sig)

def _derive_key(device_id: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        'sha256', device_id.encode(), _MASTER_SECRET,
        iterations=100_000, dklen=32)

def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    out = bytearray(len(data)); kl = len(key)
    for i, b in enumerate(data): out[i] = b ^ key[i % kl]
    return bytes(out)

def encrypt_payload(payload: dict, device_id: str) -> str:
    key = _derive_key(device_id)
    raw = json.dumps(payload, separators=(',', ':')).encode()
    enc = _xor_encrypt(raw, key)
    return base64.b64encode(enc).decode() + '.' + _sign(enc, key)

def decrypt_payload(token: str, device_id: str) -> Optional[dict]:
    try:
        b64, sig = token.rsplit('.', 1)
        enc = base64.b64decode(b64)
        key = _derive_key(device_id)
        if not _verify_sig(enc, sig, key): return None
        return json.loads(_xor_encrypt(enc, key))
    except Exception: return None


# ══════════════════════════════════════════════════════════════════════════════
# LICENSE KEY GENERATION (developer side)
# ══════════════════════════════════════════════════════════════════════════════

def generate_license_key(device_id: str, plan: str = 'basic',
                         duration_days: int = 365,
                         issued_by: str = 'MugoByte Technologies') -> str:
    now = int(time.time())
    payload = {
        'device_id':  device_id, 'plan': plan,
        'issued_at':  now, 'expires_at': now + duration_days * 86400,
        'issued_by':  issued_by, 'version': 2,
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


# ══════════════════════════════════════════════════════════════════════════════
# SECURE LICENSE STORE — hidden in system profile, survives app reinstall
# ══════════════════════════════════════════════════════════════════════════════

def _hidden_db_path() -> str:
    if platform.system() == 'Windows':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        d = os.path.join(base, 'MugoByte', '.mbt_lic')
    elif platform.system() == 'Darwin':
        d = os.path.expanduser('~/Library/Application Support/MugoByte/.mbt_lic')
    else:
        d = os.path.expanduser('~/.config/mugobyte/.mbt_lic')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'lc.db')


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
        db.commit(); db.close()

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
    'http://worldclockapi.com/api/json/utc/now',
]

def _fetch_trusted_time() -> Optional[int]:
    """Return Unix timestamp from an internet time source, or None if offline."""
    for url in _TIME_SOURCES:
        try:
            r = requests.get(url, timeout=5)
            if not r.ok: continue
            data = r.json()
            # worldtimeapi
            if 'unixtime' in data:
                return int(data['unixtime'])
            # worldclockapi  {'currentFileTime': 133...}
            if 'currentFileTime' in data:
                # Windows FILETIME → Unix: subtract 116444736000000000, divide by 10M
                ft = int(data['currentFileTime'])
                return (ft - 116444736000000000) // 10_000_000
        except Exception:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LICENSE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class LicenseEngine:

    def __init__(self, project_root: str):
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
        # Sync developer chat ID from app DB
        try:
            from mbt_paths import get_db_path
            db_path = get_db_path()
            if os.path.exists(db_path):
                db  = sqlite3.connect(db_path)
                row = db.execute(
                    "SELECT value FROM system_settings WHERE key='developer_chat_id'"
                ).fetchone()
                if row and row[0]:
                    ADMIN_TELEGRAM_IDS.add(int(row[0]))
                db.close()
        except Exception: pass

        token = self.store.get('license_token')
        if not token:
            self._state = STATE_UNACTIVATED; return

        data = decrypt_payload(token, self.device_id)
        if not data:
            # Token exists but cannot be decrypted with THIS device's key
            # → either tampered, or DB was copied from a different machine
            self._state = STATE_TAMPERED
            self.store.log('TAMPER_DETECT', 'Decryption failed — wrong device or tampered token')
            return

        # Hard device binding check — device_id baked into token
        if data.get('device_id') != self.device_id:
            self._state = STATE_TAMPERED
            self.store.log('DEVICE_MISMATCH',
                f"Token device={data.get('device_id','?')[:8]}… "
                f"Current={self.device_id[:8]}…")
            return

        self._license_data = data
        self._maybe_clear_stale_tamper()
        self._evaluate_state()

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

    def _evaluate_state(self):
        if not self._license_data:
            self._state = STATE_UNACTIVATED; return

        local_now  = int(time.time())
        last_local = self.store.get('last_checked_ts', 0)

        # Anti-rollback uses LOCAL time only (trusted time must not be stored
        # in highest_ts_seen — that caused false tamper after restart when the
        # PC clock was behind internet time).
        if last_local and local_now < (last_local - 3600):
            self._tamper_count += 1
            self.store.log('TIME_ROLLBACK',
                f'Local clock went back: last={last_local} now={local_now} '
                f'delta={last_local - local_now}s')
            self._state = STATE_TAMPERED
            self.store.set('tampered', True)
            return

        highest = self.store.get('highest_ts_seen', 0)
        if highest and local_now < (highest - 3600):
            self._state = STATE_TAMPERED
            self.store.set('tampered', True)
            self.store.log('ROLLBACK_HIGHEST',
                f'now={local_now} highest_ever={highest}')
            return

        if local_now > highest:
            self.store.set('highest_ts_seen', local_now)
        self.store.set('last_checked_ts', local_now)

        trusted = _fetch_trusted_time()
        if trusted is not None:
            drift = abs(local_now - trusted)
            if drift > 3600:
                self.store.log('CLOCK_DRIFT',
                    f'Local={local_now} Trusted={trusted} Drift={drift}s (warning only)')

        # For expiry, use the later of local vs trusted so a slow clock does not
        # falsely expire the license; still use local for rollback anchors above.
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
        data = decode_license_key(key_str)
        if not data:
            return False, "Invalid or tampered license key."

        # Key must be issued for THIS device
        key_device = data.get('device_id', '')
        if key_device and key_device != self.device_id:
            self.store.log('ACTIVATION_FAIL', 'Device ID mismatch')
            return False, "This license key is bound to a different device."

        local_now = int(time.time())
        trusted = _fetch_trusted_time()
        check_now = max(local_now, trusted) if trusted else local_now
        if check_now > data.get('expires_at', 0):
            return False, "This license key has already expired."

        lic = {
            'device_id':    self.device_id,          # bake THIS device into token
            'plan':         data.get('plan', 'basic'),
            'issued_at':    data.get('issued_at', local_now),
            'expires_at':   data.get('expires_at', local_now + 365 * 86400),
            'activated_at': local_now,
            'issued_by':    data.get('issued_by', 'MugoByte Technologies'),
            'version':      2,
        }
        with self._lock:
            _write_cached_device_id(self.device_id)
            token = encrypt_payload(lic, self.device_id)
            self.store.set('license_token', token)
            self.store.set('last_checked_ts', local_now)
            self.store.set('highest_ts_seen', local_now)
            self.store.set('tampered', False)
            self._license_data = lic
            self._tamper_count = 0
            self._evaluate_state()
            self.store.log('ACTIVATED',
                f"Plan={lic['plan']} "
                f"Expires={datetime.fromtimestamp(lic['expires_at']).date()}")
        plan_name = PLANS.get(lic['plan'], {}).get('name', lic['plan'])
        return True, f"License activated! Plan: {plan_name}"

    def activate_from_remote(self, payload: dict) -> Tuple[bool, str]:
        """Activate via signed remote payload (Telegram command)."""
        sig = payload.pop('sig', '')
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
        if not _verify_sig(raw, sig):
            self.store.log('REMOTE_ACTIVATION_FAIL', 'Bad signature')
            return False, "Invalid remote command signature."

        # Always bind to THIS device — prevents replay on other machines
        local_now = int(time.time())
        payload['device_id']    = self.device_id
        payload['activated_at'] = local_now

        with self._lock:
            _write_cached_device_id(self.device_id)
            token = encrypt_payload(payload, self.device_id)
            self.store.set('license_token', token)
            self.store.set('last_checked_ts', local_now)
            self.store.set('highest_ts_seen', local_now)
            self.store.set('tampered', False)
            self._license_data = payload
            self._tamper_count = 0
            self._evaluate_state()
            self.store.log('REMOTE_ACTIVATED',
                f"Plan={payload.get('plan')} Expires={payload.get('expires_at')}")
        return True, "Remote activation successful."

    def extend(self, extra_days: int, sig: str) -> Tuple[bool, str]:
        raw = f"extend:{extra_days}:{self.device_id}".encode()
        if not _verify_sig(raw, sig):
            return False, "Invalid extension signature."
        with self._lock:
            if not self._license_data: return False, "No active license to extend."
            self._license_data['expires_at'] += extra_days * 86400
            local_now = int(time.time())
            token = encrypt_payload(self._license_data, self.device_id)
            self.store.set('license_token', token)
            if local_now > self.store.get('highest_ts_seen', 0):
                self.store.set('highest_ts_seen', local_now)
            self._evaluate_state()
            self.store.log('EXTENDED', f"+{extra_days} days")
        return True, f"License extended by {extra_days} days."

    def revoke(self, sig: str) -> Tuple[bool, str]:
        raw = f"revoke:{self.device_id}".encode()
        if not _verify_sig(raw, sig):
            return False, "Invalid revocation signature."
        with self._lock:
            self.store.set('license_token', '')
            self.store.set('tampered', False)
            self._license_data = {}
            self._state = STATE_INACTIVE
            self.store.log('REVOKED', 'Revoked by administrator')
        return True, "License revoked."

    # ── State ──────────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            # If a previous run flagged tamper, honour it permanently
            if self.store.get('tampered'):
                self._state = STATE_TAMPERED
                return STATE_TAMPERED
            self._evaluate_state()
            return self._state

    @property
    def is_valid(self) -> bool:
        return self.state in (STATE_ACTIVE, STATE_EXPIRING, STATE_WARNING, STATE_CRITICAL)

    @property
    def days_remaining(self) -> int:
        exp = self._license_data.get('expires_at', 0)
        if not exp: return 0
        actual_now = _fetch_trusted_time() or int(time.time())
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
        }

    def revalidate(self):
        with self._lock:
            self._load_from_store()
