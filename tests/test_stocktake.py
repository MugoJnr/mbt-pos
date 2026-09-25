"""Stocktake expected quantity, permissions, and one-time adjustment."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class StocktakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, 'stocktake.db')
        self.patches = [
            patch.dict(os.environ, {'MBT_BOOTSTRAP_ADMIN_PASSWORD': ''}),
            patch('mbt_paths.get_db_path', return_value=self.db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self.db_path),
        ]
        for item in self.patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        ac._SCHEMA_READY_PATH = None
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'owner'
        db = ac._db()
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) VALUES (1,'owner','x','superadmin')"
        )
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) VALUES (2,'counter','x','cashier')"
        )
        db.commit()
        db.close()
        created = self.api.create_product({
            'name': 'Sugar 2kg', 'sku': 'SUGAR-2', 'price': 250, 'cost_price': 180,
            'stock': 10, 'unit': 'kg',
        })
        self.assertTrue(created.get('success'), created)
        self.pid = int(created['id'])
        db = self.ac._db()
        db.execute("UPDATE products SET stock=10 WHERE id=?", (self.pid,))
        db.commit()
        db.close()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self.ac._SCHEMA_READY_PATH = None
        self.tmp.cleanup()

    def test_sale_during_count_changes_expected_not_snapshot(self):
        started = self.api.start_stocktake({
            'name': 'Month-end count', 'scope_type': 'all',
            'reason': 'Month-end', 'counting_mode': 'normal',
        })
        self.assertTrue(started.get('success'), started)
        sid = started['id']
        db = self.ac._db()
        begun = db.execute("SELECT started_at FROM stocktakes WHERE id=?", (sid,)).fetchone()[0]
        db.execute(
            "INSERT INTO stock_movements (product_id, product_name, movement_type, "
            "qty_before, qty_change, qty_after, reference, reason, user_id, username, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?, datetime(?, '+2 seconds'))",
            (self.pid, 'Sugar 2kg', 'SALE', 10, -2, 8, 'SALE-1', 'Sold during count',
             2, 'counter', begun),
        )
        db.commit()
        line = db.execute(
            "SELECT id FROM stocktake_lines WHERE stocktake_id=?", (sid,)
        ).fetchone()
        db.close()
        self.api._role = 'cashier'
        self.api._user_id = 2
        self.api._username = 'counter'
        saved = self.api.record_stocktake_count(int(line['id']), 6)
        self.assertTrue(saved.get('success'), saved)
        self.api._user_id = 1
        self.api._username = 'owner'
        blocked = self.api.record_stocktake_count(int(line['id']), 9)
        self.assertIn('already counted', blocked.get('error', ''))
        self.api._role = 'superadmin'
        data = self.api.stocktake_reconcile(sid)
        row = data['lines'][0]
        self.assertEqual(row['expected_qty'], 8)
        self.assertEqual(row['physical_qty'], 6)
        self.assertEqual(row['variance_qty'], -2)
        self.assertEqual(row['cost_impact'], -360)
        self.assertEqual(row['retail_impact'], -500)
        self.api._role = 'cashier'
        self.api._user_id = 2
        denied = self.api.apply_stocktake(sid)
        self.assertEqual(denied.get('status'), 403)
        self.api._role = 'superadmin'
        self.api._user_id = 1
        applied = self.api.apply_stocktake(sid, 'Physical count accepted')
        self.assertTrue(applied.get('success'), applied)
        again = self.api.apply_stocktake(sid, 'Physical count accepted')
        self.assertTrue(again.get('error'))
        db = self.ac._db()
        stock = db.execute("SELECT stock FROM products WHERE id=?", (self.pid,)).fetchone()[0]
        moves = db.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE product_id=? AND movement_type='SUPERADMIN_ADJUST'",
            (self.pid,),
        ).fetchone()[0]
        db.close()
        self.assertEqual(float(stock), 6)
        self.assertEqual(int(moves), 1)

    def test_blind_count_hides_expected_from_counter(self):
        self.api._role = 'manager'
        started = self.api.start_stocktake({
            'name': 'Blind check', 'scope_type': 'products', 'scope_ids': [self.pid],
            'reason': 'Audit', 'counting_mode': 'blind',
        })
        self.assertTrue(started.get('success'), started)
        self.api._role = 'cashier'
        data = self.api.stocktake_reconcile(started['id'])
        self.assertNotIn('expected_qty', data['lines'][0])
        self.assertIsNone(data['summary']['shortage_cost'])

    def test_decimal_and_shop_export(self):
        db = self.ac._db()
        db.execute("UPDATE products SET stock=1.5 WHERE id=?", (self.pid,))
        db.commit()
        db.close()
        started = self.api.start_stocktake({
            'name': 'Decimal', 'scope_type': 'all', 'reason': 'Routine stocktake',
        })
        db = self.ac._db()
        baseline = db.execute(
            "SELECT baseline_qty FROM stocktake_lines WHERE stocktake_id=?",
            (started['id'],),
        ).fetchone()[0]
        db.close()
        self.assertEqual(float(baseline), 1.5)
        from desktop.utils.shop_report import build_shop_workbook
        db = self.ac._db()
        payload = build_shop_workbook(
            db, shop_name='Test Shop', preset='all', start='', end='', generated_by='owner',
        )
        db.close()
        self.assertTrue(payload.startswith(b'PK'))
        from desktop.utils.stocktake import export_workbook
        db = self.ac._db()
        book = export_workbook(db, started['id'])
        db.close()
        self.assertTrue(book.startswith(b'PK'))

    def test_remote_adjust_executes_once(self):
        started = self.api.start_stocktake({
            'name': 'Approval count', 'scope_type': 'all', 'reason': 'Audit',
        })
        db = self.ac._db()
        line = db.execute(
            "SELECT id FROM stocktake_lines WHERE stocktake_id=?", (started['id'],)
        ).fetchone()
        db.close()
        self.api.record_stocktake_count(int(line['id']), 7)
        self.api._role = 'cashier'
        self.api._user_id = 2
        self.api._username = 'counter'
        requested = self.api.request_stocktake_adjust(started['id'], 'Count is short')
        self.assertTrue(requested.get('success'), requested)
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'owner'
        first = self.api.execute_approval(requested['id'], note='Approved')
        self.assertTrue(first.get('success'), first)
        second = self.api.execute_approval(requested['id'], note='Approved')
        self.assertEqual(second.get('status'), 409)
        db = self.ac._db()
        stock = float(db.execute("SELECT stock FROM products WHERE id=?", (self.pid,)).fetchone()[0])
        db.close()
        self.assertEqual(stock, 7)
