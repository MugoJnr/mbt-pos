"""Shop categories are optional, per shop, and not a built-in list."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

RETIRED = (
    'general', 'grocery', 'pharmacy', 'electronics', 'clothing',
    'hardware', 'beverages', 'beauty',
)


class ShopCategoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ['MBT_TEST_INSTANCE'] = '1'
        os.environ['MBT_DATA_ROOT'] = self.tmp.name
        os.environ['APPDATA'] = os.path.join(self.tmp.name, 'appdata')
        os.environ['LOCALAPPDATA'] = os.path.join(self.tmp.name, 'local')
        os.environ['PROGRAMDATA'] = os.path.join(self.tmp.name, 'programdata')
        self.db_path = os.path.join(self.tmp.name, 'shop.db')
        self.patches = [
            patch('mbt_paths.get_db_path', return_value=self.db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self.db_path),
            patch('mbt_paths.get_data_dir', return_value=os.path.join(self.tmp.name, 'data')),
        ]
        for item in self.patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'admin'
        self.api._user_id = None
        self.api._username = 'qa_admin'

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self.tmp.cleanup()

    def _names(self):
        return {(row.get('name') or '').casefold() for row in self.api.get_categories(active_only=False)}

    def test_new_shop_has_no_hardcoded_categories(self):
        self.assertFalse(self._names() & set(RETIRED))
        bare = self.api.create_product({
            'name': 'Loose Soap', 'price': 20, 'cost_price': 10, 'stock': 4,
        })
        self.assertTrue(bare.get('success'), bare)
        db = self.ac._db()
        category = db.execute(
            "SELECT category FROM products WHERE id=?", (bare['id'],)
        ).fetchone()['category']
        db.close()
        self.assertFalse(category)
        self.assertFalse(self._names() & set(RETIRED))

    def test_duplicate_category_is_rejected_and_delete_keeps_products(self):
        created = self.api.create_category({'name': '  Fresh Produce  ', 'description': 'Veg'})
        self.assertEqual(created.get('name'), 'Fresh Produce', created)
        again = self.api.create_category({'name': 'fresh   produce'})
        self.assertEqual(again.get('status'), 409)
        self.assertIn('already exists', again.get('error') or '')
        self.assertTrue(self.api.create_category({'name': "Mum's & Co."}).get('id'))
        self.assertEqual(self.api.create_category({'name': 'a/b'}).get('status'), 400)
        self.assertEqual(self.api.create_category({'name': '   '}).get('status'), 400)
        self.assertEqual(self.api.create_category({'name': 'N' * 81}).get('status'), 400)
        product = self.api.create_product({
            'name': 'Tomatoes', 'category': 'FRESH PRODUCE', 'price': 50,
            'cost_price': 20, 'stock': 2,
        })
        self.assertTrue(product.get('success'), product)
        db = self.ac._db()
        stored = db.execute(
            "SELECT category FROM products WHERE id=?", (product['id'],)
        ).fetchone()['category']
        db.close()
        self.assertEqual(stored, 'Fresh Produce')
        row = self.api.get_category_by_name('fresh produce')
        blocked = self.api.delete_category(row['id'])
        self.assertEqual(blocked.get('status'), 409, blocked)
        db = self.ac._db()
        still = db.execute("SELECT name FROM products WHERE id=?", (product['id'],)).fetchone()['name']
        db.close()
        self.assertEqual(still, 'Tomatoes')
        removed = self.api.delete_category(row['id'], leave_uncategorised=True)
        self.assertTrue(removed.get('success'), removed)
        db = self.ac._db()
        after = db.execute(
            "SELECT name, category FROM products WHERE id=?", (product['id'],)
        ).fetchone()
        gone = db.execute("SELECT id FROM categories WHERE id=?", (row['id'],)).fetchone()
        db.close()
        self.assertEqual(after['name'], 'Tomatoes')
        self.assertFalse(after['category'])
        self.assertIsNone(gone)

    def test_cashier_cannot_delete_or_create_when_denied(self):
        made = self.api.create_category({'name': 'Till Snacks'})
        product = self.api.create_product({
            'name': 'Crisps', 'category': 'Till Snacks', 'price': 30,
            'cost_price': 10, 'stock': 5,
        })
        self.assertTrue(product.get('success'), product)
        self.api._role = 'cashier'
        denied = self.api.delete_category(made['id'], leave_uncategorised=True)
        self.assertEqual(denied.get('status'), 403, denied)
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, is_active, permission_denials) "
            "VALUES ('qa_cashier','x','cashier',1,?)",
            ('["categories.create"]',),
        )
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        kept = db.execute("SELECT category FROM products WHERE id=?", (product['id'],)).fetchone()['category']
        db.close()
        self.assertEqual(kept, 'Till Snacks')
        self.api._user_id = user_id
        blocked = self.api.create_category({'name': 'Cashier Special'})
        self.assertEqual(blocked.get('status'), 403, blocked)
        saved = self.api.create_product({
            'name': 'No Group', 'price': 15, 'cost_price': 5, 'stock': 1,
        })
        self.assertEqual(saved.get('status'), 403, saved)
        renamed = self.api.update_category(made['id'], {'name': 'Snacks Renamed'})
        self.assertEqual(renamed.get('status'), 403, renamed)


if __name__ == '__main__':
    unittest.main()
