"""
MBT POS — Cloudflare Tunnel Setup & Diagnostics
MugoByte Technologies | mugobyte.com

Per-shop remote dashboard: https://<shop-slug>.mugobyte.com
Used by the setup wizard, SETUP CLOUDFLARE.bat, and the embedded web service.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger('cloudflare_setup')

BASE_DOMAIN = 'mugobyte.com'
DEFAULT_PORT = 5050
_CF_RELEASE = 'https://github.com/cloudflare/cloudflared/releases/latest/download'


def _cloudflared_download_url() -> tuple[str, str]:
    """Return (download_url, local_filename) for this OS/arch."""
    if sys.platform == 'win32':
        return f'{_CF_RELEASE}/cloudflared-windows-amd64.exe', 'cloudflared.exe'
    if sys.platform == 'darwin':
        return f'{_CF_RELEASE}/cloudflared-darwin-amd64.tgz', 'cloudflared'
    machine = (os.uname().machine if hasattr(os, 'uname') else '').lower()
    if machine in ('aarch64', 'arm64'):
        return f'{_CF_RELEASE}/cloudflared-linux-arm64', 'cloudflared'
    return f'{_CF_RELEASE}/cloudflared-linux-amd64', 'cloudflared'

LogCallback = Callable[[str, str], None]  # (level, message)

AUTH_HELP = """
Cloudflare management auth failed.

PRODUCTION (all shops — no browser on shop PCs):
  Place ONE central management API token before building the installer:

  1) dash.cloudflare.com → My Profile → API Tokens → Create Token
     Permissions: Account → Cloudflare Tunnel → Edit
                  Zone  → DNS → Edit  (zone: mugobyte.com)

  2) Put it in EITHER (same key name):
     • Source (bundled into Setup.exe):
         extracted/mbt_pos/config/deploy.local.json
         "cloudflare_api_token": "cfat_…"
     • Or live AppData override (any installed shop):
         %LOCALAPPDATA%\\MugoByte\\MBT POS\\config\\deploy.local.json
     • Or env CLOUDFLARE_API_TOKEN when running BUILD.bat

  Do NOT put a tunnel connector token (cfut_… / eyJ…) in cloudflare_api_token.

VENDOR EMERGENCY only (this PC):
  Settings → Remote Web → Vendor recovery (browser login)
  Authorize the MugoByte account / mugobyte.com zone.

Zero Trust must be active (free tier is fine).
""".strip()

VENDOR_TOKEN_MISSING = (
    'Central Cloudflare management API token is missing or invalid.\n'
    'This is a MugoByte/vendor configuration problem — not a shop cashier task.\n\n'
    'Place a real API token (Account Tunnel Edit + Zone DNS Edit) in:\n'
    '  config/deploy.local.json  (before BUILD), or\n'
    '  %LOCALAPPDATA%\\MugoByte\\MBT POS\\config\\deploy.local.json\n'
    'Key: "cloudflare_api_token"  (must NOT start with cfut_)\n\n'
    'After that, every shop auto-provisions {shop}.mugobyte.com on launch.'
)


# ── Paths ─────────────────────────────────────────────────────────────────────

def _project_root() -> Path:
    try:
        from mbt_paths import get_project_root, ensure_data_dirs
        return Path(ensure_data_dirs(get_project_root()))
    except Exception:
        return Path(__file__).resolve().parent.parent


def _exe_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return _project_root()


def get_config_path() -> Path:
    return _project_root() / 'config' / 'web_config.json'


def get_config_fallback_path() -> Path:
    """Sibling fallback when primary web_config.json is locked/read-only."""
    return _project_root() / 'config' / 'web_config.user.json'


def get_log_path() -> Path:
    p = _project_root() / 'logs' / 'cloudflare_setup.log'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_writable_dir(path: Path) -> None:
    """Create config (or other) dir with user-writable permissions when possible."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == 'win32':
            # Clear directory read-only if present (FILE_ATTRIBUTE_READONLY = 1)
            import ctypes
            FILE_ATTRIBUTE_NORMAL = 0x80
            ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_NORMAL)
        else:
            os.chmod(path, 0o755)
    except Exception:
        pass


def _clear_readonly(path: Path) -> bool:
    """Clear Windows read-only attribute / Unix write bit. Returns True if cleared."""
    if not path.exists():
        return False
    cleared = False
    try:
        if sys.platform == 'win32':
            import ctypes
            FILE_ATTRIBUTE_READONLY = 0x1
            FILE_ATTRIBUTE_NORMAL = 0x80
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1 and (attrs & FILE_ATTRIBUTE_READONLY):
                ctypes.windll.kernel32.SetFileAttributesW(
                    str(path), (attrs & ~FILE_ATTRIBUTE_READONLY) or FILE_ATTRIBUTE_NORMAL)
                cleared = True
            # Also via attrib / os.chmod as belt-and-suspenders
            try:
                subprocess.run(
                    ['attrib', '-R', str(path)],
                    capture_output=True, timeout=10,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                cleared = True
            except Exception:
                pass
        mode = path.stat().st_mode
        if not (mode & 0o200):
            os.chmod(path, mode | 0o200)
            cleared = True
    except Exception as e:
        logger.debug('clear readonly %s: %s', path, e)
    return cleared


def _atomic_write_json(path: Path, data: dict) -> Path:
    """
    Atomically write JSON under AppData config with read-only / lock resilience.
    On hard PermissionError: retry after clearing RO, unlink+rewrite, then sibling
    fallback web_config.user.json. Never raises — logs WARNING if all paths fail.
    Returns the path actually written (or the intended path on total failure).
    """
    payload = json.dumps(data, indent=2).encode('utf-8') + b'\n'
    _ensure_writable_dir(path.parent)

    def _try_write(target: Path) -> bool:
        tmp = target.with_suffix(target.suffix + '.tmp')
        try:
            if target.exists():
                _clear_readonly(target)
            if tmp.exists():
                _clear_readonly(tmp)
                try:
                    tmp.unlink()
                except Exception:
                    pass
            tmp.write_bytes(payload)
            os.replace(str(tmp), str(target))
            return True
        except PermissionError:
            # Clean up tmp if replace failed mid-way
            try:
                if tmp.is_file():
                    tmp.unlink()
            except Exception:
                pass
            raise
        except OSError:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except Exception:
                pass
            raise

    # Attempt 1: normal atomic write
    try:
        if _try_write(path):
            return path
    except PermissionError as e1:
        logger.warning('web_config write PermissionError (will retry): %s — %s', path, e1)
    except OSError as e1:
        logger.warning('web_config write failed (will retry): %s — %s', path, e1)

    # Attempt 2: clear RO again + retry
    try:
        _clear_readonly(path)
        if _try_write(path):
            return path
    except (PermissionError, OSError) as e2:
        logger.warning('web_config write retry failed: %s — %s', path, e2)

    # Attempt 3: unlink then write (recreate)
    try:
        if path.exists():
            _clear_readonly(path)
            path.unlink()
        if _try_write(path):
            return path
    except (PermissionError, OSError) as e3:
        logger.warning('web_config unlink+write failed: %s — %s', path, e3)

    # Attempt 4: sibling fallback (keeps Cloudflare setup working)
    fallback = get_config_fallback_path() if path.name == 'web_config.json' else (
        path.with_suffix('.user' + path.suffix)
    )
    try:
        _ensure_writable_dir(fallback.parent)
        if _try_write(fallback):
            logger.warning(
                'Primary config unwritable (%s); wrote fallback %s. '
                'Clear read-only or take ownership of the primary file so updates merge cleanly.',
                path, fallback)
            return fallback
    except (PermissionError, OSError) as e4:
        logger.warning(
            'All config writes failed for %s (and fallback %s): %s. '
            'Remediation: remove read-only from the file/folder, or delete it and restart MBT POS. '
            'Path: %s',
            path, fallback, e4, path)
        return path

    logger.warning(
        'Could not persist config to %s. Remediation: clear read-only on '
        '%%LOCALAPPDATA%%\\MugoByte\\MBT POS\\config\\ and restart MBT POS.',
        path)
    return path


def get_legacy_cloudflared_dir() -> Path:
    """cloudflared's default home dir (login/create still write here)."""
    d = Path.home() / '.cloudflared'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cloudflared_dir() -> Path:
    """
    Durable AppData cloudflared state (survives reinstall of Program Files).
    Path: %LOCALAPPDATA%\\MugoByte\\MBT POS\\cloudflared\\ when installed.
    """
    d = _project_root() / 'cloudflared'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_if_missing(src: Path, dst: Path) -> bool:
    try:
        if src.is_file() and not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
    except Exception as e:
        logger.warning('cloudflared copy %s → %s failed: %s', src, dst, e)
    return False


def sync_cloudflared_state() -> None:
    """
    Keep AppData + ~/.cloudflared in sync so login/create artifacts persist
    across reinstalls and are found on every launch.
    """
    app = get_cloudflared_dir()
    home = get_legacy_cloudflared_dir()
    # Pull from home → AppData (source of truth for durability)
    for name in ('cert.pem', 'config.yml'):
        _copy_if_missing(home / name, app / name)
        _copy_if_missing(app / name, home / name)
    for src in list(home.glob('*.json')) + list(app.glob('*.json')):
        other = (app if src.parent == home else home) / src.name
        _copy_if_missing(src, other)
    # Backup credentials + config into config/ for extra durability
    # Skip restoring config.yml from backup when connector-token mode is active
    # (old marker/config would force a broken credentials-file launch).
    token_mode = False
    try:
        token_mode = bool(_get_tunnel_run_token())
    except Exception:
        token_mode = False
    try:
        backup = _project_root() / 'config' / 'cloudflared_backup'
        backup.mkdir(parents=True, exist_ok=True)
        for name in ('cert.pem', 'config.yml'):
            if name == 'config.yml' and token_mode:
                continue
            _copy_if_missing(app / name, backup / name)
        for src in app.glob('*.json'):
            _copy_if_missing(src, backup / src.name)
        # Restore from backup if AppData empty but backup exists
        for name in ('cert.pem', 'config.yml'):
            if name == 'config.yml' and token_mode:
                continue
            _copy_if_missing(backup / name, app / name)
            _copy_if_missing(backup / name, home / name)
        for src in backup.glob('*.json'):
            _copy_if_missing(src, app / src.name)
            _copy_if_missing(src, home / src.name)
    except Exception as e:
        logger.warning('cloudflared backup sync: %s', e)


def _credentials_file_for(tunnel_id: str, tunnel_name: str = '') -> Optional[Path]:
    """Locate tunnel credentials JSON in AppData, home, or backup."""
    names = []
    if tunnel_id:
        names.append(f'{tunnel_id}.json')
    if tunnel_name:
        names.append(f'{tunnel_name}.json')
    dirs = (
        get_cloudflared_dir(),
        get_legacy_cloudflared_dir(),
        _project_root() / 'config' / 'cloudflared_backup',
    )
    for d in dirs:
        for name in names:
            p = d / name
            if p.is_file() and p.stat().st_size > 50:
                return p
    return None


def _cloudflared_bin() -> Path:
    """Writable location for cloudflared binary in the project folder."""
    _, name = _cloudflared_download_url()
    return _project_root() / name


def _bundled_cloudflared_path() -> Optional[Path]:
    """cloudflared shipped inside MBT_POS.exe or next to the installer."""
    if getattr(sys, 'frozen', False):
        bundled = Path(sys._MEIPASS) / 'cloudflared.exe'
        if bundled.is_file():
            return bundled
    for candidate in (
        _project_root() / 'tools' / 'cloudflared.exe',
        _exe_dir() / 'cloudflared.exe',
    ):
        if candidate.is_file():
            return candidate
    return None


def bootstrap_cloudflared() -> Optional[Path]:
    """Copy bundled cloudflared into AppData (no network). Called at app start."""
    sync_cloudflared_state()
    normalize_cloudflare_tokens()
    dest = _cloudflared_bin()
    if dest.is_file():
        return dest
    bundled = _bundled_cloudflared_path()
    if not bundled:
        return None
    try:
        shutil.copy2(bundled, dest)
        if sys.platform != 'win32':
            dest.chmod(0o755)
        save_web_config({'cloudflared_exe': str(dest)})
        logger.info('Installed bundled cloudflared → %s', dest)
        return dest
    except Exception as e:
        logger.warning('Could not copy bundled cloudflared: %s', e)
        return bundled if bundled.is_file() else None


def find_cloudflared_exe() -> Optional[Path]:
    cfg = load_web_config()
    if cfg.get('cloudflared_exe'):
        p = Path(cfg['cloudflared_exe'])
        if p.is_file():
            return p
    candidates = [
        _cloudflared_bin(),
        _exe_dir() / 'cloudflared.exe',
        _exe_dir() / 'cloudflared',
    ]
    bundled = _bundled_cloudflared_path()
    if bundled:
        candidates.insert(0, bundled)
    candidates.extend([
        Path('/usr/local/bin/cloudflared'),
        Path('/usr/bin/cloudflared'),
        Path(r'C:\Program Files\cloudflared\cloudflared.exe'),
    ])
    for c in candidates:
        if c.is_file():
            return c
    return None


# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_CFG = {
    'flask_port': DEFAULT_PORT,
    'flask_host': '0.0.0.0',
    'base_domain': BASE_DOMAIN,
    'tunnel_domain': '',
    'tunnel_name': '',
    'tunnel_subdomain': '',
    'tunnel_id': '',
    'remote_enabled': False,
    'remote_setup_ok': False,
    'remote_setup_at': '',
    'cloudflared_exe': '',
    'cloudflare_api_token': '',
    'cloudflare_tunnel_token': '',
    'check_interval': 30,
    'max_restarts': 50,
}


