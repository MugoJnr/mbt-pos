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

# ── Retry / interval settings ─────────────────────────────────────────────────
FIRST_CHECK_DELAY = 60          # seconds after startup
RECHECK_INTERVAL  = 24 * 3600  # recheck every 24 hours on success
RETRY_INTERVAL    = 15 * 60    # retry sooner after a failed check
DOWNLOAD_TIMEOUT  = 300         # 5 min max download time
REQUEST_TIMEOUT   = 15          # API call timeout
FETCH_RETRIES     = 3


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

    def __init__(self, current_version: str):
        self.current_version  = current_version.lstrip('v')
        self._stop            = threading.Event()
        self._thread          = None
        self._dl_thread       = None
        self._installer_path  = None
        self._pending_version = None

        # Callbacks — set by caller (MainWindow)
        self.on_update_available = None   # (version, notes, url)
        self.on_download_ready   = None   # (installer_path, version)
        self.on_force_required   = None   # (version, reason)
        self.on_error            = None   # (msg) optional

    def start(self):
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

    def _run(self):
        # Wait before first check so app has fully loaded
        self._stop.wait(FIRST_CHECK_DELAY)
        while not self._stop.is_set():
            ok = self._check()
            delay = RECHECK_INTERVAL if ok else RETRY_INTERVAL
            self._stop.wait(delay)

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

    # ── Download ───────────────────────────────────────────────────────────────

    def _start_download(self, url: str, version: str):
        """Start background download of the installer."""
        if self._dl_thread and self._dl_thread.is_alive():
            return   # already downloading
        if self._installer_path and os.path.exists(self._installer_path):
            # Already downloaded — signal ready immediately
            if self.on_download_ready:
                self.on_download_ready(self._installer_path, version)
            return

        self._pending_version = version
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
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            logger.info(f"Installer already cached: {dest}")
            self._installer_path = dest
            if self.on_download_ready:
                self.on_download_ready(dest, version)
            return

        logger.info(f"Downloading update v{version} from {url}")
        try:
            _ensure_ssl_certs()
            headers = {'User-Agent': f'MBT-POS/{self.current_version}'}
            try:
                import requests
                with requests.get(url, headers=headers, stream=True,
                                  timeout=DOWNLOAD_TIMEOUT) as resp:
                    resp.raise_for_status()
                    with open(dest, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
            except Exception:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                    with open(dest, 'wb') as f:
                        shutil.copyfileobj(resp, f, length=65536)

            size = os.path.getsize(dest)
            if size < 1_000_000:
                os.remove(dest)
                logger.error(f"Downloaded file too small ({size} bytes) — discarding")
                return

            logger.info(f"Update downloaded: {dest} ({size/1024/1024:.1f} MB)")
            self._installer_path = dest
            if self.on_download_ready:
                self.on_download_ready(dest, version)

        except Exception as e:
            logger.warning(f"Update download failed: {e}")
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except Exception:
                    pass

    # ── Install ────────────────────────────────────────────────────────────────

    def install_and_restart(self, installer_path: str):
        """
        Run the installer silently (/S = NSIS silent mode).
        Installer replaces the exe in-place, then restarts MBT POS.
        Called from UI thread — launches subprocess and exits immediately.
        """
        import subprocess

        if not installer_path or not os.path.exists(installer_path):
            logger.error(f"Installer not found: {installer_path}")
            return False

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
            lines = [
                '@echo off',
                f':: MBT POS update launcher — PID {pid}',
                ':: Wait for POS to exit',
                f':waitloop',
                f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
                f'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitloop )',
                f':: Install silently',
                f'"{installer_path}" /S',
                f':: Wait for install to finish',
                f'timeout /t 5 /nobreak >nul',
            ]
            if restart_exe:
                lines.append(f':: Restart POS')
                lines.append(f'start "" "{restart_exe}"')
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
            return True

        except Exception as e:
            logger.error(f"install_and_restart: {e}")
            return False

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
