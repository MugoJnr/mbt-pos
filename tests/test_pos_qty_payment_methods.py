"""P02/P03: cart qty/discount math + payment method acceptance via create_sale."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CartQtyDiscountUnit(unittest.TestCase):
    """Pure cart math from SalesTab without instantiating Qt widgets."""

    def setUp(self):
        from desktop.tabs.sales_tab import SalesTab

        self.tab = SimpleNamespace(cart=[])
        self.tab._line_gross = lambda item: SalesTab._line_gross(self.tab, item)
        self.tab._apply_line_total = lambda item: SalesTab._apply_line_total(
            self.tab, item)
        self.tab._recalc = lambda: None
        self.tab._refresh_cart = lambda: None

        def _qty(idx, v):
            return SalesTab._qty(self.tab, idx, v)

        def _rm(idx):
            return SalesTab._rm(self.tab, idx)

        def _change_qty(idx, delta):
            return SalesTab._change_qty(self.tab, idx, delta)

        self.tab._qty = _qty
        self.tab._rm = _rm
        self.tab._change_qty = _change_qty

    def test_qty_edit_remove_discount(self):
        item = {
            'product_id': 1,
            'quantity': 1.0,
            'unit_price': 100.0,
            'discount': 0.0,
            'total': 100.0,
        }
        self.tab.cart = [item]
        self.tab._qty(0, 2.5)
        self.assertEqual(self.tab.cart[0]['quantity'], 2.5)
        self.assertEqual(self.tab.cart[0]['total'], 250.0)

        self.tab.cart[0]['discount'] = 50.0
        self.tab._apply_line_total(self.tab.cart[0])
        self.assertEqual(self.tab.cart[0]['total'], 200.0)

        # Discount cannot exceed gross
        self.tab.cart[0]['discount'] = 999.0
        self.tab._apply_line_total(self.tab.cart[0])
        self.assertEqual(self.tab.cart[0]['discount'], 250.0)
        self.assertEqual(self.tab.cart[0]['total'], 0.0)

        self.tab._change_qty(0, 1.0)
        self.assertEqual(self.tab.cart[0]['quantity'], 3.5)

        self.tab._rm(0)
        self.assertEqual(self.tab.cart, [])


class PaymentMethodAcceptance(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'admin'
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
            "UPDATE users SET role='superadmin' WHERE id=?",
            (self.api._user_id,),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Pay Widget', 'PW1', 50.0, 20.0, 200, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _sale(self, method: str, *, qty: float = 1, disc: float = 0,
              amount_paid: float | None = None, electronic_paid: float = 0,
              electronic_method: str = '', notes: str = ''):
        line_gross = 50.0 * qty
        total = line_gross - disc
        paid = amount_paid if amount_paid is not None else total
        return self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Pay Widget',
                'sku': 'PW1',
                'quantity': qty,
                'unit_price': 50.0,
                'discount': disc,
                'total': total,
            }],
            'subtotal': line_gross,
            'discount': disc,
            'tax': 0,
            'total': total,
            'payment_method': method,
            'amount_paid': paid,
            'change_amount': max(0, paid - total),
            'electronic_paid': electronic_paid,
            'electronic_method': electronic_method,
            'notes': notes,
        })

    def test_core_payment_methods_accepted(self):
        from desktop.utils.option_lists import POS_PAYMENT_METHODS
        # Methods that settle in full (not credit/part)
        settle = ('Cash', 'M-Pesa', 'Card', 'Bank Transfer', 'Mixed')
        for method in settle:
            self.assertIn(method, POS_PAYMENT_METHODS)
            res = self._sale(
                method,
                qty=2,
                disc=10.0,
                amount_paid=90.0,
                electronic_paid=40.0 if method == 'Mixed' else 0,
                electronic_method='M-Pesa' if method == 'Mixed' else '',
            )
            self.assertTrue(
                res.get('success') or res.get('sale_id') or res.get('receipt_number'),
                f'{method}: {res}',
            )
            db = self.ac._db()
            row = db.execute(
                "SELECT payment_method, discount, total FROM sales "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            db.close()
            self.assertEqual(row['payment_method'], method)
            self.assertEqual(float(row['discount']), 10.0)
            self.assertEqual(float(row['total']), 90.0)


if __name__ == '__main__':
    unittest.main()
