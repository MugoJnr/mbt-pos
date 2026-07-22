"""P0 production gate: credit sale → debt collect → write-off remaining."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CreditDebtCollectGate(unittest.TestCase):
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
            "UPDATE users SET role='superadmin' WHERE id=?",
            (self.api._user_id,),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Credit Widget', 'CW1', 100.0, 40.0, 50, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_credit_sale_partial_collect_then_write_off(self):
        cust = self.api.create_customer({
            'name': 'Gate Customer',
            'phone': '0712345678',
            'credit_limit': 10000,
        })
        self.assertTrue(cust.get('success'), cust)
        cid = int(cust['customer_id'])

        stock_before = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        self.ac._db().close()

        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Credit Widget',
                'sku': 'CW1',
                'quantity': 2,
                'unit_price': 100.0,
                'discount': 0,
                'total': 200.0,
            }],
            'subtotal': 200.0,
            'discount': 0,
            'tax': 0,
            'total': 200.0,
            'payment_method': 'Credit Sale',
            'amount_paid': 0.0,
            'change_amount': 0,
            'customer_id': cid,
        })
        self.assertTrue(created.get('success'), created)
        sale_id = int(created['sale_id'])
        receipt = created.get('receipt_number') or ''
        self.assertTrue(receipt)

        mid_stock = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        self.ac._db().close()
        self.assertEqual(mid_stock, stock_before - 2)

        inv = self.api.create_debt_invoice({
            'customer_id': cid,
            'sale_id': sale_id,
            'receipt_number': receipt,
            'total_amount': 200.0,
            'amount_paid': 0.0,
            'notes': 'gate credit',
        })
        self.assertTrue(inv.get('success'), inv)
        invoice_id = int(inv['invoice_id'])
        self.assertAlmostEqual(float(inv.get('balance') or 0), 200.0, places=2)

        paid = self.api.record_debt_payment(
            invoice_id, 80.0, payment_method='cash', notes='partial collect')
        self.assertTrue(paid.get('success'), paid)

        db = self.ac._db()
        row = db.execute(
            "SELECT balance, amount_paid, status FROM debt_invoices WHERE id=?",
            (invoice_id,),
        ).fetchone()
        pay_count = db.execute(
            "SELECT COUNT(*) AS c FROM debt_payments WHERE invoice_id=?",
            (invoice_id,),
        ).fetchone()['c']
        db.close()
        self.assertAlmostEqual(float(row['balance']), 120.0, places=2)
        self.assertAlmostEqual(float(row['amount_paid']), 80.0, places=2)
        self.assertEqual(row['status'], 'partial')
        self.assertEqual(int(pay_count), 1)

        wiped = self.api.delete_debt_invoice(invoice_id, 'gate write-off remaining')
        self.assertTrue(wiped.get('success'), wiped)

        db = self.ac._db()
        after = db.execute(
            "SELECT balance, status FROM debt_invoices WHERE id=?",
            (invoice_id,),
        ).fetchone()
        sale_status = db.execute(
            "SELECT status FROM sales WHERE id=?", (sale_id,)
        ).fetchone()['status']
        stock_after = float(db.execute(
            "SELECT stock FROM products WHERE id=1"
        ).fetchone()['stock'])
        db.close()

        # Partial write-off keeps sale + stock (goods delivered); clears remaining balance
        self.assertNotEqual(sale_status, 'voided')
        self.assertEqual(stock_after, stock_before - 2)
        self.assertIn(after['status'], ('written_off', 'cancelled'))
        self.assertAlmostEqual(float(after['balance'] or 0), 0.0, places=2)

    def test_manager_cannot_write_off_debt(self):
        self.api._role = 'manager'
        cust = self.api.create_customer({'name': 'Mgr Block', 'phone': '0799999999'})
        self.assertTrue(cust.get('success'), cust)
        cid = int(cust['customer_id'])
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Credit Widget', 'sku': 'CW1',
                'quantity': 1, 'unit_price': 100.0, 'discount': 0, 'total': 100.0,
            }],
            'subtotal': 100, 'total': 100, 'payment_method': 'Credit Sale',
            'amount_paid': 0, 'change_amount': 0, 'customer_id': cid,
        })
        self.assertTrue(created.get('success'), created)
        inv = self.api.create_debt_invoice({
            'customer_id': cid,
            'sale_id': created['sale_id'],
            'receipt_number': created['receipt_number'],
            'total_amount': 100.0,
            'amount_paid': 0.0,
        })
        self.assertTrue(inv.get('success'), inv)
        denied = self.api.delete_debt_invoice(inv['invoice_id'], 'should fail')
        self.assertIn('error', denied)

    def test_debt_invoices_list_and_aging(self):
        """B01: invoices list + aging report after open credit debt."""
        cust = self.api.create_customer({
            'name': 'Aging Customer', 'phone': '0711000000', 'credit_limit': 5000,
        })
        self.assertTrue(cust.get('success'), cust)
        cid = int(cust['customer_id'])
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Credit Widget', 'sku': 'CW1',
                'quantity': 1, 'unit_price': 100.0, 'discount': 0, 'total': 100.0,
            }],
            'subtotal': 100, 'total': 100, 'payment_method': 'Credit Sale',
            'amount_paid': 0, 'change_amount': 0, 'customer_id': cid,
        })
        self.assertTrue(created.get('success'), created)
        inv = self.api.create_debt_invoice({
            'customer_id': cid,
            'sale_id': created['sale_id'],
            'receipt_number': created['receipt_number'],
            'total_amount': 100.0,
            'amount_paid': 0.0,
            'due_date': '2099-01-01',
        })
        self.assertTrue(inv.get('success'), inv)
        invoice_id = int(inv['invoice_id'])

        listed = self.api.get_debt_invoices(customer_id=cid)
        self.assertTrue(any(int(r['id']) == invoice_id for r in listed), listed)

        aging = self.api.get_aging_report()
        self.assertIn('current', aging)
        self.assertIn('over_90', aging)
        self.assertGreaterEqual(int(aging['current'].get('count') or 0), 1)

        paid = self.api.record_debt_payment(invoice_id, 25.0, payment_method='cash')
        self.assertTrue(paid.get('success'), paid)
        hist = self.api.get_debt_payments(invoice_id=invoice_id)
        self.assertGreaterEqual(len(hist), 1)
        self.assertAlmostEqual(float(hist[0].get('amount') or 0), 25.0, places=2)


if __name__ == '__main__':
    unittest.main()
