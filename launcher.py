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


def _start_telegram_hub():
    try:
        from backend.telegram_hub import start_hub
        start_hub(_early_settings_cfg)
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

# ── License Check ─────────────────────────────────────────────────────────────
def check_license():
    from licensing.license_engine import LicenseEngine
    from licensing.activation_ui import show_activation_screen

    engine = LicenseEngine(PROJECT_ROOT)
    if not engine.is_valid:
        if not show_activation_screen(engine.device_id, engine):
            sys.exit(0)
        engine.revalidate()
        if not engine.is_valid:
            sys.exit(0)

# ── Main Entry Point ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    _start_telegram_hub()
    check_license()
    from desktop.main import main
    main()
