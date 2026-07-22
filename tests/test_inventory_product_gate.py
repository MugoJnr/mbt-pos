"""V01/V03: product create/update/archive + stock adjust via APIClient."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class InventoryProductGate(unittest.TestCase):
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
        self.api._username = 'owner'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('owner', 'x:y', 'superadmin'),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_v01_create_update_archive_product(self):
        created = self.api.create_product({
            'name': 'Gate Soap',
            'sku': 'SOAP-1',
            'price': 40.0,
            'cost_price': 20.0,
            'stock': 10,
            'min_stock': 3,
            'category': 'Hygiene',
            'unit': 'pcs',
        })
        self.assertTrue(created.get('success'), created)
        pid = int(created['id'])

        db = self.ac._db()
        row = dict(db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        db.close()
        self.assertEqual(row['name'], 'Gate Soap')
        self.assertEqual(float(row['stock']), 10.0)
        self.assertEqual(int(row.get('is_active', 1) or 1), 1)

        upd = self.api.update_product(pid, {
            'name': 'Gate Soap XL',
            'price': 45.0,
            'min_stock': 4,
        })
        self.assertTrue(upd.get('success'), upd)

        db = self.ac._db()
        row2 = dict(db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        db.close()
        self.assertEqual(row2['name'], 'Gate Soap XL')
        self.assertAlmostEqual(float(row2['price']), 45.0, places=2)
        self.assertEqual(int(row2['min_stock']), 4)

        archived = self.api.delete_product(pid)
        self.assertTrue(archived.get('success'), archived)
        db = self.ac._db()
        row3 = dict(db.execute("SELECT is_active FROM products WHERE id=?", (pid,)).fetchone())
        db.close()
        self.assertEqual(int(row3['is_active']), 0)

    def test_v03_stock_adjust_and_low_stock(self):
        created = self.api.create_product({
            'name': 'Low Stock Bag',
            'sku': 'BAG-1',
            'price': 15.0,
            'cost_price': 5.0,
            'stock': 20,
            'min_stock': 5,
        })
        self.assertTrue(created.get('success'), created)
        pid = int(created['id'])

        adj = self.api.adjust_stock(pid, 4, 'cycle count correction')
        self.assertTrue(adj.get('success'), adj)
        self.assertAlmostEqual(float(adj.get('new_stock') or 0), 4.0, places=2)

        db = self.ac._db()
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=?", (pid,)
        ).fetchone()['stock'])
        mov = db.execute(
            "SELECT COUNT(*) AS c FROM stock_movements "
            "WHERE product_id=? AND movement_type='SUPERADMIN_ADJUST'",
            (pid,),
        ).fetchone()['c']
        db.close()
        self.assertEqual(stock, 4.0)
        self.assertGreaterEqual(int(mov), 1)

        # Low-stock: stock <= min_stock
        products = self.api.get_products() or []
        match = next((p for p in products if int(p.get('id') or 0) == pid), None)
        self.assertIsNotNone(match)
        self.assertLessEqual(
            float(match.get('stock') or 0),
            float(match.get('min_stock') or 0),
        )

    def test_cashier_cannot_adjust_stock(self):
        created = self.api.create_product({
            'name': 'Cashier Block',
            'sku': 'CB-1',
            'price': 10.0,
            'stock': 8,
        })
        pid = int(created['id'])
        self.api._role = 'cashier'
        denied = self.api.adjust_stock(pid, 99, 'should fail')
        self.assertIn('error', denied)


if __name__ == '__main__':
    unittest.main()
