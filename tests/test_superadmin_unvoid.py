"""Signed-in Super Admin restores a voided receipt once, without a second PIN."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SuperAdminUnvoidTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'unvoid.db')
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
        self.api._role = 'manager'
        self.api._user_id = 1
        self.api._username = 'manager'
        db = ac._db()
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) VALUES (1,'manager','x:y','manager')"
        )
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) "
            "VALUES ('Restore Oil','UNVOID-OIL',100,40,10,1)"
        )
        db.execute(
            "INSERT INTO departments (name,active) VALUES ('Kitchen',1)"
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

    def _sell_and_void(self):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Restore Oil', 'sku': 'UNVOID-OIL',
                'quantity': 2, 'unit_price': 100, 'discount': 0, 'total': 200,
            }],
            'subtotal': 200, 'discount': 0, 'tax': 0, 'total': 200,
            'payment_method': 'Cash', 'amount_paid': 200, 'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        voided = self.api.void_sale(int(created['sale_id']), 'Wrong item')
        self.assertTrue(voided.get('success'), voided)
        return int(created['sale_id'])

    def test_superadmin_restores_sale_once_without_pin(self):
        sale_id = self._sell_and_void()
        self.assertEqual(self._stock(), 10)
        self.api._role = 'cashier'
        denied = self.api.unvoid_sale(sale_id, 'Put the sale back')
        self.assertEqual(denied.get('status'), 403)
        self.assertEqual(self._stock(), 10)
        self.api._role = 'manager'
        denied = self.api.unvoid_sale(sale_id, 'Put the sale back')
        self.assertEqual(denied.get('status'), 403)
        self.api._role = 'superadmin'
        self.api._username = 'super'
        missing = self.api.unvoid_sale(sale_id, '  ')
        self.assertEqual(missing.get('status'), 400)
        restored = self.api.unvoid_sale(sale_id, 'Void was a mistake')
        self.assertTrue(restored.get('success'), restored)
        self.assertFalse(restored.get('duplicate'))
        self.assertEqual(self._stock(), 8)
        again = self.api.unvoid_sale(sale_id, 'Void was a mistake')
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(self._stock(), 8)
        db = self.ac._db()
        try:
            status = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()['status']
            edits = [row['edit_type'] for row in db.execute(
                "SELECT edit_type FROM sale_edits WHERE sale_id=? ORDER BY id", (sale_id,)
            ).fetchall()]
            moves = db.execute(
                "SELECT COUNT(*) AS n FROM stock_movements WHERE movement_type='UNVOID_DEDUCT' AND reference=?",
                (f'UNVOID_sale={sale_id}',),
            ).fetchone()['n']
        finally:
            db.close()
        self.assertEqual(status, 'completed')
        self.assertEqual(edits, ['VOID', 'UNVOID'])
        self.assertEqual(int(moves), 1)

    def test_restore_refuses_when_stock_was_used_again(self):
        sale_id = self._sell_and_void()
        db = self.ac._db()
        db.execute("UPDATE products SET stock=0 WHERE id=1")
        db.commit()
        db.close()
        self.api._role = 'superadmin'
        blocked = self.api.unvoid_sale(sale_id, 'Try anyway')
        self.assertEqual(blocked.get('status'), 409)
        self.assertEqual(self._stock(), 0)
        db = self.ac._db()
        try:
            status = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()['status']
        finally:
            db.close()
        self.assertEqual(status, 'voided')

    def test_consumption_restore_deducts_once(self):
        self.api._role = 'admin'
        saved = self.api.create_consumption({
            'department_id': 1,
            'reason': 'Staff tea',
            'items': [{'product_id': 1, 'quantity': 3}],
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertEqual(self._stock(), 7)
        voided = self.api.void_consumption(saved['id'], 'Recorded on the wrong day')
        self.assertTrue(voided.get('success'), voided)
        self.assertEqual(self._stock(), 10)
        self.api._role = 'admin'
        denied = self.api.unvoid_consumption(saved['id'], 'It was the right day')
        self.assertEqual(denied.get('status'), 403)
        self.api._role = 'superadmin'
        restored = self.api.unvoid_consumption(saved['id'], 'It was the right day')
        self.assertTrue(restored.get('success'), restored)
        self.assertEqual(self._stock(), 7)
        again = self.api.unvoid_consumption(saved['id'], 'It was the right day')
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(self._stock(), 7)
        db = self.ac._db()
        try:
            voided_flag = int(db.execute(
                "SELECT voided FROM stock_consumptions WHERE id=?", (saved['id'],)
            ).fetchone()['voided'])
            reason = db.execute(
                "SELECT void_reason FROM stock_consumptions WHERE id=?", (saved['id'],)
            ).fetchone()['void_reason']
            moves = db.execute(
                "SELECT COUNT(*) AS n FROM stock_movements WHERE movement_type='INTERNAL_USE_UNVOID'"
            ).fetchone()['n']
        finally:
            db.close()
        self.assertEqual(voided_flag, 0)
        self.assertEqual(reason, 'Recorded on the wrong day')
        self.assertEqual(int(moves), 1)

    def test_signed_in_superadmin_adjusts_stock_without_pin(self):
        self.api._role = 'superadmin'
        changed = self.api.adjust_stock(1, 6, 'Count correction', pin='', expected_stock=10)
        self.assertTrue(changed.get('success'), changed)
        self.assertEqual(self._stock(), 6)
        self.api._role = 'admin'
        blocked = self.api.adjust_stock(1, 4, 'Count correction', pin='', expected_stock=6)
        self.assertIn('Super-Admin', blocked.get('error') or '')
        self.assertEqual(self._stock(), 6)
        db = self.ac._db()
        try:
            self.api._role = 'superadmin'
            self.assertIsNone(self.api._approval_pin_error(db, '', 1))
            self.api._role = 'manager'
            self.assertIsNotNone(self.api._approval_pin_error(db, '', 1))
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
