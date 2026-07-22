"""
MBT POS — Auto Update Engine
MugoByte Technologies | mugobyte.com

Checks GitHub Releases for a newer version, downloads it silently
in the background, verifies SHA-256, and installs when POS is idle.

Flow:
  1. 60s after startup → check GitHub API for latest release
  2. If newer → download installer (resumable) to TEMP / updates folder
  3. Verify SHA-256 (release metadata or sidecar asset)
  4. When idle (no cart/modal/critical UI) → silent install via elevated
     scheduled task helper, then restart only on success
  5. Manual Update button remains as fallback (legacy PCs / missing checksum)

Elevation: installer registers least-privilege task MBT_POS_UpdateHelper
(SYSTEM/Highest, on-demand). Unattended path never prompts UAC.
Legacy installs without the task: one-time UAC on manual install, then
helper can be staged for future silent updates (see docs/UNATTENDED_UPDATES.md).

Never blocks the UI. Never interrupts a sale.
The privileged helper never executes arbitrary commands.
"""
import os
import sys
import json
import re
import time
import uuid
import shutil
import logging
import hashlib
import tempfile
import threading
import urllib.request
import urllib.error
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── GitHub repo — change to your actual repo ──────────────────────────────────
GITHUB_REPO     = "MugoJnr/mbt-pos"
GITHUB_API      = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME      = "MBT_POS_Setup.exe"
CHECKSUM_ASSET_NAMES = (
    'MBT_POS_Setup.exe.sha256',
    'MBT_POS_Setup.sha256',
    'checksums.sha256',
    'SHA256SUMS',
    'checksums.txt',
)
# Broken onefile release — never offer or install (Python DLL error on update)
BLOCKED_VERSIONS = frozenset({'2.3.5'})

# ── Retry / interval settings ─────────────────────────────────────────────────
FIRST_CHECK_DELAY = 60          # seconds after startup
RECHECK_INTERVAL  = 4 * 3600   # recheck every 4 hours
RETRY_INTERVAL    = 15 * 60    # retry sooner after a failed check
DOWNLOAD_TIMEOUT  = 3600        # 1 hour — tolerate very slow shop networks (~12 KB/s)
DOWNLOAD_RETRY_INTERVAL = 30 * 60  # retry failed/partial downloads every 30 min
REQUEST_TIMEOUT   = 15          # API call timeout
FETCH_RETRIES     = 3
MIN_INSTALLER_BYTES = 1_000_000
EXPECTED_INSTALLER_BYTES = 40_000_000  # ~45 MB; used for resume detection
DOWNLOAD_CHUNK = 65536
MAX_DOWNLOAD_ATTEMPTS = 5
INSTALL_FAIL_COOLDOWN_SEC = 6 * 3600
MAX_AUTO_FAILS = 3
HELPER_TASK_NAME = 'MBT_POS_UpdateHelper'
UPDATER_MUTEX_NAME = 'Global\\MBT_POS_UpdateEngine'
INSTALLER_NAME_RE = re.compile(r'^MBT_POS_Setup(_v[\d.]+)?\.exe$', re.IGNORECASE)


def _ensure_ssl_certs():
    """PyInstaller builds need certifi path for HTTPS (GitHub API)."""
    try:
        import certifi
        bundle = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', bundle)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', bundle)
    except Exception:
        pass


# ── Version comparison helper (no external dep needed) ────────────────────────
def _parse_version(v: str) -> tuple:
    """Parse 'v1.2.3' or '1.2.3' into (1, 2, 3) tuple for comparison."""
    v = v.lstrip('v').strip()
    try:
        parts = [int(x) for x in v.split('.')[:3]]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)
    except Exception:
        return (0, 0, 0)


def _version_gt(a: str, b: str) -> bool:
    """Return True if version a is greater than version b."""
    return _parse_version(a) > _parse_version(b)


def _version_lt(a: str, b: str) -> bool:
    """Return True if version a is less than version b."""
    return _parse_version(a) < _parse_version(b)


UPDATE_LOG = os.path.join(tempfile.gettempdir(), 'mbt_update.log')

_MUTEX_HANDLE = None


