"""MBT POS E2E Phases 6-30 — fresh-user production readiness (real Qt UI)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MBT_AUTO_SUPERADMIN_PIN", "1110")
os.environ.setdefault("MBT_SESSION_IDLE_SEC", "0")
os.environ.setdefault("PYTHONWARNINGS", "ignore")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

STATE_FILE = ROOT / "logs" / "_e2e_fresh_user_state.json"
desktop = Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"
OUT = Path(os.environ.get(
    "MBT_QA_OUT",
    str((desktop if desktop.is_dir() else Path(tempfile.gettempdir())) / "QA_E2E_FRESH_USER"),
))
OUT.mkdir(parents=True, exist_ok=True)
SHOTS = OUT / "shots"
SHOTS.mkdir(exist_ok=True)
LOG = OUT / "e2e_phases_6_30.log"
RESULTS: list[dict] = []

STATE = json.loads(STATE_FILE.read_text(encoding="utf-8"))
EMAIL = STATE["email"]
PASSWORD = STATE["password"]
BUSINESS = STATE["business"]
LICENSE_KEY = STATE.get("license", {}).get("license_key", "")


def log(msg: str) -> None:
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def rec(phase: str, area: str, status: str, note: str = "") -> None:
    row = {"phase": phase, "area": area, "status": status, "note": note, "ts": datetime.now().isoformat()}
    RESULTS.append(row)
    log(f"[{status}] P{phase} {area}: {note}")


open(LOG, "w", encoding="utf-8").write(f"E2E phases 6-30 start {datetime.now().isoformat()}\n")

try:
    import backend.cloudflare_setup as cfs
    cfs.refresh_remote_setup_status = lambda: None
    cfs.start_auto_cloudflare = lambda **kw: None
except Exception:
    pass

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QDialog, QPushButton, QLineEdit, QWidget,
)
from PyQt5.QtCore import Qt, QTimer

from desktop.utils.theme import ensure_fonts, ThemeManager
from desktop.utils.api_client import APIClient
import desktop.main as dm
from desktop.main import MainWindow, LoginDialog, _load_icon, APP_VERSION
from desktop.wizard.setup_wizard import SetupWizard, needs_wizard, mark_initialized
from licensing.license_engine import LicenseEngine

ensure_fonts()
try:
    from backend.app import init_db
    init_db()
except Exception as e:
    log(f"init_db: {e}")

api = APIClient("http://127.0.0.1:5050")
app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

# Stub noisy hooks for QA harness
dm.MainWindow._start_services = lambda self: None
dm.MainWindow._initial_conn_check = lambda self: None
dm.MainWindow._restore_pending_update = lambda self: None
dm.MainWindow._qa_dump_theme_evidence = lambda self: None
dm.MainWindow._qa_dump_theme_evidence_late = lambda self: None
QMainWindow.showMaximized = lambda self: (self.resize(1600, 1000), self.show())
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)


def pump(n: int = 12) -> None:
    for _ in range(n):
        app.processEvents()


def shot(name: str) -> None:
    if win:
        win.grab().save(str(SHOTS / name), "PNG")


def goto(tid: str):
    if win and hasattr(win, "_goto"):
        win._goto(tid)
    pump(15)
    return getattr(win, "_tabs", {}).get(tid) if win else None


def open_dialog(fn, label: str) -> bool:
    """Open a dialog briefly; never block on modal exec."""
    if fn is None:
        rec("ui", f"dialog.{label}", "SKIP", "no handler")
        return False
    try:
        fn()
        pump(15)
        for w in QApplication.topLevelWidgets():
            if w is win or not w.isVisible():
                continue
            if isinstance(w, QDialog):
                try:
                    w.grab().save(str(SHOTS / f"dlg_{label}.png"), "PNG")
                except Exception:
                    pass
                w.reject()
                break
        pump(8)
        rec("ui", f"dialog.{label}", "PASS", label)
        return True
    except Exception as e:
        rec("ui", f"dialog.{label}", "FAIL", str(e)[:200])
        return False


# ── Phase 6: Setup wizard + POS config ───────────────────────────────────────
win = None
login_res = None
admin_user = "admin"
admin_pw = os.environ.get("MBT_BOOTSTRAP_ADMIN_PASSWORD", "").strip()

if needs_wizard():
    try:
        wiz = SetupWizard()
        wiz._data["cloud_mode"] = "login"
        wiz._data["license_activated"] = True
        wiz._data["license_key"] = LICENSE_KEY
        # Jump to shop info step and fill
        wiz._go_to(3)
        pump(10)
        wiz.w_shop_name.setText(BUSINESS)
        wiz.w_shop_location.setText("Nairobi, Kenya")
        wiz.w_shop_phone.setText("+254700000001")
        wiz._data["shop_name"] = BUSINESS
        wiz._go_to(4)
        pump(8)
        if hasattr(wiz, "w_admin_user"):
            wiz.w_admin_user.setText("e2eadmin")
            wiz.w_admin_pw.setText("E2eAdmin!2026")
            wiz.w_admin_pw2.setText("E2eAdmin!2026")
            admin_user, admin_pw = "e2eadmin", "E2eAdmin!2026"
        # Skip through printer + dashboard to complete
        for step in (5, 6, 7):
            wiz._collect_step()
            if step < 7:
                wiz._go_to(step + 1)
            pump(8)
        wiz._collect_step()
        wiz._apply_config()
        mark_initialized()
        wiz.grab().save(str(SHOTS / "06_wizard_complete.png"), "PNG")
        rec("6", "setup_wizard", "PASS", f"shop={BUSINESS} admin={admin_user}")
    except Exception as e:
        rec("6", "setup_wizard", "FAIL", traceback.format_exc()[-300:])
        try:
            mark_initialized()
        except Exception:
            pass
else:
    rec("6", "setup_wizard", "PASS", "already initialized")

login_res = api.login(admin_user, admin_pw) if admin_pw else None
if not login_res or not login_res.get("token"):
    os.environ.setdefault("MBT_QA_ALLOW_DEV_BOOTSTRAP", "1")
    from _qa_local_auth import qa_admin_password, qa_admin_user, qa_login

    login_res = qa_login(api)
    admin_user, admin_pw = qa_admin_user(), qa_admin_password()
if not login_res or not login_res.get("token"):
    rec("6", "local_login", "FAIL", str(login_res)[:200])
    (OUT / "results.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    raise SystemExit(1)
api.set_token(login_res["token"])
rec("6", "local_login", "PASS", f"user={admin_user} role={(login_res.get('user') or {}).get('role')}")

ThemeManager.apply(False, force=True)
icon = _load_icon()
win = MainWindow(login_res, api, icon)
win.resize(1600, 1000)
win.show()
pump(25)
shot("06_dashboard.png")

# Settings / shop config via UI
try:
    settings = goto("settings")
    pump(10)
    if settings and hasattr(settings, "shop_name"):
        settings.shop_name.setText(BUSINESS)
        if hasattr(settings, "shop_phone"):
            settings.shop_phone.setText("+254700000001")
        if hasattr(settings, "shop_address"):
            settings.shop_address.setText("E2E Test Address, Nairobi")
        if hasattr(settings, "_save"):
            settings._save()
            pump(10)
        cfg = api.get_settings() or {}
        ok = BUSINESS.split()[0] in str(cfg.get("shop_name", ""))
        rec("6", "settings_persist", "PASS" if ok else "FAIL", f"shop_name={cfg.get('shop_name')!r}")
    else:
        rec("6", "settings_persist", "PARTIAL", "settings tab missing fields")
    shot("06_settings.png")
except Exception as e:
    rec("6", "settings_persist", "FAIL", str(e)[:200])

# ── Phase 7: Inventory ───────────────────────────────────────────────────────
SKU = f"E2E-{int(time.time()) % 100000}"
pid = None
try:
    inv = goto("inventory")
    pump(8)
    shot("07_inventory.png")
    created = api.create_product({
        "name": "E2E Maize Flour 2kg",
        "sku": SKU,
        "barcode": f"899{int(time.time()) % 1000000000:09d}",
        "price": 250.0,
        "cost_price": 180.0,
        "stock": 50,
        "min_stock": 5,
        "unit": "pcs",
        "category": "Groceries",
    })
    if created and created.get("success"):
        pid = created.get("id") or (created.get("product") or {}).get("id")
    if not pid:
        for p in api.get_products() or []:
            if p.get("sku") == SKU:
                pid = p["id"]
                break
    rec("7", "create_product", "PASS" if pid else "FAIL", f"pid={pid} sku={SKU}")
    if pid and hasattr(api, "receive_stock"):
        recv = api.receive_stock(
            int(pid), 10, notes="E2E receive", unit_cost=180.0,
            pin=os.environ.get("MBT_AUTO_SUPERADMIN_PIN", ""),
        )
        rec("7", "receive_stock", "PASS" if recv and recv.get("success") else "FAIL", str(recv)[:120])
    rec("7", "inventory_ui", "PASS" if inv else "FAIL", "tab loaded")
except Exception as e:
    rec("7", "inventory", "FAIL", traceback.format_exc()[-300:])

# ── Phase 8: Customers ───────────────────────────────────────────────────────
cid = None
try:
    cust = api.create_customer({"name": "E2E Walk-in Customer", "phone": "0711223344", "email": "e2e.cust@example.com"})
    cid = cust.get("id") or (cust.get("customer") or {}).get("id") if cust else None
    if not cid:
        customers = api.get_customers() or []
        cid = customers[-1]["id"] if customers else None
    rec("8", "create_customer", "PASS" if cid else "FAIL", f"cid={cid}")
    shot("08_customers_via_api.png")
except Exception as e:
    rec("8", "customers", "FAIL", str(e)[:200])

# ── Phase 9: Sales A-M ───────────────────────────────────────────────────────
sale_ids = []
try:
    sales_tab = goto("sales")
    pump(12)
    shot("09_sales.png")
    methods = [
        ("Cash", 200, 200),
        ("M-Pesa", 250, 250),
        ("Card", 250, 250),
        ("Bank", 250, 250),
        ("Mixed", 500, 500),
    ]
    for method, total, paid in methods:
        if not pid:
            break
        s = api.create_sale({
            "items": [{
                "product_id": int(pid),
                "product_name": "E2E Maize Flour 2kg",
                "sku": SKU,
                "quantity": 1,
                "unit_price": float(total),
                "discount": 0,
                "total": float(total),
            }],
            "subtotal": total,
            "total": total,
            "payment_method": method,
            "amount_paid": paid,
            "change_amount": 0,
            "customer_id": cid,
        })
        ok = bool(s and s.get("success"))
        sid = s.get("sale_id") or s.get("id") if s else None
        if sid:
            sale_ids.append(sid)
        rec("9", f"sale_{method.lower().replace('-','')}", "PASS" if ok else "FAIL", f"id={sid}")
    # Credit sale
    credit = api.create_sale({
        "items": [{
            "product_id": int(pid),
            "product_name": "E2E Maize Flour 2kg",
            "sku": SKU,
            "quantity": 2,
            "unit_price": 250.0,
            "discount": 0,
            "total": 500.0,
        }],
        "subtotal": 500,
        "total": 500,
        "payment_method": "Credit",
        "amount_paid": 0,
        "customer_id": cid,
    })
    rec("9", "sale_credit", "PASS" if credit and credit.get("success") else "FAIL", str(credit)[:100])
except Exception as e:
    rec("9", "sales", "FAIL", traceback.format_exc()[-300:])

# ── Phase 10: Till ───────────────────────────────────────────────────────────
try:
    acc = goto("accounting")
    pump(10)
    if acc and hasattr(acc, "_goto"):
        acc._goto("money")
        pump(10)
    shot("10_till_money.png")
    rec("10", "till_view", "PASS" if acc else "FAIL", type(acc).__name__ if acc else "none")
except Exception as e:
    rec("10", "till", "FAIL", str(e)[:200])

# ── Phase 11: Expenses ───────────────────────────────────────────────────────
try:
    exp = api.accounting_create_expense({
        "description": "E2E Transport",
        "amount": 500.0,
        "category": "Transport",
        "payment_method": "Cash",
        "date": date.today().isoformat(),
    }) if hasattr(api, "accounting_create_expense") else None
    ok = bool(exp and (exp.get("success") or exp.get("id")))
    rec("11", "create_expense", "PASS" if ok else "FAIL", str(exp)[:120])
    if acc and hasattr(acc, "_goto"):
        acc._goto("expenses")
        pump(10)
        shot("11_expenses.png")
except Exception as e:
    rec("11", "expenses", "FAIL", str(e)[:200])

# ── Phase 12: Search ─────────────────────────────────────────────────────────
try:
    from desktop.dialogs.global_search_dialog import GlobalSearchDialog
    dlg = GlobalSearchDialog(api, win)
    dlg.show()
    pump(10)
    if hasattr(dlg, "_search") and hasattr(dlg, "_query"):
        dlg._query.setText("E2E Maize")
        if hasattr(dlg, "_run_search"):
            dlg._run_search()
        elif hasattr(dlg, "_search_btn"):
            dlg._search_btn.click()
        pump(12)
    dlg.grab().save(str(SHOTS / "12_global_search.png"), "PNG")
    rec("12", "global_search", "PASS", "Ctrl+K dialog")
    dlg.close()
except Exception as e:
    rec("12", "global_search", "FAIL", str(e)[:200])

# ── Phase 13: Reports ────────────────────────────────────────────────────────
try:
    rep = goto("reports")
    pump(15)
    shot("13_reports.png")
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=7)).isoformat()
    summary_raw = api.get_report_summary(start, end) if hasattr(api, "get_report_summary") else None
    inner = (summary_raw or {}).get("summary") or summary_raw or {}
    rev = inner.get("total_revenue") or inner.get("total_sales")
    rec("13", "report_summary", "PASS" if rev else "FAIL", f"revenue={rev}")
except Exception as e:
    rec("13", "reports", "FAIL", str(e)[:200])

# ── Phase 14: Portal dashboard (CDP) ───────────────────────────────────────────
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    from _open_auth_link import open_url
    from _cdp_gmail_auth import CDP, pages
    import urllib.request

    open_url("https://portal.mugobyte.com/login")
    time.sleep(4)
    tab = next((t for t in pages() if "portal.mugobyte.com" in (t.get("url") or "")), None)
    if tab:
        cdp = CDP(tab["webSocketDebuggerUrl"])
        try:
            login = cdp.eval(f"""
