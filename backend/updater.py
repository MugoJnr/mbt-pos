"""
MBT POS — Auto Update Engine
MugoByte Technologies | mugobyte.com

Checks GitHub Releases for a newer version, downloads it silently
in the background, and signals the UI when ready to install.

Flow:
  1. 60s after startup → check GitHub API for latest release
  2. If newer → download installer to TEMP folder (background thread)
  3. When download complete → emit update_ready signal
  4. UI shows "↓ Update vX.Y.Z" button in topbar
  5. Cashier clicks when convenient → silent install → restart

Never blocks the UI. Never interrupts a sale.
All exceptions are caught and logged silently.
"""
import os
import sys
import json
import time
import shutil
import logging
import hashlib
import tempfile
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ── GitHub repo — change to your actual repo ──────────────────────────────────
GITHUB_REPO     = "MugoJnr/mbt-pos"
GITHUB_API      = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME      = "MBT_POS_Setup.exe"
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
    """Copy installer out of TEMP and strip Mark-of-the-Web before running."""
    try:
        from mbt_paths import get_project_root
        updates_dir = os.path.join(get_project_root(), 'updates')
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


def acquire_single_instance() -> bool:
    """Return False if another MBT POS instance is already running."""
    global _MUTEX_HANDLE
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(
            None, False, 'Global\\MBT_POS_SingleInstance')
        err = ctypes.windll.kernel32.GetLastError()
        return err != 183  # ERROR_ALREADY_EXISTS
    except Exception as e:
        logger.warning(f'acquire_single_instance: {e}')
        return True


def _version_ge(a: str, b: str) -> bool:
    return _parse_version(a) >= _parse_version(b)


# ── Main updater class ─────────────────────────────────────────────────────────

