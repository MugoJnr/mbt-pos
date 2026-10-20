"""Approving a void or stock request performs that action once."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ExecutableApprovalTests(unittest.TestCase):
    PIN = '123456'

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'approvals.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.security import _pin_hash
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'owner'
        db = ac._db()
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) VALUES (1,'owner','x:y','superadmin')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('superadmin_pin_hash', _pin_hash(self.PIN)),
        )
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) "
            "VALUES ('Approval Item','APP-1',80,40,20,1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _stock(self):
        db = self.ac._db()
        try:
            return float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        finally:
            db.close()

    def _request(self, atype, meta, *, created_at=None, expires_at=None):
        db = self.ac._db()
        try:
            self.api._ensure_approval_table(db)
            db.execute(
                "INSERT INTO cc_approvals "
                "(type,title,details,status,meta_json,created_at,expires_at) "
                "VALUES (?,?,?,'pending',?,?,?)",
                (
                    atype, atype, 'please',
                    json.dumps(meta),
                    created_at or datetime.now().isoformat(),
                    expires_at or (datetime.now() + timedelta(hours=24)).isoformat(),
                ),
            )
            db.commit()
            return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        finally:
            db.close()

    def test_void_approval_restores_stock_once(self):
        sale = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Approval Item', 'sku': 'APP-1',
                'quantity': 4, 'unit_price': 80, 'discount': 0, 'total': 320,
            }],
            'subtotal': 320, 'discount': 0, 'tax': 0, 'total': 320,
            'payment_method': 'Cash', 'amount_paid': 320, 'change_amount': 0,
        })
        self.assertTrue(sale.get('success'), sale)
        self.assertEqual(self._stock(), 16)
        approval_id = self._request('void', {'sale_id': int(sale['sale_id'])})
        denied = self.api.execute_approval(approval_id, 'approve', pin='')
        self.assertEqual(denied.get('status'), 403)
        self.assertEqual(self._stock(), 16)
        approved = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertTrue(approved.get('success'), approved)
        self.assertEqual(self._stock(), 20)
        again = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertTrue(again.get('duplicate'), again)
        self.assertEqual(self._stock(), 20)
        db = self.ac._db()
        try:
            status = db.execute("SELECT status FROM sales WHERE id=?", (sale['sale_id'],)).fetchone()['status']
            voids = db.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE product_id=1 AND movement_type='VOID_RESTORE'"
            ).fetchone()[0]
            approval = db.execute(
                "SELECT status FROM cc_approvals WHERE id=?", (approval_id,)
            ).fetchone()['status']
        finally:
            db.close()
        self.assertEqual(status, 'voided')
        self.assertEqual(int(voids), 1)
        self.assertEqual(approval, 'approved')

    def test_stock_approval_applies_once_and_wrong_pin_does_not(self):
        approval_id = self._request('stock_adjust', {
            'product_id': 1, 'direction': 'remove', 'quantity': 3,
            'reason': 'Damaged / Spoiled', 'expected_stock': 20,
        })
        wrong = self.api.execute_approval(approval_id, 'approve', pin='000000')
        self.assertEqual(wrong.get('status'), 403)
        self.assertEqual(self._stock(), 20)
        applied = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertTrue(applied.get('success'), applied)
        self.assertEqual(self._stock(), 17)
        again = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertTrue(again.get('duplicate'), again)
        self.assertEqual(self._stock(), 17)

    def test_expired_request_does_not_void(self):
        sale = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Approval Item', 'sku': 'APP-1',
                'quantity': 1, 'unit_price': 80, 'discount': 0, 'total': 80,
            }],
            'subtotal': 80, 'discount': 0, 'tax': 0, 'total': 80,
            'payment_method': 'Cash', 'amount_paid': 80, 'change_amount': 0,
        })
        approval_id = self._request(
            'void', {'sale_id': int(sale['sale_id'])},
            created_at=(datetime.now() - timedelta(days=2)).isoformat(),
            expires_at=(datetime.now() - timedelta(hours=1)).isoformat(),
        )
        expired = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertEqual(expired.get('status'), 410)
        self.assertEqual(self._stock(), 19)
        db = self.ac._db()
        try:
            sale_status = db.execute(
                "SELECT status FROM sales WHERE id=?", (sale['sale_id'],)
            ).fetchone()['status']
            approval = db.execute(
                "SELECT status FROM cc_approvals WHERE id=?", (approval_id,)
            ).fetchone()['status']
        finally:
            db.close()
        self.assertNotEqual(sale_status, 'voided')
        self.assertEqual(approval, 'expired')

    def test_cashier_cannot_execute(self):
        approval_id = self._request('stock_adjust', {
            'product_id': 1, 'direction': 'remove', 'quantity': 1,
            'reason': 'Damaged / Spoiled', 'expected_stock': 20,
        })
        self.api._role = 'cashier'
        denied = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertEqual(denied.get('status'), 403)
        self.assertEqual(self._stock(), 20)

    def test_missing_sale_leaves_the_request_pending(self):
        approval_id = self._request('void', {})
        failed = self.api.execute_approval(approval_id, 'approve', pin=self.PIN)
        self.assertIn('error', failed)
        db = self.ac._db()
        try:
            status = db.execute(
                "SELECT status FROM cc_approvals WHERE id=?", (approval_id,)
            ).fetchone()['status']
        finally:
            db.close()
        self.assertEqual(status, 'pending')

    def test_concurrent_stock_approval_applies_once(self):
        approval_id = self._request('stock_adjust', {
            'product_id': 1, 'direction': 'remove', 'quantity': 2,
            'reason': 'Damaged / Spoiled', 'expected_stock': 20,
        })
        results = []

        def run():
            client = self.ac.APIClient()
            client._role = 'superadmin'
            client._user_id = 1
            client._username = 'owner'
            results.append(client.execute_approval(approval_id, 'approve', pin=self.PIN))

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self._stock(), 18)
        successes = [item for item in results if item.get('success')]
        self.assertGreaterEqual(len(successes), 1)
        db = self.ac._db()
        try:
            moves = db.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE product_id=1 "
                "AND movement_type='SUPERADMIN_ADJUST'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(int(moves), 1)


if __name__ == '__main__':
    unittest.main()
