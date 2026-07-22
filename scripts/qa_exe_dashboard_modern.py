"""Capture desktop dashboard and chart-dialog evidence in both themes."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from desktop.tabs.dashboard_tab import DashboardTab
from desktop.utils.api_client import APIClient
from desktop.utils.charts import PaymentBars
from desktop.utils.theme import ThemeManager


OUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "QA_EVIDENCE_EXE_DASHBOARD")
os.makedirs(OUT_DIR, exist_ok=True)

app = QApplication(sys.argv)
api = APIClient()
user = {
    "user": {
        "full_name": "Eugene",
        "username": "admin",
        "role": "superadmin",
        "tab_permissions": [],
    }
}

try:
    result = api.login("admin", "admin123")
    if result and result.get("user"):
        user = {"user": result["user"]}
except Exception as exc:
    print("login_warn", exc)


def config():
    return {"shop_name": "Edmus", "currency_symbol": "KES"}


ThemeManager.apply(False)
dashboard = DashboardTab(api, user, "", config)
dashboard.resize(1366, 768)
dashboard.show()
dashboard.set_light_mode(False)
dashboard.on_show()


def capture_dark():
    path = os.path.join(OUT_DIR, "01_dashboard_dark_1366x768.png")
    dashboard.grab().save(path)
    print("SAVED", path)
    QTimer.singleShot(350, capture_dialog)
    dashboard._trend_card._expand_btn.click()


def capture_dialog():
    dialog = QApplication.activeModalWidget()
    if dialog:
        path = os.path.join(OUT_DIR, "02_sales_chart_dialog.png")
        dialog.grab().save(path)
        print("SAVED", path)
        dialog.accept()
    QTimer.singleShot(1800, capture_payment_dialog)
    dashboard._pay_card._expand_btn.click()


def capture_payment_dialog():
    dialog = QApplication.activeModalWidget()
    if dialog:
        chart = dialog.findChild(PaymentBars)
        if chart:
            chart._anim_pct = [row["pct"] for row in chart._rows]
            chart.update()
            QApplication.processEvents()
        path = os.path.join(OUT_DIR, "03_payment_chart_dialog.png")
        dialog.grab().save(path)
        print("SAVED", path)
        dialog.accept()
    ThemeManager.apply(True)
    dashboard.set_light_mode(True)
    QTimer.singleShot(1800, capture_light)


def capture_light():
    path = os.path.join(OUT_DIR, "04_dashboard_light_1366x768.png")
    dashboard.grab().save(path)
    print("SAVED", path)
    app.quit()


QTimer.singleShot(5000, capture_dark)
app.exec_()