def _log_update(msg: str):
    try:
        with open(UPDATE_LOG, 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def read_last_install_result() -> str:
    try:
        with open(UPDATE_LOG, encoding='utf-8') as f:
            lines = f.readlines()
        for line in reversed(lines):
            if 'Install OK' in line:
                return 'OK'
            if 'Install FAILED' in line:
                return 'FAILED'
    except Exception:
        pass
    return ''


def read_last_install_error() -> str:
    """Return the most recent install failure detail from mbt_update.log."""
    try:
        with open(UPDATE_LOG, encoding='utf-8') as f:
            lines = f.readlines()
        for line in reversed(lines):
            if 'Install FAILED' in line:
                return line.strip()
    except Exception:
        pass
    return ''


def _read_update_log_tail(n: int = 40) -> list:
    try:
        with open(UPDATE_LOG, encoding='utf-8', errors='replace') as f:
            return f.readlines()[-n:]
    except Exception:
        return []


def _file_has_motw(path: str) -> bool:
    """True if Windows Mark-of-the-Web is still on the file."""
    if sys.platform != 'win32' or not path:
        return False
    try:
        zone = path + ':Zone.Identifier'
        return os.path.exists(zone)
    except Exception:
        return False


def _free_disk_bytes(folder: str) -> int:
    try:
        import shutil
        return shutil.disk_usage(folder).free
    except Exception:
        return 0


def _is_admin() -> bool:
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def diagnose_download_error(exc: Exception, is_online: bool) -> dict:
    """Classify a failed update download and suggest what to do."""
    msg = str(exc).lower()
    if not is_online:
        return {
            'category': 'offline',
            'title': 'No internet connection',
            'message': (
                'MBT POS is offline, so the update could not download.\n\n'
                'Connect this PC to the internet. The app will retry automatically '
                'when the connection returns.'),
            'retry': True,
        }
    if 'timed out' in msg or 'timeout' in msg:
        return {
            'category': 'timeout',
            'title': 'Slow internet — still downloading',
            'message': (
                'The shop internet is slow, so the update is taking longer than usual.\n\n'
                'No action needed. MBT POS keeps trying in the background every '
                '30 minutes and continues where it left off.\n\n'
                'Sales are not affected. The gold Update button appears when the '
                'download is complete.'),
            'retry': True,
        }
    if '403' in msg or '404' in msg or 'github' in msg:
        return {
            'category': 'github_blocked',
            'title': 'Cannot reach GitHub',
            'message': (
                'This PC cannot download updates from GitHub.\n\n'
                'The shop network or antivirus may be blocking github.com.\n'
                'Ask your IT person to allow github.com, or install the update '
                'manually from a USB stick.'),
            'retry': True,
        }
    if 'ssl' in msg or 'certificate' in msg:
        return {
            'category': 'ssl',
            'title': 'Secure connection failed',
            'message': (
                'The update server connection failed (security / SSL error).\n\n'
                'Check the shop internet connection and try again later.'),
            'retry': True,
        }
    if 'permission' in msg or 'access' in msg:
        return {
            'category': 'disk_permission',
            'title': 'Cannot save update file',
            'message': (
                'Windows would not let MBT POS save the update to the temp folder.\n\n'
                'Free some disk space or ask an administrator to check this PC.'),
            'retry': True,
        }
    return {
        'category': 'download_unknown',
        'title': 'Update download failed',
        'message': (
            f'The update could not download.\n\nDetails: {exc}\n\n'
            'MBT POS will retry automatically.'),
        'retry': True,
    }


def diagnose_install_failure(version: str = '') -> dict:
    """Read mbt_update.log and explain the last failed install in plain language."""
    tail = _read_update_log_tail()
    blob = '\n'.join(tail).lower()
    err_line = read_last_install_error()
    ver = version or '?'

    if 'err=1223' in blob or 'canceled' in blob or 'cancelled' in blob:
        return {
            'category': 'uac_denied',
            'title': 'Administrator permission needed',
            'message': (
                f'Update v{ver} was not installed because Windows permission '
                'was denied or cancelled.\n\n'
                'Click the gold Update button again and choose Yes when '
                'Windows asks "Do you want to allow this app to make changes".\n\n'
                'If you do not see that prompt, ask the shop owner to enter '
                'the administrator password.'),
            'retry': True,
        }

    if 'silent install failed' in blob:
        return {
            'category': 'smartscreen',
            'title': 'Windows blocked the update',
            'message': (
                f'Update v{ver}: Windows blocked the silent install.\n\n'
                'Click Update again. If a Windows security window appears, click '
                'More info, then Run anyway.\n\n'
                'MBT POS will also try opening the installer for you automatically.'),
            'retry': True,
        }

    if 'access is denied' in blob or 'err=5' in blob:
        return {
            'category': 'access_denied',
            'title': 'Not enough permission',
            'message': (
                f'Update v{ver}: Windows denied access to Program Files.\n\n'
                'An administrator must approve the update. Click Update again '
                'and choose Yes on the Windows prompt, or ask the shop owner '
                'to run the update.'),
            'retry': True,
        }

    if 'cannot find' in blob or 'not found' in blob or 'does not exist' in blob:
        return {
            'category': 'missing_file',
            'title': 'Update file missing',
            'message': (
                f'Update v{ver}: the installer file was removed — often by '
                'antivirus.\n\n'
                'MBT POS will download it again. If this keeps happening, add '
                'MBT POS to your antivirus exceptions or install from USB.'),
            'retry': True,
        }

    if 'smartscreen' in blob or 'protected your pc' in blob:
        return {
            'category': 'smartscreen',
            'title': 'Windows SmartScreen blocked the update',
            'message': (
                f'Update v{ver}: Windows SmartScreen blocked the installer.\n\n'
                'Click Update again. When Windows shows "Windows protected your PC", '
                'click More info → Run anyway.'),
            'retry': True,
        }

    extra = f'\n\nTechnical detail: {err_line}' if err_line else ''
    return {
        'category': 'install_unknown',
        'title': 'Update could not install',
        'message': (
            f'Update v{ver} did not install successfully.{extra}\n\n'
            'Click the gold Update button to try again.\n'
            'If it keeps failing, download the installer from GitHub on this PC '
            'and run it once manually (same as the first install).'),
        'retry': True,
    }


def preflight_install(installer_path: str) -> dict:
    """
    Check installer before launch. Auto-fix where possible.
    Returns dict: ok, title, message, path (possibly re-staged).
    """
    if not installer_path or not os.path.isfile(installer_path):
        return {
            'ok': False,
            'title': 'Update file not ready',
            'message': (
                'The update installer is missing — antivirus may have removed it.\n\n'
                'Wait a minute for MBT POS to download it again, then click Update.'),
            'path': installer_path,
        }

    size = os.path.getsize(installer_path)
    if size < 1_000_000:
        try:
            os.remove(installer_path)
        except Exception:
            pass
        return {
            'ok': False,
            'title': 'Update file corrupted',
            'message': (
                'The downloaded update file was incomplete.\n\n'
                'MBT POS will download it again automatically.'),
            'path': installer_path,
        }

    folder = os.path.dirname(installer_path) or tempfile.gettempdir()
    if _free_disk_bytes(folder) < 200 * 1024 * 1024:
        return {
            'ok': False,
            'title': 'Not enough disk space',
            'message': (
                'This PC does not have enough free disk space for the update '
                '(about 200 MB needed).\n\n'
                'Free some space, then click Update again.'),
            'path': installer_path,
        }

    # Auto-fix: stage out of TEMP and remove Mark-of-the-Web
    staged = _stage_installer(installer_path)
    if _file_has_motw(staged):
        _unblock_windows_file(staged)
        if _file_has_motw(staged):
            logger.warning('Mark-of-the-Web still present after unblock')

    if not _is_admin():
        return {
            'ok': True,
            'title': '',
            'message': '',
            'path': staged,
            'warn_admin': True,
        }

    return {'ok': True, 'title': '', 'message': '', 'path': staged, 'warn_admin': False}


def format_diagnosis(d: dict) -> str:
    """Plain-text message for QMessageBox."""
    return d.get('message', '')


def _stage_installer(installer_path: str) -> str:
    """Copy installer into allowlisted updates folder and strip MotW."""
    try:
        # Always use AppData brand updates dir so elevated helper allowlist matches
        updates_dir = os.path.join(_brand_data_root(), 'updates')
        os.makedirs(updates_dir, exist_ok=True)
        dest = os.path.join(updates_dir, os.path.basename(installer_path))
        if os.path.normcase(os.path.abspath(installer_path)) != os.path.normcase(os.path.abspath(dest)):
            shutil.copy2(installer_path, dest)
        else:
            dest = installer_path
        _unblock_windows_file(dest)
        return dest
    except Exception as e:
        logger.warning(f'_stage_installer: {e}')
        _unblock_windows_file(installer_path)
        return installer_path


def _unblock_windows_file(path: str):
    """Remove Mark-of-the-Web — Windows blocks silent runs on downloaded files."""
    if sys.platform != 'win32' or not path or not os.path.isfile(path):
        return
    try:
        import subprocess
        ps_path = path.replace("'", "''")
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
             f"Unblock-File -LiteralPath '{ps_path}' -ErrorAction SilentlyContinue; "
             f"$z = '{ps_path}:Zone.Identifier'; "
             f"if (Test-Path -LiteralPath $z) {{ Remove-Item -LiteralPath $z -Force -ErrorAction SilentlyContinue }}"],
            capture_output=True, timeout=20, creationflags=0x08000000)
    except Exception as e:
        logger.warning(f'_unblock_windows_file: {e}')


def acquire_single_instance(mutex_name: str | None = None) -> bool:
    """Return False if another MBT POS instance is already running.

    ``mutex_name`` is for unit tests only; production always uses the
    Global\\MBT_POS_SingleInstance mutex and keeps the process handle alive.
    """
    global _MUTEX_HANDLE
    if sys.platform != 'win32':
        return True
    name = mutex_name or 'Global\\MBT_POS_SingleInstance'
    try:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
        err = ctypes.windll.kernel32.GetLastError()
        if mutex_name is None:
            _MUTEX_HANDLE = handle
        return err != 183  # ERROR_ALREADY_EXISTS
    except Exception as e:
        logger.warning(f'acquire_single_instance: {e}')
        return True


