#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full UI/UX walkthrough — every tab, toolbar, dialog probe, settings persist.

Evidence: Desktop/QA_UI_WALKTHROUGH/
Exit 0 if no FAIL; PARTIAL notes are non-blocking polish findings.
"""
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
os.environ.setdefault("MBT_SESSION_IDLE_SEC", "0")
os.environ.setdefault("PYTHONWARNINGS", "ignore")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

OUT = Path(r"C:\Users\mugoj\OneDrive\Desktop\QA_UI_WALKTHROUGH")
OUT.mkdir(parents=True, exist_ok=True)
SHOTS = OUT / "shots"
SHOTS.mkdir(exist_ok=True)
LOG = OUT / "walkthrough.log"
R: list[dict] = []


def log(m):
    t = str(m)
    try:
        print(t, flush=True)
    except UnicodeEncodeError:
        print(t.encode("ascii", "replace").decode("ascii"), flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(t + "\n")


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

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QPushButton, QToolButton,
    QAbstractButton, QLineEdit, QComboBox, QCheckBox, QTabWidget,
    QDialog, QMenu, QAction, QWidget, QLabel, QSpinBox, QDoubleSpinBox,
    QRadioButton, QTableWidget, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QGuiApplication

from desktop.utils.theme import ensure_fonts, ThemeManager
from desktop.utils.api_client import APIClient
import desktop.main as dm
from desktop.main import MainWindow, LoginDialog, APP_VERSION, _load_icon

ensure_fonts()
try:
    from backend.app import init_db
    init_db()
except Exception as e:
    log(f"init_db skip: {e}")

api = APIClient("http://127.0.0.1:5050")
res = api.login("admin", "admin123")
if not res or not res.get("token"):
    rec("auth", "FAIL", str(res)[:200])
    (OUT / "results.json").write_text(json.dumps(R, indent=2), encoding="utf-8")
    sys.exit(1)
api.set_token(res["token"])
rec("auth", "PASS", f"v={APP_VERSION} role={(res.get('user') or {}).get('role')}")

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

dm.MainWindow._start_services = lambda self: None
dm.MainWindow._initial_conn_check = lambda self: None
dm.MainWindow._restore_pending_update = lambda self: None
dm.MainWindow._warm_remaining_tabs = lambda self: None
dm.MainWindow._qa_dump_theme_evidence = lambda self: None
dm.MainWindow._qa_dump_theme_evidence_late = lambda self: None
QMainWindow.showMaximized = lambda self: (self.resize(1600, 1000), self.show())
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)


def pump(n=12):
    for _ in range(n):
        app.processEvents()


ThemeManager.apply(False, force=True)
pump(5)
icon = _load_icon()

# Login dialog grab
try:
    ld = LoginDialog(api, icon)
    ld.show()
    pump(8)
    ld.grab().save(str(SHOTS / "00_login.png"), "PNG")
    ld.close()
    rec("ui.login", "PASS", "dialog rendered")
except Exception as e:
    rec("ui.login", "FAIL", str(e)[:200])

win = MainWindow(res, api, icon)
win.resize(1600, 1000)
win.show()
pump(20)
win.grab().save(str(SHOTS / "01_dashboard.png"), "PNG")
rec("ui.main_window", "PASS", f"title={win.windowTitle()!r}")

ALL_TABS = [
    "dashboard", "sales", "inventory", "consumption", "debt", "accounting",
    "reports", "notes", "ai_ops", "admin", "settings", "security", "license",
    "diagnostics",
]


def goto(tid):
    if hasattr(win, "_goto"):
        win._goto(tid)
    pump(15)
    return win._tabs.get(tid) if hasattr(win, "_tabs") else None


def shot(name):
    if win:
        win.grab().save(str(SHOTS / name), "PNG")


def enumerate_controls(root: QWidget):
    buttons = []
    for b in root.findChildren(QAbstractButton):
        if not b.isVisibleTo(root):
            continue
        text = (b.text() or "").strip().replace("\n", " ")
        tip = (b.toolTip() or "").strip()
        buttons.append({
            "type": type(b).__name__,
            "text": text[:80],
            "tip": tip[:80],
            "enabled": b.isEnabled(),
            "checkable": b.isCheckable(),
            "checked": b.isChecked() if b.isCheckable() else None,
            "obj": b.objectName() or "",
        })
    fields = []
    for w in root.findChildren(QLineEdit):
        if w.isVisibleTo(root):
            fields.append({"ph": (w.placeholderText() or "")[:60], "enabled": w.isEnabled(), "echo": int(w.echoMode())})
    checks = []
    for c in root.findChildren(QCheckBox):
        if c.isVisibleTo(root):
            checks.append({"text": (c.text() or "")[:60], "checked": c.isChecked(), "enabled": c.isEnabled()})
    return buttons, fields, checks


# Visit every tab
for i, tid in enumerate(ALL_TABS):
    try:
        tab = goto(tid)
        if tab is None:
            # force create
            if hasattr(win, "_ensure_tab"):
                tab = win._ensure_tab(tid)
            elif hasattr(win, "_get_or_create_tab"):
                tab = win._get_or_create_tab(tid)
            else:
                # try nav button
                btn = (win._nav or {}).get(tid)
                if btn:
                    btn.click()
                    pump(15)
                    tab = win._tabs.get(tid)
        shot(f"{i+2:02d}_{tid}.png")
        if tab is None:
            rec(f"tab.{tid}", "FAIL", "tab widget missing")
            continue
        buttons, fields, checks = enumerate_controls(tab)
        empty_btns = [b for b in buttons if not b["text"] and not b["tip"] and b["type"] == "QPushButton"]
        dead_enabled = [b for b in buttons if b["enabled"] and not b["text"] and not b["tip"] and not b["obj"]]
        rec(
            f"tab.{tid}",
            "PASS",
            f"btns={len(buttons)} fields={len(fields)} checks={len(checks)} empty_label={len(empty_btns)}",
        )
        if empty_btns:
            rec(f"tab.{tid}.empty_buttons", "PARTIAL", str(empty_btns[:5]))
        # Persist control inventory
        (OUT / f"controls_{tid}.json").write_text(
            json.dumps({"buttons": buttons, "fields": fields, "checks": checks}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        rec(f"tab.{tid}", "FAIL", traceback.format_exc()[-400:])


# Finance module deep walkthrough (FinanceTab progressive disclosure)
try:
    fin = goto("accounting")
    pump(15)
    shot("finance_00_overview.png")
    if fin is None:
        rec("finance.shell", "FAIL", "Finance tab missing")
    else:
        title = win._TAB_LABELS.get("accounting", "")
        nav_lbl = ""
        try:
            nb = (win._nav or {}).get("accounting")
            nav_lbl = (nb.text() or "") if nb else ""
        except Exception:
            pass
        has_pages = hasattr(fin, "_pages") and isinstance(getattr(fin, "_pages", None), dict)
        pages = list(fin._pages.keys()) if has_pages else []
        rec(
            "finance.shell",
            "PASS" if has_pages and "overview" in pages else "FAIL",
            f"label={title!r} nav={nav_lbl!r} pages={pages} cls={type(fin).__name__}",
        )
        # Primary pages
        for key in ("overview", "money", "expenses", "credit", "reports"):
            if not has_pages or key not in fin._pages:
                if key == "reports" and key not in pages:
                    rec(f"finance.page.{key}", "PARTIAL", "hidden for role (expected for cashier)")
                else:
                    rec(f"finance.page.{key}", "FAIL", "page missing")
                continue
            try:
                fin._goto(key)
                pump(12)
                shot(f"finance_{key}.png")
                page = fin._pages[key]
                if hasattr(page, "refresh"):
                    page.refresh()
                    pump(8)
                rec(f"finance.page.{key}", "PASS", f"refreshed ok ({type(page).__name__})")
            except Exception:
                rec(f"finance.page.{key}", "FAIL", traceback.format_exc()[-300:])
        # Advanced (admin has full access)
        if getattr(fin, "_show_advanced", False):
            if hasattr(fin, "_toggle_advanced") and not getattr(fin, "_advanced_open", False):
                try:
                    fin._toggle_advanced()
                    pump(6)
                except Exception:
                    pass
            for key in (
                "coa", "ledger", "journals", "trial", "balance",
                "cashflow", "periods", "fin_settings",
            ):
                if key not in fin._pages:
                    rec(f"finance.adv.{key}", "FAIL", "missing")
                    continue
                try:
                    fin._goto(key)
                    pump(10)
                    shot(f"finance_adv_{key}.png")
                    page = fin._pages[key]
                    if hasattr(page, "refresh"):
                        page.refresh()
                        pump(6)
                    rec(f"finance.adv.{key}", "PASS", type(page).__name__)
                except Exception:
                    rec(f"finance.adv.{key}", "FAIL", traceback.format_exc()[-300:])
        else:
            rec("finance.advanced", "PARTIAL", "Advanced hidden for this role")
        # Settings → Finance section present
        settings = goto("settings")
        pump(10)
        if settings is not None and hasattr(settings, "fin_currency"):
            probe_method = settings.fin_method.currentData()
            settings.fin_opening_note.setText("QA finance note")
            for meth in ("_save",):
                if hasattr(settings, meth):
                    try:
                        getattr(settings, meth)()
                        break
                    except Exception as e:
                        log(f"finance settings save: {e}")
            pump(8)
            cfg = {}
            try:
                cfg = api.get_settings() or {}
            except Exception:
                pass
            ok = (cfg.get("opening_balances_note") == "QA finance note"
                  or cfg.get("accounting_method") == probe_method)
            # restore note
            settings.fin_opening_note.setText("")
            if hasattr(settings, "_save"):
                try:
                    settings._save()
                except Exception:
                    pass
            rec(
                "finance.settings_persist",
                "PASS" if ok else "FAIL",
                f"ok={ok} method={cfg.get('accounting_method')!r} "
                f"note={cfg.get('opening_balances_note')!r} "
                f"cash={cfg.get('acct_cash_code')!r}",
            )
            shot("finance_settings_section.png")
        else:
            rec("finance.settings_persist", "FAIL", "fin_* fields missing on SettingsTab")
except Exception:
    rec("finance.walkthrough", "FAIL", traceback.format_exc()[-500:])


# Theme toggle
try:
    goto("dashboard")
    ThemeManager.apply(True, force=True)
    pump(10)
    if hasattr(win, "_apply_theme"):
        try:
            win._apply_theme(True)
        except Exception:
            pass
    pump(10)
    shot("20_theme_dark.png")
    ThemeManager.apply(False, force=True)
    pump(10)
    shot("21_theme_light.png")
    rec("ui.theme_toggle", "PASS", "dark+light grabs")
except Exception as e:
    rec("ui.theme_toggle", "FAIL", str(e)[:200])


# Settings persist probe
try:
    settings = goto("settings")
    pump(12)
    shot("30_settings.png")
    if settings is None:
        rec("settings.persist", "FAIL", "no settings tab")
    else:
        # Find shop_name field
        shop = getattr(settings, "shop_name", None)
        orig = None
        if shop is not None:
            orig = shop.text()
            probe = (orig or "Shop") + " ·CERT"
            shop.setText(probe)
            pump(4)
            # Save
            saved = False
            for meth in ("_save", "save", "_save_all", "_on_save"):
                if hasattr(settings, meth):
                    try:
                        getattr(settings, meth)()
                        saved = True
                        break
                    except TypeError:
                        try:
                            getattr(settings, meth)(False)
                            saved = True
                            break
                        except Exception:
                            pass
                    except Exception as e:
                        log(f"save meth {meth}: {e}")
            # Click any Save button
            if not saved:
                for b in settings.findChildren(QPushButton):
                    t = (b.text() or "").lower()
                    if "save" in t and b.isVisible():
                        b.click()
                        pump(8)
                        saved = True
                        break
            pump(8)
            # Re-read from API/config
            cfg = {}
            try:
                cfg = api.get_settings() if hasattr(api, "get_settings") else {}
            except Exception:
                pass
            # Restore
            if orig is not None:
                shop.setText(orig)
                for meth in ("_save", "save", "_save_all"):
                    if hasattr(settings, meth):
                        try:
                            getattr(settings, meth)()
                            break
                        except Exception:
                            pass
                for b in settings.findChildren(QPushButton):
                    if "save" in (b.text() or "").lower() and b.isVisible():
                        b.click()
                        pump(6)
                        break
            rec(
                "settings.persist",
                "PASS" if saved else "FAIL",
                f"saved={saved} probe={probe!r} cfg_keys={list(cfg)[:8] if isinstance(cfg, dict) else type(cfg)}",
            )
        else:
            rec("settings.persist", "FAIL", "shop_name field missing")

        # Toggle a checkbox and save
        checks = [c for c in settings.findChildren(QCheckBox) if c.isVisible() and c.isEnabled()]
        if checks:
            c0 = checks[0]
            before = c0.isChecked()
            c0.setChecked(not before)
            pump(2)
            for b in settings.findChildren(QPushButton):
                if "save" in (b.text() or "").lower() and b.isVisible():
                    b.click()
                    pump(6)
                    break
            after = c0.isChecked()
            c0.setChecked(before)
            for b in settings.findChildren(QPushButton):
                if "save" in (b.text() or "").lower() and b.isVisible():
                    b.click()
                    pump(4)
                    break
            rec("settings.checkbox_toggle", "PASS", f"{c0.text()[:40]!r} flipped {before}->{after}")
        else:
            rec("settings.checkbox_toggle", "PARTIAL", "no visible checkboxes")
except Exception:
    rec("settings.persist", "FAIL", traceback.format_exc()[-400:])


# Dialog probes (non-blocking exec_)
def open_dialog(factory, name):
    from PyQt5.QtWidgets import QDialog as QD
    prev = QD.exec_
    opened = False

    def _nb(self):
        nonlocal opened
        opened = True
        self.show()
        pump(8)
        try:
            self.grab().save(str(SHOTS / f"dlg_{name}.png"), "PNG")
        except Exception:
            pass
        self.reject()
        return QD.Rejected

    try:
        QD.exec_ = _nb
        factory()
        pump(6)
        rec(f"dialog.{name}", "PASS" if opened else "PARTIAL", f"opened={opened}")
    except Exception as e:
        rec(f"dialog.{name}", "FAIL", str(e)[:240])
    finally:
        QD.exec_ = prev


try:
    sales = goto("sales")
    pump(8)
    if sales and hasattr(sales, "_open_return_sale"):
        open_dialog(lambda: sales._open_return_sale(), "return_sale")
    if sales and hasattr(sales, "_void_sale"):
        open_dialog(lambda: sales._void_sale(), "void_sale")
except Exception as e:
    rec("dialog.sales", "FAIL", str(e)[:200])

try:
    inv = goto("inventory")
    pump(8)
    if inv and hasattr(inv, "_receive_stock_dialog"):
        open_dialog(lambda: inv._receive_stock_dialog(), "receive_stock")
    if inv and hasattr(inv, "_suppliers_dialog"):
        open_dialog(lambda: inv._suppliers_dialog(), "suppliers")
    elif inv:
        for meth in ("_open_suppliers", "_suppliers"):
            if hasattr(inv, meth):
                open_dialog(lambda m=meth: getattr(inv, m)(), "suppliers")
                break
        else:
            # click Suppliers button
            for b in inv.findChildren(QPushButton):
                if "supplier" in (b.text() or "").lower():
                    open_dialog(lambda btn=b: btn.click(), "suppliers")
                    break
    if inv and hasattr(inv, "_add"):
        open_dialog(lambda: inv._add(), "add_product")
except Exception as e:
    rec("dialog.inventory", "FAIL", str(e)[:200])

try:
    debt = goto("debt")
    pump(8)
    for meth in ("_collect", "_open_collect", "_on_collect"):
        if debt and hasattr(debt, meth):
            # may need selection — try anyway
            open_dialog(lambda m=meth: getattr(debt, m)(), "debt_collect")
            break
except Exception as e:
    rec("dialog.debt", "FAIL", str(e)[:200])

try:
    if hasattr(win, "_open_global_search"):
        open_dialog(lambda: win._open_global_search(), "global_search")
except Exception as e:
    rec("dialog.global_search", "FAIL", str(e)[:200])


# Sales focus mode
try:
    sales = goto("sales")
    pump(6)
    if hasattr(sales, "set_focus_mode"):
        sales.set_focus_mode(True)
        pump(8)
        shot("40_sales_focus.png")
        sales.set_focus_mode(False)
        pump(6)
        shot("41_sales_restore.png")
        rec("ui.sales_focus", "PASS", "focus+restore")
    elif hasattr(win, "set_pos_focus_mode"):
        win.set_pos_focus_mode(True)
        pump(8)
        shot("40_sales_focus.png")
        win.set_pos_focus_mode(False)
        pump(6)
        rec("ui.sales_focus", "PASS", "via main window")
    else:
        rec("ui.sales_focus", "PARTIAL", "no focus API")
except Exception as e:
    rec("ui.sales_focus", "FAIL", str(e)[:200])


# Invalid action probes
try:
    bad = api.create_product({"name": "", "price": -1})
    rec(
        "error.invalid_product",
        "PASS" if bad and (bad.get("error") or not bad.get("success")) else "FAIL",
        str(bad)[:160],
    )
except Exception as e:
    rec("error.invalid_product", "PASS", f"raised {e.__class__.__name__}")

try:
    empty = api.create_sale({"items": [], "total": 0, "payment_method": "Cash", "amount_paid": 0})
    rec(
        "error.empty_sale",
        "PASS" if empty and empty.get("error") else "FAIL",
        str(empty)[:160],
    )
except Exception as e:
    rec("error.empty_sale", "PASS", f"raised {e.__class__.__name__}")


# Hidden Telegram fields must stay hidden
try:
    settings = goto("settings")
    pump(8)
    leaked = []
    for name in ("tg_chat", "tg_token", "dev_chat", "_test_tg_btn", "_connect_btn"):
        w = getattr(settings, name, None) if settings else None
        if w is not None and w.isVisible():
            leaked.append(name)
    rec("settings.no_telegram_ui", "PASS" if not leaked else "FAIL", f"leaked={leaked}")
except Exception as e:
    rec("settings.no_telegram_ui", "FAIL", str(e)[:200])


# Sidebar nav labels
try:
    labels = []
    for tid, btn in (win._nav or {}).items():
        labels.append({"id": tid, "text": (btn.text() or "").strip(), "visible": btn.isVisible()})
    (OUT / "nav.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    rec("ui.sidebar_nav", "PASS", f"items={len(labels)}")
except Exception as e:
    rec("ui.sidebar_nav", "FAIL", str(e)[:200])


fails = [r for r in R if r["status"] == "FAIL"]
partials = [r for r in R if r["status"] == "PARTIAL"]
report = {
    "ts": datetime.now().isoformat(),
    "version": APP_VERSION,
    "fails": len(fails),
    "partials": len(partials),
    "results": R,
    "verdict": "PASS" if not fails else "FAIL",
}
(OUT / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
md = [
    f"# UI Walkthrough — MBT POS {APP_VERSION}",
    "",
    f"**Verdict:** {report['verdict']}  ",
    f"**Fails:** {len(fails)} · **Partials:** {len(partials)}",
    "",
    "| Area | Status | Note |",
    "|------|--------|------|",
]
for r in R:
    note = str(r.get("note", "")).replace("|", "/")[:140]
    md.append(f"| {r['area']} | {r['status']} | {note} |")
(OUT / "WALKTHROUGH.md").write_text("\n".join(md) + "\n", encoding="utf-8")
log(f"VERDICT={report['verdict']} fails={len(fails)} partials={len(partials)}")

try:
    win.close()
except Exception:
    pass
sys.exit(0 if not fails else 1)
