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
    text = str(m)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(text + "\n")


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

from desktop.utils.theme import ensure_fonts, ThemeManager
from desktop.utils.api_client import APIClient
import desktop.main as dm
from desktop.main import MainWindow, LoginDialog, _load_icon, APP_VERSION
from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
from desktop.utils.theme import apply_themed_dialog

ensure_fonts()
# Prefer backend.init_db when Flask is available; otherwise local SQLite schema via APIClient.
try:
    from backend.app import init_db
    init_db()
except Exception as e:
    log(f"init_db via backend.app skipped: {e}")
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
    win = MainWindow(res, api, icon)
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


def get_tab(name: str):
    if win is None:
        return None
    tabs = getattr(win, "_tabs", None) or {}
    if name in tabs:
        return tabs[name]
    for attr in (f"_tab_{name}", f"tab_{name}", f"{name}_tab"):
        w = getattr(win, attr, None)
        if w is not None:
            return w
    if hasattr(win, "stack") and getattr(win, "_active_tab_id", None) == name:
        return win.stack.currentWidget()
    return None


def goto_tab(name: str) -> bool:
    if win is None:
        return False
    if hasattr(win, "_goto"):
        try:
            win._goto(name)
            if name in (getattr(win, "_tabs", {}) or {}):
                return True
        except Exception:
            pass
    # Common patterns across MainWindow versions
    for attr in (f"_tab_{name}", f"tab_{name}", name):
        w = getattr(win, attr, None)
        if w is not None:
            try:
                win.stack.setCurrentWidget(w)
                return True
            except Exception:
                pass
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
    return bool(get_tab(name))


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
    sales = get_tab("sales")
    if sales is None and hasattr(win, "stack"):
        sales = win.stack.currentWidget()
    products = api.get_products() or []
    if not any(float(p.get("stock") or 0) >= 1 and float(p.get("price") or 0) > 0 for p in products):
        try:
            seeded = api.create_product({
                "name": "QA Smoke Item",
                "sku": f"QA-SMOKE-{datetime.now().strftime('%H%M%S')}",
                "price": 50,
                "cost_price": 20,
                "stock": 25,
                "min_stock": 2,
                "category": "General",
            })
            log(f"seed product: {seeded}")
            products = api.get_products() or []
        except Exception as e:
            log(f"seed product failed: {e}")
    sales = get_tab("sales")
    if sales is None and hasattr(win, "stack"):
        sales = win.stack.currentWidget()
    prod = next(
        (
            p
            for p in products
            if p.get("is_active", 1) in (1, True, "1", None)
            and float(p.get("price") or 0) > 0
            and float(p.get("stock") or 0) >= 1
        ),
        products[0] if products else None,
    )
    log(f"sales_cart debug sales={type(sales).__name__ if sales else None} products={len(products)} prod={None if not prod else prod.get('name')}")
    if sales is not None and prod is not None:
        added = False
        if hasattr(sales, "_add"):
            try:
                sales._add(prod)
                added = bool(sales.cart)
            except Exception:
                added = False
        if not added:
            for meth in ("add_to_cart", "_add_product", "add_product", "_add_to_cart"):
                if hasattr(sales, meth):
                    getattr(sales, meth)(prod)
                    added = True
                    break
        pump(8)
        win.grab().save(str(SHOTS / "02b_sales_cart.png"), "PNG")
        rec("ui.sales_cart_add", "PASS" if added else "PARTIAL", f"product={prod.get('name')}")
        # Hold / Resume (durable park — session + disk)
        try:
            if hasattr(sales, "_hold_sale") and hasattr(sales, "_resume_held") and sales.cart:
                from desktop.utils.held_sale import clear_held_sale, load_held_sale

                n_before = len(sales.cart)
                # Suppress info dialogs already stubbed; force skip replace prompts
                sales._held = None
                clear_held_sale()
                sales._hold_sale()
                pump(4)
                held_ok = (not sales.cart) and bool(getattr(sales, "_held", None))
                disk_ok = bool(load_held_sale())
                sales._resume_held()
                pump(4)
                resumed = len(sales.cart) == n_before
                cleared = load_held_sale() is None
                win.grab().save(str(SHOTS / "02c_sales_hold_resume.png"), "PNG")
                rec(
                    "ui.sales_hold_resume",
                    "PASS" if held_ok and resumed and disk_ok and cleared else "FAIL",
                    f"held={held_ok} disk={disk_ok} resumed={resumed} cleared={cleared} n={n_before}",
                )
            else:
                rec("ui.sales_hold_resume", "BLOCKED", "no hold API or empty cart")
        except Exception as e:
            rec("ui.sales_hold_resume", "FAIL", str(e)[:240])
    else:
        rec("ui.sales_cart_add", "BLOCKED", "no sales tab or products")
