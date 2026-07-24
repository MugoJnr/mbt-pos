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

from mbt_paths import get_project_root, ensure_data_dirs

PROJECT_ROOT = ensure_data_dirs(get_project_root())

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
    """True when this PC was previously set up and still has a local license.

    Used to skip the mandatory online activation wall when Portal/Supabase are
    unreachable — shops must keep selling offline under grace.
    """
    try:
        from mbt_paths import get_init_flag_path
        initialized = os.path.exists(get_init_flag_path())
    except Exception:
        initialized = False
    has_local = False
    try:
        has_local = bool(
            getattr(engine, 'has_local_license_payload', lambda: False)()
            or engine.store.get('license_token')
        )
    except Exception:
        has_local = False
    if not (initialized or has_local):
        return False
    try:
        if engine.store.get('tampered'):
            return False
        if engine.store.get('revoked') and not getattr(engine, '_license_data', None):
            return False
    except Exception:
        pass
    # Soft offline lock must not block boot — background service re-enforces grace.
    try:
        if engine.store.get('offline_lock'):
            engine.store.set('offline_lock', False)
    except Exception:
        pass
    try:
        if engine.is_valid:
            return True
    except Exception:
        pass
    # Last resort: decryptable, not-yet-expired local payload
    try:
        import time as _time
        data = getattr(engine, '_license_data', None) or {}
        exp = int(data.get('expires_at') or 0)
        if exp and exp > int(_time.time()):
            return True
    except Exception:
        pass
    return bool(initialized and has_local)


def check_license():
    from licensing.license_engine import LicenseEngine
    from licensing.activation_ui import show_activation_screen

    engine = LicenseEngine(PROJECT_ROOT)
    if engine.is_valid:
        return
    if _shop_already_ready(engine):
        return
    if not show_activation_screen(engine.device_id, engine):
        sys.exit(0)
    engine.revalidate()
    if not engine.is_valid and not _shop_already_ready(engine):
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
