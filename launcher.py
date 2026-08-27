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
    decryptable = False
    try:
        from licensing.license_engine import _read_raw_license_token, _resolve_inner_license_token
        inner, _ = _resolve_inner_license_token()
        has_local = bool(
            inner
            or getattr(engine, 'has_local_license_payload', lambda: False)()
            or _read_raw_license_token()
        )
        decryptable = bool(
            inner
            or getattr(engine, '_license_data', None)
            or getattr(engine, 'has_local_license_payload', lambda: False)()
        )
    except Exception:
        has_local = False
        decryptable = False
    if not (initialized or has_local):
        return False
    try:
        # Stale tamper flags from clock rollback must not force re-activation
        # when a license token is still on disk for this PC.
        if engine.store.get('tampered') and has_local and not decryptable:
            try:
                engine.store.set('tampered', False)
                engine.revalidate()
                decryptable = bool(
                    getattr(engine, '_license_data', None)
                    or getattr(engine, 'has_local_license_payload', lambda: False)()
                )
            except Exception:
                pass
        if engine.store.get('tampered') and not decryptable:
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
    # Raw/decryptable local token is enough — init flag can be missing after
    # a reinstall, but the shop must not be sent back to the activation wall.
    return bool(has_local or initialized)


def check_license():
    from licensing.license_engine import LicenseEngine, ensure_license_store_ready
    from licensing.activation_ui import show_activation_screen

    ensure_license_store_ready()
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
