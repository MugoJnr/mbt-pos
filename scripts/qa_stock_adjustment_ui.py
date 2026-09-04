"""Exercise the real Qt Adjust Stock dialog against isolated SQLite data."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = datetime.now().strftime('%Y%m%d_%H%M%S')
DATA_ROOT = Path(os.environ.get(
    'MBT_QA_STOCK_DATA_ROOT', rf'C:\MBT_QA\StockAdjustment\{RUN_ID}'))
OUT = Path(os.environ.get(
    'MBT_QA_STOCK_OUT', rf'C:\MBT_QA\StockAdjustmentEvidence\{RUN_ID}'))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ['MBT_DATA_ROOT'] = str(DATA_ROOT)
os.environ['MBT_QA_ALLOW_DEV_BOOTSTRAP'] = '1'
os.environ['MBT_BOOTSTRAP_ADMIN_PASSWORD'] = 'admin123'
os.environ['MBT_AUTO_SUPERADMIN_PIN'] = '1110'
os.environ['MBT_SESSION_IDLE_SEC'] = '0'

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication, QDialogButtonBox, QDoubleSpinBox, QMainWindow, QMessageBox,
)

from desktop.utils.api_client import APIClient, _db
from desktop.utils.security import _pin_hash
from desktop.utils.select_controls import ReasonSelect, SearchableSelect, Select
import desktop.main as dm
from desktop.main import MainWindow, _load_icon


def pump(count=15):
    for _ in range(count):
        QApplication.processEvents()


def configure_qa_data(api):
    db = _db()
    db.execute(
        "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
        ('superadmin_pin_hash', _pin_hash('1110')),
    )
    db.commit()
    db.close()
    result = api.create_product({
        'name': f'QA Adjust Stock {RUN_ID}',
        'sku': f'QA-AS-{RUN_ID}',
        'price': 50,
        'cost_price': 30,
        'stock': 10,
        'min_stock': 1,
        'unit': 'kg',
    })
    if not result.get('success'):
        raise RuntimeError(result)
    pid = int(result['id'])
    # Product create is metadata-only (v3.0.75+); seed opening qty for QA.
    db = _db()
    try:
        db.execute('UPDATE products SET stock=10 WHERE id=?', (pid,))
        db.commit()
    finally:
        db.close()
    return pid


def drive_adjustment(inv, pid, direction, quantity, reason, shot_name):
    failure = []

    def fill_and_submit():
        try:
            dialogs = [
                w for w in QApplication.topLevelWidgets()
                if w.isVisible() and w.windowTitle() == 'Adjust Stock'
            ]
            if not dialogs:
                raise RuntimeError('Adjust Stock dialog did not open')
            dialog = dialogs[-1]
            product = dialog.findChild(SearchableSelect)
            amount = dialog.findChild(QDoubleSpinBox)
            reason_widget = dialog.findChild(ReasonSelect)
            direction_widget = next(
                w for w in dialog.findChildren(Select)
                if w.findData('add') >= 0 and w.findData('remove') >= 0
            )
            buttons = dialog.findChild(QDialogButtonBox)
            if not all((product, amount, reason_widget, buttons)):
                raise RuntimeError('Required Adjust Stock controls are missing')
            if not product.set_value(pid):
                raise RuntimeError('QA product could not be selected')
            direction_widget.set_value(direction)
            amount.setValue(quantity)
            reason_widget._select.set_value(reason)
            pump(8)
            dialog.grab().save(str(OUT / shot_name), 'PNG')
            buttons.button(QDialogButtonBox.Ok).click()
        except Exception as exc:
            failure.append(str(exc))
            for widget in QApplication.topLevelWidgets():
                if widget.windowTitle() == 'Adjust Stock':
                    widget.reject()

    QTimer.singleShot(150, fill_and_submit)
    inv._adjust_stock_dialog()
    pump(12)
    if failure:
        raise RuntimeError(failure[0])


def database_evidence(pid):
    db = _db()
    try:
        product = dict(db.execute(
            'SELECT * FROM products WHERE id=?', (pid,)
        ).fetchone())
        movements = [
            dict(row) for row in db.execute(
                "SELECT * FROM stock_movements WHERE product_id=? "
                "AND movement_type='SUPERADMIN_ADJUST' ORDER BY id",
                (pid,),
            ).fetchall()
        ]
        audits = [
            dict(row) for row in db.execute(
                "SELECT * FROM audit_log WHERE action='STOCK_ADJUSTED' "
                "AND details LIKE ? ORDER BY id",
                (f'pid={pid} %',),
            ).fetchall()
        ]
        return product, movements, audits
    finally:
        db.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion')
    dm.MainWindow._start_services = lambda self: None
    dm.MainWindow._initial_conn_check = lambda self: None
    dm.MainWindow._restore_pending_update = lambda self: None
    dm.MainWindow._warm_remaining_tabs = lambda self: None
    dm.MainWindow._qa_dump_theme_evidence = lambda self: None
    dm.MainWindow._qa_dump_theme_evidence_late = lambda self: None
    QMainWindow.showMaximized = lambda self: (self.resize(1440, 900), self.show())
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

    api = APIClient()
    login = api.login('admin', 'admin123')
    if not login.get('token'):
        raise RuntimeError(f'QA login failed: {login}')
    api.set_token(login['token'])
    pid = configure_qa_data(api)

    window = MainWindow(login, api, _load_icon())
    window.show()
    pump(25)
    window._goto('inventory')
    pump(20)
    inventory = window._tabs.get('inventory')
    if inventory is None:
        raise RuntimeError('Inventory tab was not created')
    inventory.refresh()
    pump(12)

    drive_adjustment(
        inventory, pid, 'add', 5, 'Stock Count Correction',
        '01_add_stock_dialog.png',
    )
    drive_adjustment(
        inventory, pid, 'remove', 0.25, 'Damaged / Spoiled',
        '02_remove_decimal_dialog.png',
    )
    product, movements, audits = database_evidence(pid)
    if float(product['stock']) != 14.75:
        raise AssertionError(f"Expected 14.75, got {product['stock']}")
    if [float(row['qty_change']) for row in movements] != [5.0, -0.25]:
        raise AssertionError(f'Unexpected movements: {movements}')
    if len(audits) != 2:
        raise AssertionError(f'Expected 2 stock audits, got {len(audits)}')

    window.close()
    pump(15)
    reopened_api = APIClient()
    reopened_login = reopened_api.login('admin', 'admin123')
    reopened_api.set_token(reopened_login['token'])
    reopened = MainWindow(reopened_login, reopened_api, _load_icon())
    reopened.show()
    pump(25)
    reopened._goto('inventory')
    pump(20)
    reopened._tabs['inventory'].refresh()
    pump(12)
    reopened.grab().save(str(OUT / '03_reopened_inventory.png'), 'PNG')
    persisted, persisted_movements, persisted_audits = database_evidence(pid)
    if float(persisted['stock']) != 14.75:
        raise AssertionError('Stock did not persist after app reopen')
    reopened.close()

    report = {
        'status': 'PASS',
        'data_root': str(DATA_ROOT),
        'product_id': pid,
        'stock': persisted['stock'],
        'movements': persisted_movements,
        'audits': persisted_audits,
        'screenshots': sorted(p.name for p in OUT.glob('*.png')),
    }
    (OUT / 'result.json').write_text(
        json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
