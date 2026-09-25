"""Manual M-Pesa save, split-vs-cash, FIFO buying cost, cashier void request."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from desktop.payments.models import PaymentStatus
from desktop.payments.service import build_payment_service
from desktop.utils.payment_tenders import is_split_pay_method
from desktop.utils.stock_layers import consume_fifo, list_layers, record_receipt


def _pay_factory():
    path = tempfile.mktemp(suffix='.db')
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales ("
        "id INTEGER PRIMARY KEY, receipt_number TEXT, total REAL, payment_id TEXT)"
    )
    conn.commit()
    conn.close()

    def factory():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    return factory


class SplitAndManualTests(unittest.TestCase):
    def test_only_mixed_is_a_split(self):
        self.assertTrue(is_split_pay_method('Mixed'))
        for method in ('Cash', 'M-Pesa', 'Card', 'Bank Transfer', 'Credit Sale'):
            self.assertFalse(is_split_pay_method(method), method)

    def test_save_with_code_does_not_need_the_payments_cloud(self):
        calls = []

        class Boom:
            def register_manual_reference(self, **kwargs):
                calls.append(kwargs)
                raise AssertionError('cloud must not be called for a till override')

        svc = build_payment_service(
            db_conn_factory=_pay_factory(),
            create_sale=lambda d: {'success': True, 'sale_id': 1, 'receipt_number': 'R1'},
            shop_id_getter=lambda: 'shop_a',
            device_id_getter=lambda: 'dev',
            offline=True,
        )
        svc.provider = Boom()
        payment = svc.create_pending_payment(
            amount=250, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 250}],
        )
        saved = svc.register_manual_reference(
            payment.id, 'TG71ABCD12', force_verify=True,
            confirmed_by='cashier', phone='0712345678',
            notes='manual_pos_override',
        )
        self.assertEqual(saved.status, PaymentStatus.VERIFIED.value)
        self.assertEqual(saved.provider_reference, 'TG71ABCD12')
        self.assertTrue(saved.phone_e164.startswith('2547'))
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            svc.register_manual_reference(
                payment.id, 'TG71ABCD12', force_verify=True, phone='not-a-phone',
            )


class FifoCostTests(unittest.TestCase):
    def test_later_delivery_does_not_rewrite_older_stock_cost(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, cost_price REAL, stock REAL)"
        )
        conn.execute("INSERT INTO products VALUES (1, 100, 2)")
        record_receipt(
            conn, 1, quantity=3, unit_cost=160, qty_before=2, previous_cost=100,
        )
        layers = list_layers(conn, 1)
        self.assertEqual([row['unit_cost'] for row in layers], [100.0, 160.0])
        self.assertEqual([row['qty_remaining'] for row in layers], [2.0, 3.0])
        # Selling 3 uses both old units then one new unit: (100+100+160)/3
        sold = consume_fifo(conn, 1, 3)
        self.assertAlmostEqual(sold, round((100 + 100 + 160) / 3, 4), places=4)
        left = [row for row in list_layers(conn, 1) if row['qty_remaining'] > 0]
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]['unit_cost'], 160.0)
        self.assertEqual(left[0]['qty_remaining'], 2.0)


class VoidRequestTests(unittest.TestCase):
    PIN = '482610'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, 'void-request.db')
        self.patches = [
            patch.dict(os.environ, {'MBT_BOOTSTRAP_ADMIN_PASSWORD': ''}),
            patch('mbt_paths.get_db_path', return_value=self.db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self.db_path),
        ]
        for item in self.patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.security import _pin_hash
        ac._SCHEMA_READY = False
        ac._SCHEMA_READY_PATH = None
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'cashier'
        self.api._user_id = 2
        self.api._username = 'till'
        db = ac._db()
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) VALUES (2,'till','x','cashier')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('superadmin_pin_hash', _pin_hash(self.PIN)),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) "
            "VALUES ('Widget','W1',100,40,5,1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self.tmp.cleanup()

    def test_cashier_request_does_not_void_until_admin_approves(self):
        sale = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Widget', 'sku': 'W1',
                'quantity': 1, 'unit_price': 100, 'discount': 0, 'total': 100,
            }],
            'subtotal': 100, 'discount': 0, 'tax': 0, 'total': 100,
            'payment_method': 'Cash', 'amount_paid': 100, 'change_amount': 0,
        })
        self.assertTrue(sale.get('success'), sale)
        asked = self.api.request_sale_void(sale['sale_id'], 'Wrong item scanned')
        self.assertTrue(asked.get('success'), asked)
        waiting = self.api.pending_void_requests()
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]['sale_id'], sale['sale_id'])
        self.assertEqual(waiting[0]['reason'], 'Wrong item scanned')
        still = self.api.get_sale(sale['sale_id'])
        self.assertNotEqual((still.get('status') or ''), 'voided')
        db = self.ac._db()
        row = db.execute(
            "SELECT unit_cost FROM sale_items WHERE sale_id=?",
            (sale['sale_id'],),
        ).fetchone()
        # Opening stock had no layer, so the sale keeps the catalogue cost.
        self.assertAlmostEqual(float(row['unit_cost']), 40.0, places=2)
        db.close()

        self.api._role = 'admin'
        self.api._username = 'owner'
        denied = self.api.void_sale(sale['sale_id'], 'Wrong item scanned', pin='000000')
        self.assertFalse(denied.get('success'))
        approved = self.api.void_sale(sale['sale_id'], 'Wrong item scanned', pin=self.PIN)
        self.assertTrue(approved.get('success'), approved)
        voided = self.api.get_sale(sale['sale_id'])
        self.assertEqual(voided.get('status'), 'voided')
        self.assertEqual(self.api.pending_void_requests(), [])
        db = self.ac._db()
        note = db.execute(
            "SELECT title FROM cc_notifications WHERE title LIKE 'Voided %'"
        ).fetchone()
        db.close()
        self.assertIsNotNone(note)
        self.assertIn(sale['receipt_number'], note['title'])
