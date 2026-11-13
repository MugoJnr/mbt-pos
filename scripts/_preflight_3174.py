"""Confirm the 3.1.74 source tree contains the fixes before packaging."""
import py_compile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
js = next((root / "web" / "dashboard-ui" / "dist" / "assets").glob("index-*.js"))
text = js.read_text(encoding="utf-8")
src = {
    "tenders": (root / "desktop" / "utils" / "payment_tenders.py").read_text(encoding="utf-8"),
    "app": (root / "backend" / "app.py").read_text(encoding="utf-8"),
    "api": (root / "desktop" / "utils" / "api_client.py").read_text(encoding="utf-8"),
    "lines": (root / "backend" / "sale_lines.py").read_text(encoding="utf-8"),
    "ver": (root / "version.json").read_text(encoding="utf-8"),
    "nsi": (root / "installer.nsi").read_text(encoding="utf-8"),
    "main": (root / "desktop" / "main.py").read_text(encoding="utf-8"),
    "admin": (root / "desktop" / "tabs" / "admin_tab.py").read_text(encoding="utf-8"),
    "spec": (root / "mbt_pos.spec").read_text(encoding="utf-8"),
}
checks = {
    "ui-credit-remainder": "Leave the remainder on the customer account" in text,
    "ui-void-pin": "Super-Admin PIN" in text,
    "ui-remove-product": "Remove product" in text,
    "allocate": "def allocate_sale" in src["tenders"],
    "http-allocate": "allocate_sale" in src["app"],
    "fifo-sale": "consume_fifo" in src["app"],
    "credit-customer": "Choose a customer before a credit" in src["app"],
    "zero-qty": "Quantity must be greater than zero" in src["lines"],
    "debt-return": "debt_reduced" in src["api"],
    "purchase-layer": "'purchase'" in src["api"],
    "version": '"version": "3.1.74"' in src["ver"],
    "installer-version": 'APP_VERSION "3.1.74"' in src["nsi"],
    "main-version": 'APP_VERSION   = "3.1.74"' in src["main"],
    "admin-import": "desktop.tabs.admin_tab" in src["main"],
    "admin-hidden": "'desktop.tabs.admin_tab'" in src["spec"],
    "users-screen": "class AdminTab" in src["admin"],
    "update-helper": (root / "deploy" / "MBT_UpdateHelper.ps1").is_file(),
    "cloudflared": (root / "tools" / "cloudflared.exe").is_file(),
    "installer-copies-tree": 'File /r "dist\\MBT_POS\\*.*"' in src["nsi"],
}
for tab in (root / "desktop" / "tabs").glob("*.py"):
    py_compile.compile(str(tab), doraise=True)
failed = [name for name, ok in checks.items() if not ok]
print("bundle", js.name)
print("failed", ",".join(failed) if failed else "none")
for name, ok in checks.items():
    print("PASS" if ok else "FAIL", name)
raise SystemExit(1 if failed else 0)