def _version_ge(a: str, b: str) -> bool:
    return _parse_version(a) >= _parse_version(b)


# ── Checksum / path / idle / install-state helpers ─────────────────────────────

def normalize_checksum(value: str | None) -> str:
    from backend.cloud.update_center import normalize_checksum as _norm
    return _norm(value)


def parse_checksum_from_text(text: str | None) -> str:
    from backend.cloud.update_center import parse_checksum_from_text as _parse
    return _parse(text)


def sha256_file(file_path: str) -> str:
    from backend.cloud.update_center import sha256_file as _sha
    return _sha(file_path)


def verify_installer_checksum(file_path: str, expected: str | None) -> tuple[bool, str]:
    """
    Returns (ok, detail). ok=False when checksum missing or mismatch.
    """
    want = normalize_checksum(expected)
    if not want:
        return False, 'missing_checksum'
    if not file_path or not os.path.isfile(file_path):
        return False, 'missing_file'
    try:
        actual = sha256_file(file_path)
    except Exception as e:
        return False, f'hash_error:{e}'
    if actual != want:
        return False, f'checksum_mismatch:{actual}'
    return True, actual


def _brand_data_root() -> str:
    base = (
        os.environ.get('LOCALAPPDATA')
        or os.environ.get('APPDATA')
        or os.path.expanduser('~')
    )
    return os.path.join(base, 'MugoByte', 'MBT POS')


def update_job_path() -> str:
    return os.path.join(_brand_data_root(), 'update_job.json')


def update_job_result_path() -> str:
    return os.path.join(_brand_data_root(), 'update_job_result.json')


def install_state_path() -> str:
    return os.path.join(_brand_data_root(), 'update_install_state.json')


def allowed_installer_roots() -> list[str]:
    roots = [
        os.path.abspath(tempfile.gettempdir()),
        os.path.abspath(os.path.join(_brand_data_root(), 'updates')),
    ]
    prog = os.environ.get('ProgramData') or r'C:\ProgramData'
    roots.append(os.path.abspath(os.path.join(prog, 'MugoByte', 'MBT POS', 'updates')))
    return roots


def is_safe_installer_path(path: str) -> bool:
    """Reject anything that is not an MBT setup EXE under an allowlisted folder."""
    if not path:
        return False
    try:
        full = os.path.abspath(path)
    except Exception:
        return False
    name = os.path.basename(full)
    if not INSTALLER_NAME_RE.match(name):
        return False
    if any(ch in full for ch in ';&|<>`'):
        return False
    full_l = os.path.normcase(full)
    for root in allowed_installer_roots():
        root_l = os.path.normcase(os.path.abspath(root))
        if full_l.startswith(root_l + os.sep) or full_l == root_l:
            return True
    return False


def evaluate_idle_window(
    *,
    has_modal: bool = False,
    has_popup: bool = False,
    cart_items: int = 0,
    critical_operation: bool = False,
    backup_busy: bool = False,
) -> tuple[bool, str]:
    """
    Pure idle gate used by UI and tests.
    Returns (is_idle, reason_if_busy).
    """
    if critical_operation:
        return False, 'critical_operation'
    if has_modal:
        return False, 'modal_dialog'
    if has_popup:
        return False, 'popup'
    if cart_items > 0:
        return False, 'active_cart'
    if backup_busy:
        return False, 'backup_busy'
    return True, ''


def load_install_state() -> dict:
    path = install_state_path()
    try:
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_install_state(state: dict) -> None:
    path = install_state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning('save_install_state: %s', e)


def can_attempt_auto_install(version: str, now: float | None = None) -> tuple[bool, str]:
    """Loop / fail-storm guard for unattended installs."""
    now = time.time() if now is None else now
    ver = (version or '').lstrip('v').strip()
    if not ver:
        return False, 'missing_version'
    if ver in BLOCKED_VERSIONS:
        return False, 'blocked_version'
    st = load_install_state()
    if st.get('in_progress'):
        started = float(st.get('in_progress_started') or 0)
        # Stale lock older than 30 min — allow recovery
        if started and (now - started) < 30 * 60:
            return False, 'install_in_progress'
    if st.get('last_success_version') == ver:
        return False, 'already_installed'
    if st.get('last_attempt_version') == ver and st.get('last_result') == 'failed':
        fails = int(st.get('fail_count') or 0)
        last_t = float(st.get('last_attempt_time') or 0)
        elapsed = (now - last_t) if last_t else INSTALL_FAIL_COOLDOWN_SEC
        if fails >= MAX_AUTO_FAILS and 0 <= elapsed < INSTALL_FAIL_COOLDOWN_SEC:
            return False, 'fail_cooldown'
    return True, ''


def mark_install_started(version: str) -> None:
    st = load_install_state()
    st.update({
        'in_progress': True,
        'in_progress_started': time.time(),
        'last_attempt_version': (version or '').lstrip('v'),
        'last_attempt_time': time.time(),
    })
    save_install_state(st)


def mark_install_finished(version: str, success: bool, error: str = '') -> None:
    st = load_install_state()
    ver = (version or '').lstrip('v')
    prev_ver = st.get('last_attempt_version')
    fail_count = int(st.get('fail_count') or 0)
    if success:
        fail_count = 0
        st['last_success_version'] = ver
        st['last_result'] = 'ok'
    else:
        if prev_ver == ver:
            fail_count += 1
        else:
            fail_count = 1
        st['last_result'] = 'failed'
        st['last_error'] = (error or '')[:500]
    st.update({
        'in_progress': False,
        'in_progress_started': 0,
        'last_attempt_version': ver,
        'last_attempt_time': time.time(),
        'fail_count': fail_count,
    })
    save_install_state(st)


_UPDATER_MUTEX = None


def acquire_updater_lock() -> bool:
    """Prevent concurrent updater download/install engines on this PC."""
    global _UPDATER_MUTEX
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, UPDATER_MUTEX_NAME)
        err = ctypes.windll.kernel32.GetLastError()
        if err == 183:  # already exists — we still get a handle; check ownership
            # ERROR_ALREADY_EXISTS means another process created it
            _UPDATER_MUTEX = handle
            return False
        _UPDATER_MUTEX = handle
        return True
    except Exception as e:
        logger.warning('acquire_updater_lock: %s', e)
        return True


def is_update_helper_registered() -> bool:
    if sys.platform != 'win32':
        return False
    try:
        import subprocess
        r = subprocess.run(
            ['schtasks', '/Query', '/TN', HELPER_TASK_NAME],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000 if sys.platform == 'win32' else 0,
        )
        return r.returncode == 0
    except Exception:
        return False


def find_update_helper_script() -> str:
    """Locate MBT_UpdateHelper.ps1 next to the installed EXE or in deploy/."""
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), 'MBT_UpdateHelper.ps1'))
    try:
        from mbt_paths import get_project_root
        # Dev tree: repo/deploy; frozen data root will not have it
        root = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(root, '..', 'deploy', 'MBT_UpdateHelper.ps1'))
        candidates.append(os.path.join(get_project_root(), 'MBT_UpdateHelper.ps1'))
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, '..', 'deploy', 'MBT_UpdateHelper.ps1'))
    for c in candidates:
        try:
            p = os.path.abspath(c)
            if os.path.isfile(p):
                return p
        except Exception:
            pass
    return ''


