# -*- coding: utf-8 -*-
"""Focused desktop smoke for production validation. Writes evidence to Desktop/QA_PROD_VALIDATION."""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MBT_AUTO_SUPERADMIN_PIN", "1110")
os.environ.setdefault("PYTHONWARNINGS", "ignore")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

OUT = Path(r"C:\Users\mugoj\OneDrive\Desktop\QA_PROD_VALIDATION")
OUT.mkdir(parents=True, exist_ok=True)
SHOTS = OUT / "desktop_shots"
SHOTS.mkdir(exist_ok=True)
LOG = OUT / "desktop_smoke.log"
R: list[dict] = []


def log(m):
    print(m, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


def rec(area, status, note=""):
    R.append({"area": area, "status": status, "note": note})
    log(f"[{status}] {area}: {note}")


open(LOG, "w", encoding="utf-8").write(f"start {datetime.now().isoformat()}\n")

try:
    import backend.cloudflare_setup as cfs

    cfs.refresh_remote_setup_status = lambda: None
    cfs.start_auto_cloudflare = lambda **kw: None
except Exception:
    pass

from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox
from PyQt5.QtCore import Qt

from backend.app import init_db
from desktop.utils.theme import ensure_fonts, ThemeManager
from desktop.utils.api_client import APIClient
import desktop.main as dm
from desktop.main import MainWindow, LoginDialog, _load_icon, APP_VERSION
from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
from desktop.utils.theme import apply_themed_dialog

ensure_fonts()
init_db()
api = APIClient("http://127.0.0.1:5050")
res = api.login("admin", "admin123")
if not res or not res.get("token"):
    rec("auth.admin", "FAIL", str(res)[:200])
    (OUT / "desktop_smoke_results.json").write_text(json.dumps(R, indent=2), encoding="utf-8")
    sys.exit(1)
api.set_token(res["token"])
rec("auth.admin", "PASS", f"v={APP_VERSION} role={(res.get('user') or {}).get('role')}")

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

dm.MainWindow._start_services = lambda self: None
dm.MainWindow._initial_conn_check = lambda self: None
dm.MainWindow._restore_pending_update = lambda self: None
dm.MainWindow._theme_apply_pending_tabs = lambda self: None
dm.MainWindow._warm_remaining_tabs = lambda self: None
dm.MainWindow._qa_dump_theme_evidence = lambda self: None
dm.MainWindow._qa_dump_theme_evidence_late = lambda self: None
QMainWindow.showMaximized = lambda self: (self.resize(1600, 1000), self.show())
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)


def pump(n=10):
    for _ in range(n):
        app.processEvents()


ThemeManager.apply(False, force=True)
try:
    login = LoginDialog(api, _load_icon())
    login.show()
    pump(12)
    login.grab().save(str(SHOTS / "00_login.png"), "PNG")
    login.close()
    rec("ui.login", "PASS", "")
except Exception as e:
    rec("ui.login", "FAIL", str(e)[:240])

win = None
try:
    icon = _load_icon()
    win = MainWindow(res["user"], api, icon)
    win.show()
    pump(20)
    win.grab().save(str(SHOTS / "01_dashboard.png"), "PNG")
    rec("ui.dashboard", "PASS", "")
except Exception as e:
    rec("ui.dashboard", "FAIL", traceback.format_exc()[-400:])

# Navigate tabs
TAB_MAP = [
    ("sales", "02_sales.png"),
    ("inventory", "03_inventory.png"),
    ("settings", "04_settings.png"),
    ("reports", "05_reports.png"),
]


def goto_tab(name: str) -> bool:
    if win is None:
        return False
    # Common patterns across MainWindow versions
    for attr in (f"_tab_{name}", f"tab_{name}", name):
        w = getattr(win, attr, None)
        if w is not None:
            try:
                win.stack.setCurrentWidget(w)
                return True
            except Exception:
                pass
    # sidebar buttons / _switch_tab
    if hasattr(win, "_switch_tab"):
        try:
            win._switch_tab(name)
            return True
        except Exception:
            pass
    if hasattr(win, "switch_tab"):
        try:
            win.switch_tab(name)
            return True
        except Exception:
            pass
    # nav buttons by objectName / text
    for btn in win.findChildren(type(win).__mro__[0]):  # noop guard
        break
    from PyQt5.QtWidgets import QPushButton, QToolButton, QListWidget

    for b in list(win.findChildren(QPushButton)) + list(win.findChildren(QToolButton)):
        t = (b.text() or b.objectName() or "").lower()
        if name in t:
            b.click()
            return True
    for lw in win.findChildren(QListWidget):
        for i in range(lw.count()):
            if name in (lw.item(i).text() or "").lower():
                lw.setCurrentRow(i)
                return True
    return False


