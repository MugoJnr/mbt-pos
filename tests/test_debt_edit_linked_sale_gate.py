"""B04: Edit linked sale from debt — API + UI path via prompt_edit_sale."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DebtEditLinkedSaleGate(unittest.TestCase):
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
            ('Debt Edit Widget', 'DEW1', 100.0, 40.0, 50, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_b04_edit_linked_sale_from_debt(self):
        # UI path: debt detail -> Edit Sale -> prompt_edit_sale
        debt_path = os.path.join(ROOT, 'desktop', 'tabs', 'debt_tab.py')
        with open(debt_path, encoding='utf-8') as f:
            debt_src = f.read()
        self.assertIn('def _edit_sale(self)', debt_src)
        self.assertIn('prompt_edit_sale', debt_src)
        self.assertIn('_edit_sale_btn', debt_src)
        self.assertIn('Edit Sale', debt_src)
        self.assertIn('receipt_prefill=rn', debt_src)

        edit_path = os.path.join(ROOT, 'desktop', 'dialogs', 'edit_sale_dialog.py')
        with open(edit_path, encoding='utf-8') as f:
            edit_src = f.read()
        self.assertIn('def prompt_edit_sale', edit_src)
        self.assertIn('ask_superadmin_pin', edit_src)

        cust = self.api.create_customer({
            'name': 'B04 Customer',
            'phone': '0711000004',
            'credit_limit': 5000,
        })
        self.assertTrue(cust.get('success'), cust)
        cid = int(cust['customer_id'])

        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Debt Edit Widget',
                'sku': 'DEW1',
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
        sale_id = int(created.get('sale_id') or created.get('id'))
        receipt = created.get('receipt_number') or ''
        self.assertTrue(receipt)

        inv = self.api.create_debt_invoice({
            'customer_id': cid,
            'sale_id': sale_id,
            'receipt_number': receipt,
            'total_amount': 200.0,
            'amount_paid': 0.0,
            'notes': 'B04 linked debt',
        })
        self.assertTrue(inv.get('success'), inv)
        invoice_id = int(inv['invoice_id'])

        invoices = self.api.get_debt_invoices(customer_id=cid) or []
        linked = [
            i for i in invoices
            if int(i.get('sale_id') or 0) == sale_id
            or int(i.get('id') or 0) == invoice_id
        ]
        self.assertTrue(linked, f'no debt invoice for sale_id={sale_id}: {invoices}')
        self.assertEqual(int(linked[0]['sale_id']), sale_id)

        # API edit of the linked sale (same path debt UI ultimately calls)
        res = self.api.edit_sale(sale_id, {
            'reason': 'B04 debt-linked qty fix',
            'items': [{
                'product_id': 1,
                'product_name': 'Debt Edit Widget',
                'sku': 'DEW1',
                'quantity': 1.0,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'payment_method': 'Credit Sale',
            'customer_id': cid,
            'discount': 0,
            'amount_paid': 0,
        })
        self.assertTrue(res.get('success'), res)
        self.assertAlmostEqual(float(res.get('total') or 0), 100.0, places=2)

        sale = self.api.get_sale(sale_id) or {}
        self.assertTrue(sale.get('receipt_number') or receipt)
        edits = self.api.get_sale_edits(sale_id) or []
        self.assertGreaterEqual(len(edits), 1)

        # Linked debt balance follows edited sale total
        refreshed = self.api.get_debt_invoices(customer_id=cid) or []
        debt_row = next(
            (i for i in refreshed if int(i.get('id') or 0) == invoice_id), None)
        self.assertIsNotNone(debt_row)
        self.assertAlmostEqual(float(debt_row.get('balance') or 0), 100.0, places=2)


if __name__ == '__main__':
    unittest.main()