class UpdateChecker:
    """
    Background update checker. Instantiate once, call start().
    Set callbacks before calling start():
        on_update_available(version, release_notes, asset_url)
        on_download_ready(installer_path, version)
        on_force_required(version, reason)
        on_error(msg)          — optional, for diagnostics tab
    """

    def __init__(self, current_version: str, is_online_getter=None):
        self.current_version  = current_version.lstrip('v')
        self._is_online       = is_online_getter or (lambda: True)
        self._stop            = threading.Event()
        self._thread          = None
        self._dl_thread       = None
        self._installer_path  = None
        self._pending_version = None
        self._pending_asset_url = ''
        self._download_warned_version = ''

        # Callbacks — set by caller (MainWindow)
        self.on_update_available = None   # (version, notes, url)
        self.on_download_ready   = None   # (installer_path, version)
        self.on_force_required   = None   # (version, reason)
        self.on_error            = None   # (msg) optional
        self.on_install_failed   = None   # (version, reason)
        self.on_download_failed  = None   # (version, title, reason)

    def start(self):
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
                self._purge_stale_installers()
                return
            if not self.on_install_failed:
                return
            diag = diagnose_install_failure(ver)
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
                    return
                logger.info(f"Update available: v{remote_version}")
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
        Returns dict with keys: version, notes, asset_url, min_required_version
        """
        _ensure_ssl_certs()
        headers = {
            'Accept':     'application/vnd.github+json',
            'User-Agent': f'MBT-POS/{self.current_version}',
        }
        last_err = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                data = self._http_get_json(GITHUB_API, headers)
                if not data:
                    continue
                tag     = data.get('tag_name', '0.0.0')
                version = tag.lstrip('v')
                notes   = data.get('body', '')[:2000]

                asset_url = ''
                for asset in data.get('assets', []):
                    if asset.get('name', '').lower() == ASSET_NAME.lower():
                        asset_url = asset.get('browser_download_url', '')
                        break

                min_version = '0.0.0'
                if '[min_version:' in notes:
                    try:
                        start = notes.index('[min_version:') + len('[min_version:')
                        end   = notes.index(']', start)
                        min_version = notes[start:end].strip()
                    except Exception:
                        pass

                if not asset_url:
                    logger.warning(
                        f"GitHub release v{version} missing asset {ASSET_NAME}")

                return {
                    'version':              version,
                    'notes':                notes,
                    'asset_url':            asset_url,
                    'min_required_version': min_version,
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
        """
        existing = os.path.getsize(dest) if os.path.isfile(dest) else 0
        can_resume = (
            MIN_INSTALLER_BYTES <= existing < EXPECTED_INSTALLER_BYTES)
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
                    # Range not satisfiable — file may be complete or stale
                    if os.path.isfile(dest) and os.path.getsize(dest) >= MIN_INSTALLER_BYTES:
                        return os.path.getsize(dest)
                    os.remove(dest)
                    return self._http_download_file(url, dest, headers)
                if resp.status_code not in (200, 206):
                    resp.raise_for_status()
                append = resp.status_code == 206 and can_resume
                if not append and os.path.isfile(dest):
                    existing = 0
                written = 0
                mode = 'ab' if append else 'wb'
                with open(dest, mode) as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                return (existing + written) if append else written
        except Exception as req_err:
            logger.debug(f'requests download failed, trying urllib: {req_err}')

        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            code = getattr(resp, 'status', 200) or 200
            append = code == 206 and can_resume
            if not append and os.path.isfile(dest):
                existing = 0
            written = self._write_download_stream(resp, dest, append=append)
            return (existing + written) if append else written

    def _start_download(self, url: str, version: str):
        """Start background download of the installer."""
        if self._dl_thread and self._dl_thread.is_alive():
            return   # already downloading
        if self._installer_path and os.path.exists(self._installer_path):
            if _version_ge(self.current_version, version):
                logger.info('Cached installer is for current or older version — clearing')
                self.clear_cache()
            else:
                if self.on_download_ready:
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
        Download installer to TEMP folder silently.
        Shows no UI. Signals on_download_ready when complete.
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
            if size >= int(EXPECTED_INSTALLER_BYTES * 0.85):
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
        try:
            _ensure_ssl_certs()
            headers = {'User-Agent': f'MBT-POS/{self.current_version}'}
            self._http_download_file(url, dest, headers)

            size = os.path.getsize(dest)
            if size < int(EXPECTED_INSTALLER_BYTES * 0.85):
                logger.warning(
                    f"Update download incomplete ({size/1024/1024:.1f} MB) — will retry")
                diag = diagnose_download_error(
                    TimeoutError('download incomplete'), self._is_online())
                _log_update(
                    f"Download partial v{version}: {size} bytes — retry scheduled")
                self._notify_download_issue(version, diag['title'], diag['message'])
                self._schedule_download_retry(url, version)
                return

            logger.info(f"Update downloaded: {dest} ({size/1024/1024:.1f} MB)")
            self._download_warned_version = ''
            _unblock_windows_file(dest)
            self._installer_path = dest
            if self.on_download_ready:
                self.on_download_ready(dest, version)

        except Exception as e:
            logger.warning(f"Update download failed: {e}")
            partial = os.path.getsize(dest) if os.path.isfile(dest) else 0
            if partial < MIN_INSTALLER_BYTES and os.path.isfile(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass
            diag = diagnose_download_error(e, self._is_online())
            _log_update(f"Download FAILED v{version}: {diag['category']} — {e}")
            self._notify_download_issue(version, diag['title'], diag['message'])
            self._schedule_download_retry(url, version)

    # ── Install ────────────────────────────────────────────────────────────────

    def install_and_restart(self, installer_path: str):
        """
        Run the installer silently (/S = NSIS silent mode).
        Installer replaces the exe in-place, then restarts MBT POS.
        Called from UI thread — launches subprocess and exits immediately.
        Returns (True, '') on success, (False, error_message) on preflight failure.
        """
        import subprocess

        pre = preflight_install(installer_path)
        if not pre.get('ok'):
            return False, pre.get('title', '') + '\n\n' + pre.get('message', '')

        installer_path = pre.get('path') or installer_path
        self._installer_path = installer_path

        if not installer_path or not os.path.exists(installer_path):
            diag = diagnose_install_failure(self._pending_version or '')
            return False, diag['title'] + '\n\n' + diag['message']

        logger.info(f"Installing update: {installer_path}")
        try:
            # Get current exe path so we can restart after install
            if getattr(sys, 'frozen', False):
                restart_exe = sys.executable
            else:
                restart_exe = ''

            # Build a small launcher script that:
            #   1. Waits for current process to exit
            #   2. Runs installer silently
            #   3. Restarts the POS
            launcher_script = os.path.join(
                tempfile.gettempdir(), 'mbt_update_launcher.bat')

            pid = os.getpid()
            inst_dir = os.path.dirname(restart_exe) if restart_exe else ''
            install_ver = self._pending_version or 'unknown'
            install_ps1 = os.path.join(tempfile.gettempdir(), 'mbt_run_install.ps1')
            inst_ps = installer_path.replace("'", "''")
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
                    'function Invoke-MbtInstaller([string]$args) {\n'
                    '  Write-Host "Running installer: $inst $args"\n'
                    '  try {\n'
                    '    if ($args) {\n'
                    '      $p = Start-Process -FilePath $inst -ArgumentList $args `\n'
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
                    'exit $code\n'
                )
            update_log = UPDATE_LOG
            lines = [
                '@echo off',
                f':: MBT POS update launcher — PID {pid}',
                f'echo [%date% %time%] Update launcher started v{install_ver} >> "{update_log}"',
                ':: Wait for POS to exit',
                ':waitloop',
                f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
                'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitloop )',
                'taskkill /F /IM MBT_POS.exe >nul 2>&1',
                'timeout /t 2 /nobreak >nul',
                ':waitall',
                'tasklist /FI "IMAGENAME eq MBT_POS.exe" 2>nul | find "MBT_POS.exe" >nul',
                'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitall )',
                ':: Install silently (elevated — required for Program Files)',
                f'powershell -NoProfile -ExecutionPolicy Bypass -File "{install_ps1}" '
                f'>> "{update_log}" 2>&1',
                'set INSTALL_ERR=%ERRORLEVEL%',
                'if %INSTALL_ERR% neq 0 (',
                f'  echo [%date% %time%] Install FAILED v{install_ver} err=%INSTALL_ERR% >> "{update_log}"',
                ')',
                'if %INSTALL_ERR% equ 0 (',
                f'  echo [%date% %time%] Install OK v{install_ver} >> "{update_log}"',
                f'  del /f /q "{installer_path}" 2>nul',
                ')',
                'timeout /t 5 /nobreak >nul',
                'for /d %%D in ("%TEMP%\\_MEI*") do rd /s /q "%%D" 2>nul',
            ]
            if restart_exe:
                lines.append(':: Restart POS (always — even if install failed)')
                lines.append(f'start "" /D "{inst_dir}" "{restart_exe}"')
            lines.append(':: Clean up this script')
            lines.append(f'del "%~f0"')

            with open(launcher_script, 'w') as f:
                f.write('\n'.join(lines))

            # Run the launcher hidden — it will wait for us to exit
            flags = 0
            if sys.platform == 'win32':
                flags = 0x08000000   # CREATE_NO_WINDOW
            subprocess.Popen(
                ['cmd', '/c', launcher_script],
                creationflags=flags,
                close_fds=True
            )

            logger.info("Update launcher started — exiting for install")
            return True, ''

        except Exception as e:
            logger.error(f"install_and_restart: {e}")
            diag = diagnose_install_failure(self._pending_version or '')
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