def build_helper_register_command(helper_script: str) -> list[str]:
    """PowerShell that registers the on-demand elevated helper task (no always-on service)."""
    ps = helper_script.replace("'", "''")
    name = HELPER_TASK_NAME
    cmd = (
        f"$tn='{name}'; "
        f"$action=New-ScheduledTaskAction -Execute 'powershell.exe' "
        f"-Argument '-NoProfile -ExecutionPolicy Bypass -File \"{ps}\"'; "
        f"$prin=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount "
        f"-RunLevel Highest; "
        f"$set=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName $tn -Action $action -Principal $prin "
        f"-Settings $set -Force | Out-Null"
    )
    return [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd,
    ]


def write_update_job(installer_path: str, sha256: str, version: str) -> str:
    """Write constrained job file for the elevated helper. Returns request_id."""
    if not is_safe_installer_path(installer_path):
        raise ValueError('installer path not allowlisted')
    want = normalize_checksum(sha256)
    if not want:
        raise ValueError('checksum required for elevated job')
    request_id = uuid.uuid4().hex
    job = {
        'request_id': request_id,
        'installer_path': os.path.abspath(installer_path),
        'sha256': want,
        'version': (version or '').lstrip('v'),
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        # Explicitly no command / args field — helper hardcodes /S only
    }
    path = update_job_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    result = update_job_result_path()
    try:
        if os.path.isfile(result):
            os.remove(result)
    except Exception:
        pass
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(job, f, indent=2)
    os.replace(tmp, path)
    return request_id


def read_update_job_result(timeout_sec: float = 0) -> dict:
    path = update_job_result_path()
    deadline = time.time() + max(0, timeout_sec)
    while True:
        try:
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        if time.time() >= deadline:
            return {}
        time.sleep(0.5)


def run_update_helper_task() -> tuple[bool, str]:
    """Trigger the pre-registered elevated helper (no UAC)."""
    import subprocess
    try:
        r = subprocess.run(
            ['schtasks', '/Run', '/TN', HELPER_TASK_NAME],
            capture_output=True, text=True, timeout=60,
            creationflags=0x08000000 if sys.platform == 'win32' else 0,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or 'schtasks_failed').strip()
            return False, err[:300]
        return True, ''
    except Exception as e:
        return False, str(e)


def fetch_sidecar_checksum(asset_url: str, headers: dict) -> str:
    """Download a small .sha256 sidecar next to the installer asset."""
    if not asset_url:
        return ''
    # Try sibling URLs derived from installer URL
    candidates = []
    for suffix in ('.sha256', '.sha256.txt'):
        candidates.append(asset_url + suffix)
    base = asset_url.rsplit('/', 1)[0] if '/' in asset_url else ''
    for name in CHECKSUM_ASSET_NAMES:
        if base:
            candidates.append(f'{base}/{name}')
    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            text = _http_get_text(url, headers)
            got = parse_checksum_from_text(text)
            if got:
                return got
        except Exception:
            continue
    return ''


def _http_get_text(url: str, headers: dict) -> str:
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return ''
        return resp.text or ''
    except Exception:
        pass
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read().decode('utf-8', errors='replace')


def resolve_release_checksum(notes: str, assets: list, asset_url: str,
                             headers: dict, cloud_checksum: str = '') -> str:
    """Prefer cloud → release notes tag → named checksum asset → sidecar URL."""
    for candidate in (
        cloud_checksum,
        parse_checksum_from_text(notes),
    ):
        got = normalize_checksum(candidate)
        if got:
            return got
    for asset in assets or []:
        name = (asset.get('name') or '').lower()
        if name in {n.lower() for n in CHECKSUM_ASSET_NAMES} or name.endswith('.sha256'):
            url = asset.get('browser_download_url') or ''
            if not url:
                continue
            try:
                text = _http_get_text(url, headers)
                got = parse_checksum_from_text(text)
                if got:
                    return got
            except Exception:
                continue
    return fetch_sidecar_checksum(asset_url, headers)


# ── Main updater class ─────────────────────────────────────────────────────────

