"""Internal consumption batch, permissions, retry, and cost-layer restore."""
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


class ConsumptionBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'consumption.db')
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
            "VALUES ('Soap 500ml','SOAP-500',80,40,20,1)"
        )
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) "
            "VALUES ('Soap 1L','SOAP-1L',120,60,5,1)"
        )
        db.commit()
        db.close()
        dept = self.api.save_department('IC-AUDIT Office')
        self.dept_id = int(dept['id'])

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _stock(self, sku):
        db = self.ac._db()
        try:
            return float(db.execute(
                "SELECT stock FROM products WHERE sku=?", (sku,)
            ).fetchone()['stock'])
        finally:
            db.close()

    def test_batch_deducts_each_product_once(self):
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [
                {'product_id': 1, 'quantity': 2},
                {'product_id': 2, 'quantity': 1},
            ],
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertEqual(self._stock('SOAP-500'), 18)
        self.assertEqual(self._stock('SOAP-1L'), 4)
        detail = self.api.get_consumption(saved['id'])
        self.assertEqual(len(detail['items']), 2)
        db = self.ac._db()
        try:
            moves = db.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE movement_type='INTERNAL_USE'"
            ).fetchone()[0]
            sales = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(int(moves), 2)
        self.assertEqual(int(sales), 0)
        db = self.ac._db()
        try:
            audits = db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action='INTERNAL_USE'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(int(audits), 2)

    def test_duplicate_product_and_short_stock_change_nothing(self):
        duplicate = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [
                {'product_id': 1, 'quantity': 1},
                {'product_id': 1, 'quantity': 1},
            ],
        })
        self.assertIn('once', duplicate.get('error', ''))
        short = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [
                {'product_id': 1, 'quantity': 1},
                {'product_id': 2, 'quantity': 9},
            ],
        })
        self.assertIn('Insufficient', short.get('error', ''))
        self.assertEqual(self._stock('SOAP-500'), 20)
        self.assertEqual(self._stock('SOAP-1L'), 5)

    def test_retry_token_does_not_deduct_twice(self):
        payload = {
            'department_id': self.dept_id,
            'reason': 'Office Use',
            'client_token': 'ic-audit-token-1',
            'items': [{'product_id': 1, 'quantity': 3}],
        }
        first = self.api.create_consumption(payload)
        second = self.api.create_consumption(payload)
        self.assertTrue(first.get('success'), first)
        self.assertTrue(second.get('duplicate'), second)
        self.assertEqual(second.get('id'), first.get('id'))
        self.assertEqual(self._stock('SOAP-500'), 17)

    def test_viewer_cannot_create_and_manager_cannot_void(self):
        self.api._role = 'viewer'
        denied = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertEqual(denied.get('status'), 403)
        self.assertEqual(self._stock('SOAP-500'), 20)
        self.api._role = 'cashier'
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertTrue(saved.get('success'), saved)
        self.api._role = 'manager'
        voided = self.api.void_consumption(saved['id'], 'mistake')
        self.assertIn('error', voided)
        self.assertEqual(self._stock('SOAP-500'), 19)

    def test_void_restores_stock_and_cost_layers(self):
        from desktop.utils.stock_layers import add_layer
        db = self.ac._db()
        add_layer(db, 1, 20, 40, 'opening', '1')
        db.commit()
        db.close()
        self.api._role = 'admin'
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 4}],
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertEqual(self._stock('SOAP-500'), 16)
        db = self.ac._db()
        try:
            remaining = float(db.execute(
                "SELECT remaining_qty FROM cost_layers WHERE product_id=1"
            ).fetchone()[0])
        finally:
            db.close()
        self.assertEqual(remaining, 16)
        voided = self.api.void_consumption(saved['id'], 'wrong item')
        self.assertTrue(voided.get('success'), voided)
        self.assertEqual(self._stock('SOAP-500'), 20)
        db = self.ac._db()
        try:
            remaining = float(db.execute(
                "SELECT remaining_qty FROM cost_layers WHERE product_id=1"
            ).fetchone()[0])
            again = db.execute(
                "SELECT voided FROM stock_consumptions WHERE id=?", (saved['id'],)
            ).fetchone()['voided']
        finally:
            db.close()
        self.assertEqual(remaining, 20)
        self.assertEqual(int(again), 1)
        second = self.api.void_consumption(saved['id'], 'again')
        self.assertIn('already', second.get('error', '').lower())
        self.assertEqual(self._stock('SOAP-500'), 20)

    def test_concurrent_saves_cannot_oversell_one_unit(self):
        db = self.ac._db()
        db.execute("UPDATE products SET stock=1 WHERE sku='SOAP-500'")
        db.commit()
        db.close()
        results = []
        lock = threading.Lock()

        def save(token):
            api = self.ac.APIClient()
            api._role = 'manager'
            api._user_id = 1
            api._username = 'manager'
            result = api.create_consumption({
                'department_id': self.dept_id,
                'reason': 'Cleaning',
                'client_token': token,
                'items': [{'product_id': 1, 'quantity': 1}],
            })
            with lock:
                results.append(result)

        first = threading.Thread(target=save, args=('race-a',))
        second = threading.Thread(target=save, args=('race-b',))
        first.start()
        second.start()
        first.join()
        second.join()
        saved = [row for row in results if row.get('success')]
        rejected = [row for row in results if row.get('error')]
        self.assertEqual(len(saved), 1, results)
        self.assertEqual(len(rejected), 1, results)
        self.assertEqual(self._stock('SOAP-500'), 0)

    def test_report_totals_include_voided_lines(self):
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 2}],
        })
        report = self.api.get_consumption_report('2000-01-01', '2099-12-31', include_voided=True)
        self.assertEqual(report['totals']['line_count'], 1)
        self.assertEqual(report['totals']['total_qty'], 2)
        self.api._role = 'admin'
        self.api.void_consumption(saved['id'], 'test void')
        after = self.api.get_consumption_report('2000-01-01', '2099-12-31', include_voided=True)
        self.assertEqual(after['totals']['line_count'], 1)
        self.assertEqual(int(after['rows'][0]['voided']), 1)

    def test_web_routes_call_the_service(self):
        path = os.path.join(ROOT, 'web', 'web_routes.py')
        with open(path, encoding='utf-8') as handle:
            src = handle.read()
        self.assertIn("/api/consumptions", src)
        self.assertIn("/api/consumptions/report", src)
        self.assertIn("create_consumption", src)
        self.assertIn("/void", src)
        self.assertIn("/void-request", src)
        ui = os.path.join(ROOT, 'web', 'dashboard-ui', 'src', 'routes', 'consumption.tsx')
        with open(ui, encoding='utf-8') as handle:
            page = handle.read()
        self.assertIn('Add product', page)
        self.assertIn('Find product', page)
        self.assertIn('already on this consumption', page)
        self.assertIn('Run report', page)
        self.assertIn('Export Excel', page)
        self.assertIn('Request void', page)

    def test_cashier_void_request_restores_stock_once(self):
        self.api._role = 'cashier'
        self.api._user_id = 1
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [
                {'product_id': 1, 'quantity': 2},
                {'product_id': 2, 'quantity': 1},
            ],
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertEqual(self._stock('SOAP-500'), 18)
        self.assertEqual(self._stock('SOAP-1L'), 4)
        denied = self.api.void_consumption(saved['id'], 'cashier tries directly')
        self.assertIn('Insufficient', denied.get('error') or '')
        self.assertEqual(self._stock('SOAP-500'), 18)
        requested = self.api.request_consumption_void(saved['id'], 'Entered the wrong quantities')
        self.assertTrue(requested.get('success'), requested)
        duplicate = self.api.request_consumption_void(saved['id'], 'again')
        self.assertTrue(duplicate.get('duplicate'))
        own = self.api.execute_approval(requested['id'], 'approve', note='no')
        self.assertEqual(own.get('status'), 403)
        self.assertEqual(self._stock('SOAP-500'), 18)
        self.api._role = 'admin'
        self.api._user_id = 2
        approved = self.api.execute_approval(requested['id'], 'approve', note='Wrong quantities')
        self.assertTrue(approved.get('success'), approved)
        self.assertEqual(self._stock('SOAP-500'), 20)
        self.assertEqual(self._stock('SOAP-1L'), 5)
        again = self.api.execute_approval(requested['id'], 'approve', note='again')
        self.assertTrue(again.get('success') or again.get('duplicate'))
        self.assertEqual(self._stock('SOAP-500'), 20)
        detail = self.api.get_consumption(saved['id'])
        self.assertEqual(int(detail['voided']), 1)

    def test_rejected_consumption_void_does_not_restore_stock(self):
        self.api._role = 'cashier'
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Office Use',
            'items': [{'product_id': 1, 'quantity': 3}],
        })
        self.assertTrue(saved.get('success'), saved)
        requested = self.api.request_consumption_void(saved['id'], 'Not actually used')
        self.api._role = 'admin'
        self.api._user_id = 2
        rejected = self.api.execute_approval(requested['id'], 'reject', note='The use was real')
        self.assertEqual(rejected.get('status'), 'rejected')
        self.assertEqual(self._stock('SOAP-500'), 17)
        detail = self.api.get_consumption(saved['id'])
        self.assertEqual(int(detail['voided'] or 0), 0)


    def test_edit_applies_only_the_quantity_difference(self):
        db = self.ac._db()
        db.execute("UPDATE products SET stock=20 WHERE sku='SOAP-500'")
        db.execute("UPDATE products SET stock=10 WHERE sku='SOAP-1L'")
        db.execute("UPDATE products SET unit='pcs' WHERE sku IN ('SOAP-500','SOAP-1L')")
        sales_before = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        db.commit()
        db.close()
        self.api._role = 'admin'
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Staff Consumption',
            'taken_by': 'QA',
            'items': [
                {'product_id': 1, 'quantity': 2},
                {'product_id': 2, 'quantity': 3},
            ],
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertEqual(self._stock('SOAP-500'), 18)
        self.assertEqual(self._stock('SOAP-1L'), 7)
        self.api._role = 'cashier'
        denied = self.api.edit_consumption(saved['id'], {
            'edit_reason': 'Cashier must not correct this',
            'items': [{'product_id': 1, 'quantity': 3}],
        })
        self.assertEqual(denied.get('status'), 403)
        self.assertEqual(self._stock('SOAP-500'), 18)
        self.api._role = 'admin'
        edited = self.api.edit_consumption(saved['id'], {
            'edit_reason': 'Soap was 3 and oil was 1',
            'items': [
                {'product_id': 1, 'quantity': 3},
                {'product_id': 2, 'quantity': 1},
            ],
            'client_token': 'edit-once',
        })
        self.assertTrue(edited.get('success'), edited)
        self.assertEqual(self._stock('SOAP-500'), 17)
        self.assertEqual(self._stock('SOAP-1L'), 9)
        again = self.api.edit_consumption(saved['id'], {
            'edit_reason': 'Soap was 3 and oil was 1',
            'items': [
                {'product_id': 1, 'quantity': 3},
                {'product_id': 2, 'quantity': 1},
            ],
            'client_token': 'edit-once',
        })
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(self._stock('SOAP-500'), 17)
        detail = self.api.get_consumption(saved['id'])
        self.assertEqual(len(detail.get('revisions') or []), 1)
        self.api._role = 'cashier'
        self.api._user_id = 1
        requested = self.api.request_consumption_void(saved['id'], 'Put the goods back')
        self.api._role = 'admin'
        self.api._user_id = 2
        approved = self.api.execute_approval(requested['id'], 'approve', note='Put the goods back')
        self.assertTrue(approved.get('success'), approved)
        self.assertEqual(self._stock('SOAP-500'), 20)
        self.assertEqual(self._stock('SOAP-1L'), 10)
        repeat = self.api.execute_approval(requested['id'], 'approve', note='again')
        self.assertTrue(repeat.get('success') or repeat.get('duplicate'))
        self.assertEqual(self._stock('SOAP-500'), 20)
        db = self.ac._db()
        try:
            sales_after = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(sales_after, sales_before)

    def test_decimal_quantity_keeps_the_original_stock_snapshot(self):
        db = self.ac._db()
        db.execute("UPDATE products SET unit='kg' WHERE id=1")
        db.commit()
        db.close()
        self.api._role = 'admin'
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 0.25}],
            'client_token': 'decimal-create',
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertAlmostEqual(self._stock('SOAP-500'), 19.75, places=3)
        detail = self.api.get_consumption(saved['id'])
        item = detail['items'][0]
        self.assertEqual(item['unit'], 'kg')
        self.assertAlmostEqual(float(item['quantity']), 0.25, places=3)
        self.assertAlmostEqual(float(item['stock_before']), 20, places=3)
        self.assertAlmostEqual(float(item['stock_after']), 19.75, places=3)
        edited = self.api.edit_consumption(saved['id'], {
            'edit_reason': 'Used a little more',
            'items': [{'product_id': 1, 'quantity': 0.5}],
            'client_token': 'decimal-edit',
        })
        self.assertTrue(edited.get('success'), edited)
        self.assertAlmostEqual(self._stock('SOAP-500'), 19.5, places=3)
        detail = self.api.get_consumption(saved['id'])
        item = detail['items'][0]
        self.assertAlmostEqual(float(item['quantity']), 0.5, places=3)
        self.assertAlmostEqual(float(item['stock_before']), 20, places=3)
        self.assertAlmostEqual(float(item['stock_after']), 19.5, places=3)

    def test_future_date_and_piece_fraction_leave_stock_unchanged(self):
        future = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'date': '2099-01-01',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertEqual(future.get('status'), 400, future)
        self.assertIn('Future', future.get('error') or '')
        half = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 0.5}],
        })
        self.assertEqual(half.get('status'), 400, half)
        self.assertEqual(self._stock('SOAP-500'), 20)

    def test_past_business_date_keeps_the_real_creation_time(self):
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'date': '2020-01-15',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertTrue(saved.get('success'), saved)
        detail = self.api.get_consumption(saved['id'])
        self.assertEqual(str(detail.get('date'))[:10], '2020-01-15')
        self.assertTrue(str(detail.get('created_at') or '').startswith('2026'))

    def test_cashier_cannot_backdate_consumption(self):
        self.api._role = 'cashier'
        refused = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'date': '2020-01-15',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertEqual(refused.get('status'), 403, refused)
        self.assertEqual(self._stock('SOAP-500'), 20)
        self.api._role = 'manager'

    def test_cashier_response_hides_consumption_cost(self):
        saved = self.api.create_consumption({
            'department_id': self.dept_id,
            'reason': 'Cleaning',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertTrue(saved.get('success'), saved)
        self.assertIn('total_cost', saved)
        self.api._role = 'cashier'
        hidden = self.api.get_consumption(saved['id'])
        self.assertNotIn('total_cost', hidden)
        self.assertNotIn('unit_cost', hidden['items'][0])
        listed = self.api.get_consumptions(start='2000-01-01', end='2099-01-01')
        self.assertTrue(listed)
        self.assertNotIn('total_cost', listed[0])
        self.api._role = 'manager'
        db = self.ac._db()
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('shop_name', 'QA Shop')"
        )
        db.commit()
        db.close()
        visible = self.api.get_consumption(saved['id'])
        self.assertEqual(visible.get('shop_name'), 'QA Shop')
        self.assertIn('unit_cost', visible['items'][0])
        from desktop.tabs.consumption_tab import consumption_money_label
        self.assertIsNone(consumption_money_label(None, False))
        self.assertIsNone(consumption_money_label(1600, False))
        self.assertEqual(consumption_money_label(1600, True), 'KES 1,600.00')

    def test_save_does_not_need_a_network(self):
        """The till writes consumption to the local shop file. A dead network must not block it."""
        def _offline(*_args, **_kwargs):
            raise OSError('offline')
        with patch('socket.create_connection', side_effect=_offline):
            saved = self.api.create_consumption({
                'department_id': self.dept_id,
                'reason': 'Cleaning',
                'notes': 'offline sample',
                'items': [{'product_id': 1, 'quantity': 1}],
            })
        self.assertTrue(saved.get('success'), saved)
        self.assertTrue(saved.get('reference_no'))
        self.assertEqual(self._stock('SOAP-500'), 19)
        again = self.api.get_consumption(saved['id'])
        self.assertEqual(again.get('notes'), 'offline sample')
        self.assertEqual(self._stock('SOAP-500'), 19)

    def test_print_opens_our_preview_instead_of_the_blank_windows_pane(self):
        import inspect
        from desktop.tabs.consumption_tab import _HistoryPane
        from desktop.tabs.receipts_tab import ReceiptDetailDialog
        consumption = inspect.getsource(_HistoryPane._print_receipt)
        preview = inspect.getsource(_HistoryPane._preview_receipt)
        receipts = inspect.getsource(ReceiptDetailDialog._print)
        self.assertIn('print_saved_document', consumption)
        self.assertNotIn('QPrintDialog', consumption)
        self.assertNotIn('QPrintPreviewDialog', preview)
        self.assertIn('print_saved_document', receipts)
        self.assertNotIn('QPrintDialog', receipts)


if __name__ == '__main__':
    unittest.main()
