"""Certification: checkout money, split tenders, stock atomicity (temp DB)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CertCheckoutMoney(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'cert.db')
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
        self.api._username = 'cert'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('cert', 'x:y', 'superadmin'),
        )
        db.execute(
            "INSERT INTO products (name, sku, barcode, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?,?)",
            ('Cert Soap', 'CERT-SOAP', '6161999001', 110.50, 80.0, 20, 2),
        )
        db.execute(
            "INSERT INTO products (name, sku, barcode, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?,?)",
            ('Cert Oil', 'CERT-OIL', '6161999002', 40.0, 25.0, 10, 1),
        )
        db.execute(
            "INSERT INTO customers (name, phone, credit_limit) VALUES (?,?,?)",
            ('Cert Customer', '0700', 5000),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _sale(self, **extra):
        payload = {
            'items': [
                {'product_id': 1, 'quantity': 1, 'unit_price': 110.50, 'discount': 0},
                {'product_id': 2, 'quantity': 0.5, 'unit_price': 40.0, 'discount': 0},
            ],
            'subtotal': 130.50,
            'discount': 0,
            'tax': 0,
            'total': 130.50,
            'payment_method': extra.get('payment_method', 'Cash'),
            'amount_paid': extra.get('amount_paid', 130.50),
            'change_amount': extra.get('change_amount', 0),
            'customer_id': extra.get('customer_id'),
            'status': 'completed',
        }
        payload.update(extra)
        return self.api.create_sale(payload)

    def test_decimal_qty_stock_and_history_agree(self):
        r = self._sale()
        self.assertTrue(r.get('ok') or r.get('id') or r.get('sale_id'), r)
        db = self.ac._db()
        soap = db.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]
        oil = db.execute('SELECT stock FROM products WHERE id=2').fetchone()[0]
        sale = db.execute(
            'SELECT total, amount_paid, change_amount FROM sales ORDER BY id DESC LIMIT 1'
        ).fetchone()
        items = db.execute('SELECT COUNT(*) FROM sale_items').fetchone()[0]
        db.close()
        self.assertEqual(float(soap), 19.0)
        self.assertEqual(float(oil), 9.5)
        self.assertAlmostEqual(float(sale[0]), 130.50, places=2)
        self.assertEqual(items, 2)

    def test_overpay_change(self):
        r = self._sale(amount_paid=150.50, change_amount=20.0)
        self.assertTrue(r.get('ok') or r.get('id') or r.get('sale_id'), r)
        db = self.ac._db()
        row = db.execute(
            'SELECT total, amount_paid, change_amount FROM sales ORDER BY id DESC LIMIT 1'
        ).fetchone()
        db.close()
        self.assertAlmostEqual(float(row[0]), 130.50, places=2)
        self.assertAlmostEqual(float(row[1]), 150.50, places=2)
        self.assertAlmostEqual(float(row[2]), 20.0, places=2)

    def test_split_tenders_persisted(self):
        r = self._sale(
            payment_method='Mixed',
            amount_paid=130.50,
            electronic_paid=80.50,
            electronic_method='M-Pesa',
            cash_paid=50.0,
        )
        self.assertTrue(r.get('ok') or r.get('id') or r.get('sale_id'), r)
        db = self.ac._db()
        row = db.execute(
            'SELECT electronic_paid, electronic_method, cash_paid, payment_tenders, notes '
            'FROM sales ORDER BY id DESC LIMIT 1'
        ).fetchone()
        db.close()
        self.assertAlmostEqual(float(row[0] or 0), 80.50, places=2)
        self.assertEqual(row[1], 'M-Pesa')
        self.assertAlmostEqual(float(row[2] or 0), 50.0, places=2)

    def test_split_part_pay_creates_debt_balance(self):
        r = self._sale(
            payment_method='part payment',
            amount_paid=70.0,
            electronic_paid=40.0,
            electronic_method='M-Pesa',
            cash_paid=30.0,
            customer_id=1,
            payment_tenders=[
                {'method': 'M-Pesa', 'amount': 40.0},
                {'method': 'Cash', 'amount': 30.0},
            ],
        )
        self.assertTrue(r.get('success') or r.get('sale_id'), r)
        sid = r.get('sale_id')
        self.assertTrue(sid)
        self.assertTrue(r.get('debt_invoice_id') or r.get('debt_invoice_number'), r)
        self.assertAlmostEqual(float(r.get('debt_balance') or 0), 60.50, places=2)
        db = self.ac._db()
        sale = db.execute(
            'SELECT payment_method, amount_paid, electronic_paid, cash_paid, payment_tenders '
            'FROM sales WHERE id=?',
            (sid,),
        ).fetchone()
        inv = db.execute(
            'SELECT total_amount, amount_paid, balance, status FROM debt_invoices WHERE sale_id=?',
            (sid,),
        ).fetchone()
        db.close()
        self.assertEqual(str(sale[0]).lower(), 'part payment')
        self.assertAlmostEqual(float(sale[1]), 70.0, places=2)
        self.assertAlmostEqual(float(sale[2]), 40.0, places=2)
        self.assertAlmostEqual(float(sale[3]), 30.0, places=2)
        self.assertIn('M-Pesa', str(sale[4] or ''))
        self.assertAlmostEqual(float(inv[0]), 130.50, places=2)
        self.assertAlmostEqual(float(inv[1]), 70.0, places=2)
        self.assertAlmostEqual(float(inv[2]), 60.50, places=2)
        self.assertEqual(str(inv[3]), 'partial')
        from desktop.utils.payment_tenders import collected_and_balance, format_sale_payment
        collected, bal = collected_and_balance(
            due=130.50, cash_paid=30.0, electronic_paid=40.0)
        self.assertAlmostEqual(collected, 70.0, places=2)
        self.assertAlmostEqual(bal, 60.50, places=2)
        self.assertIn('Part pay', format_sale_payment({
            'payment_method': 'part payment',
            'payment_tenders': [
                {'method': 'M-Pesa', 'amount': 40.0},
                {'method': 'Cash', 'amount': 30.0},
            ],
        }))

    def test_insufficient_stock_rolls_back_all_lines(self):
        r = self._sale(
            items=[
                {'product_id': 1, 'quantity': 1, 'unit_price': 110.50, 'discount': 0},
                {'product_id': 2, 'quantity': 50, 'unit_price': 40.0, 'discount': 0},
            ],
            total=2110.50,
            amount_paid=2110.50,
        )
        self.assertTrue(isinstance(r, dict) and r.get('error'), r)
        db = self.ac._db()
        soap = db.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]
        oil = db.execute('SELECT stock FROM products WHERE id=2').fetchone()[0]
        sales_n = db.execute('SELECT COUNT(*) FROM sales').fetchone()[0]
        db.close()
        self.assertEqual(float(soap), 20.0)
        self.assertEqual(float(oil), 10.0)
        self.assertEqual(int(sales_n), 0)

    def test_credit_sale_zero_paid_full_debt(self):
        r = self._sale(
            payment_method='credit sale',
            amount_paid=0,
            customer_id=1,
        )
        self.assertTrue(r.get('success') or r.get('sale_id'), r)
        self.assertAlmostEqual(float(r.get('debt_balance') or 0), 130.50, places=2)

    def test_void_restores_stock(self):
        r = self._sale()
        sid = r.get('id') or r.get('sale_id')
        if not sid:
            db = self.ac._db()
            sid = db.execute('SELECT id FROM sales ORDER BY id DESC LIMIT 1').fetchone()[0]
            db.close()
        out = self.api.void_sale(int(sid), 'cert void')
        self.assertTrue(
            out.get('ok') or out.get('success') or 'void' in str(out).lower(),
            out,
        )
        db = self.ac._db()
        soap = db.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]
        status = db.execute('SELECT status FROM sales WHERE id=?', (sid,)).fetchone()[0]
        db.close()
        self.assertEqual(float(soap), 20.0)
        self.assertIn(str(status).lower(), ('voided', 'void', 'cancelled', 'revoked'))


if __name__ == '__main__':
    unittest.main()
