"""Capture desktop tabs + Settings screenshots for Claude system gate."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Prefer isolated QA demo shop (never mutate production AppData during capture)
_QA = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS QA"
if not os.environ.get("MBT_DATA_ROOT") and (_QA / "data" / "mbt_pos.db").is_file():
    os.environ["MBT_DATA_ROOT"] = str(_QA)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MBT_SESSION_IDLE_SEC", "0")
os.environ.setdefault("MBT_AUTO_SUPERADMIN_PIN", "1110")
os.environ.setdefault("MBT_QA_ALLOW_DEV_BOOTSTRAP", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

OUT = ROOT / "_qa_full_system_polish" / "desktop_iter24" / "system"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    from PyQt5.QtWidgets import QApplication, QMessageBox, QMainWindow, QTabWidget
    from PyQt5.QtGui import QIcon

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

    from desktop.utils.theme import ensure_fonts, ThemeManager
    from desktop.utils.api_client import APIClient
    import desktop.main as dm
    from desktop.main import MainWindow, _load_icon

    ensure_fonts()
    try:
        ThemeManager.apply(False, force=True)
    except Exception:
        pass

    try:
        from backend.app import init_db
        init_db()
    except Exception as e:
        print("init_db skip", e, flush=True)

    api = APIClient("http://127.0.0.1:5050")
    user = {
        "id": 1,
        "username": "admin",
        "role": "superadmin",
        "full_name": "QA",
        "token": "qa",
        "permissions": ["*"],
    }
    from _qa_local_auth import qa_login
    try:
        res = qa_login(api)
        if res and res.get("token"):
            api.set_token(res["token"])
            user = res.get("user") or user
            if isinstance(user, dict):
                user = dict(user)
                user["token"] = res["token"]
            print("LOGIN ok", flush=True)
        else:
            print("LOGIN skip", res, flush=True)
            res = user
    except Exception as e:
        print("LOGIN fail", e, flush=True)
        res = user

    dm.MainWindow._start_services = lambda self: None
    dm.MainWindow._initial_conn_check = lambda self: None
    dm.MainWindow._restore_pending_update = lambda self: None
    dm.MainWindow._warm_remaining_tabs = lambda self: None
    QMainWindow.showMaximized = lambda self: (self.resize(1600, 1000), self.show())

    try:
        icon = _load_icon()
    except Exception:
        icon = QIcon()

    # walkthrough uses MainWindow(res, api, icon) where res is login payload
    win = MainWindow(res if isinstance(res, dict) else user, api, icon)
    win.resize(1600, 1000)
    win.show()
    for _ in range(20):
        app.processEvents()

    ALL_TABS = [
        "dashboard", "sales", "inventory", "consumption", "debt", "accounting",
        "reports", "notes", "ai_ops", "admin", "settings", "security", "license",
        "diagnostics",
    ]

    def shot(name: str):
        for _ in range(8):
            app.processEvents()
        path = OUT / f"{name}.png"
        win.grab().save(str(path), "PNG")
        print("SAVED", path.name, path.stat().st_size, flush=True)

    shot("01_dashboard")
    for tid in ALL_TABS:
        try:
            if hasattr(win, "_goto"):
                win._goto(tid)
            for _ in range(12):
                app.processEvents()
            # Prefer a selected row so sparse empty-states don't dominate shots
            try:
                tab = None
                if hasattr(win, "_tabs"):
                    tab = win._tabs.get(tid)
                if tid == "notes" and tab is not None:
                    if hasattr(tab, "_list") and tab._list.count() > 0:
                        tab._list.setCurrentRow(0)
                    if hasattr(tab, "refresh"):
                        tab.refresh()
                if tid in ("admin",) and tab is not None and hasattr(tab, "_tbl"):
                    if tab._tbl.rowCount() > 0:
                        tab._tbl.selectRow(0)
                if tid == "debt" and tab is not None and hasattr(tab, "refresh"):
                    tab.refresh()
                if tid in ("dashboard", "accounting", "reports") and tab is not None:
                    if hasattr(tab, "refresh"):
                        tab.refresh()
                    elif hasattr(tab, "on_show"):
                        tab.on_show()
                # Settings: keep fold-cue visible (top of page) — Jump scroll-spy sticky above
                if tid == "settings" and tab is not None:
                    try:
                        if hasattr(tab, "_update_settings_fold_cue"):
                            tab._update_settings_fold_cue()
                        for _ in range(4):
                            app.processEvents()
                    except Exception as e:
                        print("settings cue fail", e, flush=True)
            except Exception as e:
                print("enrich fail", tid, e, flush=True)
            for _ in range(10):
                app.processEvents()
            shot(f"tab_{tid}")
        except Exception as e:
            print("tab fail", tid, e, flush=True)

    # Also grab any QTabWidget indices if present
    for tw in win.findChildren(QTabWidget):
        for i in range(tw.count()):
            try:
                tw.setCurrentIndex(i)
                for _ in range(6):
                    app.processEvents()
                label = tw.tabText(i)
                safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label).strip("_") or f"i{i}"
                shot(f"qtab_{i:02d}_{safe}")
            except Exception:
                pass

    print("DONE", OUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