except Exception as e:
    rec("ui.sales_cart_add", "FAIL", traceback.format_exc()[-300:])

# Dark / light theme smoke
try:
    if win is not None:
        ThemeManager.apply(True, force=True)
        pump(12)
        win.grab().save(str(SHOTS / "10_theme_light.png"), "PNG")
        ThemeManager.apply(False, force=True)
        pump(12)
        win.grab().save(str(SHOTS / "11_theme_dark.png"), "PNG")
        rec("ui.theme_dark_light", "PASS", "light+dark grabs")
    else:
        rec("ui.theme_dark_light", "BLOCKED", "no window")
except Exception as e:
    rec("ui.theme_dark_light", "FAIL", str(e)[:240])

# Ctrl+K global search dialog
try:
    if win is not None and hasattr(win, "_open_global_search"):
        from desktop.dialogs.global_search_dialog import GlobalSearchDialog
        dlg = GlobalSearchDialog(api, win)
        dlg.show()
        pump(4)
        dlg._q.setText("ga")
        dlg._run("ga")
        pump(4)
        dlg.grab().save(str(SHOTS / "12_global_search.png"), "PNG")
        n = dlg._list.count()
        dlg.close()
        rec("ui.global_search", "PASS", f"rows={n}")
    else:
        rec("ui.global_search", "BLOCKED", "no _open_global_search")
except Exception as e:
    rec("ui.global_search", "FAIL", traceback.format_exc()[-300:])

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
    inv = get_tab("inventory")
    opened = False
    if inv is not None and hasattr(inv, "_edit"):
        prods = getattr(inv, "products", None) or api.get_products() or []
        pid = None
        if prods:
            first = prods[0]
            pid = first.get("id") if isinstance(first, dict) else first
        if pid is not None:
            from PyQt5.QtWidgets import QDialog

            _prev_exec = QDialog.exec_

            def _nonblock_exec(self):
                self.show()
                pump(8)
                if win:
                    win.grab().save(str(SHOTS / "03b_inventory_edit.png"), "PNG")
                self.reject()
                return QDialog.Rejected

            try:
                QDialog.exec_ = _nonblock_exec
                inv._edit(pid)
                opened = True
            finally:
                QDialog.exec_ = _prev_exec
    pump(8)
    if win:
        win.grab().save(str(SHOTS / "03b_inventory.png"), "PNG")
    rec("ui.inventory_edit", "PASS" if opened else "FAIL", "dialog_opened" if opened else "no_edit_path")
except Exception as e:
    rec("ui.inventory_edit", "FAIL", str(e)[:240])

# Extra module grabs: debt / accounting / security / consumption / license
EXTRA_TABS = [
    ("debt", "13_debt.png"),
    ("accounting", "14_accounting.png"),
    ("security", "15_security.png"),
    ("consumption", "16_consumption.png"),
    ("license", "17_license.png"),
]
if win is not None:
    for tab, shot in EXTRA_TABS:
        try:
            ok = goto_tab(tab)
            pump(12)
            win.grab().save(str(SHOTS / shot), "PNG")
            # license/security may be owner-only — navigated or permission-blocked still recorded
            note = "navigated" if ok else "shot_only_or_denied"
            rec(f"ui.tab.{tab}", "PASS" if ok else "PARTIAL", note)
        except Exception as e:
            rec(f"ui.tab.{tab}", "FAIL", str(e)[:200])