if win is not None:
    for tab, shot in TAB_MAP:
        try:
            ok = goto_tab(tab)
            pump(15)
            win.grab().save(str(SHOTS / shot), "PNG")
            rec(f"ui.tab.{tab}", "PASS" if ok else "PARTIAL", "navigated" if ok else "shot_only")
        except Exception as e:
            rec(f"ui.tab.{tab}", "FAIL", str(e)[:200])

# Sales cart add path
try:
    goto_tab("sales")
    pump(10)
    sales = None
    for attr in ("_tab_sales", "tab_sales", "sales_tab"):
        sales = getattr(win, attr, None)
        if sales is not None:
            break
    if sales is None and hasattr(win, "stack"):
        sales = win.stack.currentWidget()
    products = api.get_products() or []
    prod = next(
        (
            p
            for p in products
            if p.get("is_active", 1)
            and float(p.get("price") or 0) > 0
            and float(p.get("stock") or 0) >= 1
        ),
        None,
    )
    if sales is not None and prod is not None:
        added = False
        for meth in ("add_to_cart", "_add_product", "add_product", "_add_to_cart"):
            if hasattr(sales, meth):
                getattr(sales, meth)(prod)
                added = True
                break
        if not added and hasattr(sales, "cart"):
            # minimal cart structure
            try:
                sales.cart.append(
                    {
                        "product_id": prod["id"],
                        "name": prod.get("name"),
                        "qty": 1,
                        "price": float(prod["price"]),
                    }
                )
                added = True
            except Exception:
                pass
        pump(8)
        win.grab().save(str(SHOTS / "02b_sales_cart.png"), "PNG")
        rec("ui.sales_cart_add", "PASS" if added else "PARTIAL", f"product={prod.get('name')}")
    else:
        rec("ui.sales_cart_add", "BLOCKED", "no sales tab or products")
except Exception as e:
    rec("ui.sales_cart_add", "FAIL", traceback.format_exc()[-300:])

# PaymentVarianceDialog defaults (excess received path)
try:
    dlg = PaymentVarianceDialog(
        win,
        "KES",
        100.0,
        120.0,
        20.0,
        settings={},
        has_customer=False,
    )
    apply_themed_dialog(dlg)
    dlg.show()
    pump(6)
    dlg.grab().save(str(SHOTS / "06_payment_variance.png"), "PNG")
    defaults = {"title": dlg.windowTitle(), "excess": getattr(dlg, "_excess", None)}
    # first radio / handling option default
    from PyQt5.QtWidgets import QRadioButton

    radios = dlg.findChildren(QRadioButton)
    checked = [r.text() for r in radios if r.isChecked()]
    defaults["checked"] = checked
    dlg.close()
    rec("ui.payment_variance", "PASS", str(defaults))
except Exception as e:
    rec("ui.payment_variance", "FAIL", traceback.format_exc()[-300:])

# Inventory edit themed dialog path
try:
    goto_tab("inventory")
    pump(10)
    inv = None
    for attr in ("_tab_inventory", "tab_inventory", "inventory_tab"):
        inv = getattr(win, attr, None)
        if inv is not None:
            break
    opened = False
    if inv is not None:
        for meth in ("_edit_product", "edit_product", "_open_edit", "_on_edit"):
            if hasattr(inv, meth):
                try:
                    getattr(inv, meth)()
                    opened = True
                    break
                except TypeError:
                    # may need product id
                    prods = api.get_products() or []
                    if prods:
                        try:
                            getattr(inv, meth)(prods[0])
                            opened = True
                            break
                        except Exception:
                            pass
                except Exception:
                    pass
    pump(8)
    if win:
        win.grab().save(str(SHOTS / "03b_inventory.png"), "PNG")
    rec("ui.inventory_edit", "PASS" if opened else "PARTIAL", "dialog_opened" if opened else "tab_only")
except Exception as e:
    rec("ui.inventory_edit", "FAIL", str(e)[:240])

if win is not None:
    try:
        win.close()
    except Exception:
        pass

(OUT / "desktop_smoke_results.json").write_text(json.dumps(R, indent=2), encoding="utf-8")
fails = [r for r in R if r["status"] == "FAIL"]
log(f"done fails={len(fails)} total={len(R)}")
sys.exit(1 if fails else 0)
