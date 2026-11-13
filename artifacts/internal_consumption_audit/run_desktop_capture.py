"""Capture the real Internal Consumption widgets against an isolated database."""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime

ROOT = r'C:\MBT_Build\mbt-pos-port'
ISOLATED = r'C:\MBT_Build\qa-isolated-consumption'
OUT = os.path.join(ROOT, 'artifacts', 'internal_consumption_audit', 'desktop')
os.environ['MBT_DATA_ROOT'] = ISOLATED
os.environ['PROGRAMDATA'] = os.path.join(ISOLATED, 'programdata')
os.environ['MBT_BOOTSTRAP_ADMIN_PASSWORD'] = 'ic-audit-only'
os.environ['QT_QPA_PLATFORM'] = 'windows'
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(ISOLATED, 'programdata'), exist_ok=True)
sys.path.insert(0, ROOT)

from mbt_paths import get_db_path  # noqa: E402

db_path = os.path.abspath(get_db_path())
if not db_path.lower().startswith(os.path.abspath(ISOLATED).lower()):
    raise SystemExit(f'isolation failed: {db_path}')
if os.path.exists(db_path):
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    shutil.copy2(db_path, os.path.join(OUT, f'backup-before-{stamp}.db'))

from PyQt5.QtCore import QTimer, Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from desktop.tabs.consumption_tab import ConsumptionTab  # noqa: E402
from desktop.utils.api_client import APIClient, _SCHEMA_READY  # noqa: E402
import desktop.utils.api_client as ac  # noqa: E402

ac._SCHEMA_READY = False
api = APIClient()
api._role = 'superadmin'
api._user_id = 1
api._username = 'admin'
db = ac._db()
admin = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
if not admin:
    raise SystemExit('bootstrap admin missing')
api._user_id = int(admin['id'])
prefix = 'IC-AUDIT'
existing = db.execute(
    "SELECT COUNT(*) FROM products WHERE sku LIKE ?", (prefix + '%',)
).fetchone()[0]
if int(existing) == 0:
    samples = [
        ('IC-AUDIT Soap 500ml', 'IC-AUDIT-SOAP-500', 20, 40),
        ('IC-AUDIT Soap 1L', 'IC-AUDIT-SOAP-1L', 5, 60),
        ('IC-AUDIT Soap 500ml Refill', 'IC-AUDIT-SOAP-REFILL', 8, 30),
        ('IC-AUDIT Long Name Cleaning Concentrate (Kitchen & Bar) 5L', 'IC-AUDIT-LONG', 12, 90),
        ('IC-AUDIT Item #12 / 50%', 'IC-AUDIT-PUNCT', 3, 15),
        ('IC-AUDIT Zero Stock Cups', 'IC-AUDIT-ZERO', 0, 10),
        ('IC-AUDIT Low Napkins', 'IC-AUDIT-LOW', 1, 8),
    ]
    for name, sku, stock, cost in samples:
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock,is_active) "
            "VALUES (?,?,?,?,?,?,1)",
            (name, sku, cost * 2, cost, stock, 1),
        )
    for n in range(1, 36):
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock,is_active) "
            "VALUES (?,?,?,?,?,?,1)",
            (f'IC-AUDIT Bulk Item {n:02d}', f'IC-AUDIT-BULK-{n:02d}', 10, 4, 25, 1),
        )
    db.commit()
dept = api.save_department('IC-AUDIT Office')
if dept.get('error'):
    raise SystemExit(dept)
db.close()

shots = []


def save(widget, name):
    path = os.path.join(OUT, name)
    widget.grab().save(path)
    shots.append({'file': name, 'bytes': os.path.getsize(path)})
    return path


app = QApplication.instance() or QApplication([])
user = {'id': api._user_id, 'username': 'admin', 'role': 'superadmin', 'full_name': 'Shop Owner'}
tab = ConsumptionTab(api, {'user': user}, db_path, lambda: {'currency_symbol': 'KES'})
tab.resize(1280, 860)
tab.show()
tab.on_show()
app.processEvents()
save(tab, 'baseline-new-consumption.png')

pane = tab._create
pane._search.setText('soap')
pane._filter_products()
app.processEvents()
save(tab, 'search-soap-matches.png')
pane._search.setText('NO-SUCH-PRODUCT')
pane._filter_products()
app.processEvents()
save(tab, 'search-no-results.png')
pane._search.setText('  IC-AUDIT-SOAP-500  ')
pane._filter_products()
app.processEvents()
save(tab, 'search-sku-with-spaces.png')

pane._search.setText('IC-AUDIT Soap 500ml')
pane._filter_products()
pane._qty_add.setValue(2)
pane._add_top_result()
pane._search.setText('IC-AUDIT-SOAP-1L')
pane._filter_products()
pane._qty_add.setValue(1)
pane._add_top_result()
app.processEvents()
save(tab, 'batch-two-products.png')

pane._dept.showPopup()
app.processEvents()
save(tab, 'department-dropdown-open.png')
pane._dept.hidePopup()
if not pane._dept.set_value(dept['id']):
    pane._dept.setCurrentIndex(1 if pane._dept.count() > 1 else 0)
pane._reason._select.showPopup()
app.processEvents()
popup = QApplication.activePopupWidget()
save(popup or tab, 'reason-dropdown-open.png')
pane._reason._select.hidePopup()

pending = []


def accept_dialog():
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QMessageBox):
            save(widget, f'dialog-{len(shots)}.png')
            pending.append(widget.text() if hasattr(widget, 'text') else widget.windowTitle())
            widget.accept()


QTimer.singleShot(200, accept_dialog)
pane._qty_add.setValue(999)
pane._search.setText('IC-AUDIT-ZERO')
pane._filter_products()
pane._add_top_result()
app.processEvents()
save(tab, 'after-zero-stock-attempt.png')

before = {}
db = ac._db()
for sku in ('IC-AUDIT-SOAP-500', 'IC-AUDIT-SOAP-1L'):
    before[sku] = db.execute("SELECT stock FROM products WHERE sku=?", (sku,)).fetchone()['stock']
db.close()

QTimer.singleShot(200, accept_dialog)
pane._save()
for _ in range(20):
    app.processEvents()
save(tab, 'after-save.png')

tab._tabs.setCurrentIndex(1)
tab._history.refresh()
app.processEvents()
save(tab, 'history.png')
tab._tabs.setCurrentIndex(2)
tab._report.refresh()
app.processEvents()
save(tab, 'report.png')

db = ac._db()
after = {}
for sku in before:
    after[sku] = db.execute("SELECT stock FROM products WHERE sku=?", (sku,)).fetchone()['stock']
rows = db.execute(
    "SELECT reference_no, voided FROM stock_consumptions ORDER BY id DESC LIMIT 3"
).fetchall()
sales = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
db.close()
report = {
    'db_path': db_path,
    'before': {k: float(v) for k, v in before.items()},
    'after': {k: float(v) for k, v in after.items()},
    'recent': [dict(r) for r in rows],
    'sales': int(sales),
    'dialogs': pending,
    'shots': shots,
    'lines_left': len(pane._lines),
}
with open(os.path.join(OUT, 'desktop-capture.json'), 'w', encoding='utf-8') as handle:
    json.dump(report, handle, indent=2, default=str)
print(json.dumps(report, indent=2, default=str))
