"""P0: create_sale with Credit/Part Payment auto-creates debt invoice."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CreditSaleAutoDebtGate(unittest.TestCase):
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
            ('Auto Debt Widget', 'AD1', 100.0, 40.0, 50, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_credit_sale_auto_creates_debt_invoice(self):
        cust = self.api.create_customer({
            'name': 'Auto Debt Cust',
            'phone': '0711111111',
            'credit_limit': 5000,
        })
        self.assertTrue(cust.get('success'), cust)
        cid = int(cust['customer_id'])

        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Auto Debt Widget',
                'sku': 'AD1',
                'quantity': 1,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Credit Sale',
            'amount_paid': 0.0,
            'change_amount': 0,
            'customer_id': cid,
        })
        self.assertTrue(created.get('success'), created)
        self.assertTrue(created.get('debt_invoice_id'), created)
        self.assertAlmostEqual(float(created.get('debt_balance') or -1), 100.0, places=2)

        invs = self.api.get_debt_invoices(customer_id=cid) or []
        self.assertTrue(invs)
        self.assertEqual(int(invs[0]['id']), int(created['debt_invoice_id']))

        # UI second call is idempotent
        again = self.api.create_debt_invoice({
            'customer_id': cid,
            'sale_id': int(created['sale_id']),
            'receipt_number': created['receipt_number'],
            'total_amount': 100.0,
            'amount_paid': 0.0,
        })
        self.assertTrue(again.get('success'), again)
        self.assertTrue(again.get('already_existed'), again)
        self.assertEqual(int(again['invoice_id']), int(created['debt_invoice_id']))

    def test_part_payment_auto_creates_partial_debt(self):
        cust = self.api.create_customer({
            'name': 'Part Pay Cust',
            'phone': '0722222222',
            'credit_limit': 5000,
        })
        cid = int(cust['customer_id'])
        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Auto Debt Widget',
                'sku': 'AD1',
                'quantity': 1,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Part Payment',
            'amount_paid': 40.0,
            'change_amount': 0,
            'customer_id': cid,
        })
        self.assertTrue(created.get('success'), created)
        self.assertTrue(created.get('debt_invoice_id'), created)
        self.assertAlmostEqual(float(created.get('debt_balance') or -1), 60.0, places=2)

    def test_debt_invoice_failure_rolls_back_sale_and_stock(self):
        cust = self.api.create_customer({
            'name': 'Rollback Cust',
            'phone': '0733333333',
            'credit_limit': 5000,
        })
        cid = int(cust['customer_id'])
        db = self.ac._db()
        db.execute(
            "CREATE TRIGGER fail_debt_insert BEFORE INSERT ON debt_invoices "
            "BEGIN SELECT RAISE(ABORT, 'forced debt failure'); END"
        )
        db.commit()
        db.close()

        denied = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Auto Debt Widget',
                'sku': 'AD1',
                'quantity': 1,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'subtotal': 100.0,
            'discount': 0,
            'total': 100.0,
            'payment_method': 'Credit Sale',
            'amount_paid': 0.0,
            'customer_id': cid,
        })
        self.assertIn('error', denied)
        db = self.ac._db()
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM debt_invoices").fetchone()[0], 0)
        self.assertEqual(
            float(db.execute(
                "SELECT stock FROM products WHERE id=1").fetchone()['stock']),
            50.0,
        )
        db.close()

    def test_manual_invoice_uses_linked_sale_amounts_not_client_values(self):
        cust = self.api.create_customer({
            'name': 'Canonical Debt Cust',
            'phone': '0744444444',
            'credit_limit': 5000,
        })
        cid = int(cust['customer_id'])
        db = self.ac._db()
        db.execute(
            "INSERT INTO sales "
            "(receipt_number,cashier_id,cashier_name,subtotal,discount,tax,"
            "total,payment_method,amount_paid,change_amount,customer_id,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                'RCP-CANONICAL', self.api._user_id, 'admin',
                100, 0, 0, 100, 'Credit Sale', 0, 0, cid, 'completed',
            ),
        )
        sale_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
        db.close()

        created = self.api.create_debt_invoice({
            'customer_id': cid,
            'sale_id': sale_id,
            'receipt_number': 'RCP-CANONICAL',
            'total_amount': 99999,
            'amount_paid': 99998,
        })
        self.assertTrue(created.get('success'), created)
        self.assertEqual(float(created['balance']), 100.0)
        db = self.ac._db()
        invoice = db.execute(
            "SELECT total_amount,amount_paid,balance FROM debt_invoices "
            "WHERE id=?",
            (created['invoice_id'],),
        ).fetchone()
        db.close()
        self.assertEqual(float(invoice['total_amount']), 100.0)
        self.assertEqual(float(invoice['amount_paid']), 0.0)
        self.assertEqual(float(invoice['balance']), 100.0)


if __name__ == '__main__':
    unittest.main()
