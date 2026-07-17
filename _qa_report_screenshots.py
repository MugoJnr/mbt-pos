"""Capture Reports / Debt / Inventory / Consumption tab screenshots via Qt."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_OPENGL", "software")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

EVIDENCE = r"c:\Users\mugoj\OneDrive\Desktop\QA_EVIDENCE_REPORTS"
os.makedirs(EVIDENCE, exist_ok=True)

from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget
from PyQt5.QtCore import QTimer


def grab(widget, path: str):
    widget.resize(1280, 820)
    widget.show()
    QApplication.processEvents()
    pix = widget.grab()
    ok = pix.save(path)
    print("Saved" if ok else "FAIL", path, pix.width(), "x", pix.height())


def main():
    app = QApplication(sys.argv)

    from desktop.utils.api_client import APIClient
    from desktop.utils.theme import ThemeManager
    from desktop.tabs.reports_tab import ReportsTab
    from desktop.tabs.debt_tab import DebtTab
    from desktop.tabs.inventory_tab import InventoryTab
    from desktop.tabs.consumption_tab import ConsumptionTab
    from mbt_paths import get_db_path

    api = APIClient()
    try:
        api.login("admin", "admin123")
    except Exception as e:
        print("login:", e)

    user = {
        "user": {
            "username": "admin",
            "role": "admin",
            "full_name": "Admin",
            "tab_permissions": [],
        },
        "username": "admin",
        "role": "admin",
        "full_name": "Admin",
    }
    cfg_getter = lambda: api.get_settings() or {}
    db_path = get_db_path()

    try:
        ThemeManager.apply(False)
    except Exception as e:
        print("theme:", e)

    win = QMainWindow()
    win.setWindowTitle("MBT POS Report Capture")
    win.resize(1360, 900)
    tabs = QTabWidget()
    win.setCentralWidget(tabs)

    reports = ReportsTab(api, user, db_path, cfg_getter)
    debt = DebtTab(api, user, db_path, cfg_getter)
    inv = InventoryTab(api, user, db_path, cfg_getter)
    cons = ConsumptionTab(api, user, db_path, cfg_getter)

    tabs.addTab(reports, "Reports")
    tabs.addTab(debt, "Debt")
    tabs.addTab(inv, "Inventory")
    tabs.addTab(cons, "Consumption")
    win.show()
    QApplication.processEvents()

    for label, w in (
        ("reports", reports),
        ("debt", debt),
        ("inv", inv),
        ("cons", cons),
    ):
        try:
            if hasattr(w, "on_show"):
                w.on_show()
            elif hasattr(w, "refresh"):
                w.refresh()
        except Exception as e:
            print(label, "on_show:", e)
    QApplication.processEvents()

    def shoot():
        tabs.setCurrentWidget(reports)
        QApplication.processEvents()
        grab(win, os.path.join(EVIDENCE, "01_reports_overview.png"))

        for i, name in enumerate(
            ["sales", "line_items", "top_products", "payment", "variance"]
        ):
            for tw in reports.findChildren(QTabWidget):
                if tw.count() >= 5:
                    tw.setCurrentIndex(min(i, tw.count() - 1))
                    QApplication.processEvents()
                    grab(win, os.path.join(EVIDENCE, f"02_reports_{name}.png"))
                    break

        tabs.setCurrentWidget(debt)
        QApplication.processEvents()
        try:
            debt.refresh()
        except Exception:
            pass
        QApplication.processEvents()
        grab(win, os.path.join(EVIDENCE, "03_debt_overview.png"))

        tabs.setCurrentWidget(inv)
        QApplication.processEvents()
        grab(win, os.path.join(EVIDENCE, "04_inventory.png"))

        tabs.setCurrentWidget(cons)
        QApplication.processEvents()
        grab(win, os.path.join(EVIDENCE, "05_consumption.png"))

        try:
            ThemeManager.apply(True)
            if hasattr(reports, "apply_theme"):
                reports.apply_theme(True)
            tabs.setCurrentWidget(reports)
            QApplication.processEvents()
            grab(win, os.path.join(EVIDENCE, "06_reports_light_theme.png"))
        except Exception as e:
            print("light theme:", e)

        print("Screenshot capture complete")
        app.quit()

    QTimer.singleShot(1200, shoot)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