def load_web_config() -> dict:
    path = get_config_path()
    fallback = get_config_fallback_path()
    cfg = dict(_DEFAULT_CFG)
    # Load oldest → newest so a newer fallback (written when primary was RO) wins
    candidates: list[Path] = []
    for candidate in (path, fallback):
        if candidate.is_file():
            candidates.append(candidate)
    try:
        candidates.sort(key=lambda p: p.stat().st_mtime)
    except Exception:
        pass
    loaded = False
    for candidate in candidates:
        try:
            with open(candidate, encoding='utf-8-sig') as f:
                cfg.update(json.load(f))
            loaded = True
            if candidate == fallback and path.is_file():
                logger.debug('Merged web_config fallback %s', fallback)
        except Exception as e:
            logger.warning('web_config read failed (%s): %s', candidate, e)
    if candidates and not loaded:
        logger.warning('web_config read failed for all candidates')
    # If subdomain empty, derive from shop name in the live database
    if not (cfg.get('tunnel_subdomain') or '').strip():
        shop = _read_shop_name_from_db()
        if shop:
            sub = shop_to_subdomain(shop)
            cfg['tunnel_subdomain'] = sub
            cfg['tunnel_domain'] = full_domain(sub)
            cfg['tunnel_name'] = tunnel_name_for(sub)
    return cfg


def _read_shop_name_from_db() -> str:
    try:
        from mbt_paths import get_db_path
        import sqlite3
        db_path = get_db_path()
        if not os.path.exists(db_path):
            return ''
        db = sqlite3.connect(db_path)
        row = db.execute(
            "SELECT value FROM system_settings WHERE key='shop_name'"
        ).fetchone()
        db.close()
        return (row[0] or '').strip() if row else ''
    except Exception:
        return ''


def save_web_config(updates: dict) -> Path:
    path = get_config_path()
    cfg = load_web_config()
    cfg.update(updates)
    # Never write UTF-8 BOM (PowerShell -Encoding UTF8 breaks older readers)
    return _atomic_write_json(path, cfg)


# ── Naming ────────────────────────────────────────────────────────────────────

def shop_to_subdomain(shop_name: str) -> str:
    """Turn shop name into a DNS-safe subdomain slug."""
    s = (shop_name or '').strip().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    if not s:
        s = 'mbt-shop'
    if s[0].isdigit():
        s = 'shop-' + s
    return s[:40].rstrip('-')


def full_domain(subdomain: str) -> str:
    sub = (subdomain or '').strip().lower().strip('.')
    if not sub:
        return ''
    if sub.endswith('.' + BASE_DOMAIN):
        return sub
    return f'{sub}.{BASE_DOMAIN}'


def tunnel_name_for(subdomain: str) -> str:
    slug = shop_to_subdomain(subdomain)
    return f'mbt-pos-{slug}'[:63]


# ── Logging helper ────────────────────────────────────────────────────────────

