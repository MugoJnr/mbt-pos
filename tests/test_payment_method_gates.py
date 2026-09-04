"""P0 payment-method normalization + Mixed tender gates + debt release gate."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class PaymentMethodNormalizeUnit(unittest.TestCase):
    def test_aliases_map_to_canonical(self):
        from desktop.utils.payment_methods import normalize_payment_method
        cases = {
            'Credit': 'Credit Sale',
            'credit': 'Credit Sale',
            'Credit Sale': 'Credit Sale',
            'credit_sale': 'Credit Sale',
            'Credit Account': 'Credit Sale',
            'Part Payment': 'Part Payment',
            'part_payment': 'Part Payment',
            'part payment': 'Part Payment',
            'mixed': 'Mixed',
            'Split Pay': 'Mixed',
            'cash': 'Cash',
            'M-Pesa': 'M-Pesa',
            'mpesa': 'M-Pesa',
            'Bank': 'Bank Transfer',
        }
        for raw, expect in cases.items():
            self.assertEqual(
                normalize_payment_method(raw), expect, msg=raw)

    def test_unknown_rejected(self):
        from desktop.utils.payment_methods import normalize_payment_method
        with self.assertRaises(ValueError):
            normalize_payment_method('Barter')
        with self.assertRaises(ValueError):
            normalize_payment_method('Crypto')


class PaymentCreateSaleGates(unittest.TestCase):
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
            ('Pay Gate Widget', 'PG1', 100.0, 40.0, 500, 5),
        )
        db.commit()
        db.close()
        cust = self.api.create_customer({
            'name': 'Gate Cust', 'phone': '0700000001', 'credit_limit': 50000,
        })
        self.cid = int(cust['customer_id'])

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _sale(self, **overrides):
        payload = {
            'items': [{
                'product_id': 1,
                'product_name': 'Pay Gate Widget',
                'sku': 'PG1',
                'quantity': 1,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Cash',
            'amount_paid': 100.0,
            'change_amount': 0,
            'customer_id': self.cid,
        }
        payload.update(overrides)
        return self.api.create_sale(payload)

    def test_credit_aliases_create_debt_invoice(self):
        for method in ('Credit', 'credit', 'Credit Sale'):
            res = self._sale(
                payment_method=method, amount_paid=0.0, change_amount=0,
            )
            self.assertTrue(res.get('success'), f'{method}: {res}')
            self.assertTrue(res.get('debt_invoice_id'), method)
            sale = self.api.get_sale(res['sale_id'])
            self.assertEqual(sale['payment_method'], 'Credit Sale')
            self.assertTrue(sale.get('debt_invoice_id') or res.get('debt_invoice_id'))

    def test_part_payment_aliases_create_partial_debt(self):
        for method in ('Part Payment', 'part_payment'):
            res = self._sale(
                payment_method=method, amount_paid=40.0, change_amount=0,
            )
            self.assertTrue(res.get('success'), f'{method}: {res}')
            self.assertTrue(res.get('debt_invoice_id'), method)
            self.assertAlmostEqual(float(res.get('debt_balance') or -1), 60.0, places=2)
            sale = self.api.get_sale(res['sale_id'])
            self.assertEqual(sale['payment_method'], 'Part Payment')

    def test_unknown_payment_method_rejected(self):
        res = self._sale(payment_method='BarterIOU', amount_paid=100.0)
        self.assertIn('error', res)
        db = self.ac._db()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        db.close()

    def test_mixed_without_tenders_rejected(self):
        res = self._sale(
            payment_method='Mixed',
            amount_paid=100.0,
            cash_paid=0,
            electronic_paid=0,
            payment_tenders=[],
        )
        self.assertIn('error', res)
        self.assertIn('Mixed', str(res.get('error') or ''))

    def test_mixed_tender_total_mismatch_rejected(self):
        res = self._sale(
            payment_method='Mixed',
            amount_paid=100.0,
            payment_tenders=[
                {'method': 'Cash', 'amount': 30.0},
                {'method': 'M-Pesa', 'amount': 40.0},
            ],
        )
        self.assertIn('error', res)
        self.assertIn('tender', str(res.get('error') or '').lower())

    def test_mixed_valid_tenders_persisted_and_derived(self):
        res = self._sale(
            payment_method='Mixed',
            amount_paid=100.0,
            payment_tenders=[
                {'method': 'Cash', 'amount': 40.0},
                {'method': 'M-Pesa', 'amount': 60.0},
            ],
        )
        self.assertTrue(res.get('success'), res)
        sale = self.api.get_sale(res['sale_id'])
        self.assertEqual(sale['payment_method'], 'Mixed')
        self.assertAlmostEqual(float(sale['cash_paid']), 40.0, places=2)
        self.assertAlmostEqual(float(sale['electronic_paid']), 60.0, places=2)
        self.assertEqual(sale.get('electronic_method'), 'M-Pesa')
        methods = {t['method'] for t in (sale.get('payment_tenders') or [])}
        self.assertEqual(methods, {'Cash', 'M-Pesa'})

    def test_release_gate_completed_credit_has_debt_invoice(self):
        """Release gate: every completed credit/part-payment sale has a debt invoice."""
        for method, paid in (('Credit', 0.0), ('part_payment', 25.0)):
            res = self._sale(
                payment_method=method, amount_paid=paid, change_amount=0,
            )
            self.assertTrue(res.get('success'), res)
        db = self.ac._db()
        orphans = db.execute(
            "SELECT s.receipt_number, s.payment_method FROM sales s "
            "LEFT JOIN debt_invoices d ON d.sale_id=s.id "
            "WHERE IFNULL(s.status,'completed')='completed' "
            "AND d.id IS NULL "
            "AND lower(replace(s.payment_method,' ','')) IN "
            "('creditsale','partpayment','credit')"
        ).fetchall()
        db.close()
        self.assertEqual(list(orphans), [])


class SalePaymentRepairIsolated(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'repair.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        # Touch schema
        ac._db().close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_repair_credit_and_flag_mixed_without_inventing(self):
        import sqlite3
        from desktop.utils.sale_payment_repair import (
            apply_supervised_mixed_correction,
            flag_mixed_sales_missing_tenders,
            repair_debt_sales_missing_invoices,
        )
        db = sqlite3.connect(self._db_path)
        db.execute(
            "INSERT INTO customers (name, phone, credit_limit, is_active) "
            "VALUES (?,?,?,1)",
            ('Repair Cust', '0712345678', 10000),
        )
        cid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO sales "
            "(receipt_number,cashier_id,cashier_name,subtotal,discount,tax,"
            "total,payment_method,amount_paid,change_amount,customer_id,"
            "status,sale_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                'RCP-REPAIR-CREDIT', 1, 'admin', 250, 0, 0, 250,
                'Credit', 0, 0, cid, 'completed', '2026-09-04',
            ),
        )
        credit_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO sales "
            "(receipt_number,cashier_id,cashier_name,subtotal,discount,tax,"
            "total,payment_method,amount_paid,change_amount,status,sale_date,"
            "cash_paid,electronic_paid,payment_tenders) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                'RCP-REPAIR-MIXED', 1, 'admin', 250, 0, 0, 250,
                'Mixed', 250, 0, 'completed', '2026-09-04',
                0, 0, None,
            ),
        )
        mixed_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        db.close()

        debt = repair_debt_sales_missing_invoices(
            self._db_path, receipt_numbers=['RCP-REPAIR-CREDIT'], dry_run=False,
        )
        self.assertTrue(debt.get('success'), debt)
        self.assertEqual(len(debt.get('created') or []), 1)

        flagged = flag_mixed_sales_missing_tenders(
            self._db_path, receipt_numbers=['RCP-REPAIR-MIXED'], dry_run=False,
        )
        self.assertTrue(flagged.get('success'), flagged)
        self.assertEqual(len(flagged.get('flagged') or []), 1)

        # Refuse inventing without explicit tenders
        denied = apply_supervised_mixed_correction(
            self._db_path, sale_id=mixed_id, tenders=[], actor='qa', confirm=True,
        )
        self.assertFalse(denied.get('success'))

        ok = apply_supervised_mixed_correction(
            self._db_path,
            sale_id=mixed_id,
            tenders=[
                {'method': 'Cash', 'amount': 100.0},
                {'method': 'M-Pesa', 'amount': 150.0},
            ],
            actor='qa-supervisor',
            confirm=True,
        )
        self.assertTrue(ok.get('success'), ok)

        db = sqlite3.connect(self._db_path)
        db.row_factory = sqlite3.Row
        credit = dict(db.execute(
            "SELECT payment_method FROM sales WHERE id=?", (credit_id,)
        ).fetchone())
        inv = db.execute(
            "SELECT balance,status FROM debt_invoices WHERE sale_id=?",
            (credit_id,),
        ).fetchone()
        mixed = dict(db.execute(
            "SELECT payment_tenders,cash_paid,electronic_paid,notes FROM sales "
            "WHERE id=?",
            (mixed_id,),
        ).fetchone())
        db.close()
        self.assertEqual(credit['payment_method'], 'Credit Sale')
        self.assertIsNotNone(inv)
        self.assertEqual(float(inv['balance']), 250.0)
        self.assertIn('M-Pesa', mixed['payment_tenders'] or '')
        self.assertNotIn('NEEDS_MIXED_TENDER_CORRECTION', mixed['notes'] or '')


if __name__ == '__main__':
    unittest.main()