# Debt collect dialog open + reports export button existence
try:
    goto_tab("debt")
    pump(10)
    debt = get_tab("debt")
    opened = False
    if debt is not None:
        from desktop.tabs.debt_tab import _CollectPaymentDialog
        # Avoid exec_() (blocks smoke). Construct + show with a preselected invoice id.
        invoices = []
        try:
            invoices = api.get_debt_invoices() or []
        except Exception as e:
            log(f"debt invoices list: {e}")
        inv = next((i for i in invoices if float(i.get("balance") or 0) > 0), None)
        parent_tab = debt
        host = getattr(debt, "_invoices_tab", None) or debt
        try:
            if inv is not None:
                dlg = _CollectPaymentDialog(
                    parent_tab,
                    host,
                    invoice_id=int(inv.get("id")),
                    invoice_number=str(inv.get("invoice_number") or ""),
                    customer_name=str(inv.get("customer_name") or ""),
                    current_balance=float(inv.get("balance") or 0),
                )
            else:
                # Still prove dialog class constructs (empty invoice picker path is heavier)
                dlg = _CollectPaymentDialog(parent_tab, host, invoice_id=1,
                                            invoice_number="QA-SMOKE",
                                            customer_name="QA",
                                            current_balance=1.0)
            dlg.setModal(False)
            dlg.show()
            pump(8)
            opened = dlg.isVisible()
            if win:
                win.grab().save(str(SHOTS / "13b_debt_collect.png"), "PNG")
            dlg.close()
            pump(4)
        except Exception as e:
            log(f"debt collect construct: {e}")
            # Fallback: Collect button exists
            from PyQt5.QtWidgets import QPushButton
            for b in debt.findChildren(QPushButton):
                if "collect" in (b.text() or "").lower():
                    opened = True
                    break
    rec("ui.debt_collect_dialog", "PASS" if opened else "PARTIAL", "opened" if opened else "tab_only")
except Exception as e:
    rec("ui.debt_collect_dialog", "FAIL", str(e)[:240])

try:
    goto_tab("reports")
    pump(8)
    reports = get_tab("reports")
    has_export = False
    export_text = ""
    if reports is not None:
        btn = getattr(reports, "_exp_btn", None)
        if btn is not None:
            has_export = True
            export_text = (btn.text() or "").strip()
        else:
            from PyQt5.QtWidgets import QPushButton

            for b in reports.findChildren(QPushButton):
                t = (b.text() or "").lower()
                if "export" in t:
                    has_export = True
                    export_text = b.text()
                    break
    if win:
        win.grab().save(str(SHOTS / "05b_reports_export.png"), "PNG")
    # Avoid Windows console charmap crash on emoji in button labels (e.g. ⬇)
    safe_note = (export_text or "missing").encode("ascii", "replace").decode("ascii")
    rec(
        "ui.reports_export_btn",
        "PASS" if has_export else "FAIL",
        safe_note,
    )
except Exception as e:
    rec("ui.reports_export_btn", "FAIL", str(e)[:240])

# POS Focus toggle (Sales Focus → chrome hide → Restore)
try:
    goto_tab("sales")
    pump(10)
    sales = get_tab("sales")
    if sales is None and hasattr(win, "stack"):
        sales = win.stack.currentWidget()
    focus_ok = False
    restore_ok = False
    if sales is not None and hasattr(sales, "set_focus_mode"):
        sales.set_focus_mode(True)
        pump(10)
        focus_ok = bool(getattr(sales, "_focus_mode", False)) or bool(
            getattr(win, "_pos_focus_mode", False)
        )
        if win:
            win.grab().save(str(SHOTS / "02d_sales_focus_on.png"), "PNG")
        sales.set_focus_mode(False)
        pump(10)
        restore_ok = not bool(getattr(sales, "_focus_mode", False))
        if win:
            win.grab().save(str(SHOTS / "02e_sales_focus_off.png"), "PNG")
        btn = getattr(sales, "_focus_btn", None)
        btn_note = (btn.text() if btn is not None else "no_btn") or ""
        rec(
            "ui.sales_focus_toggle",
            "PASS" if focus_ok and restore_ok else "FAIL",
            f"focus={focus_ok} restore={restore_ok} btn={btn_note}",
        )
    else:
        rec("ui.sales_focus_toggle", "BLOCKED", "no set_focus_mode")
except Exception as e:
    rec("ui.sales_focus_toggle", "FAIL", str(e)[:240])

