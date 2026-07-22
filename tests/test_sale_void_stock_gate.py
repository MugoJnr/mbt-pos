"""P0 production gate: cash sale → void → stock + report consistency."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SaleVoidStockGate(unittest.TestCase):
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
        self.api._role = 'manager'
        self.api._user_id = 1
        self.api._username = 'mgr'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('mgr', 'x:y', 'manager'),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Gate Widget', 'GW1', 50.0, 20.0, 100, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_cash_sale_void_restores_stock_and_excludes_from_revenue(self):
        before = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        self.ac._db().close()

        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Gate Widget',
                'sku': 'GW1',
                'quantity': 4,
                'unit_price': 50.0,
                'discount': 0,
                'total': 200.0,
            }],
            'subtotal': 200.0,
            'discount': 0,
            'tax': 0,
            'total': 200.0,
            'payment_method': 'Cash',
            'amount_paid': 200.0,
            'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        sale_id = int(created['sale_id'])
        receipt = created.get('receipt_number') or ''

        db = self.ac._db()
        mid = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        sale_day = db.execute(
            "SELECT date(created_at) AS d FROM sales WHERE id=?", (sale_id,)
        ).fetchone()['d']
        db.close()
        self.assertEqual(mid, before - 4)

        summary = (self.api.get_report_summary(sale_day, sale_day) or {}).get('summary') or {}
        self.assertGreaterEqual(float(summary.get('collected_revenue') or 0), 200.0)

        voided = self.api.void_sale(sale_id, 'gate test void')
        self.assertTrue(voided.get('success'), voided)

        db = self.ac._db()
        after = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        status = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()['status']
        restores = db.execute(
            "SELECT COUNT(*) AS c FROM stock_movements "
            "WHERE movement_type='VOID_RESTORE' AND product_id=1"
        ).fetchone()['c']
        db.close()

        self.assertEqual(after, before)
        self.assertEqual(status, 'voided')
        self.assertGreaterEqual(int(restores), 1)
        self.assertTrue(receipt)

        summary2 = (self.api.get_report_summary(sale_day, sale_day) or {}).get('summary') or {}
        # Voided cash must not keep inflating completed revenue
        self.assertEqual(float(summary2.get('total_revenue') or 0), 0.0)

    def test_cashier_cannot_void(self):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Gate Widget', 'sku': 'GW1',
                'quantity': 1, 'unit_price': 50.0, 'discount': 0, 'total': 50.0,
            }],
            'subtotal': 50, 'total': 50, 'payment_method': 'Cash',
            'amount_paid': 50, 'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        self.api._role = 'cashier'
        denied = self.api.void_sale(int(created['sale_id']), 'nope')
        self.assertIn('error', denied)

    def test_void_then_reinstate_deducts_stock_again(self):
        self.api._role = 'superadmin'
        db = self.ac._db()
        db.execute("UPDATE users SET role='superadmin' WHERE id=1")
        before = float(db.execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        db.commit()
        db.close()

        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Gate Widget', 'sku': 'GW1',
                'quantity': 3, 'unit_price': 50.0, 'discount': 0, 'total': 150.0,
            }],
            'subtotal': 150, 'total': 150, 'payment_method': 'Cash',
            'amount_paid': 150, 'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        sale_id = int(created['sale_id'])

        voided = self.api.void_sale(sale_id, 'reinstate gate void')
        self.assertTrue(voided.get('success'), voided)
        mid = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        self.ac._db().close()
        self.assertEqual(mid, before)

        rein = self.api.edit_sale(sale_id, {
            'reason': 'reinstate after void',
            'items': [{
                'product_id': 1, 'product_name': 'Gate Widget', 'sku': 'GW1',
                'quantity': 3, 'unit_price': 50.0, 'discount': 0, 'total': 150.0,
            }],
            'payment_method': 'Cash',
            'discount': 0,
            'amount_paid': 150,
            'change_amount': 0,
        })
        self.assertTrue(rein.get('success'), rein)
        self.assertTrue(rein.get('reinstated'), rein)

        db = self.ac._db()
        after = float(db.execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        status = db.execute(
            "SELECT status FROM sales WHERE id=?", (sale_id,)
        ).fetchone()['status']
        moves = db.execute(
            "SELECT COUNT(*) AS c FROM stock_movements "
            "WHERE movement_type='SALE_REINSTATE' AND product_id=1"
        ).fetchone()['c']
        db.close()
        self.assertEqual(after, before - 3)
        self.assertEqual((status or '').lower(), 'completed')
        self.assertGreaterEqual(int(moves), 1)


if __name__ == '__main__':
    unittest.main()
