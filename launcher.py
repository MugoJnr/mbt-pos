"""
MBT POS — Launcher
MugoByte Technologies | mugobyte.com
All services are internal threads — no CMD or terminal shown.
"""
import sys
import os

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    if BUNDLE_DIR not in sys.path:
        sys.path.insert(0, BUNDLE_DIR)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == '__main__' and '--repair-license-store' in sys.argv:
    # Runs elevated from the installer. Handled before any per-profile data
    # directory is created so an alternate UAC admin leaves no shop folders.
    import json

    from licensing.license_engine import repair_machine_license_store

    _repair = repair_machine_license_store()
    print(json.dumps(_repair, sort_keys=True))
    raise SystemExit(0 if _repair.get('ok') else 1)

if __name__ == '__main__' and '--license-report' in sys.argv:
    # Support tool for a shop stuck on the activation screen. The license audit
    # log records the real cause, which the cloud side cannot show.
    import json
    import tempfile

    from licensing.license_engine import collect_activation_diagnostics

    _report = collect_activation_diagnostics()
    _out = os.path.join(tempfile.gettempdir(), 'MBT_POS_license_report.json')
    try:
        with open(_out, 'w', encoding='utf-8') as _handle:
            json.dump(_report, _handle, indent=2, sort_keys=True)
        print(f'Report written to: {_out}')
    except OSError as _err:
        print(f'Could not write report file: {_err}')
    print(json.dumps(_report, indent=2, sort_keys=True))
    raise SystemExit(0)

from mbt_paths import get_project_root, ensure_data_dirs

PROJECT_ROOT = ensure_data_dirs(get_project_root())


def _enable_native_crash_log(base_dir: str):
    """Record a stack trace for hard crashes, not just Python exceptions.

    sys.excepthook cannot see Qt/C++ access violations, so a shop reporting
    "it just closes" previously left nothing behind to diagnose. The handle is
    kept open for the life of the process on purpose.
    """
    try:
        import faulthandler

        log_dir = os.path.join(base_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        handle = open(os.path.join(log_dir, 'native_crash.log'),
                      'a', encoding='utf-8')
        handle.write(f'\n=== session started {__import__("datetime").datetime.now()} ===\n')
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        return handle
    except Exception:
        return None


_CRASH_LOG_HANDLE = _enable_native_crash_log(PROJECT_ROOT)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BUNDLE_DIR not in sys.path:
    sys.path.insert(0, BUNDLE_DIR)


def _early_settings_cfg() -> dict:
    try:
        import sqlite3
        from mbt_paths import get_db_path
        path = get_db_path()
        if not os.path.exists(path):
            from config.deploy import shop_settings_defaults
            return shop_settings_defaults()
        db = sqlite3.connect(path)
        rows = db.execute("SELECT key, value FROM system_settings").fetchall()
        db.close()
        return {k: v for k, v in rows}
    except Exception:
        try:
            from config.deploy import shop_settings_defaults
            return shop_settings_defaults()
        except Exception:
            return {}


def _start_cloud_services():
    try:
        from backend.cloud.device_service import get_device_service
        get_device_service(_early_settings_cfg).start_heartbeat()
    except Exception:
        pass

# Hide Windows console window immediately
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

def _ensure_shop_cloud_endpoints():
    """Seed Portal URL + public anon key before license / sign-in UI."""
    try:
        from backend.cloud_backup.paths import ensure_production_cloud_config
        ensure_production_cloud_config(persist=True)
    except Exception:
        pass


# ── License Check ─────────────────────────────────────────────────────────────
def _shop_already_ready(engine) -> bool:
    """True only when LicenseEngine.is_valid allows this PC to open the till.

    A licence file or an already-setup flag is not authorization. This does
    not clear offline_lock. A valid local licence inside the existing offline
    grace rules still reports valid through is_valid. An expired, tampered,
    revoked, or otherwise invalid licence does not.
    """
    try:
        return bool(engine.is_valid)
    except Exception:
        return False


def ensure_licensed() -> bool:
    """Return True only after LicenseEngine.is_valid. Shows activation otherwise.

    Does not treat a raw token or the setup flag as a reason to open the till.
    """
    from licensing.license_engine import LicenseEngine, ensure_license_store_ready
    from licensing.activation_ui import show_activation_screen

    ensure_license_store_ready()
    engine = LicenseEngine(PROJECT_ROOT)
    if engine.is_valid:
        return True
    if not show_activation_screen(engine.device_id, engine):
        return False
    engine.revalidate()
    return bool(engine.is_valid)


def check_license():
    if not ensure_licensed():
        sys.exit(0)


# ── Main Entry Point ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    _ensure_shop_cloud_endpoints()
    # Cloud heartbeats are optional — never block license gate / UI on Portal.
    try:
        _start_cloud_services()
    except Exception:
        pass
    check_license()
    from desktop.main import main
    main()