class UpdateChecker:
    """
    Background update checker. Instantiate once, call start().
    Set callbacks before calling start():
        on_update_available(version, release_notes, asset_url)
        on_download_ready(installer_path, version)
        on_force_required(version, reason)
        on_error(msg)          — optional, for diagnostics tab
        on_install_failed(version, reason)
        on_download_failed(version, title, reason)
        idle_getter() -> bool  — optional; True when safe to auto-install
    """

    def __init__(self, current_version: str, is_online_getter=None,
                 idle_getter: Optional[Callable[[], bool]] = None):
        self.current_version  = current_version.lstrip('v')
        self._is_online       = is_online_getter or (lambda: True)
        self._idle_getter     = idle_getter  # reserved; UI also polls
        self._stop            = threading.Event()
        self._thread          = None
        self._dl_thread       = None
        self._installer_path  = None
        self._pending_version = None
        self._pending_asset_url = ''
        self._pending_checksum = ''
        self._pending_notes = ''
        self._expected_bytes = 0
        self._download_warned_version = ''
        self._has_updater_lock = False
        self._install_lock = threading.Lock()

        # Callbacks — set by caller (MainWindow)
        self.on_update_available = None   # (version, notes, url)
        self.on_download_ready   = None   # (installer_path, version)
        self.on_force_required   = None   # (version, reason)
        self.on_error            = None   # (msg) optional
        self.on_install_failed   = None   # (version, reason)
        self.on_download_failed  = None   # (version, title, reason)

    def start(self):
        self._has_updater_lock = acquire_updater_lock()
        if not self._has_updater_lock:
            logger.warning('Another updater engine is active — skipping start')
            return
        self._check_previous_install()
        logger.info(
            f"UpdateChecker started (v{self.current_version}); "
            f"first check in {FIRST_CHECK_DELAY}s")
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='UpdateChecker')
        self._thread.start()

    def check_now(self):
        """Manual / on-demand check (e.g. from Settings)."""
        threading.Thread(
            target=self._check, daemon=True, name='UpdateCheckerNow'
        ).start()

    def stop(self):
        self._stop.set()

    def get_pending_checksum(self) -> str:
        return self._pending_checksum or ''

    def has_verified_checksum(self) -> bool:
        return bool(normalize_checksum(self._pending_checksum))

    def can_unattended_install(self) -> tuple[bool, str]:
        """Whether silent auto-install is allowed right now (no UAC path)."""
        if not self._installer_path or not os.path.isfile(self._installer_path):
            return False, 'no_installer'
        ver = self._pending_version or ''
        ok, reason = can_attempt_auto_install(ver)
        if not ok:
            return False, reason
        if not normalize_checksum(self._pending_checksum):
            return False, 'missing_checksum'
        ok_hash, detail = verify_installer_checksum(
            self._installer_path, self._pending_checksum)
        if not ok_hash:
            return False, detail
        if not is_update_helper_registered():
            return False, 'helper_not_registered'
        return True, ''

    # ── Core loop ──────────────────────────────────────────────────────────────

    def _check_previous_install(self):
        """
        Show a one-time recovery hint only when the *last* install attempt
        failed AND that version is still newer than what is running now.

        Manual USB/setup installs do not write Install OK into the temp log,
        so a stale FAILED entry used to pop forever after upgrading by hand.
        """
        if read_last_install_result() != 'FAILED':
            return
        try:
            ver = self._pending_version or ''
            if not ver or ver == '?':
                for line in reversed(_read_update_log_tail()):
                    if 'Install FAILED v' in line:
                        try:
                            ver = line.split('Install FAILED v')[1].split()[0].strip()
                        except Exception:
                            pass
                        break
            # Already on this version (or newer) via manual install — clear nag.
            if ver and ver != '?' and not _version_gt(ver, self.current_version):
                _log_update(
                    f'Ignored stale Install FAILED v{ver} '
                    f'(running v{self.current_version} — treating as OK)')
                _log_update(f'Install OK v{self.current_version} (manual / supersede)')
                mark_install_finished(ver, True)
                self._purge_stale_installers()
                return
            if not self.on_install_failed:
                return
            diag = diagnose_install_failure(ver)
            mark_install_finished(ver or '?', False, diag.get('category', 'failed'))
            self.on_install_failed(ver or '?', diag['title'] + '\n\n' + diag['message'])
        except Exception:
            pass

    def _purge_stale_installers(self):
        """Delete cached setup EXEs that are not newer than the running app."""
        import glob
        import re
        roots = [tempfile.gettempdir()]
        try:
            from mbt_paths import get_project_root
            roots.append(os.path.join(get_project_root(), 'updates'))
        except Exception:
            pass
        for root in roots:
            try:
                for path in glob.glob(os.path.join(root, 'MBT_POS_Setup_v*.exe')):
                    m = re.search(r'_v([\d.]+)\.exe$', path, re.I)
                    if not m:
                        continue
                    ver = m.group(1)
                    if ver in BLOCKED_VERSIONS or not _version_gt(ver, self.current_version):
                        try:
                            os.remove(path)
                            logger.info(f'Removed stale installer: {path}')
                        except Exception:
                            pass
            except Exception:
                pass

    def _run(self):
        self._stop.wait(FIRST_CHECK_DELAY)
        last_online = self._is_online()
        while not self._stop.is_set():
            ok = self._check()
            deadline = time.time() + (RECHECK_INTERVAL if ok else RETRY_INTERVAL)
            while time.time() < deadline and not self._stop.is_set():
                self._stop.wait(30)
                now_online = self._is_online()
                if now_online and not last_online:
                    logger.info('Internet reconnected — rechecking for updates')
                    break
                last_online = now_online

    def _check(self) -> bool:
        """Return True when GitHub was reached (even if already up to date)."""
        try:
            logger.info(f"Update check starting (current=v{self.current_version})")
            info = self._fetch_release_info()
            if not info:
                logger.warning("Update check failed — could not reach GitHub releases API")
                return False
            remote_version = info['version']
            min_version    = info.get('min_required_version', '0.0.0')
            notes          = info.get('notes', '')
            asset_url      = info.get('asset_url', '')

            logger.info(
                f"Update check: current={self.current_version} "
                f"remote={remote_version} min={min_version}")

            # Force update if current version is below minimum
            if _version_lt(self.current_version, min_version):
                logger.warning(
                    f"Version {self.current_version} below minimum {min_version} — force update")
                self._pending_checksum = info.get('checksum_sha256') or ''
                if self.on_force_required:
                    self.on_force_required(remote_version,
                        f"Version {self.current_version} is no longer supported. "
                        f"Please update to v{remote_version} to continue.")
                # Still download the update
                if asset_url and _version_gt(remote_version, self.current_version):
                    self._start_download(asset_url, remote_version)
                return True

            # Normal update available
            if _version_gt(remote_version, self.current_version):
                if remote_version in BLOCKED_VERSIONS:
                    logger.warning(
                        f"Skipping blocked release v{remote_version}")
                    return True
                logger.info(f"Update available: v{remote_version}")
                self._pending_checksum = info.get('checksum_sha256') or ''
                self._pending_notes = notes
                if self.on_update_available:
                    self.on_update_available(remote_version, notes, asset_url)
                if asset_url:
                    self._start_download(asset_url, remote_version)
                else:
                    logger.warning(
                        f"Release v{remote_version} has no {ASSET_NAME} asset")
            else:
                logger.info("No newer release — app is up to date")
            return True

        except Exception as e:
            logger.warning(f"UpdateChecker._check: {e}")
            if self.on_error:
                try:
                    self.on_error(str(e))
                except Exception:
                    pass
            return False

    def _fetch_release_info(self) -> dict:
        """
        Fetch latest release from GitHub API.
        Returns dict with keys: version, notes, asset_url, min_required_version,
        checksum_sha256
        """
        _ensure_ssl_certs()
        headers = {
            'Accept':     'application/vnd.github+json',
            'User-Agent': f'MBT-POS/{self.current_version}',
        }
        last_err = None
        cloud_checksum = ''
        try:
            from backend.cloud.update_center import get_update_center
            cloud = get_update_center().check_for_update(self.current_version)
            if cloud:
                cloud_checksum = cloud.get('checksum_sha256') or ''
        except Exception:
            pass

        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                data = self._http_get_json(GITHUB_API, headers)
                if not data:
                    continue
                tag     = data.get('tag_name', '0.0.0')
                version = tag.lstrip('v')
                notes   = data.get('body', '')[:2000]
                assets  = data.get('assets', []) or []

                asset_url = ''
                for asset in assets:
                    if asset.get('name', '').lower() == ASSET_NAME.lower():
                        asset_url = asset.get('browser_download_url', '')
                        size = int(asset.get('size') or 0)
                        if size > MIN_INSTALLER_BYTES:
                            self._expected_bytes = size
                        break

                min_version = '0.0.0'
                if '[min_version:' in notes:
                    try:
                        start = notes.index('[min_version:') + len('[min_version:')
                        end   = notes.index(']', start)
                        min_version = notes[start:end].strip()
                    except Exception:
                        pass

                checksum = resolve_release_checksum(
                    notes, assets, asset_url, headers, cloud_checksum)

                if not asset_url:
                    logger.warning(
                        f"GitHub release v{version} missing asset {ASSET_NAME}")
                if not checksum:
                    logger.warning(
                        f"GitHub release v{version} missing SHA-256 checksum "
                        f"(unattended install will be blocked)")

                return {
                    'version':              version,
                    'notes':                notes,
                    'asset_url':            asset_url,
                    'min_required_version': min_version,
                    'checksum_sha256':      checksum,
                }
            except Exception as e:
                last_err = e
                logger.warning(
                    f"Update API attempt {attempt}/{FETCH_RETRIES} failed: {e}")
                time.sleep(min(attempt * 2, 6))
        if last_err:
            logger.warning(f"Update check gave up: {last_err}")
        return {}

    def _http_get_json(self, url: str, headers: dict) -> dict:
        """HTTPS GET returning parsed JSON — requests first, urllib fallback."""
        try:
            import requests
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as req_err:
            logger.debug(f"requests GET failed, trying urllib: {req_err}")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read())

    def _schedule_download_retry(self, url: str, version: str):
        """Retry a failed or partial download — for slow shop networks."""
        def _retry():
            if self._stop.wait(DOWNLOAD_RETRY_INTERVAL):
                return
            if self._installer_path and os.path.isfile(self._installer_path):
                if os.path.getsize(self._installer_path) >= MIN_INSTALLER_BYTES:
                    return
            if not self._is_online():
                logger.info(f'Update v{version} download retry delayed — offline')
                self._schedule_download_retry(url, version)
                return
            logger.info(f'Retrying update download v{version} (slow network retry)')
            self._start_download(url, version)
        threading.Thread(
            target=_retry, daemon=True, name='UpdateDownloadRetry').start()

    def _notify_download_issue(self, version: str, title: str, message: str):
        """Tell the user once per version — avoid spamming slow networks."""
        if self._download_warned_version == version:
            return
        self._download_warned_version = version
        if self.on_download_failed:
            try:
                self.on_download_failed(version, title, message)
            except Exception:
                pass
        elif self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass

    def _write_download_stream(self, resp, dest: str, append: bool = False) -> int:
        """Stream response body to dest. Returns bytes written."""
        mode = 'ab' if append else 'wb'
        written = 0
        with open(dest, mode) as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
        return written

    def _http_download_file(self, url: str, dest: str, headers: dict) -> int:
        """
        Download with resume support for slow networks.
        Returns total file size after download attempt.
        Stores Content-Length into self._expected_bytes when available.
        """
        existing = os.path.getsize(dest) if os.path.isfile(dest) else 0
        expect = self._expected_bytes or EXPECTED_INSTALLER_BYTES
        can_resume = (
            existing >= MIN_INSTALLER_BYTES
            and (expect <= 0 or existing < expect)
        )
        req_headers = dict(headers)
        if can_resume:
            req_headers['Range'] = f'bytes={existing}-'
            logger.info(
                f'Resuming update download at {existing/1024/1024:.1f} MB')

        try:
            import requests
            timeout = (REQUEST_TIMEOUT, DOWNLOAD_TIMEOUT)
            with requests.get(url, headers=req_headers, stream=True,
                              timeout=timeout) as resp:
                if resp.status_code == 416:
                    if os.path.isfile(dest) and os.path.getsize(dest) >= MIN_INSTALLER_BYTES:
                        return os.path.getsize(dest)
                    os.remove(dest)
                    return self._http_download_file(url, dest, headers)
                if resp.status_code not in (200, 206):
                    resp.raise_for_status()
                cl = resp.headers.get('Content-Length')
                if cl and resp.status_code == 200:
                    try:
                        self._expected_bytes = int(cl)
                    except Exception:
                        pass
                elif cl and resp.status_code == 206 and can_resume:
                    try:
                        # Total size ≈ existing + remaining
                        self._expected_bytes = existing + int(cl)
                    except Exception:
                        pass
                cr = resp.headers.get('Content-Range') or ''
                if '/' in cr:
                    try:
                        total = int(cr.rsplit('/', 1)[-1])
                        if total > MIN_INSTALLER_BYTES:
                            self._expected_bytes = total
                    except Exception:
                        pass
                append = resp.status_code == 206 and can_resume
                if not append and os.path.isfile(dest):
                    existing = 0
                written = 0
                mode = 'ab' if append else 'wb'
                with open(dest, mode) as f:
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                return (existing + written) if append else written
        except Exception as req_err:
            logger.debug(f'requests download failed, trying urllib: {req_err}')

        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            code = getattr(resp, 'status', 200) or 200
            cl = resp.headers.get('Content-Length') if hasattr(resp, 'headers') else None
            if cl and code == 200:
                try:
                    self._expected_bytes = int(cl)
                except Exception:
                    pass
            append = code == 206 and can_resume
            if not append and os.path.isfile(dest):
                existing = 0
            written = self._write_download_stream(resp, dest, append=append)
            return (existing + written) if append else written

    def _download_complete_enough(self, size: int) -> bool:
        expect = self._expected_bytes or EXPECTED_INSTALLER_BYTES
        if expect and expect > MIN_INSTALLER_BYTES:
            return size >= int(expect * 0.98)
        return size >= int(EXPECTED_INSTALLER_BYTES * 0.85)

    def _start_download(self, url: str, version: str):
        """Start background download of the installer."""
        if self._dl_thread and self._dl_thread.is_alive():
            return   # already downloading
        if self._installer_path and os.path.exists(self._installer_path):
            if _version_ge(self.current_version, version):
                logger.info('Cached installer is for current or older version — clearing')
                self.clear_cache()
            else:
                # Re-verify checksum if we have one
                if self._pending_checksum:
                    ok, _ = verify_installer_checksum(
                        self._installer_path, self._pending_checksum)
                    if not ok:
                        logger.warning('Cached installer failed checksum — re-download')
                        self.clear_cache()
                    elif self.on_download_ready:
                        self.on_download_ready(self._installer_path, version)
                        return
                elif self.on_download_ready:
                    self.on_download_ready(self._installer_path, version)
                    return

        self._pending_version = version
        self._pending_asset_url = url
        self._dl_thread = threading.Thread(
            target=self._download, args=(url, version),
            daemon=True, name='UpdateDownload')
        self._dl_thread.start()

    def _download(self, url: str, version: str):
        """
        Download installer to TEMP folder silently (resumable + retries).
        Shows no UI. Signals on_download_ready when complete and verified.
        """
        dest = os.path.join(
            tempfile.gettempdir(),
            f'MBT_POS_Setup_v{version}.exe'
        )

        # Already downloaded in a previous run
        if os.path.isfile(dest):
            size = os.path.getsize(dest)
            if not _version_gt(version, self.current_version):
                try:
                    os.remove(dest)
                    logger.info(f'Removed stale cached installer v{version}')
                except Exception:
                    pass
                return
            if self._download_complete_enough(size):
                if self._pending_checksum:
                    ok, detail = verify_installer_checksum(dest, self._pending_checksum)
                    if not ok:
                        logger.warning(
                            f'Cached installer checksum failed ({detail}) — re-download')
                        try:
                            os.remove(dest)
                        except Exception:
                            pass
                    else:
                        logger.info(f"Installer already cached+verified: {dest}")
                        _unblock_windows_file(dest)
                        self._installer_path = dest
                        if self.on_download_ready:
                            self.on_download_ready(dest, version)
                        return
                else:
                    logger.info(f"Installer already cached: {dest}")
                    _unblock_windows_file(dest)
                    self._installer_path = dest
                    if self.on_download_ready:
                        self.on_download_ready(dest, version)
                    return
            if size >= MIN_INSTALLER_BYTES:
                logger.info(
                    f"Partial update download found ({size/1024/1024:.1f} MB) — resuming")

        logger.info(f"Downloading update v{version} from {url}")
        last_err = None
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            if self._stop.is_set():
                return
            try:
                _ensure_ssl_certs()
                headers = {'User-Agent': f'MBT-POS/{self.current_version}'}
                # Refresh checksum from sidecar if still missing
                if not self._pending_checksum:
                    self._pending_checksum = fetch_sidecar_checksum(url, headers)

                self._http_download_file(url, dest, headers)

                size = os.path.getsize(dest) if os.path.isfile(dest) else 0
                if not self._download_complete_enough(size):
                    logger.warning(
                        f"Update download incomplete attempt {attempt} "
                        f"({size/1024/1024:.1f} MB) — will retry")
                    last_err = TimeoutError('download incomplete')
                    time.sleep(min(attempt * 3, 15))
                    continue

                if self._pending_checksum:
                    ok, detail = verify_installer_checksum(dest, self._pending_checksum)
                    if not ok:
                        logger.error(f'Checksum verification failed: {detail}')
                        try:
                            os.remove(dest)
                        except Exception:
                            pass
                        self._notify_download_issue(
                            version,
                            'Update file failed verification',
                            'The downloaded update did not match the expected '
                            'security checksum and was discarded.\n\n'
                            'MBT POS will retry the download automatically.')
                        _log_update(f'Download BAD checksum v{version}: {detail}')
                        self._schedule_download_retry(url, version)
                        return

                logger.info(f"Update downloaded: {dest} ({size/1024/1024:.1f} MB)")
                self._download_warned_version = ''
                _unblock_windows_file(dest)
                self._installer_path = dest
                if self.on_download_ready:
                    self.on_download_ready(dest, version)
                return

            except Exception as e:
                last_err = e
                logger.warning(
                    f"Update download attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS} failed: {e}")
                partial = os.path.getsize(dest) if os.path.isfile(dest) else 0
                if partial < MIN_INSTALLER_BYTES and os.path.isfile(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                time.sleep(min(attempt * 3, 15))

        diag = diagnose_download_error(
            last_err or RuntimeError('download failed'), self._is_online())
        _log_update(
            f"Download FAILED v{version}: {diag['category']} — {last_err}")
        self._notify_download_issue(version, diag['title'], diag['message'])
        self._schedule_download_retry(url, version)

    # ── Install ────────────────────────────────────────────────────────────────

    def install_and_restart(self, installer_path: str, unattended: bool = False):
        """
        Run the installer silently (/S = NSIS silent mode).

        unattended=True (idle auto-update):
          - Requires SHA-256 checksum
          - Requires pre-registered MBT_POS_UpdateHelper task (no UAC)
          - Rejects missing checksum / missing helper

        unattended=False (manual Update button):
          - Prefers helper when available
          - Falls back to one-time UAC RunAs on legacy PCs
          - Missing checksum allowed only for this manual path (logged)

        Restart happens only after successful install.
        Returns (True, '') on success, (False, error_message) on failure.
        """
        import subprocess

        if not self._install_lock.acquire(blocking=False):
            return False, (
                'An update install is already in progress.\n\n'
                'Wait for it to finish before trying again.')

        try:
            return self._install_and_restart_locked(installer_path, unattended)
        finally:
            try:
                self._install_lock.release()
            except Exception:
                pass

    def _install_and_restart_locked(self, installer_path: str, unattended: bool):
        import subprocess

        version = self._pending_version or ''
        ok_attempt, reason = can_attempt_auto_install(version) if unattended else (True, '')
        if unattended and not ok_attempt:
            return False, (
                f'Automatic update deferred ({reason}).\n\n'
                'Use the Update button if you need to install manually.')

        pre = preflight_install(installer_path)
        if not pre.get('ok'):
            return False, pre.get('title', '') + '\n\n' + pre.get('message', '')

        installer_path = pre.get('path') or installer_path
        self._installer_path = installer_path

        if not is_safe_installer_path(installer_path):
            # Stage into allowlisted updates folder
            installer_path = _stage_installer(installer_path)
            self._installer_path = installer_path
        if not is_safe_installer_path(installer_path):
            return False, (
                'Update installer is not in an allowed folder.\n\n'
                'Download was blocked for safety.')

        if not installer_path or not os.path.exists(installer_path):
            diag = diagnose_install_failure(version)
            return False, diag['title'] + '\n\n' + diag['message']

        checksum = normalize_checksum(self._pending_checksum)
        if checksum:
            ok_hash, detail = verify_installer_checksum(installer_path, checksum)
            if not ok_hash:
                return False, (
                    'Update file failed security verification.\n\n'
                    f'Detail: {detail}\n\n'
                    'The installer will not run. MBT POS will re-download it.')
        elif unattended:
            return False, (
                'Automatic install blocked: release checksum is missing.\n\n'
                'Publish SHA-256 with the GitHub release (notes tag or '
                '.sha256 sidecar). Manual Update may still work as fallback.')
        else:
            logger.warning(
                'Manual install without checksum — legacy/fallback path')
            _log_update(f'Install WARN v{version}: missing checksum (manual)')

        use_helper = is_update_helper_registered()
        if unattended and not use_helper:
            return False, (
                'Automatic install blocked: elevated update helper is not '
                'installed on this PC.\n\n'
                'Click Update once and approve the Windows permission prompt. '
                'That one-time approval stages the helper so future updates '
                'can install silently. See docs/UNATTENDED_UPDATES.md.')

        logger.info(
            f"Installing update: {installer_path} "
            f"unattended={unattended} helper={use_helper}")
        try:
            if getattr(sys, 'frozen', False):
                restart_exe = sys.executable
            else:
                restart_exe = ''

            launcher_script = os.path.join(
                tempfile.gettempdir(), 'mbt_update_launcher.bat')
            pid = os.getpid()
            inst_dir = os.path.dirname(restart_exe) if restart_exe else ''
            install_ver = version or 'unknown'
            update_log = UPDATE_LOG

            if use_helper:
                # Job file + schtasks — no UAC
                try:
                    if not checksum:
                        # Manual + helper still needs checksum for privileged path
                        return False, (
                            'Elevated helper requires a SHA-256 checksum.\n\n'
                            'Re-download the update after the release publishes '
                            'checksum metadata, or install manually from USB.')
                    write_update_job(installer_path, checksum, install_ver)
                except Exception as e:
                    return False, f'Could not prepare update job: {e}'

                lines = [
                    '@echo off',
                    f':: MBT POS unattended update — PID {pid}',
                    f'echo [%date% %time%] Helper install start v{install_ver} >> "{update_log}"',
                    ':waitloop',
                    f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
                    'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitloop )',
                    'taskkill /F /IM MBT_POS.exe >nul 2>&1',
                    'timeout /t 2 /nobreak >nul',
                    ':waitall',
                    'tasklist /FI "IMAGENAME eq MBT_POS.exe" 2>nul | find "MBT_POS.exe" >nul',
                    'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitall )',
                    f'schtasks /Run /TN "{HELPER_TASK_NAME}" >> "{update_log}" 2>&1',
                    'set RUN_ERR=%ERRORLEVEL%',
                    'if %RUN_ERR% neq 0 (',
                    f'  echo [%date% %time%] Install FAILED v{install_ver} err=%RUN_ERR% helper_run >> "{update_log}"',
                    '  goto end',
                    ')',
                    ':: Wait for helper result (up to ~10 minutes)',
                    'set /a waits=0',
                    ':waitresult',
                    f'if exist "%LOCALAPPDATA%\\MugoByte\\MBT POS\\update_job_result.json" goto gotresult',
                    'timeout /t 2 /nobreak >nul',
                    'set /a waits+=1',
                    'if %waits% lss 300 goto waitresult',
                    f'echo [%date% %time%] Install FAILED v{install_ver} err=timeout >> "{update_log}"',
                    'goto end',
                    ':gotresult',
                    f'findstr /C:"\\"ok\\": true" /C:"\\"ok\\":true" "%LOCALAPPDATA%\\MugoByte\\MBT POS\\update_job_result.json" >nul',
                    'if errorlevel 1 (',
                    f'  echo [%date% %time%] Install FAILED v{install_ver} err=helper_result >> "{update_log}"',
                    '  goto end',
                    ')',
                    f'echo [%date% %time%] Install OK v{install_ver} >> "{update_log}"',
                    f'del /f /q "{installer_path}" 2>nul',
                    'timeout /t 3 /nobreak >nul',
                    'for /d %%D in ("%TEMP%\\_MEI*") do rd /s /q "%%D" 2>nul',
                ]
                if restart_exe:
                    lines.append(f'start "" /D "{inst_dir}" "{restart_exe}"')
                lines += [':end', 'del "%~f0"']
            else:
                # Legacy fallback: one-time UAC via RunAs + optionally stage helper
                install_ps1 = os.path.join(tempfile.gettempdir(), 'mbt_run_install.ps1')
                inst_ps = installer_path.replace("'", "''")
                helper_ps = find_update_helper_script().replace("'", "''")
                with open(install_ps1, 'w', encoding='utf-8') as pf:
                    pf.write(
                        '$ErrorActionPreference = "Continue"\n'
                        f'$inst = "{inst_ps}"\n'
                        'if (-not (Test-Path -LiteralPath $inst)) {\n'
                        '  Write-Host "ERROR: installer not found: $inst"\n'
                        '  exit 2\n'
                        '}\n'
                        'Unblock-File -LiteralPath $inst -ErrorAction SilentlyContinue\n'
                        '$zone = "${inst}:Zone.Identifier"\n'
                        'if (Test-Path -LiteralPath $zone) { Remove-Item -LiteralPath $zone -Force -ErrorAction SilentlyContinue }\n'
                        'function Invoke-MbtInstaller([string]$argList) {\n'
                        '  Write-Host "Running installer: $inst $argList"\n'
                        '  try {\n'
                        '    if ($argList) {\n'
                        '      $p = Start-Process -FilePath $inst -ArgumentList $argList `\n'
                        '        -Wait -PassThru -Verb RunAs\n'
                        '    } else {\n'
                        '      $p = Start-Process -FilePath $inst `\n'
                        '        -Wait -PassThru -Verb RunAs\n'
                        '    }\n'
                        '  } catch {\n'
                        '    Write-Host "Start-Process error: $_"\n'
                        '    return 1\n'
                        '  }\n'
                        '  if (-not $p) { Write-Host "UAC denied or process did not start"; return 1223 }\n'
                        '  Write-Host "Installer exit code: $($p.ExitCode)"\n'
                        '  return [int]$p.ExitCode\n'
                        '}\n'
                        '$code = Invoke-MbtInstaller "/S"\n'
                        'if ($code -ne 0) {\n'
                        '  Write-Host "Silent install failed (exit $code), showing installer UI"\n'
                        '  $code = Invoke-MbtInstaller $null\n'
                        '}\n'
                        # Stage helper for future unattended updates (same elevated context)
                        f'$helper = "{helper_ps}"\n'
                        'if ($code -eq 0 -and $helper -and (Test-Path -LiteralPath $helper)) {\n'
                        '  try {\n'
                        f"    $tn = '{HELPER_TASK_NAME}'\n"
                        '    $action = New-ScheduledTaskAction -Execute "powershell.exe" '
                        '-Argument "-NoProfile -ExecutionPolicy Bypass -File `"$helper`""\n'
                        '    $prin = New-ScheduledTaskPrincipal -UserId "SYSTEM" '
                        '-LogonType ServiceAccount -RunLevel Highest\n'
                        '    $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries '
                        '-DontStopIfGoingOnBatteries -StartWhenAvailable '
                        '-MultipleInstances IgnoreNew\n'
                        '    Register-ScheduledTask -TaskName $tn -Action $action '
                        '-Principal $prin -Settings $set -Force | Out-Null\n'
                        '    Write-Host "Registered update helper task"\n'
                        '  } catch { Write-Host "Helper register skipped: $_" }\n'
                        '}\n'
                        'exit $code\n'
                    )
                lines = [
                    '@echo off',
                    f':: MBT POS update launcher (legacy UAC) — PID {pid}',
                    f'echo [%date% %time%] Update launcher started v{install_ver} >> "{update_log}"',
                    ':waitloop',
                    f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
                    'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitloop )',
                    'taskkill /F /IM MBT_POS.exe >nul 2>&1',
                    'timeout /t 2 /nobreak >nul',
                    ':waitall',
                    'tasklist /FI "IMAGENAME eq MBT_POS.exe" 2>nul | find "MBT_POS.exe" >nul',
                    'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitall )',
                    f'powershell -NoProfile -ExecutionPolicy Bypass -File "{install_ps1}" '
                    f'>> "{update_log}" 2>&1',
                    'set INSTALL_ERR=%ERRORLEVEL%',
                    'if %INSTALL_ERR% neq 0 (',
                    f'  echo [%date% %time%] Install FAILED v{install_ver} err=%INSTALL_ERR% >> "{update_log}"',
                    '  goto end',
                    ')',
                    f'echo [%date% %time%] Install OK v{install_ver} >> "{update_log}"',
                    f'del /f /q "{installer_path}" 2>nul',
                    'timeout /t 5 /nobreak >nul',
                    'for /d %%D in ("%TEMP%\\_MEI*") do rd /s /q "%%D" 2>nul',
                ]
                if restart_exe:
                    lines.append(f'start "" /D "{inst_dir}" "{restart_exe}"')
                lines += [':end', 'del "%~f0"']

            with open(launcher_script, 'w') as f:
                f.write('\n'.join(lines))

            mark_install_started(install_ver)
            flags = 0x08000000 if sys.platform == 'win32' else 0
            subprocess.Popen(
                ['cmd', '/c', launcher_script],
                creationflags=flags,
                close_fds=True
            )
            logger.info("Update launcher started — exiting for install")
            return True, ''

        except Exception as e:
            logger.error(f"install_and_restart: {e}")
            mark_install_finished(version, False, str(e))
            diag = diagnose_install_failure(version)
            return False, diag['title'] + '\n\n' + diag['message']

    # ── Public helpers ─────────────────────────────────────────────────────────

    def get_cached_installer(self) -> str:
        """Return path to downloaded installer, or empty string."""
        return self._installer_path or ''

    def get_pending_version(self) -> str:
        """Return version of pending update, or empty string."""
        return self._pending_version or ''

    def clear_cache(self):
        """Delete cached installer file."""
        if self._installer_path and os.path.exists(self._installer_path):
            try:
                os.remove(self._installer_path)
                logger.info("Update cache cleared")
            except Exception as e:
                logger.warning(f"clear_cache: {e}")
        self._installer_path  = None
        self._pending_version = None
        self._pending_checksum = ''
        self._pending_asset_url = ''
        self._expected_bytes = 0