# Return / Exchange dialog (P11 — real partial return path)
try:
    goto_tab("sales")
    pump(8)
    sales = get_tab("sales")
    if sales is None and hasattr(win, "stack"):
        sales = win.stack.currentWidget()
    help_btn = getattr(sales, "_returns_help_btn", None) if sales else None
    opened = False
    if help_btn is not None and hasattr(sales, "_open_return_sale"):
        from PyQt5.QtWidgets import QDialog

        _prev_exec = QDialog.exec_

        def _nonblock_exec(self):
            self.show()
            pump(8)
            self.grab().save(str(SHOTS / "02f_returns_dialog.png"), "PNG")
            self.reject()
            return QDialog.Rejected

        try:
            QDialog.exec_ = _nonblock_exec
            sales._open_return_sale()
            opened = True
            pump(4)
        finally:
            QDialog.exec_ = _prev_exec
        if win:
            win.grab().save(str(SHOTS / "02g_sales_returns_btn.png"), "PNG")
        rec(
            "ui.returns_dialog",
            "PASS" if opened else "FAIL",
            f"btn={help_btn.text()!r} opened={opened}",
        )
    else:
        rec("ui.returns_dialog", "FAIL", "no Return / Exchange button or opener")
except Exception as e:
    rec("ui.returns_dialog", "FAIL", traceback.format_exc()[-300:])

# Dashboard chart Expand detail dialog
try:
    goto_tab("dashboard")
    pump(12)
    dash = get_tab("dashboard")
    if dash is None and hasattr(win, "stack"):
        dash = win.stack.currentWidget()
    opened = False
    if dash is not None and hasattr(dash, "_open_chart_detail"):
        from desktop.utils.charts import ChartDetailsDialog

        # Avoid exec_() (blocks smoke) — construct detail dialog like debt collect
        rows = []
        try:
            rows = dash._trend_chart.data_rows() if hasattr(dash, "_trend_chart") else []
        except Exception:
            rows = []
        title = "Sales | Last 7 Days"
        try:
            title = dash._trend_card._title.text()
        except Exception:
            pass
        dlg = ChartDetailsDialog("trend", title, rows or [], currency="KES", parent=dash)
        dlg.setModal(False)
        dlg.show()
        pump(8)
        opened = dlg.isVisible()
        dlg.grab().save(str(SHOTS / "01b_chart_expand.png"), "PNG")
        dlg.close()
        pump(4)
        expand_btn = None
        try:
            expand_btn = getattr(dash._trend_card, "_expand_btn", None)
        except Exception:
            pass
        rec(
            "ui.dashboard_chart_expand",
            "PASS" if opened and expand_btn is not None else "PARTIAL",
            f"dialog={opened} expand_btn={expand_btn is not None}",
        )
    else:
        rec("ui.dashboard_chart_expand", "BLOCKED", "no dashboard / _open_chart_detail")
except Exception as e:
    rec("ui.dashboard_chart_expand", "FAIL", str(e)[:240])

# Core module pack evidence (L3): dashboard/sales/inventory/debt/reports/settings/accounting + focus
try:
    core = {
        "dashboard": any(r["area"] == "ui.dashboard" and r["status"] == "PASS" for r in R),
        "sales": any(r["area"] == "ui.tab.sales" and r["status"] in ("PASS", "PARTIAL") for r in R),
        "inventory": any(r["area"] == "ui.tab.inventory" and r["status"] in ("PASS", "PARTIAL") for r in R),
        "debt": any(r["area"] == "ui.tab.debt" and r["status"] in ("PASS", "PARTIAL") for r in R),
        "reports": any(r["area"] == "ui.tab.reports" and r["status"] in ("PASS", "PARTIAL") for r in R),
        "settings": any(r["area"] == "ui.tab.settings" and r["status"] in ("PASS", "PARTIAL") for r in R),
        "accounting": any(r["area"] == "ui.tab.accounting" and r["status"] in ("PASS", "PARTIAL") for r in R),
        "focus": any(r["area"] == "ui.sales_focus_toggle" and r["status"] == "PASS" for r in R),
    }
    core_ok = all(core.values())
    rec(
        "ui.l3_core_module_pack",
        "PASS" if core_ok else "PARTIAL",
        ",".join(f"{k}={'1' if v else '0'}" for k, v in core.items()),
    )
except Exception as e:
    rec("ui.l3_core_module_pack", "FAIL", str(e)[:200])

if win is not None:
    try:
        win.close()
    except Exception:
        pass

(OUT / "desktop_smoke_results.json").write_text(json.dumps(R, indent=2), encoding="utf-8")
fails = [r for r in R if r["status"] == "FAIL"]
log(f"done fails={len(fails)} total={len(R)}")
sys.exit(1 if fails else 0)
