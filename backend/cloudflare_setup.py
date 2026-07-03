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
Cloudflare authentication failed (error 10000).

The cert.pem on this PC is missing, expired, or from the wrong Cloudflare account.

FIX — try in order:

1) Fresh login (recommended)
   In MBT POS: Settings → Remote Web Dashboard → Re-login to Cloudflare
   In the browser:
   • Log into the Cloudflare account that OWNS mugobyte.com
   • If you see multiple accounts, pick the MugoByte account
   • Select zone: mugobyte.com  →  click Authorize

2) API token (best for shop installs — no browser on customer PC)
   dash.cloudflare.com → My Profile → API Tokens → Create Token
   Permissions: Account → Cloudflare Tunnel → Edit
                Zone  → DNS → Edit  (zone: mugobyte.com)
   Add to config/deploy.local.json:
     "cloudflare_api_token": "your_token_here"
   Then run setup again from Settings → Remote Web Dashboard.

3) Zero Trust must be active on the account (free tier is fine):
   dash.cloudflare.com → Zero Trust → Networks → Tunnels

Delete stale cert manually if needed:
   %USERPROFILE%\\.cloudflared\\cert.pem
""".strip()


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


def get_log_path() -> Path:
    p = _project_root() / 'logs' / 'cloudflare_setup.log'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_cloudflared_dir() -> Path:
    d = Path.home() / '.cloudflared'
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    'remote_enabled': False,
    'remote_setup_ok': False,
    'remote_setup_at': '',
    'cloudflared_exe': '',
    'check_interval': 30,
    'max_restarts': 50,
}


def load_web_config() -> dict:
    path = get_config_path()
    cfg = dict(_DEFAULT_CFG)
    if path.is_file():
        try:
            with open(path, encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception as e:
            logger.warning('web_config read failed: %s', e)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_web_config()
    cfg.update(updates)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    return path


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


def _get_cloudflare_api_token() -> str:
    """API token bypasses stale cert.pem (set in deploy.local.json or env)."""
    tok = (load_web_config().get('cloudflare_api_token') or '').strip()
    if tok:
        return tok
    try:
        from config.deploy import load_deploy_config
        tok = (load_deploy_config().get('cloudflare_api_token') or '').strip()
        if tok:
            return tok
    except Exception:
        pass
    return os.environ.get('CLOUDFLARE_API_TOKEN', '').strip()


def _subprocess_env() -> dict:
    env = os.environ.copy()
    tok = _get_cloudflare_api_token()
    if tok:
        env['CLOUDFLARE_API_TOKEN'] = tok
    return env


def _is_auth_error(text: str) -> bool:
    t = (text or '').lower()
    return any(x in t for x in (
        'authentication error', 'unauthorized', 'code: 10000',
        'code":10000', 'rest request failed: unauthorized',
    ))


def clear_cloudflare_login(log: Optional[_SetupLog] = None):
    """Remove stale origin certificate so the next login is fresh."""
    cert = get_cloudflared_dir() / 'cert.pem'
    if cert.is_file():
        try:
            cert.unlink()
            if log:
                log.info('Removed stale cert.pem — will re-login')
        except Exception as e:
            if log:
                log.warn(f'Could not delete cert.pem: {e}')


def verify_tunnel_api(cf: Path, log: Optional[_SetupLog] = None) -> tuple[bool, str]:
    """True if cloudflared can list tunnels (proves API auth works)."""
    if _get_cloudflare_api_token():
        if log:
            log.ok('Using Cloudflare API token from config')
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
) -> None:
    """Browser login + verify API, or API token only. Raises on failure."""
    if force_relogin:
        clear_cloudflare_login(log)

    has_token = bool(_get_cloudflare_api_token())

    if not has_token:
        ok, detail = verify_tunnel_api(cf, log)
        if ok:
            log.ok('Cloudflare API auth verified')
            return
        if has_cloudflare_login():
            log.warn(f'Existing cert.pem rejected by Cloudflare: {detail[:200]}')
            clear_cloudflare_login(log)

    if not has_token and not has_cloudflare_login():
        log.info(
            'Opening browser — log into the MugoByte Cloudflare account, '
            f'then authorize zone {BASE_DOMAIN}')
        r = _run([str(cf), 'tunnel', 'login'], timeout=300, visible=True)
        if r.returncode != 0 or not has_cloudflare_login():
            raise RuntimeError(
                'Cloudflare login failed or was cancelled.\n'
                f'{r.stderr or r.stdout or ""}\n\n{AUTH_HELP}')

    ok, detail = verify_tunnel_api(cf, log)
    if ok:
        log.ok('Cloudflare API auth verified')
        return

    if not has_token:
        log.warn('Auth failed — retrying with fresh browser login…')
        clear_cloudflare_login(log)
        r = _run([str(cf), 'tunnel', 'login'], timeout=300, visible=True)
        if r.returncode != 0 or not has_cloudflare_login():
            raise RuntimeError(
                'Cloudflare re-login failed.\n\n' + AUTH_HELP)
        ok, detail = verify_tunnel_api(cf, log)
        if ok:
            log.ok('Cloudflare API auth verified after re-login')
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
    cert = get_cloudflared_dir() / 'cert.pem'
    return cert.is_file() and cert.stat().st_size > 100


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
    cfdir = get_cloudflared_dir()
    cred = cfdir / f'{tunnel_id}.json'
    if not cred.is_file():
        alt = cfdir / f'{tunnel_name}.json'
        if alt.is_file():
            cred = alt
        elif log:
            log.warn(f'Credentials file not found at {cred} — tunnel may still work if created earlier')

    cfg_path = cfdir / 'config.yml'
    body = (
        f'tunnel: {tunnel_id}\n'
        f'credentials-file: {cred}\n'
        f'ingress:\n'
        f'  - hostname: {hostname}\n'
        f'    service: http://localhost:{port}\n'
        f'  - service: http_status:404\n'
    )
    cfg_path.write_text(body, encoding='utf-8')
    if log:
        log.ok(f'Wrote {cfg_path}')
    logger.info('cloudflared config.yml -> %s (%s)', hostname, tunnel_id)
    return cfg_path


def sync_tunnel_config_from_web(log: Optional[_SetupLog] = None) -> bool:
    """
    Align ~/.cloudflared/config.yml with web_config.json (tunnel name + hostname).
    Fixes shops where web_config was updated but config.yml still points elsewhere.
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
    cf = find_cloudflared_exe()
    if not cf:
        return False
    tid = _tunnel_id_by_name(cf, tname, log or _SetupLog())
    if not tid:
        # Fallback: derive tunnel name from subdomain slug
        sub = cfg.get('tunnel_subdomain', '')
        alt_name = tunnel_name_for(sub) if sub else ''
        if alt_name and alt_name != tname:
            tid = _tunnel_id_by_name(cf, alt_name, log or _SetupLog())
            if tid:
                tname = alt_name
    if not tid:
        logger.warning('Could not resolve tunnel id for %s', tname)
        return False
    port = int(cfg.get('flask_port', DEFAULT_PORT))
    _write_cloudflared_config(tname, tid, domain, port, log)
    return True


