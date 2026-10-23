"""A repeated sale or debt payment with the same token must not post twice."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class IdempotentMoneyTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'cashier'
        self.api._user_id = 1
        self.api._username = 'cashier'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('cashier', 'x:y', 'cashier'),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Idem Widget', 'ID1', 100.0, 40.0, 20, 1),
        )
        db.execute(
            "INSERT INTO customers (name, phone) VALUES (?,?)",
            ('Idem Customer', '0700'),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _sale(self, token, method='Cash', paid=100):
        return self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Idem Widget',
                'sku': 'ID1',
                'quantity': 1,
                'unit_price': 100,
                'discount': 0,
                'total': 100,
            }],
            'subtotal': 100,
            'total': 100,
            'payment_method': method,
            'amount_paid': paid,
            'change_amount': 0,
            'customer_id': 1,
            'client_token': token,
        })

    def test_same_sale_token_does_not_move_stock_twice(self):
        first = self._sale('sale-1')
        second = self._sale('sale-1')
        self.assertTrue(first.get('success'), first)
        self.assertTrue(second.get('success'), second)
        self.assertTrue(second.get('duplicate'))
        self.assertEqual(first['receipt_number'], second['receipt_number'])
        db = self.ac._db()
        stock = db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock']
        count = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        db.close()
        self.assertEqual(float(stock), 19)
        self.assertEqual(count, 1)

    def test_debt_overpay_is_rejected_and_replay_does_not_double_post(self):
        sale = self._sale('sale-debt', method='Credit Sale', paid=0)
        self.assertTrue(sale.get('success'), sale)
        invoices = self.api.get_debt_invoices()
        self.assertTrue(invoices, invoices)
        invoice_id = invoices[0]['id']
        over = self.api.record_debt_payment(invoice_id, 150, payment_reference='pay-1')
        self.assertIn('exceeds', over.get('error', '').lower())
        first = self.api.record_debt_payment(invoice_id, 40, payment_reference='pay-1')
        second = self.api.record_debt_payment(invoice_id, 40, payment_reference='pay-1')
        self.assertTrue(first.get('success'), first)
        self.assertTrue(second.get('success'), second)
        self.assertTrue(second.get('duplicate'))
        self.assertEqual(first['payment_receipt'], second['payment_receipt'])
        db = self.ac._db()
        balance = db.execute(
            "SELECT balance FROM debt_invoices WHERE id=?", (invoice_id,)
        ).fetchone()['balance']
        pays = db.execute(
            "SELECT COUNT(*) FROM debt_payments WHERE invoice_id=?", (invoice_id,)
        ).fetchone()[0]
        db.close()
        self.assertEqual(float(balance), 60)
        self.assertEqual(pays, 1)


if __name__ == '__main__':
    unittest.main()
