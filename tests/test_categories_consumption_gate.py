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

    def _department(self, name='Stores'):
        created = self.api.create_department(name)
        self.assertTrue(created.get('success'), created)
        return int(created['id'])

    def test_shop_starts_without_builtin_departments(self):
        names = {
            (row.get('name') or '').lower()
            for row in (self.api.get_departments(active_only=False) or [])
        }
        self.assertFalse(names & {
            'kitchen', 'bakery', 'juice bar', 'office',
            'workshop', 'manufacturing', 'maintenance',
        })
        db = self.ac._db()
        db.execute(
            "DELETE FROM system_settings WHERE key='departments_seed_retired'"
        )
        db.execute(
            "INSERT INTO departments (name, active) VALUES ('Kitchen', 1)"
        )
        db.execute(
            "INSERT INTO departments (name, active) VALUES ('Poultry', 1)"
        )
        db.commit()
        db.close()
        self.ac._SCHEMA_READY = False
        self.ac._db().close()
        active = {
            (row.get('name') or '').lower()
            for row in self.api.get_departments(active_only=True)
        }
        self.assertNotIn('kitchen', active)
        self.assertIn('poultry', active)

    def test_v04_create_consumption_decrements_stock_and_movement(self):
        dept_id = self._department()

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
        detail = self.api.get_consumption(int(created['id']))
        self.assertEqual(len(detail['items']), 1)
        self.assertEqual(float(detail['items'][0]['unit_cost']), 20.0)
        self.assertEqual(
            float(detail['items'][0]['effective_selling_price']), 50.0)
        self.assertEqual(float(detail['total_buying_cost']), 60.0)
        self.assertEqual(float(detail['average_buying_cost']), 20.0)
        self.assertEqual(float(detail['opportunity_value']), 150.0)
        self.assertEqual(float(detail['foregone_gross_profit']), 90.0)
        self.assertFalse(detail['has_estimated_selling_prices'])

    def test_duplicate_consumption_product_is_rejected_atomically(self):
        dept_id = self._department()
        denied = self.api.create_consumption({
            'date': str(date.today()),
            'department_id': dept_id,
            'reason': 'duplicate payload',
            'items': [
                {'product_id': 1, 'quantity': 3},
                {'product_id': 1, 'quantity': 4},
            ],
        })
        self.assertIn('error', denied)
        db = self.ac._db()
        self.assertEqual(
            float(db.execute(
                "SELECT stock FROM products WHERE id=1").fetchone()['stock']),
            30.0,
        )
        self.assertEqual(
            db.execute(
                "SELECT COUNT(*) FROM stock_consumptions").fetchone()[0],
            0,
        )
        db.close()

    def test_consumption_rolls_back_stock_if_accounting_cannot_post(self):
        dept_id = self._department()
        with patch(
            'desktop.utils.accounting_hooks.post_consumption_journal',
            side_effect=RuntimeError('journal unavailable'),
        ):
            denied = self.api.create_consumption({
                'date': str(date.today()),
                'department_id': dept_id,
                'reason': 'must remain atomic',
                'items': [{'product_id': 1, 'quantity': 3}],
            })
        self.assertIn('error', denied)
        self.assertNotIn('journal unavailable', denied['error'])
        db = self.ac._db()
        self.assertEqual(
            float(db.execute(
                'SELECT stock FROM products WHERE id=1').fetchone()['stock']),
            30.0,
        )
        self.assertEqual(
            db.execute(
                'SELECT COUNT(*) FROM stock_consumptions').fetchone()[0],
            0,
        )
        db.close()

    def test_cashier_cannot_record_internal_consumption_directly(self):
        dept_id = self._department()
        self.api._role = 'cashier'
        denied = self.api.create_consumption({
            'date': str(date.today()),
            'department_id': dept_id,
            'reason': 'unauthorized',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertIn('error', denied)
        db = self.ac._db()
        self.assertEqual(
            float(db.execute(
                "SELECT stock FROM products WHERE id=1").fetchone()['stock']),
            30.0,
        )
        db.close()

    def test_department_management_preserves_history_and_permissions(self):
        self.api._role = 'manager'
        created = self.api.create_department('Packing Room')
        self.assertTrue(created.get('success'), created)
        department_id = int(created['id'])
        renamed = self.api.update_department(department_id, 'Main Packing Room')
        self.assertTrue(renamed.get('success'), renamed)

        db = self.ac._db()
        db.execute(
            "INSERT INTO stock_consumptions "
            "(reference_no,date,department_id,reason,total_cost,voided) "
            "VALUES ('AUTO-DEPT',?,?,?,?,0)",
            (str(date.today()), department_id, 'maintenance', 5.0),
        )
        db.commit()
        db.close()

        archived = self.api.archive_department(department_id)
        self.assertTrue(archived.get('success'), archived)
        active_ids = {
            int(row['id']) for row in self.api.get_departments(active_only=True)
        }
        self.assertNotIn(department_id, active_ids)
        all_rows = self.api.get_departments(active_only=False)
        row = next(r for r in all_rows if int(r['id']) == department_id)
        self.assertEqual(row['name'], 'Main Packing Room')
        self.assertEqual(int(row['usage_count']), 1)
        self.assertEqual(int(row['active']), 0)

        restored = self.api.create_department('Main Packing Room')
        self.assertTrue(restored.get('success'), restored)
        self.assertIn('restored', restored.get('message', '').lower())

        self.api._role = 'cashier'
        denied = self.api.create_department('Cashier Department')
        self.assertEqual(denied.get('status'), 403)
        denied_archive = self.api.archive_department(department_id)
        self.assertEqual(denied_archive.get('status'), 403)

    def test_consumption_uses_fifo_cost_and_restores_the_layer(self):
        from desktop.utils.stock_layers import record_receipt, list_layers
        dept_id = self._department('Cold Room')
        db = self.ac._db()
        record_receipt(
            db, 1, quantity=10, unit_cost=8, qty_before=0, previous_cost=0,
            source='purchase',
        )
        db.commit()
        db.close()
        created = self.api.create_consumption({
            'date': str(date.today()),
            'department_id': dept_id,
            'reason': 'Staff use',
            'items': [{'product_id': 1, 'quantity': 4}],
        })
        self.assertTrue(created.get('success'), created)
        detail = self.api.get_consumption(int(created['id']))
        self.assertEqual(float(detail['total_buying_cost']), 32.0)
        self.assertEqual(float(detail['opportunity_value']), 200.0)
        self.assertEqual(float(detail['foregone_gross_profit']), 168.0)
        db = self.ac._db()
        left = sum(float(row['qty_remaining']) for row in list_layers(db, 1))
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=1").fetchone()[0])
        db.close()
        self.assertAlmostEqual(left, 6.0, places=3)
        self.assertAlmostEqual(stock, 26.0, places=3)
        self.api._role = 'superadmin'
        voided = self.api.void_consumption(int(created['id']), 'Wrong entry', pin='')
        self.assertTrue(voided.get('success'), voided)
        db = self.ac._db()
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=1").fetchone()[0])
        db.close()
        self.assertAlmostEqual(stock, 30.0, places=3)

    def test_consumption_ui_and_dashboard_expose_departments_and_multi_select(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        desktop = (
            root / 'desktop' / 'tabs' / 'consumption_tab.py'
        ).read_text(encoding='utf-8')
        web = (
            root / 'web' / 'dashboard-ui' / 'src' / 'routes'
            / 'consumption.tsx'
        ).read_text(encoding='utf-8')
        routes = (
            root / 'web' / 'web_routes.py'
        ).read_text(encoding='utf-8')
        nav = (
            root / 'web' / 'dashboard-ui' / 'src' / 'components'
            / 'app-shell.tsx'
        ).read_text(encoding='utf-8')
        self.assertIn("self._tabs.addTab(self._departments, 'Departments')", desktop)
        self.assertIn('QAbstractItemView.ExtendedSelection', desktop)
        self.assertIn('+ Add Selected', desktop)
        self.assertIn('PROD_LIST_ITEM_H * 3', desktop)
        self.assertIn('no departments yet', desktop)
        self.assertIn('Tick as many products as needed', web)
        self.assertIn('max-h-[520px] min-h-[360px]', web)
        self.assertIn('setDetailId(Number(row.id))', web)
        self.assertIn('product_name', web)
        self.assertIn('Departments', web)
        self.assertIn("@web.route('/api/departments', methods=['GET', 'POST'])", routes)
        self.assertIn("@web.route('/api/consumptions', methods=['GET', 'POST'])", routes)
        self.assertIn('to: "/consumption"', nav)


if __name__ == '__main__':
    unittest.main()
