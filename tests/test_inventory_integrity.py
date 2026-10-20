"""Isolated inventory ledger: receive, adjust, approve, and sale stock."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class InventoryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'inventory.db')
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
            ('Audit Soap', 'SOAP1', 50.0, 20.0, 10, 1),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Audit Oil', 'OIL1', 80.0, 30.0, 4, 1),
        )
        db.execute(
            "INSERT INTO suppliers (name, phone) VALUES (?,?)",
            ('Audit Supplies', '0700'),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _stock(self, pid):
        db = self.ac._db()
        try:
            return db.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()['stock']
        finally:
            db.close()

    def _movements(self, pid):
        db = self.ac._db()
        try:
            rows = db.execute(
                "SELECT movement_type, qty_change, qty_after FROM stock_movements "
                "WHERE product_id=? ORDER BY id",
                (pid,),
            ).fetchall()
            return [(r['movement_type'], r['qty_change'], r['qty_after']) for r in rows]
        finally:
            db.close()

    def test_cashier_cannot_adjust_and_receive_is_idempotent(self):
        denied = self.api.adjust_stock(1, 99, 'guess')
        self.assertIn('Super-Admin', denied.get('error', ''))
        self.assertEqual(self._stock(1), 10)

        first = self.api.receive_delivery(
            1,
            [
                {'product_id': 1, 'quantity': 3, 'unit_cost': 18},
                {'product_id': 2, 'quantity': 2, 'unit_cost': 25},
            ],
            client_token='rcv-1',
        )
        self.assertTrue(first.get('success'), first)
        self.assertEqual(self._stock(1), 13)
        self.assertEqual(self._stock(2), 6)
        self.assertEqual(len(first['lines']), 2)
        self.assertAlmostEqual(first['grand_total'], 3 * 18 + 2 * 25)

        second = self.api.receive_delivery(
            1,
            [{'product_id': 1, 'quantity': 3, 'unit_cost': 18}],
            client_token='rcv-1',
        )
        self.assertTrue(second.get('duplicate'))
        self.assertEqual(self._stock(1), 13)
        self.assertEqual(self._stock(2), 6)

        dup = self.api.receive_delivery(
            1,
            [
                {'product_id': 1, 'quantity': 1},
                {'product_id': 1, 'quantity': 1},
            ],
        )
        self.assertIn('once', dup.get('error', ''))
        self.assertEqual(self._stock(1), 13)

    def test_viewer_cannot_receive(self):
        self.api._role = 'viewer'
        result = self.api.receive_delivery(1, [{'product_id': 1, 'quantity': 1}])
        self.assertIn('cannot receive', result.get('error', ''))
        self.assertEqual(self._stock(1), 10)

    def test_request_does_not_change_stock_and_approval_is_once(self):
        asked = self.api.request_stock_adjustment(1, 7, 'Damaged bottles')
        self.assertTrue(asked.get('success'), asked)
        self.assertEqual(self._stock(1), 10)
        review = self.api.review_stock_adjustment(1, 'approved')
        self.assertIn('Super-Admin', review.get('error', ''))
        self.assertEqual(self._stock(1), 10)

        self.api._role = 'superadmin'
        self.api._username = 'admin'
        approved = self.api.review_stock_adjustment(1, 'approved')
        self.assertTrue(approved.get('success'), approved)
        self.assertEqual(approved.get('new_stock'), 7)
        self.assertEqual(self._stock(1), 7)
        again = self.api.review_stock_adjustment(1, 'approved')
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(self._stock(1), 7)
        moves = self._movements(1)
        self.assertEqual(len([m for m in moves if m[0] == 'SUPERADMIN_ADJUST']), 1)

    def test_concurrent_approval_applies_stock_once(self):
        asked = self.api.request_stock_adjustment(1, 6, 'Count')
        self.assertTrue(asked.get('success'), asked)
        self.api._role = 'superadmin'
        barrier = threading.Barrier(2)
        results = []

        def approve():
            barrier.wait(timeout=5)
            results.append(self.api.review_stock_adjustment(1, 'approved'))

        threads = [threading.Thread(target=approve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(len(results), 2)
        self.assertEqual(self._stock(1), 6)
        applied = [r for r in results if r.get('success') and not r.get('duplicate') and r.get('status') == 'approved']
        self.assertEqual(len(applied), 1)
        moves = [m for m in self._movements(1) if m[0] == 'SUPERADMIN_ADJUST']
        self.assertEqual(len(moves), 1)

    def test_failed_adjustment_journal_rolls_stock_back(self):
        asked = self.api.request_stock_adjustment(1, 4, 'Shrink')
        self.assertTrue(asked.get('success'), asked)
        self.api._role = 'superadmin'

        def boom(*_args, **_kwargs):
            raise RuntimeError('journal down')

        with patch('desktop.utils.accounting_hooks.post_stock_adjust_journal', side_effect=boom):
            failed = self.api.review_stock_adjustment(1, 'approved')
        self.assertIn('error', failed)
        self.assertEqual(self._stock(1), 10)
        db = self.ac._db()
        try:
            status = db.execute(
                "SELECT status FROM stock_adjustment_requests WHERE id=1"
            ).fetchone()['status']
        finally:
            db.close()
        self.assertEqual(status, 'pending')
        self.assertEqual(
            [m for m in self._movements(1) if m[0] == 'SUPERADMIN_ADJUST'],
            [],
        )

    def test_sale_deducts_once_and_blocks_oversell(self):
        sale = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Audit Soap',
                'sku': 'SOAP1',
                'quantity': 2,
                'unit_price': 50,
                'discount': 0,
                'total': 100,
            }],
            'subtotal': 100,
            'total': 100,
            'payment_method': 'Cash',
            'amount_paid': 100,
            'change_amount': 0,
            'client_token': 'sale-audit-1',
        })
        self.assertTrue(sale.get('success'), sale)
        self.assertEqual(self._stock(1), 8)
        again = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Audit Soap',
                'quantity': 2,
                'unit_price': 50,
                'discount': 0,
                'total': 100,
            }],
            'subtotal': 100,
            'total': 100,
            'payment_method': 'Cash',
            'amount_paid': 100,
            'client_token': 'sale-audit-1',
        })
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(self._stock(1), 8)
        over = self.api.create_sale({
            'items': [{
                'product_id': 2,
                'product_name': 'Audit Oil',
                'quantity': 50,
                'unit_price': 80,
                'discount': 0,
                'total': 4000,
            }],
            'subtotal': 4000,
            'total': 4000,
            'payment_method': 'Cash',
            'amount_paid': 4000,
            'client_token': 'sale-audit-over',
        })
        self.assertFalse(over.get('success'))
        self.assertEqual(self._stock(2), 4)


if __name__ == '__main__':
    unittest.main()
