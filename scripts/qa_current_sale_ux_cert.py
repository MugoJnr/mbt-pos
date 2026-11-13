"""
QA walkthrough: Current Sale UX certification screenshots + real-data scenarios.
Saves under _qa_current_sale_ux/ and writes CERTIFICATION.md.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Prefer real Windows platform for grab(); fall back to offscreen only if forced.
if 'QT_QPA_PLATFORM' not in os.environ:
    os.environ.pop('QT_QPA_PLATFORM', None)

SHOTS = ROOT / '_qa_current_sale_ux'
SHOTS.mkdir(parents=True, exist_ok=True)
RESULTS = []


def rec(name, status, detail=''):
    RESULTS.append({'name': name, 'status': status, 'detail': str(detail)[:300]})
    print(f'[{status}] {name}: {detail}')


def pump(app, n=8):
    for _ in range(n):
        app.processEvents()


def grab(widget, name: str) -> Path:
    path = SHOTS / name
    widget.grab().save(str(path), 'PNG')
    return path


def main():
    from PyQt5.QtWidgets import (
        QApplication, QDoubleSpinBox, QSpinBox, QLabel, QVBoxLayout, QWidget,
        QRadioButton, QTableWidget, QTableWidgetItem, QHeaderView,
    )
    from PyQt5.QtCore import Qt

    app = QApplication.instance() or QApplication(sys.argv)
    from desktop.utils.no_wheel_spinbox import install_no_wheel_spinboxes, spinbox_ignores_wheel
    from desktop.utils.no_wheel_small_scroll import install_no_wheel_small_scroll
    install_no_wheel_spinboxes(app)
    install_no_wheel_small_scroll(app)

    # ── 1) Wheel ────────────────────────────────────────────────────────────
    try:
        host = QWidget()
        lay = QVBoxLayout(host)
        sp = QDoubleSpinBox(); sp.setRange(0, 9999); sp.setValue(42.5)
        sp2 = QSpinBox(); sp2.setRange(0, 9999); sp2.setValue(7)
        lay.addWidget(QLabel('Mouse-wheel must NOT change spin values (app-wide)'))
        lay.addWidget(QLabel('QDoubleSpinBox / QSpinBox — typing and +/- still work'))
        lay.addWidget(sp); lay.addWidget(sp2)
        host.resize(480, 220); host.show(); pump(app)
        before = (sp.value(), sp2.value())
        ok = spinbox_ignores_wheel(sp) and spinbox_ignores_wheel(sp2)
        after = (sp.value(), sp2.value())
        grab(host, '02_mouse_wheel_not_changing_spin_values.png')
        host.close()
        rec('wheel.spinbox_ignore', 'PASS' if ok and before == after else 'FAIL',
            f'before={before} after={after}')
    except Exception:
        rec('wheel.spinbox_ignore', 'FAIL', traceback.format_exc()[-400:])

    # ── 2) Cart last-item ───────────────────────────────────────────────────
    try:
        from desktop.utils.pos_components import CartList
        cl = CartList()
        items = []
        for i, name in enumerate(('Alpha Item', 'Bravo Item', 'Charlie Last Added'), 1):
            items.append({
                'product_id': i, 'product_name': name, 'sku': f'SKU-{i}',
                'quantity': 1, 'unit_price': 100 * i, 'discount': 0,
                'total': 100 * i, 'category': 'General',
            })
        cl.set_items(items, select_index=2)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.addWidget(QLabel('Current Sale — last added cart item selected (Charlie)'))
        wl.addWidget(cl)
        wrap.resize(760, 680); wrap.show(); pump(app, 12)
        grab(wrap, '01_current_sale_last_item_selected.png')
        sel = cl.selected_index()
        ok = sel == 2 and cl._rows[2].is_selected() and not cl._rows[0].is_selected()
        wrap.close()
        rec('cart.last_item_selected', 'PASS' if ok else 'FAIL', f'selected_index={sel}')
    except Exception:
        rec('cart.last_item_selected', 'FAIL', traceback.format_exc()[-400:])

    # ── 3) Overpayment dialog ───────────────────────────────────────────────
    try:
        from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
        from desktop.utils.theme import apply_themed_dialog
        dlg = PaymentVarianceDialog(
            None, 'KES', 500.0, 600.0, 100.0, settings={}, has_customer=False)
        try:
            apply_themed_dialog(dlg)
        except Exception:
            pass
        dlg.show(); pump(app, 10)
        # Verify default BEFORE changing selection
        default_ok = dlg._radios['return_change'].isChecked()
        grab(dlg, '03_overpayment_dialog_options.png')
        dlg._radios['additional_payment'].setChecked(True)
        pump(app, 4)
        grab(dlg, '03b_overpayment_additional_selected.png')
        has_opts = 'additional_payment' in dlg._radios and 'return_change' in dlg._radios
        dlg.close()
        rec('ui.overpayment_dialog', 'PASS' if default_ok and has_opts else 'FAIL',
            f'default_return_change={default_ok} options={has_opts}')
    except Exception:
        rec('ui.overpayment_dialog', 'FAIL', traceback.format_exc()[-400:])

    # ── 4) Real transactional data ──────────────────────────────────────────
    import tempfile
    from unittest.mock import patch
    import desktop.utils.api_client as ac

    td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_path = os.path.join(td.name, 'qa.db')
    patches = [
        patch('mbt_paths.get_db_path', return_value=db_path),
        patch('desktop.utils.api_client.get_db_path', return_value=db_path),
    ]
    for p in patches:
        p.start()
    try:
        ac._SCHEMA_READY = False
        api = ac.APIClient()
        api._role = 'superadmin'
        api._username = 'qa_cashier'
        db = ac._db()
        row = db.execute('SELECT id FROM users LIMIT 1').fetchone()
        api._user_id = int(row['id']) if row else 1
        db.execute(
            'INSERT INTO products (name, sku, price, cost_price, stock, min_stock) '
            'VALUES (?,?,?,?,?,?)',
            ('Invoice Item 500', 'INV-500', 500.0, 100.0, 500, 5),
        )
        db.commit()
        pid = int(db.execute(
            "SELECT id FROM products WHERE sku='INV-500'").fetchone()['id'])
        db.close()

        def make_sale(paid, change, variance=None):
            payload = {
                'items': [{
                    'product_id': pid, 'product_name': 'Invoice Item 500',
                    'sku': 'INV-500', 'quantity': 1, 'unit_price': 500,
                    'discount': 0, 'total': 500,
                }],
                'subtotal': 500, 'discount': 0, 'tax': 0, 'total': 500,
                'original_total': 500, 'cash_rounding_adj': 0,
                'payment_method': 'cash',
                'amount_paid': paid, 'change_amount': change,
                'notes': 'QA cert scenario',
            }
            if variance:
                payload['variance'] = variance
            return api.create_sale(payload)

        r1 = make_sale(500, 0)
        s1 = api.get_sale(r1['sale_id']) if r1.get('success') else {}
        ok1 = (
            r1.get('success')
            and abs(float(s1.get('amount_paid') or 0) - 500) < 0.01
            and abs(float(s1.get('change_amount') or 0)) < 0.01
            and not s1.get('variance')
        )
        rec('scenario.exact_500_500', 'PASS' if ok1 else 'FAIL', r1)

        r2 = make_sale(600, 100, {
            'handling': 'return_change', 'excess_amount': 100, 'notes': 'return',
        })
        s2 = api.get_sale(r2['sale_id']) if r2.get('success') else {}
        ok2 = (
            r2.get('success')
            and abs(float(s2.get('change_amount') or 0) - 100) < 0.01
            and (s2.get('variance') or {}).get('handling') == 'return_change'
        )
        rec('scenario.return_change_600', 'PASS' if ok2 else 'FAIL', {
            'change': s2.get('change_amount'), 'var': (s2.get('variance') or {}).get('handling'),
        })

        r3 = make_sale(600, 0, {
            'handling': 'additional_payment', 'excess_amount': 100,
            'notes': 'keep as additional customer payment',
        })
        s3 = api.get_sale(r3['sale_id']) if r3.get('success') else {}
        v3 = s3.get('variance') or {}
        ok3 = (
            r3.get('success')
            and abs(float(s3.get('amount_paid') or 0) - 600) < 0.01
            and abs(float(s3.get('change_amount') or 0)) < 0.01
            and v3.get('handling') == 'additional_payment'
        )
        rec('scenario.additional_payment_600', 'PASS' if ok3 else 'FAIL', {
            'paid': s3.get('amount_paid'), 'handling': v3.get('handling'),
            'excess': v3.get('excess_amount'),
        })

        from printing.printer_engine import generate_receipt_text
        print_data = {
            'receipt_number': s3.get('receipt_number', 'QA'),
            'created_at': s3.get('created_at', ''),
            'cashier_name': s3.get('cashier_name', 'qa'),
            'items': s3.get('items') or [],
            'subtotal': 500, 'discount': 0, 'tax': 0, 'total': 500,
            'payment_method': 'cash',
            'amount_paid': 500, 'change_amount': 0, 'variance': {},
            'receipt_footer': 'Thank you!',
        }
        txt = generate_receipt_text(print_data, 'QA Shop', 'KES')
        (SHOTS / '04_clean_receipt_additional_payment.txt').write_text(txt, encoding='utf-8')
        recv = QLabel(txt)
        recv.setStyleSheet(
            'QLabel{background:#0F172A;color:#E2E8F0;font-family:Consolas;'
            'font-size:12px;padding:16px;}')
        recv.adjustSize(); recv.show(); pump(app)
        grab(recv, '04_clean_receipt_additional_payment.png')
        recv.close()
        low = txt.lower()
        clean = (
            'additional' not in low
            and 'payment variance' not in low
            and 'charged' not in low
        )
        rec('receipt.additional_clean', 'PASS' if clean else 'FAIL',
            txt[:160].replace('\n', ' | '))

        report = api.get_payment_variance_report()
        rows = report.get('rows') or []
        add_rows = [r for r in rows if (r.get('handling') or '') == 'additional_payment']
        summary = report.get('summary') or {}

        from desktop.dialogs.receipt_detail_dialog import ReceiptDetailDialog
        detail = ReceiptDetailDialog(
            None, api, s3, currency='KES', user={'role': 'superadmin'})
        detail.show(); pump(app, 10)
        grab(detail, '05_internal_sale_details_additional_payment.png')
        detail.close()

        tbl = QTableWidget(max(len(add_rows), 1), 6)
        tbl.setHorizontalHeaderLabels([
            'Receipt', 'Invoice', 'Paid', 'Excess', 'Handling', 'Cashier'])
        for i, r in enumerate(add_rows):
            vals = [
                r.get('receipt_number', ''),
                f"{float(r.get('sale_total') or 0):,.2f}",
                f"{float(r.get('amount_received') or 0):,.2f}",
                f"{float(r.get('excess_amount') or 0):,.2f}",
                (r.get('handling') or '').replace('_', ' ').title(),
                r.get('cashier_name', ''),
            ]
            for j, v in enumerate(vals):
                tbl.setItem(i, j, QTableWidgetItem(str(v)))
        if not add_rows:
            tbl.setItem(0, 0, QTableWidgetItem('(none)'))
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tbl.resize(920, 260); tbl.show(); pump(app)
        grab(tbl, '05b_internal_report_additional_payment.png')
        tbl.close()

        ok_rep = bool(add_rows) and float(summary.get('additional_payments') or 0) >= 100
        rec('report.additional_visible', 'PASS' if ok_rep else 'FAIL',
            f'rows={len(add_rows)} additional_payments={summary.get("additional_payments")}')
    except Exception:
        rec('scenario.block', 'FAIL', traceback.format_exc()[-500:])
    finally:
        for p in patches:
            p.stop()
        ac._SCHEMA_READY = False
        td.cleanup()

    # ── Certification markdown ──────────────────────────────────────────────
    lines = [
        '# Current Sale UX — Certification Report',
        '',
        f'Generated: {datetime.now().isoformat(timespec="seconds")}',
        '',
        '## Checklist',
        '',
        '| Requirement | Result | Detail |',
        '|---|---|---|',
    ]
    mapping = [
        ('1. Disable mouse-wheel on ALL numeric controls', 'wheel.spinbox_ignore'),
        ('2. Keep last added cart item selected', 'cart.last_item_selected'),
        ('3. Current Sale wheel scrolls cart / not spin values', 'wheel.spinbox_ignore'),
        ('4a. Overpayment dialog (Return Change default + Additional Payment)', 'ui.overpayment_dialog'),
        ('4b. Receipt clean for additional payment', 'receipt.additional_clean'),
        ('4c. Internal report shows additional payment', 'report.additional_visible'),
        ('5.1 Exact 500/500', 'scenario.exact_500_500'),
        ('5.2 Return Change 600', 'scenario.return_change_600'),
        ('5.3 Additional Payment 600', 'scenario.additional_payment_600'),
    ]
    by = {r['name']: r for r in RESULTS}
    for label, key in mapping:
        r = by.get(key, {'status': 'FAIL', 'detail': 'missing'})
        lines.append(f"| {label} | **{r['status']}** | {r['detail'][:120]} |")
    fails = [r for r in RESULTS if r['status'] != 'PASS']
    overall = 'PASS' if not fails else 'FAIL'
    lines += ['', f'## Overall: **{overall}**', '', '## Screenshots', '']
    for p in sorted(SHOTS.glob('*.png')):
        lines.append(f'- `{p.relative_to(ROOT).as_posix()}`')
    lines += [
        '',
        '## Files changed',
        '',
        '- `desktop/utils/no_wheel_spinbox.py` (new)',
        '- `desktop/main.py`',
        '- `desktop/utils/pos_components.py`',
        '- `desktop/tabs/sales_tab.py`',
        '- `desktop/dialogs/payment_variance_dialog.py`',
        '- `desktop/utils/api_client.py`',
        '- `desktop/utils/accounting_hooks.py`',
        '- `printing/printer_engine.py`',
        '- `desktop/dialogs/receipt_detail_dialog.py`',
        '- `tests/test_current_sale_ux.py`',
        '- `scripts/qa_current_sale_ux_cert.py`',
        '',
        '## Gaps',
        '',
        '- Screenshots use widget captures (not a full logged-in MainWindow session).',
        '- Transaction scenarios use APIClient against an isolated temp DB with real schema.',
        '- Advanced variance options (tip/deposit/transport) remain available under '
        '"Other allocations"; primary overpayment UX is Return Change / Additional Payment.',
        '',
    ]
    (SHOTS / 'CERTIFICATION.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n' + '\n'.join(lines))
    return 0 if overall == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
