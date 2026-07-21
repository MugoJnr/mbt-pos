"""
Critical bugfix regression tests:
  - Debt delete restocks unpaid credit sales
  - Today's Revenue (Collected) excludes unpaid credit
  - edit_sale adjusts inventory

Run:
  python -m pytest tests/test_critical_bugfixes.py -v
  python tests/test_critical_bugfixes.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _ApiFixture(unittest.TestCase):
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
        self.api._username = 'tester'
        # Bootstrap schema
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('tester', 'x:y', 'superadmin')
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Widget', 'W1', 100.0, 40.0, 50, 5)
        )
        db.execute(
            "INSERT INTO customers (name, phone, credit_limit) VALUES (?,?,?)",
            ('Ada Debt', '0700', 5000)
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _make_credit_sale(self, qty=2.0, stock_before=None):
        db = self.ac._db()
        if stock_before is not None:
            db.execute("UPDATE products SET stock=? WHERE id=1", (stock_before,))
        db.execute(
            "INSERT INTO sales (receipt_number,cashier_id,cashier_name,subtotal,"
            "discount,tax,total,payment_method,amount_paid,change_amount,"
            "customer_id,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ('RCP-TEST-001', 1, 'tester', qty * 100, 0, 0, qty * 100,
             'Credit Sale', 0, 0, 1, 'completed')
        )
        sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO sale_items (sale_id,product_id,product_name,sku,"
            "quantity,unit_price,discount,total) VALUES (?,?,?,?,?,?,?,?)",
            (sale_id, 1, 'Widget', 'W1', qty, 100.0, 0, qty * 100)
        )
        # Simulate stock already deducted at sale time
        prod = db.execute("SELECT stock FROM products WHERE id=1").fetchone()
        db.execute(
            "UPDATE products SET stock=? WHERE id=1",
            (float(prod['stock']) - qty,)
        )
        db.execute(
            "INSERT INTO debt_invoices (invoice_number,sale_id,receipt_number,"
            "customer_id,customer_name,total_amount,amount_paid,balance,status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ('INV-TEST-001', sale_id, 'RCP-TEST-001', 1, 'Ada Debt',
             qty * 100, 0, qty * 100, 'unpaid')
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()
        return sale_id, inv_id


class TestDebtDeleteRestock(_ApiFixture):
    def test_unpaid_debt_delete_restores_stock(self):
        sale_id, inv_id = self._make_credit_sale(qty=3.0, stock_before=50)
        db = self.ac._db()
        stock_mid = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        db.close()
        self.assertEqual(stock_mid, 47.0)

        res = self.api.delete_debt_invoice(inv_id, 'test delete unpaid debt')
        self.assertTrue(res.get('success'), res)
        self.assertTrue(res.get('restocked'), res)

        db = self.ac._db()
        stock_after = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        sale_status = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()['status']
        inv_status = db.execute(
            "SELECT status, balance FROM debt_invoices WHERE id=?", (inv_id,)
        ).fetchone()
        mov = db.execute(
            "SELECT COUNT(*) AS c FROM stock_movements "
            "WHERE movement_type='VOID_RESTORE' AND product_id=1"
        ).fetchone()['c']
        db.close()

        self.assertEqual(stock_after, 50.0)
        self.assertEqual(sale_status, 'voided')
        self.assertEqual((inv_status['status'] or '').lower(), 'cancelled')
        self.assertEqual(float(inv_status['balance'] or 0), 0.0)
        self.assertGreaterEqual(int(mov), 1)

    def test_no_double_restock_when_already_voided(self):
        sale_id, inv_id = self._make_credit_sale(qty=2.0, stock_before=40)
        # First void restores stock
        v = self.api.void_sale(sale_id, 'pre-void')
        self.assertTrue(v.get('success'), v)
        db = self.ac._db()
        stock1 = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        # Re-open debt row for delete path (void may have cancelled it)
        db.execute(
            "UPDATE debt_invoices SET status='unpaid', balance=200, amount_paid=0 "
            "WHERE id=?",
            (inv_id,)
        )
        db.commit()
        db.close()
        self.assertEqual(stock1, 40.0)

        res = self.api.delete_debt_invoice(inv_id, 'delete after void')
        self.assertTrue(res.get('success'), res)

        db = self.ac._db()
        stock2 = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        db.close()
        self.assertEqual(stock2, 40.0)  # no double restore


class TestCollectedRevenue(_ApiFixture):
    def test_credit_sale_excluded_from_collected(self):
        today = date.today().isoformat()
        db = self.ac._db()
        # Cash sale
        db.execute(
            "INSERT INTO sales (receipt_number,cashier_name,subtotal,total,"
            "payment_method,amount_paid,change_amount,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ('RCP-CASH', 't', 100, 100, 'Cash', 100, 0, 'completed', today)
        )
        # Unpaid credit sale
        db.execute(
            "INSERT INTO sales (receipt_number,cashier_name,subtotal,total,"
            "payment_method,amount_paid,change_amount,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ('RCP-CREDIT', 't', 250, 250, 'Credit Sale', 0, 0, 'completed', today)
        )
        # Debt collection
        db.execute(
            "INSERT INTO debt_payments "
            "(payment_receipt,invoice_id,customer_id,amount,payment_method,"
            "balance_before,balance_after,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ('PAY-TEST-1', 1, 1, 80.0, 'Cash', 80.0, 0.0, today)
        )
        db.commit()
        db.close()

        summary = (self.api.get_report_summary(today, today) or {}).get('summary') or {}
        self.assertEqual(float(summary.get('total_revenue') or 0), 350.0)
        self.assertEqual(float(summary.get('credit_sales_outstanding') or 0), 250.0)
        # Collected = cash 100 + debt collection 80 (credit unpaid excluded)
        self.assertEqual(float(summary.get('collected_revenue') or 0), 180.0)


class TestEditSale(_ApiFixture):
    def test_edit_qty_adjusts_stock(self):
        sale_id, _inv = self._make_credit_sale(qty=2.0, stock_before=30)
        # stock after sale = 28
        res = self.api.edit_sale(sale_id, {
            'reason': 'qty fix',
            'items': [{
                'product_id': 1,
                'product_name': 'Widget',
                'sku': 'W1',
                'quantity': 1.0,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'payment_method': 'Credit Sale',
            'customer_id': 1,
            'discount': 0,
            'amount_paid': 0,
        })
        self.assertTrue(res.get('success'), res)
        self.assertEqual(float(res.get('total') or 0), 100.0)

        db = self.ac._db()
        stock = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        qty = float(db.execute(
            "SELECT quantity FROM sale_items WHERE sale_id=?", (sale_id,)
        ).fetchone()['quantity'])
        edits = db.execute(
            "SELECT COUNT(*) AS c FROM sale_edits WHERE sale_id=?", (sale_id,)
        ).fetchone()['c']
        db.close()
        # Restored 2 then deducted 1 → 29
        self.assertEqual(stock, 29.0)
        self.assertEqual(qty, 1.0)
        self.assertGreaterEqual(int(edits), 1)

    def test_non_superadmin_denied(self):
        sale_id, _ = self._make_credit_sale(qty=1.0, stock_before=10)
        self.api._role = 'cashier'
        res = self.api.edit_sale(sale_id, {
            'reason': 'nope',
            'items': [{
                'product_id': 1, 'product_name': 'Widget', 'quantity': 1,
                'unit_price': 100, 'discount': 0, 'total': 100,
            }],
        })
        self.assertIn('error', res)


class TestCloudLicenseMirror(unittest.TestCase):
    def test_default_engine_can_mirror_cloud_activation(self):
        import licensing.license_engine as le

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = os.path.join(tmp, 'license.db')
            with (
                patch.object(le, '_hidden_db_path', return_value=db_path),
                patch.object(le, 'resolve_device_id', return_value='a' * 40),
                patch('mbt_paths.get_project_root', return_value=tmp),
            ):
                engine = le.LicenseEngine()
                ok, message = engine.activate_from_cloud(
                    plan='trial',
                    duration_days=30,
                    license_key='MBT-TRI-TEST-CLOUD-MIRROR',
                )

                self.assertTrue(ok, message)
                self.assertTrue(engine.is_valid)
                self.assertEqual(engine._license_data.get('source'), 'mbt_cloud')
                self.assertEqual(
                    engine.store.get('cloud_license_key'),
                    'MBT-TRI-TEST-CLOUD-MIRROR',
                )


if __name__ == '__main__':
    unittest.main()