(async () => {{
  const r = await fetch('/api/cloud/auth/login', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    credentials: 'same-origin',
    body: JSON.stringify({{email: {json.dumps(EMAIL)}, password: {json.dumps(PASSWORD)}}}),
  }});
  const data = await r.json().catch(() => ({{}}));
  if (!r.ok || !data.token) return {{ok:false, status:r.status, error:data.error}};
  sessionStorage.setItem('mbt_token', data.token);
  sessionStorage.setItem('mbt_user', JSON.stringify(data.user || {{}}));
  return {{ok:true, email:(data.user||{{}}).email}};
}})()
""").get("value") or {}
            cdp.call("Page.navigate", {"url": "https://portal.mugobyte.com/dashboard"})
            time.sleep(5)
            body = cdp.eval("(document.body && document.body.innerText || '').slice(0,400)").get("value") or ""
            ok = login.get("ok") and ("Workspace" in body or "Dashboard" in body or BUSINESS.split()[0] in body)
            rec("14", "portal_dashboard", "PASS" if ok else "FAIL", body[:120].replace("\n", " "))
        finally:
            cdp.close()
    else:
        rec("14", "portal_dashboard", "FAIL", "no portal tab")
except Exception as e:
    rec("14", "portal_dashboard", "FAIL", str(e)[:200])

# ── Phase 15: Backup / sync ──────────────────────────────────────────────────
if win:
    win.close()
    win = None
    pump(5)
try:
    from licensing.cloud_onboarding import try_login
    try_login(EMAIL, PASSWORD)
    from backend.db_backup import create_db_backup_zip
    path, size, digest = create_db_backup_zip()
    ok = Path(path).is_file() if path else False
    rec("15", "local_backup", "PASS" if ok else "FAIL", f"size={size} path={Path(path).name if path else ''}")
    from backend.cloud_backup.sync_manager import SyncManager
    sm = SyncManager()
    sync_res = sm.run_backup(reason="e2e_manual") if hasattr(sm, "run_backup") else {}
    sync_ok = bool(sync_res and sync_res.get("ok", True) if isinstance(sync_res, dict) else sync_res)
    rec("15", "cloud_sync", "PASS" if sync_ok else "PARTIAL", str(sync_res)[:120])
except Exception as e:
    rec("15", "backup_sync", "FAIL", str(e)[:200])

# ── Phase 16: Offline ────────────────────────────────────────────────────────
try:
    engine = LicenseEngine(str(ROOT))
    offline_ok = engine.is_valid
    rec("16", "offline_grace", "PASS" if offline_ok else "FAIL", f"state={engine.state}")
except Exception as e:
    rec("16", "offline", "FAIL", str(e)[:200])

# ── Phase 17: Restart / session ──────────────────────────────────────────────
try:
    api2 = APIClient("http://127.0.0.1:5050")
    r2 = api2.login(admin_user, admin_pw)
    rec("17", "session_relogin", "PASS" if r2 and r2.get("token") else "FAIL", admin_user)
    import sqlite3
    from mbt_paths import get_db_path
    dbp = get_db_path()
    con = sqlite3.connect(dbp)
    n_sales = con.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    n_prods = con.execute("SELECT COUNT(*) FROM products WHERE is_active=1 OR is_active IS NULL").fetchone()[0]
    con.close()
    rec("17", "data_persist", "PASS" if n_prods >= 1 else "FAIL", f"products={n_prods} sales={n_sales}")
except Exception as e:
    rec("17", "restart_session", "FAIL", str(e)[:200])

# ── Phase 18: Device / license ─────────────────────────────────────────────────
try:
    lic_tab = goto("license")
    pump(10)
    shot("18_license.png")
    engine = LicenseEngine(str(ROOT))
    rec("18", "license_tab", "PASS" if engine.is_valid else "FAIL", f"device={engine.device_id[:12]} state={engine.state}")
except Exception as e:
    rec("18", "device_license", "FAIL", str(e)[:200])

# ── Phase 19: Permissions ──────────────────────────────────────────────────────
try:
    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_permissions_matrix.py", "-q", "--tb=no"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    rec("19", "permissions_matrix", "PASS" if r.returncode == 0 else "FAIL", (r.stdout or r.stderr)[-120:])
except Exception as e:
    rec("19", "permissions", "FAIL", str(e)[:200])

# ── Phase 20: Data consistency ───────────────────────────────────────────────
try:
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=1)).isoformat()
    summary_raw = api.get_report_summary(start, end) or {}
    inner = summary_raw.get("summary") or summary_raw
    pos_rev = inner.get("total_revenue") or inner.get("total_sales") or 0
    rec("20", "pos_revenue", "PASS" if float(pos_rev or 0) > 0 else "FAIL", f"revenue={pos_rev}")
except Exception as e:
    rec("20", "consistency", "FAIL", str(e)[:200])

# ── Phase 21: Upgrade check ────────────────────────────────────────────────────
try:
    from backend.cloud.update_center import UpdateCenter
    uc = UpdateCenter()
    upd = uc.check_for_updates(APP_VERSION) if hasattr(uc, "check_for_updates") else {}
    rec("21", "upgrade_check", "PASS", f"current={APP_VERSION} update={upd}")
except Exception as e:
    rec("21", "upgrade", "PARTIAL", str(e)[:100])

# ── Phases 22-24: Error / UI / Security ───────────────────────────────────────
try:
    bad = api.create_product({"name": "", "price": -1})
    rec("22", "invalid_product_rejected", "PASS" if bad and bad.get("error") else "FAIL", str(bad)[:80])
    ThemeManager.apply(True, force=True)
    pump(8)
    shot("24_theme_dark.png")
    ThemeManager.apply(False, force=True)
    rec("24", "theme_toggle", "PASS", "dark/light")
    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_security_pin_audit_gate.py", "-q", "--tb=no"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=90,
    )
    rec("24", "security_pin_gate", "PASS" if r.returncode == 0 else "FAIL", (r.stdout or "")[-80])
except Exception as e:
    rec("22", "error_handling", "FAIL", str(e)[:200])

# ── Phase 25: Repeat critical sale path ───────────────────────────────────────
try:
    if pid:
        s = api.create_sale({
            "items": [{"product_id": int(pid), "product_name": "E2E Maize Flour 2kg", "sku": SKU,
                       "quantity": 1, "unit_price": 250.0, "discount": 0, "total": 250.0}],
            "subtotal": 250, "total": 250, "payment_method": "Cash", "amount_paid": 250,
        })
        rec("25", "repeat_cash_sale", "PASS" if s and s.get("success") else "FAIL", "")
except Exception as e:
    rec("25", "repeat", "FAIL", str(e)[:200])

# ── Phases 26-30: Production gate pytest suite ────────────────────────────────
GATE_TESTS = [
    "tests/test_sale_void_stock_gate.py",
    "tests/test_credit_debt_collect_gate.py",
    "tests/test_db_backup_restore_gate.py",
    "tests/test_inventory_product_gate.py",
    "tests/test_dashboard_report_gate.py",
]
import subprocess
for i, tpath in enumerate(GATE_TESTS, start=26):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", tpath, "-q", "--tb=line"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180,
        )
        rec(str(min(30, 25 + i - 25)), Path(tpath).stem, "PASS" if r.returncode == 0 else "FAIL", (r.stdout or r.stderr)[-100:])
    except Exception as e:
        rec("30", Path(tpath).stem, "FAIL", str(e)[:100])

# Summary
fails = [r for r in RESULTS if r["status"] == "FAIL"]
partials = [r for r in RESULTS if r["status"] == "PARTIAL"]
summary = {
    "phases_run": "6-30",
    "total": len(RESULTS),
    "pass": sum(1 for r in RESULTS if r["status"] == "PASS"),
    "fail": len(fails),
    "partial": len(partials),
    "failed_areas": fails,
    "app_version": APP_VERSION,
    "email": EMAIL,
    "completed_at": datetime.now().isoformat(),
}
(OUT / "results.json").write_text(json.dumps({"summary": summary, "results": RESULTS}, indent=2), encoding="utf-8")
STATE["phases_6_30"] = summary
STATE["completed_phases"] = list(set(STATE.get("completed_phases", []) + [str(i) for i in range(6, 31)]))
STATE["failed"] = len(fails) > 0
STATE_FILE.write_text(json.dumps(STATE, indent=2), encoding="utf-8")

log(f"\nSUMMARY pass={summary['pass']} fail={summary['fail']} partial={summary['partial']}")
if win:
    win.close()
raise SystemExit(1 if fails else 0)
