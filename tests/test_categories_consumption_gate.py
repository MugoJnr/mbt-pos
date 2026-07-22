"""V02 categories+icons and V04 internal consumption API gates."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CategoriesConsumptionGate(unittest.TestCase):
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
        self.api._role = 'admin'
        self.api._user_id = 1
        self.api._username = 'admin'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
            db.execute(
                "UPDATE users SET role='admin' WHERE id=?", (self.api._user_id,)
            )
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'admin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Cons Widget', 'CW1', 50.0, 20.0, 30, 2),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_v02_ensure_category_and_list_with_icon(self):
        ensured = self.api.ensure_category_for_product_name('Beverages')
        self.assertTrue(ensured.get('id') or ensured.get('name'), ensured)
        self.assertEqual((ensured.get('name') or '').lower(), 'beverages')
        # Visual defaults from suggest_visual_for_category_name
        self.assertIn(ensured.get('visual_type'), ('icon', 'image', None))
        if ensured.get('visual_type') == 'icon':
            self.assertTrue(ensured.get('icon_name') or ensured.get('accent_color'))

        again = self.api.ensure_category_for_product_name('Beverages')
        self.assertEqual(int(again.get('id')), int(ensured.get('id')))

        cats = self.api.get_categories(active_only=True) or []
        names = {(c.get('name') or '').lower() for c in cats}
        self.assertIn('beverages', names)
        bev = next(c for c in cats if (c.get('name') or '').lower() == 'beverages')
        self.assertTrue(bev.get('icon_name') or bev.get('accent_color') or bev.get('image_path'))

    def test_v04_create_consumption_decrements_stock_and_movement(self):
        depts = self.api.get_departments(active_only=True) or []
        self.assertTrue(depts, 'seeded departments expected')
        dept_id = int(depts[0]['id'])

        db = self.ac._db()
        before = float(db.execute(
            "SELECT stock FROM products WHERE sku=?", ('CW1',)
        ).fetchone()[0])
        db.close()

        created = self.api.create_consumption({
            'date': str(date.today()),
            'department_id': dept_id,
            'reason': 'Office tea',
            'notes': 'gate test',
            'taken_by': 'staff',
            'items': [{'product_id': 1, 'quantity': 3}],
        })
        self.assertTrue(created.get('success'), created)
        self.assertTrue(created.get('reference_no'))

        db = self.ac._db()
        after = float(db.execute(
            "SELECT stock FROM products WHERE sku=?", ('CW1',)
        ).fetchone()[0])
        mov = db.execute(
            "SELECT * FROM stock_movements WHERE movement_type='INTERNAL_USE' "
            "AND reference=? ORDER BY id DESC LIMIT 1",
            (created['reference_no'],),
        ).fetchone()
        db.close()
        self.assertAlmostEqual(after, before - 3.0, places=3)
        self.assertIsNotNone(mov)
        self.assertAlmostEqual(float(mov['qty_change']), -3.0, places=3)


if __name__ == '__main__':
    unittest.main()
