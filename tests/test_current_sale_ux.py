"""Unit tests: no-wheel spinbox filter + payment variance allocation + small scroll."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestNoWheelSpinBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from desktop.utils.no_wheel_spinbox import install_no_wheel_spinboxes
        install_no_wheel_spinboxes(cls.app)

    def test_qdoublespinbox_wheel_does_not_change_value(self):
        from PyQt5.QtWidgets import QDoubleSpinBox
        from desktop.utils.no_wheel_spinbox import spinbox_ignores_wheel
        sp = QDoubleSpinBox()
        sp.setRange(0, 1000)
        sp.setValue(50)
        self.assertTrue(spinbox_ignores_wheel(sp))
        self.assertEqual(sp.value(), 50)

    def test_qspinbox_wheel_does_not_change_value(self):
        from PyQt5.QtWidgets import QSpinBox
        from desktop.utils.no_wheel_spinbox import spinbox_ignores_wheel
        sp = QSpinBox()
        sp.setRange(0, 1000)
        sp.setValue(7)
        self.assertTrue(spinbox_ignores_wheel(sp))
        self.assertEqual(sp.value(), 7)

    def test_keyboard_and_buttons_still_work(self):
        from PyQt5.QtWidgets import QDoubleSpinBox
        sp = QDoubleSpinBox()
        sp.setRange(0, 1000)
        sp.setSingleStep(1)
        sp.setValue(10)
        sp.stepBy(1)
        self.assertEqual(sp.value(), 11)
        sp.setValue(25)
        self.assertEqual(sp.value(), 25)


class TestNoWheelSmallScroll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        from desktop.utils.no_wheel_small_scroll import install_no_wheel_small_scroll
        install_no_wheel_small_scroll(cls.app)

    def test_height_threshold_marks_small(self):
        from PyQt5.QtWidgets import QScrollArea, QLabel, QWidget, QVBoxLayout
        from desktop.utils.no_wheel_small_scroll import (
            is_small_scroll_host, SMALL_HEIGHT_PX, mark_wheel_scroll,
        )
        small = QScrollArea()
        small.setMaximumHeight(200)
        small.setFixedHeight(200)
        body = QWidget()
        lay = QVBoxLayout(body)
        for i in range(20):
            lay.addWidget(QLabel(f'row {i}'))
        small.setWidget(body)
        small.show()
        self.assertTrue(is_small_scroll_host(small))
        self.assertLess(small.height(), SMALL_HEIGHT_PX)

        large = QScrollArea()
        large.setFixedHeight(480)
        large.show()
        self.assertFalse(is_small_scroll_host(large))

        opted = QScrollArea()
        opted.setFixedHeight(160)
        mark_wheel_scroll(opted, True)
        opted.show()
        self.assertFalse(is_small_scroll_host(opted))

        denied = QScrollArea()
        denied.setFixedHeight(500)
        mark_wheel_scroll(denied, False)
        denied.show()
        self.assertTrue(is_small_scroll_host(denied))

    def test_classic_actions_objectname_denied(self):
        from PyQt5.QtWidgets import QScrollArea
        from desktop.utils.no_wheel_small_scroll import is_small_scroll_host
        s = QScrollArea()
        s.setObjectName('posClassicActionsScroll')
        s.setFixedHeight(500)  # tall but deny-listed
        self.assertTrue(is_small_scroll_host(s))

    def test_cart_list_objectname_allowed(self):
        from PyQt5.QtWidgets import QScrollArea
        from desktop.utils.no_wheel_small_scroll import is_small_scroll_host
        s = QScrollArea()
        s.setObjectName('posCartListScroll')
        s.setFixedHeight(200)  # short but allow-listed
        self.assertFalse(is_small_scroll_host(s))

    def test_small_scroll_ignores_wheel(self):
        from PyQt5.QtWidgets import QScrollArea, QLabel, QWidget, QVBoxLayout
        from desktop.utils.no_wheel_small_scroll import small_scroll_ignores_wheel
        host = QScrollArea()
        host.setWidgetResizable(True)
        host.setMaximumHeight(180)
        host.setFixedSize(320, 180)
        body = QWidget()
        lay = QVBoxLayout(body)
        for i in range(40):
            lay.addWidget(QLabel(f'line {i} ' + ('x' * 20)))
        host.setWidget(body)
        host.show()
        self.assertTrue(small_scroll_ignores_wheel(host))

    def test_large_scroll_not_consumed_by_filter(self):
        from PyQt5.QtCore import Qt, QPoint, QPointF
        from PyQt5.QtGui import QWheelEvent
        from PyQt5.QtWidgets import QScrollArea, QLabel, QWidget, QVBoxLayout
        from desktop.utils.no_wheel_small_scroll import (
            is_small_scroll_host, NoWheelSmallScrollFilter,
        )
        host = QScrollArea()
        host.setWidgetResizable(True)
        host.setFixedSize(400, 480)
        body = QWidget()
        lay = QVBoxLayout(body)
        for i in range(60):
            lay.addWidget(QLabel(f'row {i}'))
        host.setWidget(body)
        host.show()
        self.assertFalse(is_small_scroll_host(host))
        ev = QWheelEvent(
            QPointF(20, 20), QPointF(20, 20),
            QPoint(0, 0), QPoint(0, -480),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
        )
        filt = NoWheelSmallScrollFilter()
        # Filter must NOT consume — default scroll can proceed
        self.assertFalse(filt.eventFilter(host.viewport(), ev))


class TestPaymentVarianceAllocation(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self._td.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self.db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self.db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._username = 'qa_cashier'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'superadmin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('QA Widget 500', 'QA-500', 500.0, 100.0, 200, 5),
        )
        db.commit()
        row = db.execute("SELECT id FROM products WHERE sku='QA-500'").fetchone()
        self.product = {'id': int(row['id']), 'name': 'QA Widget 500', 'sku': 'QA-500'}
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.ac._SCHEMA_READY = False
        self._td.cleanup()

    def _sale(self, total, paid, variance=None, change=0.0):
        item = {
            'product_id': self.product['id'],
            'product_name': self.product.get('name', 'Item'),
            'sku': self.product.get('sku', ''),
            'quantity': 1,
            'unit_price': total,
            'discount': 0,
            'total': total,
        }
        payload = {
            'items': [item],
            'subtotal': total,
            'discount': 0,
            'tax': 0,
            'total': total,
            'payment_method': 'cash',
            'amount_paid': paid,
            'change_amount': change,
            'notes': 'QA variance',
            'cash_rounding_adj': 0,
            'original_total': total,
        }
        if variance:
            payload['variance'] = variance
        return self.api.create_sale(payload)

    def test_exact_payment_500_500(self):
        res = self._sale(500, 500, change=0)
        self.assertTrue(res.get('success'), res)
        sale = self.api.get_sale(res['sale_id'])
        self.assertAlmostEqual(float(sale['total']), 500, places=2)
        self.assertAlmostEqual(float(sale['amount_paid']), 500, places=2)
        self.assertAlmostEqual(float(sale.get('change_amount') or 0), 0, places=2)
        self.assertFalse(sale.get('variance'))

    def test_return_change_600(self):
        var = {
            'handling': 'return_change',
            'excess_amount': 100,
            'notes': 'QA return change',
        }
        res = self._sale(500, 600, variance=var, change=100)
        self.assertTrue(res.get('success'), res)
        sale = self.api.get_sale(res['sale_id'])
        self.assertAlmostEqual(float(sale['amount_paid']), 600, places=2)
        self.assertAlmostEqual(float(sale['change_amount']), 100, places=2)
        v = sale.get('variance') or {}
        self.assertEqual(v.get('handling'), 'return_change')
        self.assertAlmostEqual(float(v.get('change_returned') or 0), 100, places=2)

    def test_additional_payment_600_internal(self):
        var = {
            'handling': 'additional_payment',
            'excess_amount': 100,
            'notes': 'QA keep extra',
        }
        res = self._sale(500, 600, variance=var, change=0)
        self.assertTrue(res.get('success'), res)
        sale = self.api.get_sale(res['sale_id'])
        self.assertAlmostEqual(float(sale['total']), 500, places=2)
        self.assertAlmostEqual(float(sale['amount_paid']), 600, places=2)
        self.assertAlmostEqual(float(sale.get('change_amount') or 0), 0, places=2)
        self.assertEqual(sale.get('variance_handling'), 'additional_payment')
        v = sale.get('variance') or {}
        self.assertEqual(v.get('handling'), 'additional_payment')
        self.assertAlmostEqual(float(v.get('excess_amount') or 0), 100, places=2)
        report = self.api.get_payment_variance_report()
        rows = report.get('rows') or []
        self.assertTrue(any(
            (r.get('handling') or '') == 'additional_payment'
            and abs(float(r.get('excess_amount') or 0) - 100) < 0.01
            for r in rows
        ))
        self.assertGreaterEqual(
            float((report.get('summary') or {}).get('additional_payments') or 0), 100)

    def test_receipt_text_hides_additional_payment(self):
        from printing.printer_engine import generate_receipt_text
        var = {
            'handling': 'additional_payment',
            'excess_amount': 100,
            'reason': 'INTERNAL ONLY',
            'notes': 'charged-more note',
        }
        data = {
            'receipt_number': 'QA-ADD-1',
            'created_at': '2026-07-23T12:00:00',
            'cashier_name': 'qa',
            'items': [{'product_name': 'Widget', 'quantity': 1,
                       'unit_price': 500, 'discount': 0, 'total': 500}],
            'subtotal': 500, 'discount': 0, 'tax': 0, 'total': 500,
            'payment_method': 'cash',
            'amount_paid': 500,
            'change_amount': 0,
            'variance': var,
            'receipt_footer': 'Thank you!',
        }
        txt = generate_receipt_text(data, 'QA Shop', 'KES')
        low = txt.lower()
        self.assertNotIn('additional', low)
        self.assertNotIn('payment variance', low)
        self.assertNotIn('charged-more', low)
        self.assertNotIn('internal only', low)
        self.assertIn('500', txt)


class TestCartLastItemSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_set_items_selects_last_not_first(self):
        from desktop.utils.pos_components import CartList
        cl = CartList()
        items = [
            {'product_id': 1, 'product_name': 'A', 'quantity': 1,
             'unit_price': 10, 'discount': 0, 'total': 10, 'sku': 'A'},
            {'product_id': 2, 'product_name': 'B', 'quantity': 1,
             'unit_price': 20, 'discount': 0, 'total': 20, 'sku': 'B'},
            {'product_id': 3, 'product_name': 'C', 'quantity': 1,
             'unit_price': 30, 'discount': 0, 'total': 30, 'sku': 'C'},
        ]
        cl.set_items(items, select_index=2)
        self.assertEqual(cl.selected_index(), 2)
        self.assertTrue(cl._rows[2].is_selected())
        self.assertFalse(cl._rows[0].is_selected())

    def test_explicit_middle_selection(self):
        from desktop.utils.pos_components import CartList
        cl = CartList()
        items = [
            {'product_id': 1, 'product_name': 'A', 'quantity': 1,
             'unit_price': 10, 'discount': 0, 'total': 10},
            {'product_id': 2, 'product_name': 'B', 'quantity': 1,
             'unit_price': 20, 'discount': 0, 'total': 20},
        ]
        cl.set_items(items, select_index=0)
        self.assertEqual(cl.selected_index(), 0)
        cl.select_index(1)
        self.assertEqual(cl.selected_index(), 1)


class TestOverpaymentDialogDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_default_is_return_change(self):
        from PyQt5.QtWidgets import QLabel
        from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
        dlg = PaymentVarianceDialog(None, 'KES', 500, 600, 100, settings={})
        self.assertTrue(dlg._radios['return_change'].isChecked())
        self.assertFalse(dlg._radios['additional_payment'].isChecked())
        self.assertIn('additional_payment', dlg._radios)
        texts = ' '.join(l.text() for l in dlg.findChildren(QLabel))
        self.assertIn('more than the invoice', texts.lower())


if __name__ == '__main__':
    unittest.main()
