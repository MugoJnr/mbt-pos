"""Offline till: local sales survive a dead network, and the UI probe does not block."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class OfflineSaleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'offline.db')
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
        self.api._username = 'offline'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('offline', 'x:y', 'superadmin'),
        )
        db.execute(
            "INSERT INTO products (name, sku, barcode, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?,?)",
            ('Offline Soap', 'OFF-SOAP', '6161001', 100.0, 40.0, 10, 1),
        )
        db.execute(
            "INSERT INTO customers (name, phone, credit_limit) VALUES (?,?,?)",
            ('Offline Customer', '0700', 5000),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def _cash(self, token):
        return self.api.create_sale({
            'items': [{'product_id': 1, 'quantity': 1, 'unit_price': 100.0, 'discount': 0}],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Cash',
            'amount_paid': 100.0,
            'change_amount': 0,
            'client_token': token,
        })

    def test_offline_sales_stock_debt_and_restart(self):
        first = self._cash('off-1')
        self.assertTrue(first.get('success'), first)
        again = self._cash('off-1')
        self.assertTrue(again.get('duplicate'), again)
        split = self.api.create_sale({
            'items': [{'product_id': 1, 'quantity': 1, 'unit_price': 100.0, 'discount': 0}],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Cash',
            'amount_paid': 100.0,
            'cash_paid': 40.0,
            'electronic_paid': 60.0,
            'electronic_method': 'M-Pesa',
            'payment_tenders': [
                {'method': 'Cash', 'amount': 40.0},
                {'method': 'M-Pesa', 'amount': 60.0},
            ],
            'client_token': 'off-split',
        })
        self.assertTrue(split.get('success'), split)
        credit = self.api.create_sale({
            'items': [{'product_id': 1, 'quantity': 1, 'unit_price': 100.0, 'discount': 0}],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'credit sale',
            'amount_paid': 0,
            'customer_id': 1,
            'client_token': 'off-credit',
        })
        self.assertTrue(credit.get('success'), credit)
        self.assertAlmostEqual(float(credit.get('debt_balance') or 0), 100.0, places=2)

        # New connection stands in for a process restart. Nothing is in memory.
        db = self.ac._db()
        sales = db.execute('SELECT COUNT(*) FROM sales').fetchone()[0]
        stock = db.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]
        pending = db.execute(
            "SELECT COUNT(*) FROM sync_queue WHERE action_type='sale' AND status='pending'"
        ).fetchone()[0]
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        db.close()
        self.assertEqual(int(sales), 3)
        self.assertEqual(float(stock), 7.0)
        self.assertGreaterEqual(int(pending), 3)
        self.assertEqual(integrity, 'ok')

        replay = self._cash('off-1')
        self.assertTrue(replay.get('duplicate'), replay)
        db = self.ac._db()
        sales_after = db.execute('SELECT COUNT(*) FROM sales').fetchone()[0]
        db.close()
        self.assertEqual(int(sales_after), 3)


class ProbeDoesNotBlockTests(unittest.TestCase):
    def test_request_probe_returns_while_a_check_would_wait(self):
        from backend.internet_monitor import InternetMonitor

        mon = InternetMonitor(os.devnull, lambda: {})
        started = threading.Event()

        def slow(*_a, **_k):
            started.set()
            time.sleep(2.5)
            return False

        with patch('backend.cloud.net_gate.network_up', slow):
            worker = threading.Thread(target=mon.check_connection)
            worker.start()
            self.assertTrue(started.wait(1))
            t0 = time.perf_counter()
            mon.request_probe()
            elapsed = time.perf_counter() - t0
            worker.join(4)
        self.assertLess(elapsed, 0.2)
        self.assertTrue(mon._wake.is_set())