def _config_yml_hostname() -> str:
    """Read hostname from existing config.yml if present."""
    try:
        yml = get_cloudflared_dir() / 'config.yml'
        if not yml.is_file():
            return ''
        for line in yml.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('hostname:'):
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

            ensure_cloudflare_auth(cf, self.log, force_relogin=self.force_relogin)
            self._step('Cloudflare login', True)

            r = _run([str(cf), 'tunnel', 'create', self.tunnel_name], timeout=120)
            out = (r.stdout or '') + (r.stderr or '')
            if r.returncode != 0 and 'already exists' not in out.lower():
                if _is_auth_error(out):
                    raise RuntimeError(f'Tunnel create auth failed:\n{out.strip()}\n\n{AUTH_HELP}')
                self.log.warn(f'tunnel create: {out.strip()}')
            else:
                self.log.ok(f'Tunnel "{self.tunnel_name}" ready')

            tunnel_id = _tunnel_id_by_name(cf, self.tunnel_name, self.log)
            if not tunnel_id:
                if _is_auth_error(out):
                    raise RuntimeError(f'Tunnel API unauthorized:\n{out.strip()}\n\n{AUTH_HELP}')
                raise RuntimeError(
                    f'Could not find tunnel "{self.tunnel_name}" after create.\n'
                    f'Output: {out.strip()}')
            self._step('Create tunnel', True, tunnel_id)
            self.log.info(f'Tunnel ID: {tunnel_id}')

            port = int(load_web_config().get('flask_port', DEFAULT_PORT))
            _write_cloudflared_config(
                self.tunnel_name, tunnel_id, self.domain, port, self.log)
            self._step('Write cloudflared config', True)

            r = _run(
                [str(cf), 'tunnel', 'route', 'dns', self.tunnel_name, self.domain],
                timeout=120,
            )
            route_out = (r.stdout or '') + (r.stderr or '')
            if r.returncode != 0 and 'already exists' in route_out.lower():
                log.info('DNS record exists — overwriting with tunnel CNAME…')
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

            verify = verify_remote_setup(
                self.domain, self.log, start_tunnel=True, wait_dns=90)

            if verify.get('remote_https_ok'):
                self._step('Verify remote URL', True, verify.get('remote_detail', ''))
            elif verify.get('pending_dns'):
                self._step('Verify remote URL', True,
                           'DNS propagating — remote URL will work in a few minutes')
                self.log.info(
                    'Tunnel is configured. DNS may take 2–5 minutes worldwide.')
            elif verify.get('tunnel_ok') and verify.get('local_ok'):
                self._step('Verify remote URL', True,
                           verify.get('remote_detail', 'tunnel running'))
            else:
                self._step('Verify remote URL', False, verify.get('detail', ''))

            setup_complete = (
                verify.get('tunnel_ok')
                or verify.get('remote_https_ok')
                or verify.get('pending_dns')
            )

            save_web_config({
                'remote_enabled': True,
                'remote_setup_ok': setup_complete,
                'remote_setup_at': datetime.now().isoformat(),
                'cloudflared_exe': str(cf),
            })

            self.result['ok'] = True
            self.result['remote_ok'] = verify.get('remote_https_ok', False)
            self.result['remote_pending_dns'] = verify.get('pending_dns', False)
            self.result['tunnel_running'] = verify.get('tunnel_ok', False)
            self.log.ok('Setup complete')
            self.log.info(f'Local:  http://127.0.0.1:{port}')
            self.log.info(f'Remote: https://{self.domain}')
            if verify.get('pending_dns'):
                self.log.info(
                    'Next: wait 2–5 min, then open https://%s or run DIAGNOSE CLOUDFLARE.bat',
                    self.domain)
            elif not verify.get('remote_https_ok'):
                self.log.info('Restart MBT POS to keep the tunnel running automatically.')

        except Exception as e:
            self.log.error(str(e))
            self._step('Setup', False, str(e))
            save_web_config({
                'remote_enabled': True,
                'remote_setup_ok': False,
                'remote_setup_at': datetime.now().isoformat(),
            })

        self.result['log'] = '\n'.join(self.log.lines)
        return self.result