class _SetupLog:
    def __init__(self, callback: Optional[LogCallback] = None):
        self._cb = callback
        self._file = get_log_path()
        self.lines: list[str] = []

    def write(self, level: str, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        line = f'[{ts}] [{level.upper()}] {msg}'
        self.lines.append(line)
        logger.log(
            logging.ERROR if level == 'error' else logging.INFO, msg)
        try:
            with open(self._file, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass
        if self._cb:
            try:
                self._cb(level, msg)
            except Exception:
                pass

    def info(self, msg): self.write('info', msg)
    def warn(self, msg): self.write('warn', msg)
    def error(self, msg): self.write('error', msg)
    def ok(self, msg): self.write('ok', msg)


# ── Shell helpers ─────────────────────────────────────────────────────────────

def _hide_flags() -> int:
    if sys.platform == 'win32':
        return 0x08000000  # CREATE_NO_WINDOW
    return 0


def _is_tunnel_run_token(tok: str) -> bool:
    """
    Connector token for `cloudflared tunnel run --token`.
    Formats: cfut_… (legacy) or eyJ… JWT from Cloudflare tunnel token API.
    """
    t = (tok or '').strip()
    if not t:
        return False
    if t.lower().startswith('cfut_'):
        return True
    # GET /accounts/.../cfd_tunnel/{id}/token returns a JWT
    if t.startswith('eyJ') and len(t) >= 40:
        return True
    return False


def _looks_like_management_api_token(tok: str) -> bool:
    """True if token is usable as CLOUDFLARE_API_TOKEN (not a tunnel-run token)."""
    t = (tok or '').strip()
    if not t or _is_tunnel_run_token(t):
        return False
    return len(t) >= 20


def _token_from_sources() -> str:
    """Raw token from web_config / deploy.local / env (any type). Prefer management."""
    candidates = []
    cfg = load_web_config()
    candidates.append((cfg.get('cloudflare_api_token') or '').strip())
    candidates.append((cfg.get('cloudflare_management_token') or '').strip())
    try:
        from config.deploy import load_deploy_config
        dep = load_deploy_config()
        candidates.append((dep.get('cloudflare_api_token') or '').strip())
        candidates.append((dep.get('cloudflare_management_token') or '').strip())
    except Exception:
        pass
    candidates.append(os.environ.get('CLOUDFLARE_API_TOKEN', '').strip())
    # Prefer a real management token if any source has one
    for tok in candidates:
        if _looks_like_management_api_token(tok):
            return tok
    for tok in candidates:
        if tok:
            return tok
    return ''


def _get_cloudflare_api_token() -> str:
    """Management API token only — never returns tunnel-run tokens (cfut_/JWT)."""
    candidates = []
    cfg = load_web_config()
    candidates.append((cfg.get('cloudflare_api_token') or '').strip())
    candidates.append((cfg.get('cloudflare_management_token') or '').strip())
    try:
        from config.deploy import load_deploy_config
        dep = load_deploy_config()
        candidates.append((dep.get('cloudflare_api_token') or '').strip())
        candidates.append((dep.get('cloudflare_management_token') or '').strip())
    except Exception:
        pass
    candidates.append(os.environ.get('CLOUDFLARE_API_TOKEN', '').strip())
    for tok in candidates:
        if _looks_like_management_api_token(tok):
            return tok
    return ''


def _get_tunnel_run_token() -> str:
    """Named-tunnel connector token for `cloudflared tunnel run --token`."""
    cfg = load_web_config()
    for key in ('cloudflare_tunnel_token', 'cloudflare_api_token'):
        tok = (cfg.get(key) or '').strip()
        if _is_tunnel_run_token(tok):
            return tok
    try:
        from config.deploy import load_deploy_config
        dep = load_deploy_config()
        for key in ('cloudflare_tunnel_token', 'cloudflare_api_token'):
            tok = (dep.get(key) or '').strip()
            if _is_tunnel_run_token(tok):
                return tok
    except Exception:
        pass
    env = os.environ.get('TUNNEL_TOKEN', '').strip()
    if _is_tunnel_run_token(env):
        return env
    return ''


def normalize_cloudflare_tokens() -> None:
    """
    One-time cleanup: cfut_ must not live in cloudflare_api_token.
    That mis-filing caused silent auth loops (tunnel list → cert.pem missing).
    """
    try:
        cfg = load_web_config()
        api = (cfg.get('cloudflare_api_token') or '').strip()
        run = (cfg.get('cloudflare_tunnel_token') or '').strip()
        updates = {}
        if _is_tunnel_run_token(api):
            if not _is_tunnel_run_token(run):
                updates['cloudflare_tunnel_token'] = api
            updates['cloudflare_api_token'] = ''
            logger.warning(
                'Moved cfut_ token out of cloudflare_api_token '
                '(it is a tunnel-run token, not a management API token)')
        if updates:
            save_web_config(updates)
        # Same cleanup for AppData deploy.local.json
        try:
            dep_path = _project_root() / 'config' / 'deploy.local.json'
            if dep_path.is_file():
                with open(dep_path, encoding='utf-8-sig') as f:
                    dep = json.load(f)
                d_api = (dep.get('cloudflare_api_token') or '').strip()
                if _is_tunnel_run_token(d_api):
                    if not (dep.get('cloudflare_tunnel_token') or '').strip():
                        dep['cloudflare_tunnel_token'] = d_api
                    dep['cloudflare_api_token'] = ''
                    _atomic_write_json(dep_path, dep)
                    logger.warning('Cleaned cfut_ from AppData deploy.local.json')
        except Exception as e:
            logger.warning('deploy.local token cleanup: %s', e)
    except Exception as e:
        logger.warning('normalize_cloudflare_tokens: %s', e)


# ── Cloudflare REST API (shop auto-provision — no browser / no cert.pem) ──────

_CF_API = 'https://api.cloudflare.com/client/v4'
_cf_account_cache: str = ''
_cf_zone_cache: str = ''


def _subprocess_env() -> dict:
    env = os.environ.copy()
    # Never pass a tunnel-run token as CLOUDFLARE_API_TOKEN — cloudflared
    # ignores it and then fails looking for cert.pem.
    api = _get_cloudflare_api_token()
    if api:
        env['CLOUDFLARE_API_TOKEN'] = api
    else:
        env.pop('CLOUDFLARE_API_TOKEN', None)
    cert = get_cloudflared_dir() / 'cert.pem'
    if not cert.is_file():
        cert = get_legacy_cloudflared_dir() / 'cert.pem'
    if cert.is_file():
        env['TUNNEL_ORIGIN_CERT'] = str(cert)
    return env


def _is_auth_error(text: str) -> bool:
    t = (text or '').lower()
    return any(x in t for x in (
        'authentication error', 'unauthorized', 'code: 10000',
        'code":10000', 'rest request failed: unauthorized',
        'provided tunnel token is not valid',
        'error locating origin cert',
    ))


def _cf_api(
    method: str,
    path: str,
    body: Optional[dict] = None,
    timeout: int = 45,
) -> dict:
    """Call Cloudflare v4 API with the management token. Raises RuntimeError."""
    token = _get_cloudflare_api_token()
    if not token:
        raise RuntimeError(VENDOR_TOKEN_MISSING)
    url = path if path.startswith('http') else f'{_CF_API}{path}'
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'MBT-POS/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        err_body = ''
        try:
            err_body = e.read().decode('utf-8', errors='replace')
        except Exception:
            err_body = str(e)
        raise RuntimeError(
            f'Cloudflare API {method} {path}: HTTP {e.code}\n{err_body[:500]}'
        ) from e
    except Exception as e:
        raise RuntimeError(f'Cloudflare API {method} {path}: {e}') from e
    if not payload.get('success', True):
        errs = payload.get('errors') or payload.get('messages') or payload
        raise RuntimeError(f'Cloudflare API {method} {path} failed: {errs}')
    return payload


def _cf_account_id() -> str:
    global _cf_account_cache
    if _cf_account_cache:
        return _cf_account_cache
    try:
        from config.deploy import load_deploy_config
        pinned = (
            os.environ.get('CLOUDFLARE_ACCOUNT_ID', '').strip()
            or (load_deploy_config().get('cloudflare_account_id') or '').strip()
        )
        if pinned:
            _cf_account_cache = pinned
            return pinned
    except Exception:
        pass
    data = _cf_api('GET', '/accounts?per_page=50')
    accounts = data.get('result') or []
    if not accounts:
        raise RuntimeError('Cloudflare API token has no accessible accounts')
    _cf_account_cache = accounts[0]['id']
    return _cf_account_cache


def _cf_zone_id(zone_name: str = BASE_DOMAIN) -> str:
    global _cf_zone_cache
    if _cf_zone_cache:
        return _cf_zone_cache
    try:
        from config.deploy import load_deploy_config
        pinned = (
            os.environ.get('CLOUDFLARE_ZONE_ID', '').strip()
            or (load_deploy_config().get('cloudflare_zone_id') or '').strip()
        )
        if pinned:
            _cf_zone_cache = pinned
            return pinned
    except Exception:
        pass
    q = urllib.parse.quote(zone_name)
    data = _cf_api('GET', f'/zones?name={q}')
    zones = data.get('result') or []
    if not zones:
        raise RuntimeError(
            f'Zone {zone_name} not found — token needs Zone DNS Edit on {zone_name}')
    _cf_zone_cache = zones[0]['id']
    return _cf_zone_cache


def verify_management_api_token(log: Optional[_SetupLog] = None) -> tuple[bool, str]:
    """Prove management token works (accounts list) — no cloudflared/cert needed."""
    if not _get_cloudflare_api_token():
        raw = _token_from_sources()
        if _is_tunnel_run_token(raw):
            msg = (
                'Stored token is a tunnel-run token (cfut_/JWT), not a management '
                'API token. Put a cfat_… token in deploy.local.json.')
            if log:
                log.warn(msg)
            return False, msg
        return False, 'No management API token configured'
    try:
        aid = _cf_account_id()
        msg = f'API auth OK (account {aid[:8]}…)'
        if log:
            log.ok(msg)
        return True, msg
    except Exception as e:
        return False, str(e)


def _api_find_tunnel(account_id: str, name: str) -> Optional[dict]:
    q = urllib.parse.quote(name)
    data = _cf_api(
        'GET',
        f'/accounts/{account_id}/cfd_tunnel?name={q}&is_deleted=false',
    )
    results = data.get('result') or []
    for t in results:
        if t.get('name') == name:
            return t
    return results[0] if results else None


def _api_create_or_get_tunnel(
    account_id: str,
    name: str,
    log: Optional[_SetupLog] = None,
) -> dict:
    existing = _api_find_tunnel(account_id, name)
    if existing:
        if log:
            log.ok(f'Reusing tunnel "{name}" ({existing.get("id", "")[:8]}…)')
        return existing
    data = _cf_api(
        'POST',
        f'/accounts/{account_id}/cfd_tunnel',
        {'name': name, 'config_src': 'cloudflare'},
    )
    tunnel = data.get('result') or {}
    if log:
        log.ok(f'Created tunnel "{name}" ({(tunnel.get("id") or "")[:8]}…)')
    return tunnel


def _api_put_ingress(
    account_id: str,
    tunnel_id: str,
    hostname: str,
    port: int,
    log: Optional[_SetupLog] = None,
) -> None:
    _cf_api(
        'PUT',
        f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations',
        {
            'config': {
                'ingress': [
                    {
                        'hostname': hostname,
                        'service': f'http://127.0.0.1:{port}',
                    },
                    {'service': 'http_status:404'},
                ],
            }
        },
    )
    if log:
        log.ok(f'Remote ingress → {hostname} → 127.0.0.1:{port}')


def _api_ensure_dns_cname(
    zone_id: str,
    hostname: str,
    tunnel_id: str,
    log: Optional[_SetupLog] = None,
) -> None:
    target = f'{tunnel_id}.cfargotunnel.com'
    q = urllib.parse.quote(hostname)
    data = _cf_api('GET', f'/zones/{zone_id}/dns_records?name={q}&type=CNAME')
    records = data.get('result') or []
    body = {
        'type': 'CNAME',
        'name': hostname,
        'content': target,
        'proxied': True,
        'ttl': 1,
    }
    if records:
        rid = records[0]['id']
        cur = (records[0].get('content') or '').strip().rstrip('.')
        if cur.lower() == target.lower() and records[0].get('proxied', True):
            if log:
                log.ok(f'DNS already OK → {hostname}')
            return
        _cf_api('PUT', f'/zones/{zone_id}/dns_records/{rid}', body)
        if log:
            log.ok(f'DNS updated → {hostname} → {target}')
        return
    _cf_api('POST', f'/zones/{zone_id}/dns_records', body)
    if log:
        log.ok(f'DNS created → {hostname} → {target}')


def _api_tunnel_run_token(account_id: str, tunnel_id: str) -> str:
    data = _cf_api('GET', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token')
    tok = (data.get('result') or '').strip()
    if isinstance(data.get('result'), dict):
        tok = (data['result'].get('token') or '').strip()
    if not tok:
        raise RuntimeError('Cloudflare returned empty tunnel connector token')
    return tok


def provision_shop_tunnel_via_api(
    subdomain: str,
    port: int = DEFAULT_PORT,
    log: Optional[_SetupLog] = None,
) -> dict:
    """
    Zero-browser shop provisioning:
      create/reuse named tunnel → remote ingress → DNS CNAME → connector token.
    Persists token + tunnel ids in AppData web_config (survives Program Files reinstall).
    """
    slug = shop_to_subdomain(subdomain)
    domain = full_domain(slug)
    tname = tunnel_name_for(slug)
    if log:
        log.info(f'API provision for https://{domain} (tunnel {tname})')

    ok, detail = verify_management_api_token(log)
    if not ok:
        raise RuntimeError(f'{detail}\n\n{VENDOR_TOKEN_MISSING}')

    account_id = _cf_account_id()
    zone_id = _cf_zone_id(BASE_DOMAIN)
    tunnel = _api_create_or_get_tunnel(account_id, tname, log)
    tunnel_id = (tunnel.get('id') or '').strip()
    if not tunnel_id:
        raise RuntimeError(f'Tunnel create/list returned no id for {tname}')

    _api_put_ingress(account_id, tunnel_id, domain, port, log)
    _api_ensure_dns_cname(zone_id, domain, tunnel_id, log)
    run_tok = _api_tunnel_run_token(account_id, tunnel_id)

    # Durable AppData marker so status UI knows tunnel is configured
    cfdir = get_cloudflared_dir()
    marker = (
        f'# Managed by MBT POS API provision — run via connector token\n'
        f'tunnel: {tunnel_id}\n'
        f'ingress:\n'
        f'  - hostname: {domain}\n'
        f'    service: http://127.0.0.1:{port}\n'
        f'  - service: http_status:404\n'
    )
    (cfdir / 'config.yml').write_text(marker, encoding='utf-8')
    sync_cloudflared_state()

    save_web_config({
        'base_domain': BASE_DOMAIN,
        'tunnel_subdomain': slug,
        'tunnel_domain': domain,
        'tunnel_name': tname,
        'tunnel_id': tunnel_id,
        'remote_enabled': True,
        'cloudflare_tunnel_token': run_tok,
        # Keep management token out of web_config when it lives in deploy.local
        'remote_setup_ok': True,
        'remote_setup_at': datetime.now().isoformat(),
    })
    if log:
        log.ok(f'Persisted connector token + config for {domain}')
    return {
        'ok': True,
        'tunnel_id': tunnel_id,
        'tunnel_name': tname,
        'domain': domain,
        'subdomain': slug,
        'via': 'api',
    }


def clear_cloudflare_login(log: Optional[_SetupLog] = None):
    """Remove stale origin certificate so the next login is fresh."""
    for d in (get_cloudflared_dir(), get_legacy_cloudflared_dir()):
        cert = d / 'cert.pem'
        if cert.is_file():
            try:
                cert.unlink()
                if log:
                    log.info(f'Removed stale cert.pem ({cert}) — will re-login')
            except Exception as e:
                if log:
                    log.warn(f'Could not delete cert.pem: {e}')
    bak = _project_root() / 'config' / 'cloudflared_backup' / 'cert.pem'
    if bak.is_file():
        try:
            bak.unlink()
        except Exception:
            pass


def verify_tunnel_api(cf: Path, log: Optional[_SetupLog] = None) -> tuple[bool, str]:
    """True if management API works (REST first, else cloudflared tunnel list)."""
    if _get_cloudflare_api_token():
        return verify_management_api_token(log)
    raw = _token_from_sources()
    if _is_tunnel_run_token(raw):
        msg = (
            'Stored token is a tunnel-run token (cfut_/JWT), not a management API token. '
            'Put a real API token in deploy.local.json (vendor).')
        if log:
            log.warn(msg)
        return False, msg
    if not cf:
        return False, 'cloudflared missing'
    r = _run([str(cf), 'tunnel', 'list', '-o', 'json'], timeout=90)
    out = ((r.stdout or '') + (r.stderr or '')).strip()
    if r.returncode == 0:
        try:
            json.loads(r.stdout or '[]')
            return True, 'API auth OK'
        except json.JSONDecodeError:
            return True, 'tunnel list OK'
    if _is_auth_error(out):
        return False, out
    if r.returncode != 0:
        return False, out or f'exit code {r.returncode}'
    return True, 'OK'


def ensure_cloudflare_auth(
    cf: Path,
    log: _SetupLog,
    force_relogin: bool = False,
    allow_browser: Optional[bool] = None,
) -> None:
    """
    Prefer management API token (automatic, all shops).
    Browser login only when allow_browser=True (vendor emergency / --relogin).
    """
    if allow_browser is None:
        allow_browser = bool(force_relogin)

    if force_relogin:
        clear_cloudflare_login(log)

    sync_cloudflared_state()
    has_token = bool(_get_cloudflare_api_token())
    raw = _token_from_sources()
    if _is_tunnel_run_token(raw) and not has_token:
        log.warn(
            'Ignoring tunnel-run token for management auth — need a management '
            'API token (Account Tunnel Edit + Zone DNS Edit) in deploy.local.json.')

    if has_token:
        ok, detail = verify_management_api_token(log)
        if ok:
            log.ok('Cloudflare API token verified')
            return
        raise RuntimeError(
            f'Cloudflare API token was rejected:\n{detail}\n\n'
            'Fix deploy.local.json (or AppData config/deploy.local.json):\n'
            '  Permissions: Account → Cloudflare Tunnel → Edit\n'
            '               Zone → DNS → Edit (mugobyte.com)\n'
            '  Do NOT use a cfut_… / JWT tunnel connector token here.')

    # Existing cert.pem from a prior vendor login — usable without browser
    if has_cloudflare_login() and not force_relogin:
        ok, detail = verify_tunnel_api(cf, log)
        if ok:
            log.ok('Cloudflare cert.pem auth verified')
            sync_cloudflared_state()
            return
        log.warn(f'Existing cert.pem rejected: {detail[:200]}')
        if not allow_browser:
            clear_cloudflare_login(log)
            raise RuntimeError(VENDOR_TOKEN_MISSING + '\n\n' + AUTH_HELP)

    if not allow_browser:
        raise RuntimeError(VENDOR_TOKEN_MISSING)

    if has_cloudflare_login() and force_relogin:
        clear_cloudflare_login(log)

    if not has_cloudflare_login():
        log.info(
            'VENDOR recovery — opening browser for MugoByte Cloudflare account / '
            f'zone {BASE_DOMAIN}')
        r = _run([str(cf), 'tunnel', 'login'], timeout=300, visible=True)
        sync_cloudflared_state()
        if r.returncode != 0 or not has_cloudflare_login():
            raise RuntimeError(
                'Cloudflare login failed or was cancelled.\n'
                f'{r.stderr or r.stdout or ""}\n\n{AUTH_HELP}')

    ok, detail = verify_tunnel_api(cf, log)
    if ok:
        log.ok('Cloudflare API auth verified')
        sync_cloudflared_state()
        return

    raise RuntimeError(
        f'Cloudflare tunnel API still unauthorized:\n{detail}\n\n{AUTH_HELP}')


def _run(
    args: list,
    timeout: int = 180,
    visible: bool = False,
) -> subprocess.CompletedProcess:
    flags = 0 if visible else _hide_flags()
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=flags,
        cwd=str(_exe_dir()),
        env=_subprocess_env(),
    )


def is_online() -> bool:
    for host, port in (('1.1.1.1', 53), ('8.8.8.8', 53)):
        try:
            s = socket.create_connection((host, port), timeout=3)
            s.close()
            return True
        except OSError:
            pass
    return False


def has_cloudflare_login() -> bool:
    for d in (get_cloudflared_dir(), get_legacy_cloudflared_dir()):
        cert = d / 'cert.pem'
        if cert.is_file() and cert.stat().st_size > 100:
            return True
    bak = _project_root() / 'config' / 'cloudflared_backup' / 'cert.pem'
    return bak.is_file() and bak.stat().st_size > 100


def download_cloudflared(log: _SetupLog) -> Path:
    existing = find_cloudflared_exe()
    if existing:
        log.ok(f'cloudflared already present: {existing}')
        return existing
    bundled = bootstrap_cloudflared()
    if bundled and bundled.is_file():
        log.ok(f'Using bundled cloudflared: {bundled}')
        return bundled
    url, _ = _cloudflared_download_url()
    dest = _cloudflared_bin()
    log.info('Downloading cloudflared…')
    try:
        urllib.request.urlretrieve(url, str(dest))
    except Exception as e:
        raise RuntimeError(
            f'Download failed: {e}\n'
            f'Manual fix: install cloudflared to {dest} or /usr/local/bin/cloudflared'
        ) from e
    if not dest.is_file():
        raise RuntimeError('cloudflared download did not create the file')
    if sys.platform != 'win32':
        dest.chmod(0o755)
    log.ok(f'Downloaded cloudflared → {dest}')
    save_web_config({'cloudflared_exe': str(dest)})
    return dest


def _tunnel_id_by_name(cf: Path, name: str, log: _SetupLog) -> Optional[str]:
    r = _run([str(cf), 'tunnel', 'list', '-o', 'json'], timeout=60)
    if r.returncode != 0:
        log.warn(f'tunnel list failed: {r.stderr or r.stdout}')
        return None
    try:
        tunnels = json.loads(r.stdout or '[]')
    except json.JSONDecodeError:
        return None
    for t in tunnels:
        if t.get('name') == name:
            return t.get('id')
    return None


def _write_cloudflared_config(
    tunnel_name: str,
    tunnel_id: str,
    hostname: str,
    port: int,
    log: Optional[_SetupLog] = None,
) -> Path:
    sync_cloudflared_state()
    cfdir = get_cloudflared_dir()
    cred = _credentials_file_for(tunnel_id, tunnel_name)
    if cred is None:
        # Prefer AppData path even if file not yet present (create just wrote to home)
        sync_cloudflared_state()
        cred = _credentials_file_for(tunnel_id, tunnel_name)
    if cred is None:
        cred = cfdir / f'{tunnel_id}.json'
        if log:
            log.warn(
                f'Credentials file not found at {cred} — '
                'tunnel may fail until cloudflared creates it')
    else:
        # Ensure AppData has a durable copy
        app_cred = cfdir / f'{tunnel_id}.json'
        if cred.resolve() != app_cred.resolve():
            try:
                shutil.copy2(cred, app_cred)
                cred = app_cred
            except Exception:
                pass

    body = (
        f'tunnel: {tunnel_id}\n'
        f'credentials-file: {cred}\n'
        f'ingress:\n'
        f'  - hostname: {hostname}\n'
        f'    service: http://localhost:{port}\n'
        f'  - service: http_status:404\n'
    )
    # Write to AppData (primary) and ~/.cloudflared (cloudflared defaults)
    for dest_dir in (cfdir, get_legacy_cloudflared_dir()):
        cfg_path = dest_dir / 'config.yml'
        cfg_path.write_text(body, encoding='utf-8')
    sync_cloudflared_state()
    cfg_path = cfdir / 'config.yml'
    if log:
        log.ok(f'Wrote {cfg_path}')
    logger.info('cloudflared config.yml -> %s (%s)', hostname, tunnel_id)
    return cfg_path


def ensure_remote_ingress_port(
    port: Optional[int] = None,
    log: Optional[_SetupLog] = None,
) -> bool:
    """
    Push Cloudflare remote ingress to http://127.0.0.1:{flask_port}.
    Critical for token-mode tunnels: connector config is remote; local config.yml
    is ignored. Without this, a one-off 5051 workaround can leave edmus on 502
    after the workaround stops.
    """
    cfg = load_web_config()
    domain = (cfg.get('tunnel_domain') or '').strip()
    tunnel_id = (cfg.get('tunnel_id') or '').strip() or _config_yml_tunnel_id()
    if not domain or not tunnel_id:
        return False
    if not _get_cloudflare_api_token():
        return False
    try:
        account_id = _cf_account_id()
        use_port = int(port if port is not None else cfg.get('flask_port', DEFAULT_PORT))
        _api_put_ingress(account_id, tunnel_id, domain, use_port, log)
        logger.info('Ensured remote ingress %s → 127.0.0.1:%s', domain, use_port)
        return True
    except Exception as e:
        logger.warning('ensure_remote_ingress_port failed: %s', e)
        if log:
            log.warn(f'Could not sync remote ingress: {e}')
        return False


def sync_tunnel_config_from_web(log: Optional[_SetupLog] = None) -> bool:
    """
    Align AppData cloudflared/config.yml with web_config.json.
    Fixes shops where web_config was updated but config.yml still points elsewhere.
    Prefer existing local credentials — do not require live API if already configured.
    """
    cfg = load_web_config()
    if not cfg.get('remote_enabled'):
        return False
    domain = (cfg.get('tunnel_domain') or '').strip()
    tname = (cfg.get('tunnel_name') or '').strip()
    if not domain or not tname:
        if log:
            log.warn('Remote enabled but tunnel_domain/tunnel_name missing')
        return False
    # Connector-token path: still push remote ingress to flask_port (config.yml unused)
    if _get_tunnel_run_token():
        ensure_remote_ingress_port(log=log)
        return True
    sync_cloudflared_state()
    tid = (cfg.get('tunnel_id') or '').strip() or _config_yml_tunnel_id()
    if tid and _credentials_file_for(tid, tname):
        port = int(cfg.get('flask_port', DEFAULT_PORT))
        _write_cloudflared_config(tname, tid, domain, port, log)
        save_web_config({'tunnel_id': tid})
        return True
    cf = find_cloudflared_exe()
    if not cf:
        return False
    # Only hit the API when we lack local credentials
    if not tid and (_get_cloudflare_api_token() or has_cloudflare_login()):
        found = _tunnel_id_by_name(cf, tname, log or _SetupLog())
        if not found:
            sub = cfg.get('tunnel_subdomain', '')
            alt_name = tunnel_name_for(sub) if sub else ''
            if alt_name and alt_name != tname:
                found = _tunnel_id_by_name(cf, alt_name, log or _SetupLog())
                if found:
                    tname = alt_name
        if found:
            tid = found
    if not tid:
        logger.warning('Could not resolve tunnel id for %s', tname)
        return False
    if not _credentials_file_for(tid, tname):
        logger.warning('Tunnel id %s known but credentials JSON missing', tid)
        return False
    port = int(cfg.get('flask_port', DEFAULT_PORT))
    _write_cloudflared_config(tname, tid, domain, port, log)
    save_web_config({'tunnel_id': tid})
    return True


def _config_yml_hostname() -> str:
    """Read hostname from existing config.yml if present."""
    try:
        for d in (get_cloudflared_dir(), get_legacy_cloudflared_dir()):
            yml = d / 'config.yml'
            if not yml.is_file():
                continue
            for line in yml.read_text(encoding='utf-8').splitlines():
                line = line.strip().lstrip('-').strip()
                if line.startswith('hostname:'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return ''


def _config_yml_tunnel_id() -> str:
    """Read tunnel UUID from existing config.yml if present."""
    try:
        for d in (get_cloudflared_dir(), get_legacy_cloudflared_dir()):
            yml = d / 'config.yml'
            if not yml.is_file():
                continue
            for line in yml.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith('tunnel:'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return ''


# ── Full setup ────────────────────────────────────────────────────────────────

class CloudflareSetup:
    """One-time per-shop Cloudflare tunnel provisioning."""

    def __init__(
        self,
        shop_name: str,
        subdomain: Optional[str] = None,
        log_callback: Optional[LogCallback] = None,
        force_relogin: bool = False,
    ):
        self.shop_name = shop_name.strip()
        self.subdomain = shop_to_subdomain(subdomain or shop_name)
        self.domain = full_domain(self.subdomain)
        self.tunnel_name = tunnel_name_for(self.subdomain)
        self.force_relogin = force_relogin
        self.log = _SetupLog(log_callback)
        self.result: dict = {
            'ok': False,
            'domain': self.domain,
            'local_url': f'http://127.0.0.1:{DEFAULT_PORT}',
            'tunnel_name': self.tunnel_name,
            'subdomain': self.subdomain,
            'log_path': str(get_log_path()),
            'steps': [],
            'errors': [],
        }

    def _step(self, name: str, ok: bool, detail: str = ''):
        self.result['steps'].append({'name': name, 'ok': ok, 'detail': detail})
        if not ok:
            self.result['errors'].append(f'{name}: {detail}')

    def run(self) -> dict:
        self.log.info(f'Starting Cloudflare setup for {self.shop_name}')
        self.log.info(f'Remote URL → https://{self.domain}')

        try:
            if not is_online():
                raise RuntimeError('No internet. Connect Wi‑Fi/Ethernet and retry.')

            save_web_config({
                'base_domain': BASE_DOMAIN,
                'tunnel_subdomain': self.subdomain,
                'tunnel_domain': self.domain,
                'tunnel_name': self.tunnel_name,
                'remote_enabled': True,
            })
            self._step('Write web_config.json', True)
            self.log.ok('Saved config/web_config.json')

            cf = download_cloudflared(self.log)
            self._step('cloudflared binary', True, str(cf))

            port = int(load_web_config().get('flask_port', DEFAULT_PORT))
            tunnel_id = ''

            # Production path: management API — no browser, no cert.pem
            if _get_cloudflare_api_token() and not self.force_relogin:
                self.log.info('Using Cloudflare management API (automatic, no browser)')
                provisioned = provision_shop_tunnel_via_api(
                    self.subdomain, port=port, log=self.log)
                tunnel_id = provisioned['tunnel_id']
                self._step('Cloudflare API provision', True, tunnel_id)
            else:
                # Vendor emergency browser path, or legacy cert.pem
                ensure_cloudflare_auth(
                    cf, self.log,
                    force_relogin=self.force_relogin,
                    allow_browser=bool(self.force_relogin),
                )
                self._step('Cloudflare login', True)

                r = _run([str(cf), 'tunnel', 'create', self.tunnel_name], timeout=120)
                out = (r.stdout or '') + (r.stderr or '')
                if r.returncode != 0 and 'already exists' not in out.lower():
                    if _is_auth_error(out):
                        raise RuntimeError(
                            f'Tunnel create auth failed:\n{out.strip()}\n\n{AUTH_HELP}')
                    self.log.warn(f'tunnel create: {out.strip()}')
                else:
                    self.log.ok(f'Tunnel "{self.tunnel_name}" ready')

                tunnel_id = _tunnel_id_by_name(cf, self.tunnel_name, self.log)
                if not tunnel_id:
                    if _is_auth_error(out):
                        raise RuntimeError(
                            f'Tunnel API unauthorized:\n{out.strip()}\n\n{AUTH_HELP}')
                    raise RuntimeError(
                        f'Could not find tunnel "{self.tunnel_name}" after create.\n'
                        f'Output: {out.strip()}')
                self._step('Create tunnel', True, tunnel_id)
                self.log.info(f'Tunnel ID: {tunnel_id}')
                sync_cloudflared_state()

                _write_cloudflared_config(
                    self.tunnel_name, tunnel_id, self.domain, port, self.log)
                self._step('Write cloudflared config', True)

                stop_all_cloudflared()
                time.sleep(1)

                r = _run(
                    [str(cf), 'tunnel', 'route', 'dns',
                     self.tunnel_name, self.domain],
                    timeout=120,
                )
                route_out = (r.stdout or '') + (r.stderr or '')
                if r.returncode != 0 and 'already exists' in route_out.lower():
                    self.log.info('DNS record exists — overwriting with tunnel CNAME…')
                    r = _run(
                        [str(cf), 'tunnel', 'route', 'dns', '--overwrite-dns',
                         self.tunnel_name, self.domain],
                        timeout=120,
                    )
                    route_out = (r.stdout or '') + (r.stderr or '')
                if r.returncode != 0 and 'already exists' not in route_out.lower():
                    raise RuntimeError(
                        f'DNS route failed for {self.domain}:\n{route_out.strip()}')
                self.log.ok(f'DNS → {self.domain}')
                self._step('DNS route', True, self.domain)

            # Subdomain change leaves an old cloudflared serving the previous tunnel
            stop_all_cloudflared()
            time.sleep(1)

            verify = verify_remote_setup(
                self.domain, self.log, start_tunnel=True, wait_dns=90)

            pub_ok, _ = _dns_resolves_via(self.domain, '1.1.1.1')

            if verify.get('remote_https_ok'):
                self._step('Verify remote URL', True, verify.get('remote_detail', ''))
            elif verify.get('pending_dns') or pub_ok:
                self._step('Verify remote URL', True,
                           'DNS propagating — remote URL will work in a few minutes')
                self.log.info(
                    'Tunnel is configured. DNS may take 2–5 minutes worldwide.')
            elif verify.get('tunnel_ok') and verify.get('local_ok'):
                self._step('Verify remote URL', True,
                           verify.get('remote_detail', 'tunnel running'))
            else:
                self._step('Verify remote URL', False, verify.get('detail', ''))

            setup_complete = bool(tunnel_id) and bool(self.domain)

            save_web_config({
                'remote_enabled': True,
                'remote_setup_ok': setup_complete,
                'remote_setup_at': datetime.now().isoformat(),
                'cloudflared_exe': str(cf),
                'tunnel_id': tunnel_id,
            })

            self.result['ok'] = True
            self.result['remote_ok'] = verify.get('remote_https_ok', False) or pub_ok
            self.result['remote_pending_dns'] = (
                verify.get('pending_dns', False) or (pub_ok and not verify.get('dns_ok'))
            )
            self.result['tunnel_running'] = verify.get('tunnel_ok', False)
            self.log.ok('Setup complete')
            self.log.info(f'Local:  http://127.0.0.1:{port}')
            self.log.info(f'Remote: https://{self.domain}')
            if verify.get('pending_dns'):
                self.log.info(
                    f'Next: wait 2–5 min, then open https://{self.domain} '
                    f'or run DIAGNOSE CLOUDFLARE.bat')
            elif not verify.get('remote_https_ok'):
                self.log.info('Restart MBT POS to keep the tunnel running automatically.')

        except Exception as e:
            self.log.error(str(e))
            self._step('Setup', False, str(e))
            cfg_now = load_web_config()
            save_web_config({
                'remote_enabled': True,
                'remote_setup_ok': bool(cfg_now.get('tunnel_id') and cfg_now.get('tunnel_domain')),
                'remote_setup_at': datetime.now().isoformat(),
            })

        self.result['log'] = '\n'.join(self.log.lines)
        return self.result


# ── Verification & diagnostics ────────────────────────────────────────────────

def _dns_resolves(hostname: str) -> tuple[bool, str]:
    """Return True if hostname resolves via this PC's default DNS."""
    try:
        socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        return True, 'DNS resolves'
    except socket.gaierror as e:
        return False, f'DNS not ready ({e})'
    except Exception as e:
        return False, str(e)


def _dns_resolves_via(hostname: str, resolver: str = '1.1.1.1') -> tuple[bool, str]:
    """Check a public resolver (Cloudflare 1.1.1.1) — catches slow shop-router DNS."""
    if sys.platform == 'win32':
        try:
            r = subprocess.run(
                ['nslookup', hostname, resolver],
                capture_output=True, text=True, timeout=15,
                creationflags=_hide_flags(),
            )
            out = ((r.stdout or '') + (r.stderr or '')).lower()
            if 'non-existent domain' in out or "can't find" in out:
                return False, f'not on {resolver} yet'
            if hostname.lower() in out and 'address' in out:
                return True, f'resolves on {resolver}'
        except Exception as e:
            return False, str(e)
    return _dns_resolves(hostname)


ROUTER_DNS_FIX = (
    'Shop-router DNS is slow. MBT POS sets this PC to 1.1.1.1 automatically during setup. '
    'If the browser still fails, click Allow when Windows asks, then run Test Connection again.'
)


def _active_net_interface() -> str:
    """Name of the connected network adapter (Windows)."""
    if sys.platform != 'win32':
        return ''
    try:
        r = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command',
             "(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | "
             "Sort-Object InterfaceMetric | Select-Object -First 1 -ExpandProperty Name)"],
            capture_output=True, text=True, timeout=25,
            creationflags=_hide_flags(),
        )
        name = (r.stdout or '').strip().splitlines()[0].strip() if r.stdout else ''
        if name:
            return name
    except Exception:
        pass
    try:
        r = subprocess.run(
            ['netsh', 'interface', 'show', 'interface'],
            capture_output=True, text=True, timeout=15,
            creationflags=_hide_flags(),
        )
        for line in (r.stdout or '').splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[1] == 'Connected':
                return ' '.join(parts[3:])
    except Exception:
        pass
    return ''


def _try_set_windows_dns(
    iface: str,
    primary: str = '1.1.1.1',
    secondary: str = '8.8.8.8',
) -> tuple[bool, str]:
    """Set DNS on one adapter. Needs admin on most shop PCs."""
    r1 = subprocess.run(
        ['netsh', 'interface', 'ip', 'set', 'dns', f'name={iface}', 'static', primary],
        capture_output=True, text=True, timeout=30,
        creationflags=_hide_flags(),
    )
    if r1.returncode != 0:
        err = ((r1.stderr or '') + (r1.stdout or '')).lower()
        if 'denied' in err or 'administrator' in err or 'elevation' in err:
            return False, 'needs_admin'
        return False, (r1.stderr or r1.stdout or 'netsh set dns failed').strip()
    subprocess.run(
        ['netsh', 'interface', 'ip', 'add', 'dns', f'name={iface}', secondary, 'index=2'],
        capture_output=True, text=True, timeout=30,
        creationflags=_hide_flags(),
    )
    subprocess.run(
        ['ipconfig', '/flushdns'],
        capture_output=True, timeout=15,
        creationflags=_hide_flags(),
    )
    return True, iface


def _elevate_dns_fix(iface: str, primary: str, secondary: str) -> bool:
    """One UAC prompt — sets DNS then exits."""
    import tempfile
    bat = os.path.join(tempfile.gettempdir(), 'mbt_pos_dns_fix.bat')
    try:
        with open(bat, 'w', encoding='utf-8') as f:
            f.write('\n'.join([
                '@echo off',
                f'netsh interface ip set dns name="{iface}" static {primary}',
                f'netsh interface ip add dns name="{iface}" {secondary} index=2 2>nul',
                'ipconfig /flushdns >nul',
                f'del "%~f0" 2>nul',
            ]))
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', 'cmd.exe', f'/c "{bat}"', None, 0)
        return int(rc) > 32
    except Exception as e:
        logger.warning('elevate dns fix: %s', e)
        return False


def apply_shop_pc_dns_fix(
    log: Optional[_SetupLog] = None,
    primary: str = '1.1.1.1',
    secondary: str = '8.8.8.8',
) -> tuple[bool, str]:
    """
    Point the shop PC at fast public DNS when the router DNS lags behind Cloudflare.
    Runs during Cloudflare setup — shop staff do not configure DNS manually.
    """
    if sys.platform != 'win32':
        return False, 'not Windows'
    iface = _active_net_interface()
    if not iface:
        msg = 'Could not detect active network adapter'
        if log:
            log.warn(msg)
        return False, msg

    if log:
        log.info(f'Updating PC DNS on "{iface}" → {primary} / {secondary}…')

    ok, detail = _try_set_windows_dns(iface, primary, secondary)
    if ok:
        if log:
            log.ok('PC DNS updated for this shop link')
        return True, iface

    if detail == 'needs_admin':
        if log:
            log.info(
                'Windows security — click Allow once so MBT POS can fix DNS on this PC')
        if _elevate_dns_fix(iface, primary, secondary):
            time.sleep(8)
            subprocess.run(
                ['ipconfig', '/flushdns'],
                capture_output=True, timeout=15,
                creationflags=_hide_flags(),
            )
            ok2, _ = _dns_resolves('cloudflare.com')
            if ok2:
                if log:
                    log.ok('PC DNS updated (after Allow)')
                return True, iface
        if log:
            log.warn('DNS fix needs Allow on the Windows prompt, or run setup as administrator')
        return False, 'needs_admin'

    if log:
        log.warn(f'DNS update failed: {detail}')
    return False, detail


def _wait_for_dns(
    hostname: str,
    log: Optional[_SetupLog] = None,
    max_wait: int = 90,
) -> tuple[bool, str]:
    """Poll DNS after route dns — propagation often takes 30–120 seconds."""
    attempts = max(1, max_wait // 5)
    for i in range(attempts):
        ok, detail = _dns_resolves(hostname)
        if ok:
            if log:
                log.ok(f'DNS ready: {hostname}')
            return True, detail
        if i == 0 and log:
            log.info(f'Waiting for DNS ({hostname}) — up to {max_wait}s…')
        time.sleep(5)
    public_ok, public_detail = _dns_resolves_via(hostname, '1.1.1.1')
    if public_ok:
        if log:
            log.ok(f'DNS live on internet ({public_detail})')
            log.info('Fixing this PC DNS automatically…')
        fixed, _ = apply_shop_pc_dns_fix(log)
        if fixed:
            ok, detail = _dns_resolves(hostname)
            if ok:
                if log:
                    log.ok(f'DNS ready on this PC: {hostname}')
                return True, detail
        if log:
            log.warn(ROUTER_DNS_FIX)
        return False, (
            'Link works on phones — this PC DNS was updated or needs Allow on Windows prompt.'
        )
    return False, (
        f'DNS not resolving yet on this PC (normal for 2–5 min after setup). '
        f'Run DIAGNOSE CLOUDFLARE.bat later.'
    )


def _http_check(url: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            url, method='GET',
            headers={'User-Agent': 'Mozilla/5.0 (compatible; MBT-POS/1.0)'},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
            # 200 = perfect; 403 often means Cloudflare edge (tunnel still works in browser)
            if code == 200:
                return True, f'HTTP {code}'
            if code == 403:
                return True, f'HTTP {code} (reachable — open in browser to log in)'
            return code < 500, f'HTTP {code}'
    except urllib.error.HTTPError as e:
        return e.code < 500, f'HTTP {e.code}'
    except Exception as e:
        return False, str(e)


def verify_remote_setup(
    domain: str,
    log: Optional[_SetupLog] = None,
    *,
    start_tunnel: bool = True,
    wait_dns: int = 90,
) -> dict:
    """Check local Flask, DNS, tunnel process, and remote HTTPS."""
    cfg = load_web_config()
    port = int(cfg.get('flask_port', DEFAULT_PORT))
    local_ok, local_detail = _http_check(f'http://127.0.0.1:{port}/api/health')

    if log:
        if local_ok:
            log.ok(f'Local dashboard OK ({local_detail})')
        else:
            log.warn(
                f'Local dashboard not responding on port {port} '
                f'(launch MBT POS first): {local_detail}')

    tunnel_ok = False
    if start_tunnel and cfg.get('remote_enabled'):
        stop_all_cloudflared()
        time.sleep(1)
        tunnel_ok = CloudflareTunnelService().start()
        if log:
            if tunnel_ok:
                log.ok('cloudflared tunnel process started')
            else:
                log.warn(
                    'cloudflared did not stay running from setup script '
                    '(MBT POS will start it automatically when you launch the app)')

    dns_ok, dns_detail = False, 'not tested'
    remote_ok, remote_detail = False, 'not tested'
    if domain:
        dns_ok, dns_detail = _wait_for_dns(domain, log, wait_dns)
        if dns_ok:
            for attempt in range(4):
                remote_ok, remote_detail = _http_check(
                    f'https://{domain}/api/health', timeout=12)
                if remote_ok:
                    break
                # Dashboard HTML page — less likely blocked than /api paths
                remote_ok, remote_detail = _http_check(
                    f'https://{domain}/', timeout=12)
                if remote_ok:
                    break
                time.sleep(3)
            if log:
                if remote_ok:
                    log.ok(f'Remote dashboard OK ({remote_detail})')
                else:
                    log.warn(f'Remote HTTPS: {remote_detail}')
        elif log:
            log.warn(dns_detail)

    # Setup is successful if tunnel infra is in place; HTTPS may lag DNS.
    infra_ok = bool(domain) and (tunnel_ok or _cloudflared_running())
    ok = remote_ok or (infra_ok and local_ok)

    return {
        'ok': ok,
        'remote_https_ok': remote_ok,
        'dns_ok': dns_ok,
        'dns_detail': dns_detail,
        'tunnel_ok': tunnel_ok or _cloudflared_running(),
        'local_ok': local_ok,
        'local_detail': local_detail,
        'remote_detail': remote_detail if dns_ok else dns_detail,
        'domain': domain,
        'detail': remote_detail if remote_ok else (dns_detail if not dns_ok else remote_detail),
        'pending_dns': bool(domain) and not dns_ok and not remote_ok,
        'public_dns_ok': _dns_resolves_via(domain, '1.1.1.1')[0] if domain else False,
    }


def refresh_remote_setup_status(save: bool = True) -> bool:
    """
    Mark remote_setup_ok when the tunnel is clearly working.
    Fixes UI stuck on 'setup in progress' after a good install.
    """
    cfg = load_web_config()
    if not cfg.get('remote_enabled'):
        return False
    if cfg.get('remote_setup_ok'):
        return True
    domain = (cfg.get('tunnel_domain') or '').strip()
    tunnel_id = (cfg.get('tunnel_id') or '').strip()
    if not domain or not tunnel_id:
        return False

    live = (
        _cloudflared_running()
        or _dns_resolves_via(domain, '1.1.1.1')[0]
        or _dns_resolves(domain)[0]
    )
    if live and save:
        save_web_config({
            'remote_setup_ok': True,
            'remote_setup_at': datetime.now().isoformat(),
        })
        logger.info('remote_setup_ok refreshed — %s is live', domain)
        return True
    return bool(live)


def run_diagnostics(log_callback: Optional[LogCallback] = None) -> dict:
    """Full Cloudflare + web diagnostics report."""
    log = _SetupLog(log_callback)
    cfg = load_web_config()
    port = int(cfg.get('flask_port', DEFAULT_PORT))
    domain = cfg.get('tunnel_domain', '')

    report = {
        'timestamp': datetime.now().isoformat(),
        'config_path': str(get_config_path()),
        'log_path': str(get_log_path()),
        'checks': [],
        'ok': True,
    }

    def add(name: str, ok: bool, detail: str = '', fix: str = ''):
        report['checks'].append({
            'name': name, 'ok': ok, 'detail': detail, 'fix': fix,
        })
        if not ok:
            report['ok'] = False
        mark = 'OK' if ok else 'FAIL'
        log.write('ok' if ok else 'error', f'{name}: {detail or mark}')

    add('Internet', is_online(), fix='Connect shop PC to the internet')

    cf = find_cloudflared_exe()
    add('cloudflared.exe', cf is not None, str(cf) if cf else 'not found',
        'Reinstall MBT POS or run setup from Settings → Remote Web Dashboard')

    add('Cloudflare login / API',
        has_cloudflare_login() or bool(_get_cloudflare_api_token()) or bool(_get_tunnel_run_token()),
        'management token' if _get_cloudflare_api_token() else (
            'connector token' if _get_tunnel_run_token() else (
                'cert.pem' if has_cloudflare_login() else 'none')),
        'Vendor: set cloudflare_api_token in deploy.local.json (not shop Re-login)')

    if cf or _get_cloudflare_api_token():
        api_ok, api_detail = verify_tunnel_api(cf) if cf else verify_management_api_token()
        add('Cloudflare API auth', api_ok, api_detail[:120],
            'Vendor: management API token (Account Tunnel Edit + Zone DNS Edit) '
            'in deploy.local.json — not cfut_/JWT')
    else:
        add('Cloudflare API auth', False, 'cloudflared missing and no API token',
            'Reinstall MBT POS or place management token in deploy.local.json')

    if _get_cloudflare_api_token():
        add('API token configured', True, 'management token in deploy.local.json or web_config')
    elif _get_tunnel_run_token():
        add('API token configured', True,
            'connector token present (tunnel run) — management token preferred for new shops')
    else:
        add('API token configured', False, 'none',
            'REQUIRED for silent shop installs: cloudflare_api_token in deploy.local.json')

    cfg_exists = get_config_path().is_file()
    add('web_config.json', cfg_exists, str(get_config_path()),
        'Complete setup wizard remote web step')

    add('Remote enabled', bool(cfg.get('remote_enabled')),
        cfg.get('tunnel_domain', 'LAN only'))

    yml = get_cloudflared_dir() / 'config.yml'
    add('cloudflared config.yml', yml.is_file(), str(yml),
        'Settings → Set Up Cloudflare (one-time)')
    tid = (cfg.get('tunnel_id') or '').strip() or _config_yml_tunnel_id()
    cred = _credentials_file_for(tid, cfg.get('tunnel_name', '')) if tid else None
    add('tunnel credentials', cred is not None,
        str(cred) if cred else 'missing — tunnel cannot start',
        'Re-run Set Up Cloudflare so tunnel create writes credentials JSON')

    local_ok, ld = _http_check(f'http://127.0.0.1:{port}/api/health')
    add('Local web dashboard', local_ok, ld,
        'Launch MBT POS (web starts automatically)')

    if cfg.get('remote_enabled') and domain:
        v = verify_remote_setup(domain, log, start_tunnel=True, wait_dns=30)
        pub_ok, _ = _dns_resolves_via(domain, '1.1.1.1')
        dns_fix = ROUTER_DNS_FIX if pub_ok and not v.get('dns_ok') else (
            'Wait 2–5 min after setup, or click Set Up Cloudflare again')
        if pub_ok and not v.get('dns_ok'):
            apply_shop_pc_dns_fix(log)
            pub_recheck, _ = _dns_resolves(domain)
            if pub_recheck:
                add('DNS resolves', True, 'fixed automatically on this PC', '')
            else:
                add('DNS resolves', False, v.get('dns_detail', ''), dns_fix)
        else:
            add('DNS resolves', v.get('dns_ok', False), v.get('dns_detail', ''), dns_fix)
        add('cloudflared tunnel', v.get('tunnel_ok', False),
            'running' if v.get('tunnel_ok') else 'not running',
            'Restart MBT POS or run setup again')
        add('Remote HTTPS', v.get('remote_https_ok', False), v.get('remote_detail', ''),
            'Ensure MBT POS is running and DNS has propagated')

    proc_ok = _cloudflared_running()
    add('cloudflared process', proc_ok or not cfg.get('remote_enabled'),
        'running' if proc_ok else 'not running',
        'Restart MBT POS to start tunnel')

    report['log'] = '\n'.join(log.lines)
    report['domain'] = domain
    report['local_url'] = f'http://127.0.0.1:{port}'
    report['remote_url'] = f'https://{domain}' if domain else ''
    return report


def _cloudflared_running() -> bool:
    try:
        if sys.platform == 'win32':
            r = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq cloudflared.exe'],
                capture_output=True, text=True, timeout=10,
                creationflags=_hide_flags(),
            )
            return 'cloudflared.exe' in (r.stdout or '').lower()
        r = subprocess.run(['pgrep', '-f', 'cloudflared'], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def stop_all_cloudflared():
    """Stop every cloudflared process (needed when switching tunnel hostname)."""
    try:
        if sys.platform == 'win32':
            subprocess.run(
                ['taskkill', '/F', '/IM', 'cloudflared.exe'],
                capture_output=True, timeout=15,
                creationflags=_hide_flags(),
            )
        else:
            subprocess.run(['pkill', '-f', 'cloudflared'], capture_output=True, timeout=15)
    except Exception as e:
        logger.warning('stop_all_cloudflared: %s', e)


# ── Tunnel service (embedded with desktop app) ────────────────────────────────

class CloudflareTunnelService:
    """Keep cloudflared running while MBT POS is open."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._monitor_thread = None
        self._stop = False
        self._lock = threading.Lock()

    def _launch_args(self) -> Optional[list]:
        """Build cloudflared argv — prefer connector token, else durable config.yml."""
        sync_cloudflared_state()
        cf = find_cloudflared_exe()
        if not cf:
            return None
        cfg = load_web_config()
        tid = _config_yml_tunnel_id() or (cfg.get('tunnel_id') or '').strip()
        tname = (cfg.get('tunnel_name') or '').strip()
        cfg_yml = get_cloudflared_dir() / 'config.yml'
        if not cfg_yml.is_file():
            cfg_yml = get_legacy_cloudflared_dir() / 'config.yml'
        # Local credentials JSON → classic named-tunnel config
        if cfg_yml.is_file() and tid and _credentials_file_for(tid, tname):
            return [str(cf), 'tunnel', '--config', str(cfg_yml), 'run']
        # Remotely-managed / API-provisioned → connector token
        run_tok = _get_tunnel_run_token()
        if run_tok:
            return [str(cf), 'tunnel', 'run', '--token', run_tok]
        # Do NOT run marker config.yml without credentials (causes HTTP 530)
        return None

    def _launch(self) -> bool:
        cfg = load_web_config()
        args = self._launch_args()
        if not args:
            return False
        log_file = _project_root() / 'logs' / 'cloudflared.log'
        log_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_fh = open(log_file, 'a', encoding='utf-8')
            self._proc = subprocess.Popen(
                args,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=_hide_flags(),
                cwd=str(_exe_dir()),
                env=_subprocess_env(),
            )
            for _ in range(12):
                time.sleep(1)
                if self._proc.poll() is not None:
                    break
            ok = self._proc.poll() is None
            if ok:
                logger.info('Cloudflare tunnel started → %s', cfg.get('tunnel_domain'))
            else:
                logger.warning(
                    'cloudflared exited (code %s) — see %s',
                    self._proc.returncode, log_file)
            return ok
        except Exception as e:
            logger.error('Tunnel start failed: %s', e)
            return False

    def _monitor_loop(self):
        while not self._stop:
            time.sleep(30)
            if self._stop:
                break
            proc_dead = self._proc is not None and self._proc.poll() is not None
            if proc_dead or not _cloudflared_running():
                logger.warning('cloudflared not running — restarting tunnel')
                with self._lock:
                    if not self._stop:
                        self._proc = None
                        self._launch()

    def start(self) -> bool:
        """
        Start tunnel if already configured. Does NOT run full setup / re-auth.
        Safe to call on every app launch.
        """
        cfg = load_web_config()
        if not cfg.get('remote_enabled'):
            return False
        bootstrap_cloudflared()
        sync_cloudflared_state()
        expected = (cfg.get('tunnel_domain') or '').strip()
        # Token-managed tunnels do not need config.yml / credentials sync
        if not _get_tunnel_run_token():
            yml_host = _config_yml_hostname()
            if expected and yml_host and yml_host != expected:
                logger.warning(
                    'cloudflared config.yml hostname mismatch — syncing to %s', expected)
                stop_all_cloudflared()
                sync_tunnel_config_from_web()

        if not find_cloudflared_exe():
            logger.warning('cloudflared not found — remote tunnel disabled')
            return False

        # Already configured locally → start without touching Cloudflare API
        if _remote_infra_ready() or self._launch_args():
            pass
        else:
            logger.info(
                'Tunnel not configured yet — waiting for API auto-provision '
                '(central management token in deploy.local.json)')
            return False

        with self._lock:
            yml_tid = _config_yml_tunnel_id()
            cfg_tid = (cfg.get('tunnel_id') or '').strip()
            if _cloudflared_running():
                if (yml_tid and cfg_tid and yml_tid == cfg_tid) or not cfg_tid:
                    logger.info('cloudflared already running')
                    ok = True
                else:
                    logger.warning(
                        'cloudflared running with stale tunnel — restarting')
                    stop_all_cloudflared()
                    time.sleep(1)
                    ok = self._launch()
            else:
                if _remote_infra_ready():
                    sync_tunnel_config_from_web()
                ok = self._launch()
            if ok and self._monitor_thread is None:
                self._stop = False
                self._monitor_thread = threading.Thread(
                    target=self._monitor_loop, name='CF-Tunnel-Monitor', daemon=True)
                self._monitor_thread.start()
            if ok:
                # Keep remote ingress on flask_port (token tunnels ignore config.yml)
                try:
                    ensure_remote_ingress_port()
                except Exception:
                    pass
                # Mark setup OK once tunnel stays up — avoids re-prompt loops
                if not cfg.get('remote_setup_ok'):
                    save_web_config({
                        'remote_setup_ok': True,
                        'remote_setup_at': datetime.now().isoformat(),
                        'tunnel_id': cfg_tid or yml_tid or cfg.get('tunnel_id', ''),
                    })
            return ok or _cloudflared_running()

    def stop(self):
        self._stop = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=8)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None


# ── Automatic provisioning (shop PCs — no browser login) ─────────────────────

AUTO_CF_FIRST_DELAY = 15          # seconds after app start
AUTO_CF_RETRY_INTERVAL = 30 * 60   # retry failed setup every 30 min

_auto_cf_lock = threading.Lock()
_auto_cf_running = False
_auto_cf_stop = threading.Event()
_auto_cf_thread: Optional[threading.Thread] = None
_auto_cf_callbacks: dict = {}


def _shop_ready_for_remote() -> tuple[bool, str]:
    shop = _read_shop_name_from_db()
    if not shop or shop.strip().lower() in ('', 'my shop'):
        return False, 'shop_name_not_set'
    return True, shop


def _remote_infra_ready() -> bool:
    """True when tunnel can start from local AppData alone (no re-auth)."""
    cfg = load_web_config()
    domain = (cfg.get('tunnel_domain') or '').strip()
    if not domain:
        return False
    # Remotely-managed path: durable connector token is enough
    if _get_tunnel_run_token():
        return True
    tid = (cfg.get('tunnel_id') or '').strip() or _config_yml_tunnel_id()
    tname = (cfg.get('tunnel_name') or '').strip()
    yml = get_cloudflared_dir() / 'config.yml'
    if not yml.is_file():
        yml = get_legacy_cloudflared_dir() / 'config.yml'
    if not yml.is_file() or not tid:
        return False
    return _credentials_file_for(tid, tname) is not None


def get_remote_dashboard_status() -> dict:
    """
    Structured status for Settings UI.
    state: off | needs_setup | configured | running | vendor_token_missing | broken
    """
    cfg = load_web_config()
    domain = (cfg.get('tunnel_domain') or '').strip()
    remote = bool(cfg.get('remote_enabled'))
    running = _cloudflared_running()
    ready = _remote_infra_ready()
    has_mgmt = bool(_get_cloudflare_api_token())
    has_cert = has_cloudflare_login()
    has_run = bool(_get_tunnel_run_token())
    raw = _token_from_sources()
    bad_tok = (
        _is_tunnel_run_token(raw)
        and not has_mgmt
        and not ready
        and remote
    )

    if not remote and not has_mgmt:
        state = 'off'
        detail = 'LAN only — remote access disabled'
    elif running and (ready or domain):
        state = 'running'
        detail = f'https://{domain}' if domain else 'Tunnel process running'
    elif ready:
        state = 'configured'
        detail = (
            f'Configured for https://{domain} — tunnel starts with the app'
            if domain else 'Tunnel configured — will auto-start')
    elif remote and not has_mgmt and not has_cert and not has_run:
        state = 'vendor_token_missing'
        detail = (
            'Vendor: central Cloudflare API token missing. '
            'Shops cannot auto-provision until deploy.local.json has a cfat_… token.')
    elif bad_tok:
        state = 'vendor_token_missing'
        detail = (
            'Wrong token type in cloudflare_api_token (connector token). '
            'Vendor must place a management API token (cfat_…) in deploy.local.json.')
    elif has_mgmt:
        state = 'needs_setup'
        detail = (
            f'Will auto-provision https://{domain or "….mugobyte.com"} '
            'on launch (management API token present)')
    elif domain and not ready:
        state = 'needs_setup'
        detail = (
            f'https://{domain} waiting for automatic provision '
            '(management API token required at vendor)')
    else:
        state = 'needs_setup'
        detail = 'Remote dashboard will auto-configure when vendor token is present'

    return {
        'state': state,
        'detail': detail,
        'domain': domain,
        'remote_enabled': remote,
        'running': running,
        'configured': ready,
        'remote_setup_ok': bool(cfg.get('remote_setup_ok')),
        'has_management_token': has_mgmt,
        'has_cert': has_cert,
        'wrong_token_type': bad_tok,
        'cloudflared_dir': str(get_cloudflared_dir()),
    }


def needs_auto_cloudflare_setup() -> tuple[bool, str]:
    """
    Return (should_act, reason).
    reason: full_setup | start_tunnel | start_token_tunnel | repair |
            needs_one_time_setup | vendor_token_missing | offline |
            shop_name_not_set | running | remote_disabled
    """
    normalize_cloudflare_tokens()
    if not is_online():
        return False, 'offline'
    ready, shop_or_reason = _shop_ready_for_remote()
    if not ready:
        return False, shop_or_reason

    cfg = load_web_config()

    # If infra already on disk, always prefer start — never re-run full setup
    if _remote_infra_ready():
        if not cfg.get('remote_enabled'):
            save_web_config({'remote_enabled': True})
        if _cloudflared_running():
            if not cfg.get('remote_setup_ok'):
                return True, 'repair'
            return False, 'running'
        return True, 'start_tunnel'

    if not cfg.get('remote_enabled'):
        # Auto-enable remote when we can provision silently for any shop
        if _get_cloudflare_api_token():
            save_web_config({
                'remote_enabled': True,
                'tunnel_subdomain': shop_to_subdomain(shop_or_reason),
                'tunnel_domain': full_domain(shop_to_subdomain(shop_or_reason)),
                'tunnel_name': tunnel_name_for(shop_to_subdomain(shop_or_reason)),
            })
        else:
            return False, 'remote_disabled'

    if _get_cloudflare_api_token():
        return True, 'full_setup'

    if has_cloudflare_login() and cfg.get('remote_enabled'):
        return True, 'full_setup'

    # Pre-issued connector token (HQ-provisioned tunnel) — run only, no create
    if _get_tunnel_run_token() and cfg.get('remote_enabled'):
        return True, 'start_token_tunnel'

    if cfg.get('remote_enabled'):
        return False, 'vendor_token_missing'
    return False, 'remote_disabled'


def run_auto_cloudflare_setup(log_callback: Optional[LogCallback] = None) -> dict:
    """Start existing tunnel or provision once via management API. No shop browser login."""
    global _auto_cf_running
    with _auto_cf_lock:
        if _auto_cf_running:
            return {'ok': False, 'skipped': True, 'reason': 'already_running'}
        _auto_cf_running = True

    log = _SetupLog(log_callback)
    try:
        need, reason = needs_auto_cloudflare_setup()
        if not need and reason == 'running':
            return {'ok': True, 'skipped': True, 'reason': 'running'}
        if not need:
            return {'ok': False, 'skipped': True, 'reason': reason}

        bootstrap_cloudflared()

        if reason in ('start_tunnel', 'repair'):
            log.info(
                'Starting existing Cloudflare tunnel…'
                if reason == 'start_tunnel' else 'Repairing Cloudflare tunnel status…')
            # Start tunnel FIRST — do not block on DNS UAC / tunnel list
            ok = CloudflareTunnelService().start()
            if reason == 'start_tunnel':
                try:
                    apply_shop_pc_dns_fix(log)
                except Exception:
                    pass
            refresh_remote_setup_status()
            return {
                'ok': ok or bool(load_web_config().get('remote_setup_ok')) or _cloudflared_running(),
                'action': reason,
                'domain': load_web_config().get('tunnel_domain', ''),
            }

        if reason == 'start_token_tunnel':
            log.info('Starting Cloudflare tunnel via connector token…')
            save_web_config({'remote_enabled': True})
            apply_shop_pc_dns_fix(log)
            ok = CloudflareTunnelService().start()
            if ok:
                save_web_config({
                    'remote_setup_ok': True,
                    'remote_setup_at': datetime.now().isoformat(),
                })
                refresh_remote_setup_status()
                return {
                    'ok': True,
                    'action': 'start_token_tunnel',
                    'domain': load_web_config().get('tunnel_domain', ''),
                }
            return {
                'ok': False,
                'error': (
                    'Tunnel connector token was rejected. '
                    'Vendor: refresh management API token and re-provision.'),
                'reason': 'vendor_token_missing',
            }

        if reason != 'full_setup':
            return {'ok': False, 'skipped': True, 'reason': reason}

        if not _get_cloudflare_api_token() and not has_cloudflare_login():
            return {
                'ok': False,
                'error': VENDOR_TOKEN_MISSING,
                'reason': 'vendor_token_missing',
            }

        ready, shop = _shop_ready_for_remote()
        if not ready:
            return {'ok': False, 'error': 'Set shop name in Settings first'}

        log.info(f'Automatic Cloudflare setup for {shop}…')
        apply_shop_pc_dns_fix(log)
        cfg = load_web_config()
        sub = (cfg.get('tunnel_subdomain') or '').strip() or shop_to_subdomain(shop)
        save_web_config({'remote_enabled': True})
        result = CloudflareSetup(
            shop, subdomain=sub, log_callback=log_callback,
            force_relogin=False,
        ).run()
        if result.get('ok'):
            sync_cloudflared_state()
            CloudflareTunnelService().start()
            refresh_remote_setup_status()
        result['action'] = 'full_setup'
        return result
    except Exception as e:
        logger.exception('run_auto_cloudflare_setup: %s', e)
        return {'ok': False, 'error': str(e)}
    finally:
        with _auto_cf_lock:
            _auto_cf_running = False


def _auto_cf_worker():
    """Background loop — starts existing tunnel; provisions via API when possible."""
    _auto_cf_stop.wait(AUTO_CF_FIRST_DELAY)
    warned_vendor = False
    while not _auto_cf_stop.is_set():
        need, reason = needs_auto_cloudflare_setup()
        if reason in ('needs_one_time_setup', 'vendor_token_missing'):
            if not warned_vendor:
                logger.warning(
                    'Remote access blocked: central Cloudflare management API token '
                    'missing/invalid. Vendor must place cfat_… token in deploy.local.json. '
                    'Shop staff do not need to Re-login.')
                warned_vendor = True
            return
        if reason in ('remote_disabled', 'shop_name_not_set', 'no_api_token'):
            if reason == 'no_api_token' and not warned_vendor:
                logger.info(
                    'Auto Cloudflare: no management API token — '
                    'will only auto-start if AppData tunnel credentials already exist')
                warned_vendor = True
            wait = 120
            _auto_cf_stop.wait(wait)
            continue
        if not need:
            wait = AUTO_CF_RETRY_INTERVAL if reason == 'running' else 60
            _auto_cf_stop.wait(wait)
            continue

        result = run_auto_cloudflare_setup()
        cb_ok = _auto_cf_callbacks.get('on_done')
        cb_fail = _auto_cf_callbacks.get('on_failed')
        if result.get('ok'):
            dom = result.get('domain', '')
            logger.info('Auto Cloudflare OK — %s', dom or result.get('action', 'ok'))
            if cb_ok:
                try:
                    cb_ok(result)
                except Exception:
                    pass
            _auto_cf_stop.wait(AUTO_CF_RETRY_INTERVAL)
            continue
        if result.get('reason') in ('needs_one_time_setup', 'vendor_token_missing') or (
                not result.get('skipped') and 'vendor' in str(result.get('error', '')).lower()):
            if not warned_vendor:
                logger.warning('Auto Cloudflare: %s', result.get('error') or reason)
                warned_vendor = True
            if cb_fail:
                try:
                    cb_fail(result)
                except Exception:
                    pass
            return
        if not result.get('skipped'):
            err = result.get('error') or result.get('errors', ['unknown'])
            if isinstance(err, list):
                err = '; '.join(str(x) for x in err[:3])
            logger.warning('Auto Cloudflare failed: %s', err)
            if cb_fail:
                try:
                    cb_fail(result)
                except Exception:
                    pass

        _auto_cf_stop.wait(AUTO_CF_RETRY_INTERVAL)


def start_auto_cloudflare(on_done=None, on_failed=None):
    """Start background auto-provisioning (once per app session)."""
    global _auto_cf_thread
    logger.info(
        'Auto Cloudflare provisioner starting '
        '(API-auto build: provision_shop_tunnel_via_api)')
    _auto_cf_callbacks['on_done'] = on_done
    _auto_cf_callbacks['on_failed'] = on_failed
    with _auto_cf_lock:
        if _auto_cf_thread and _auto_cf_thread.is_alive():
            return
        _auto_cf_stop.clear()
        _auto_cf_thread = threading.Thread(
            target=_auto_cf_worker, name='AutoCloudflare', daemon=True)
        _auto_cf_thread.start()
        logger.info('Auto Cloudflare provisioner started')


def stop_auto_cloudflare():
    _auto_cf_stop.set()


# ── CLI (SETUP CLOUDFLARE.bat) ────────────────────────────────────────────────

def cli_main():
    import argparse
    parser = argparse.ArgumentParser(description='MBT POS Cloudflare setup')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--shop', default='', help='Shop name for subdomain')
    parser.add_argument('--subdomain', default='', help='Override subdomain slug')
    parser.add_argument('--relogin', action='store_true',
                        help='Delete stale cert.pem and log in again')
    args = parser.parse_args()

    if args.diagnose:
        rep = run_diagnostics(lambda lvl, m: print(f'[{lvl}] {m}'))
        print('\n=== SUMMARY ===')
        for c in rep['checks']:
            mark = 'PASS' if c['ok'] else 'FAIL'
            print(f'  {mark}: {c["name"]} — {c["detail"]}')
            if not c['ok'] and c.get('fix'):
                print(f'         Fix: {c["fix"]}')
        print(f'\nLog: {rep["log_path"]}')
        sys.exit(0 if rep['ok'] else 1)

    shop = args.shop.strip()
    if not shop:
        try:
            db = __import__('mbt_paths', fromlist=['get_db_path']).get_db_path()
            import sqlite3
            conn = sqlite3.connect(db)
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key='shop_name'"
            ).fetchone()
            conn.close()
            shop = row[0] if row else ''
        except Exception:
            shop = ''
    if not shop:
        shop = input('Shop name: ').strip()
    if not shop:
        print('ERROR: shop name required (--shop "Shop Name")')
        sys.exit(1)

    def _print(lvl, msg):
        print(f'[{lvl}] {msg}')

    result = CloudflareSetup(
        shop, subdomain=args.subdomain or None, log_callback=_print,
        force_relogin=args.relogin,
    ).run()
    print('\n=== RESULT ===')
    print(json.dumps({k: v for k, v in result.items() if k != 'log'}, indent=2))
    if result.get('log'):
        print(f"\nFull log: {result['log_path']}")
    sys.exit(0 if result.get('ok') else 1)


if __name__ == '__main__':
    cli_main()