# ── Verification & diagnostics ────────────────────────────────────────────────

def _dns_resolves(hostname: str) -> tuple[bool, str]:
    """Return True if hostname resolves (Windows errno 11001 = not yet propagated)."""
    try:
        socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        return True, 'DNS resolves'
    except socket.gaierror as e:
        return False, f'DNS not ready ({e})'
    except Exception as e:
        return False, str(e)


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
        'pending_dns': bool(domain) and not dns_ok,
    }


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

    add('Cloudflare login', has_cloudflare_login(),
        fix='Settings → Remote Web Dashboard → Re-login to Cloudflare')

    if cf:
        api_ok, api_detail = verify_tunnel_api(cf)
        add('Cloudflare API auth', api_ok, api_detail[:120],
            'Settings → Remote Web → Re-login, or set cloudflare_api_token in deploy.local.json')
    else:
        add('Cloudflare API auth', False, 'cloudflared missing',
            'Settings → Remote Web Dashboard → Set Up Cloudflare')

    if _get_cloudflare_api_token():
        add('API token configured', True, 'deploy.local.json or web_config')

    cfg_exists = get_config_path().is_file()
    add('web_config.json', cfg_exists, str(get_config_path()),
        'Complete setup wizard remote web step')

    add('Remote enabled', bool(cfg.get('remote_enabled')),
        cfg.get('tunnel_domain', 'LAN only'))

    yml = get_cloudflared_dir() / 'config.yml'
    add('cloudflared config.yml', yml.is_file(), str(yml))

    local_ok, ld = _http_check(f'http://127.0.0.1:{port}/api/health')
    add('Local web dashboard', local_ok, ld,
        'Launch MBT POS (web starts automatically)')

    if cfg.get('remote_enabled') and domain:
        v = verify_remote_setup(domain, log, start_tunnel=True, wait_dns=30)
        add('DNS resolves', v.get('dns_ok', False), v.get('dns_detail', ''),
            'Wait 2–5 min after setup, or check CNAME in Cloudflare dashboard')
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

    def _launch(self) -> bool:
        cfg = load_web_config()
        cfg_yml = get_cloudflared_dir() / 'config.yml'
        cf = find_cloudflared_exe()
        if not cf or not cfg_yml.is_file():
            return False
        log_file = _project_root() / 'logs' / 'cloudflared.log'
        log_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_fh = open(log_file, 'a', encoding='utf-8')
            self._proc = subprocess.Popen(
                [str(cf), 'tunnel', '--config', str(cfg_yml), 'run'],
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                creationflags=_hide_flags(),
                cwd=str(_exe_dir()),
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
        cfg = load_web_config()
        if not cfg.get('remote_enabled'):
            return False
        expected = (cfg.get('tunnel_domain') or '').strip()
        if expected and _config_yml_hostname() != expected:
            logger.warning(
                'cloudflared config.yml hostname mismatch — syncing to %s', expected)
            stop_all_cloudflared()
            sync_tunnel_config_from_web()
        cfg_yml = get_cloudflared_dir() / 'config.yml'
        if not cfg_yml.is_file() and not cfg.get('remote_setup_ok'):
            return False
        if not find_cloudflared_exe():
            logger.warning('cloudflared not found — remote tunnel disabled')
            return False
        if not cfg_yml.is_file():
            logger.warning('cloudflared config.yml missing')
            return False
        with self._lock:
            if _cloudflared_running():
                logger.info('cloudflared already running')
                ok = True
            else:
                sync_tunnel_config_from_web()
                ok = self._launch()
            if ok and self._monitor_thread is None:
                self._stop = False
                self._monitor_thread = threading.Thread(
                    target=self._monitor_loop, name='CF-Tunnel-Monitor', daemon=True)
                self._monitor_thread.start()
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
