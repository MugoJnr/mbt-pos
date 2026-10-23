"""Confirm the remaining shop services on a disposable database."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class RemainingShopServices(unittest.TestCase):
    PIN = '123456'

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'shop.db')
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
            "INSERT INTO users (id,username,password_hash,role,is_active) "
            "VALUES (1,'owner','x:y','superadmin',1)"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('superadmin_pin_hash', _pin_hash(self.PIN)),
        )
        db.execute(
            "INSERT INTO products (name,sku,price,cost_price,stock,min_stock) "
            "VALUES ('Sugar','SUG-1',200,50,30,1)"
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

    def test_fifo_sale_uses_oldest_cost_and_void_restores_it(self):
        from desktop.utils.stock_layers import add_layer
        db = self.ac._db()
        try:
            add_layer(db, 1, 10, 100, 'purchase', 'p1')
            add_layer(db, 1, 10, 120, 'purchase', 'p2')
            add_layer(db, 1, 10, 150, 'purchase', 'p3')
            again = add_layer(db, 1, 10, 100, 'purchase', 'p1')
            db.commit()
        finally:
            db.close()
        self.assertTrue(again.get('duplicate'))

        sale = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Sugar', 'sku': 'SUG-1',
                'quantity': 15, 'unit_price': 200, 'discount': 0, 'total': 3000,
            }],
            'subtotal': 3000, 'discount': 0, 'tax': 0, 'total': 3000,
            'payment_method': 'Cash', 'amount_paid': 3000, 'change_amount': 0,
        })
        self.assertTrue(sale.get('success'), sale)
        self.assertEqual(self._stock(), 15)
        db = self.ac._db()
        try:
            cogs = db.execute(
                "SELECT COALESCE(SUM(quantity * unit_cost),0) FROM cost_layer_uses "
                "WHERE sale_id=? AND reversed=0",
                (sale['sale_id'],),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(cogs), 1600.0, places=2)

        voided = self.api.void_sale(int(sale['sale_id']), 'Wrong sale', pin=self.PIN)
        self.assertTrue(voided.get('success'), voided)
        self.assertEqual(self._stock(), 30)
        db = self.ac._db()
        try:
            left = db.execute(
                "SELECT COALESCE(SUM(remaining_qty),0) FROM cost_layers WHERE product_id=1"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(left), 30.0, places=2)

    def test_sale_rolls_back_when_layers_are_short(self):
        from desktop.utils.stock_layers import add_layer
        db = self.ac._db()
        try:
            add_layer(db, 1, 5, 100, 'purchase', 'only')
            db.commit()
        finally:
            db.close()
        sale = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Sugar', 'sku': 'SUG-1',
                'quantity': 10, 'unit_price': 200, 'discount': 0, 'total': 2000,
            }],
            'subtotal': 2000, 'discount': 0, 'tax': 0, 'total': 2000,
            'payment_method': 'Cash', 'amount_paid': 2000, 'change_amount': 0,
        })
        self.assertIn('Insufficient cost layers', sale.get('error', ''))
        self.assertEqual(self._stock(), 30)
        db = self.ac._db()
        try:
            sales = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(sales, 0)

    def test_opening_backfill_does_not_invent_a_missing_cost(self):
        from desktop.utils.stock_layers import opening_backfill
        db = self.ac._db()
        try:
            db.execute("UPDATE products SET cost_price=NULL WHERE id=1")
            db.execute(
                "INSERT INTO products (name,sku,price,cost_price,stock) "
                "VALUES ('Empty','EMP-1',10,5,0)"
            )
            db.execute(
                "INSERT INTO products (name,sku,price,cost_price,stock) "
                "VALUES ('Known','KNW-1',10,8,4)"
            )
            first = opening_backfill(db)
            second = opening_backfill(db)
            layers = db.execute("SELECT COUNT(*) FROM cost_layers").fetchone()[0]
            db.commit()
        finally:
            db.close()
        by_name = {row['name']: row['status'] for row in first}
        self.assertEqual(by_name['Sugar'], 'missing_cost')
        self.assertEqual(by_name['Empty'], 'skipped_zero')
        self.assertEqual(by_name['Known'], 'created')
        self.assertEqual(layers, 1)
        self.assertEqual(
            next(row['status'] for row in second if row['name'] == 'Known'),
            'duplicate',
        )

    def test_consumption_values_and_journal_failure_rolls_back(self):
        self.assertEqual(self.api.get_departments(), [])
        saved = self.api.save_department('Office')
        created = self.api.create_consumption({
            'department_id': saved['id'],
            'reason': 'Staff tea',
            'items': [
                {'product_id': 1, 'quantity': 2},
                {'product_id': 1, 'quantity': 1},
            ],
        })
        self.assertIn('once', created.get('error', ''))
        self.assertEqual(self._stock(), 30)

        self.api._role = 'cashier'
        denied = self.api.create_consumption({
            'department_id': saved['id'],
            'reason': 'Staff tea',
            'items': [{'product_id': 1, 'quantity': 1}],
        })
        self.assertEqual(denied.get('status'), 403)
        self.api._role = 'superadmin'

        with patch(
            'desktop.utils.accounting_hooks.post_consumption_journal',
            return_value={'error': 'ledger down'},
        ):
            failed = self.api.create_consumption({
                'department_id': saved['id'],
                'reason': 'Staff tea',
                'items': [{'product_id': 1, 'quantity': 2}],
            })
        self.assertIn('ledger down', failed.get('error', ''))
        self.assertEqual(self._stock(), 30)

        ok = self.api.create_consumption({
            'department_id': saved['id'],
            'reason': 'Staff tea',
            'items': [{'product_id': 1, 'quantity': 2}],
        })
        self.assertTrue(ok.get('success'), ok)
        self.assertEqual(self._stock(), 28)
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT retail_opportunity, total_cost, foregone_profit "
                "FROM stock_consumption_items WHERE consumption_id=?",
                (ok['id'],),
            ).fetchone()
        finally:
            db.close()
        self.assertAlmostEqual(float(row['retail_opportunity']), 400.0, places=2)
        self.assertAlmostEqual(float(row['total_cost']), 100.0, places=2)
        self.assertAlmostEqual(float(row['foregone_profit']), 300.0, places=2)

    def test_write_off_keeps_history_and_does_not_repeat(self):
        db = self.ac._db()
        try:
            db.execute(
                "INSERT INTO customers (name, phone) VALUES ('Asha','0700')"
            )
            db.execute(
                "INSERT INTO debt_invoices "
                "(invoice_number, customer_id, customer_name, total_amount, amount_paid, balance) "
                "VALUES ('INV-1', 1, 'Asha', 500, 0, 500)"
            )
            db.commit()
        finally:
            db.close()
        first = self.api.write_off_debt(1, 200, 'Bad debt', pin=self.PIN, client_token='wo-1')
        self.assertTrue(first.get('success'), first)
        self.assertFalse(first.get('cash_receipt'))
        self.assertAlmostEqual(first['balance'], 300.0, places=2)
        second = self.api.write_off_debt(1, 200, 'Bad debt', pin=self.PIN, client_token='wo-1')
        self.assertTrue(second.get('duplicate'))
        db = self.ac._db()
        try:
            balance = db.execute("SELECT balance FROM debt_invoices WHERE id=1").fetchone()['balance']
            payments = db.execute("SELECT COUNT(*) FROM debt_payments").fetchone()[0]
            invoice = db.execute("SELECT id FROM debt_invoices WHERE id=1").fetchone()
        finally:
            db.close()
        self.assertAlmostEqual(float(balance), 300.0, places=2)
        self.assertEqual(payments, 0)
        self.assertIsNotNone(invoice)

    def test_expense_reversal_restores_cash_without_deleting(self):
        self.api._role = 'admin'
        saved = self.api.accounting_save_expense_category('Transport')
        self.assertTrue(saved.get('success'), saved)
        again = self.api.accounting_save_expense_category('Transport')
        self.assertTrue(again.get('duplicate'))
        created = self.api.accounting_create_expense({
            'amount': 150, 'description': 'Transport',
            'account_code': '6000', 'pay_from_code': '1000',
        })
        self.assertTrue(created.get('success'), created)
        self.assertAlmostEqual(self.api.accounting_cash_position()['balance'], -150.0, places=2)
        self.api._role = 'cashier'
        denied = self.api.accounting_reverse_expense(created['id'], 'Wrong vendor')
        self.assertIn('Insufficient', denied.get('error', ''))
        self.api._role = 'admin'
        reversed_row = self.api.accounting_reverse_expense(created['id'], 'Wrong vendor')
        self.assertTrue(reversed_row.get('success'), reversed_row)
        self.assertFalse(reversed_row.get('deleted'))
        self.assertAlmostEqual(self.api.accounting_cash_position()['balance'], 0.0, places=2)
        db = self.ac._db()
        try:
            original = db.execute(
                "SELECT status, deleted_at FROM expense_entries WHERE id=?",
                (created['id'],),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(original['status'], 'reversed')
        self.assertIsNone(original['deleted_at'])

    def test_protected_export_writes_nothing_without_the_pin(self):
        from desktop.utils.security import _pin_hash
        from backend.report_export_service import export_protected_workbook
        path = os.path.join(self._tmpdir.name, 'finance.xlsx')
        stored = _pin_hash(self.PIN)
        blocked = export_protected_workbook(
            path, [['Cash', 10]], role='manager', pin=self.PIN, stored_hash=stored,
        )
        self.assertEqual(blocked.get('status'), 403)
        self.assertFalse(os.path.exists(path))
        missing = export_protected_workbook(
            path, [['Cash', 10]], role='superadmin', pin='', stored_hash=stored,
        )
        self.assertEqual(missing.get('status'), 403)
        self.assertFalse(os.path.exists(path))
        written = export_protected_workbook(
            path, [['Cash', 10]], role='superadmin', pin=self.PIN, stored_hash=stored,
        )
        self.assertTrue(written.get('success'), written)
        self.assertTrue(os.path.exists(path))
        from openpyxl import load_workbook
        sheet = load_workbook(path).active
        self.assertTrue(sheet.protection.sheet)

    def test_print_retry_does_not_create_a_sale(self):
        failed = self.api.record_print_attempt(4, 'failed', 'printer offline')
        retried = self.api.record_print_attempt(4, 'printed', 'retry')
        self.assertTrue(failed.get('sales_unchanged'))
        self.assertTrue(retried.get('sales_unchanged'))
        history = self.api.print_history(4)
        self.assertEqual([row['outcome'] for row in history], ['failed', 'printed'])

    def test_cashier_void_request_waits_for_approval(self):
        sale = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Sugar', 'sku': 'SUG-1',
                'quantity': 1, 'unit_price': 200, 'discount': 0, 'total': 200,
            }],
            'subtotal': 200, 'discount': 0, 'tax': 0, 'total': 200,
            'payment_method': 'Cash', 'amount_paid': 200, 'change_amount': 0,
        })
        self.api._role = 'cashier'
        requested = self.api.request_sale_void(int(sale['sale_id']), 'Customer changed mind')
        self.assertTrue(requested.get('success'), requested)
        self.assertEqual(requested['sale_status'], 'completed')
        self.assertEqual(self._stock(), 29)
        approved = self.api.execute_approval(requested['id'], 'approve', pin=self.PIN)
        self.assertEqual(approved.get('status'), 403)
        self.api._role = 'superadmin'
        approved = self.api.execute_approval(requested['id'], 'approve', pin=self.PIN)
        self.assertTrue(approved.get('success'), approved)
        self.assertEqual(self._stock(), 30)

    def test_stocktake_count_does_not_change_stock_until_apply(self):
        from desktop.utils.stocktake import apply_stocktake, record_count, start_stocktake
        db = self.ac._db()
        try:
            started = start_stocktake(db, 'Morning')
            counted = record_count(db, started['id'], 1, 12)
            self.assertTrue(counted['stock_unchanged'])
            self.assertEqual(counted['stock'], 30)
            db.commit()
            applied = apply_stocktake(db, started['id'])
            self.assertTrue(applied.get('success'), applied)
            stock = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
            second = apply_stocktake(db, started['id'])
            stock_again = float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        finally:
            db.close()
        self.assertEqual(stock, 12)
        self.assertTrue(second.get('duplicate'))
        self.assertEqual(stock_again, 12)

    def test_remote_shop_commands_apply_once_and_do_not_start_an_installer(self):
        from backend.cloud.command_center import CommandCenter, dispatch_remote_command
        import backend.cloud.command_center as commands
        center = CommandCenter(self._db_path)
        missing = center.execute_local('update_product_price', {'product_id': 99, 'price': 10})
        self.assertFalse(missing[0])
        changed = center.execute_local('update_product_price', {'product_id': 1, 'price': 180})
        self.assertTrue(changed[0], changed)
        cost = center.execute_local('update_product_cost', {'product_id': 1, 'cost_price': 40})
        self.assertTrue(cost[0], cost)
        stock = center.execute_local('adjust_stock', {
            'product_id': 1, 'delta': 5, 'command_id': 'stk-1', 'reason': 'Count',
        })
        self.assertTrue(stock[0], stock)
        again = center.execute_local('adjust_stock', {
            'product_id': 1, 'delta': 5, 'command_id': 'stk-1', 'reason': 'Count',
        })
        self.assertTrue(again[2].get('duplicate'))
        disabled = center.execute_local('disable_user', {'user_id': 1})
        self.assertTrue(disabled[0], disabled)
        reset = center.execute_local('reset_user_pin', {'user_id': 1, 'pin': '654321'})
        self.assertTrue(reset[0], reset)
        self.assertNotIn('654321', str(reset))
        restart = center.execute_local('restart_sync', {})
        self.assertEqual(restart[2]['processes_killed'], 0)
        update = center.execute_local('update_now', {})
        self.assertFalse(update[2]['installer_started'])
        db = sqlite3.connect(self._db_path)
        try:
            price, cost_price, stock_qty, active = db.execute(
                "SELECT price, cost_price, stock, "
                "(SELECT is_active FROM users WHERE id=1) "
                "FROM products WHERE id=1"
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(price, 180)
        self.assertEqual(cost_price, 40)
        self.assertEqual(stock_qty, 35)
        self.assertEqual(active, 0)

        calls = []
        center.report_result = lambda *args, **kwargs: calls.append(args)
        with patch.object(commands, 'claim_pending_command', lambda cmd_id: True):
            receipt = os.path.join(self._tmpdir.name, 'receipts.json')
            cmd = {
                'id': 'price-2', 'command': 'update_product_price',
                'params': {'product_id': 1, 'price': 175},
            }
            self.assertEqual(dispatch_remote_command(center, cmd, receipt), 'executed')
            self.assertEqual(dispatch_remote_command(center, cmd, receipt), 'skipped')
        db = sqlite3.connect(self._db_path)
        try:
            final_price = db.execute("SELECT price FROM products WHERE id=1").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(final_price, 175)

    def test_local_payment_and_inbox_do_not_create_sales(self):
        from desktop.payments.local_checkout import LocalCheckout
        from desktop.payments.payment_inbox import PaymentInbox
        checkout = LocalCheckout()
        started = checkout.start('ABC123', '254700000000')
        self.assertFalse(started['sale_created'])
        uncertain = checkout.mark_uncertain(started['id'])
        self.assertEqual(uncertain['status'], 'uncertain')
        self.assertNotEqual(uncertain['status'], 'accepted')
        accepted = checkout.accept(started['id'])
        self.assertIn('error', accepted)

        inbox = PaymentInbox()
        inbox.add_open_sale(1, 500, 'RCP-1')
        inbox.add_open_sale(2, 500, 'RCP-2')
        credit = inbox.add_credit('cr-1', 500, 'PAYBILL')
        self.assertEqual(credit['status'], 'ambiguous')
        self.assertFalse(credit['sale_created'])
        once = inbox.reconcile('cr-1', 2)
        twice = inbox.reconcile('cr-1', 1)
        self.assertTrue(twice.get('duplicate'))
        self.assertEqual(twice['sale_id'], 2)
        self.assertEqual(once['sale_id'], 2)

    def test_cloud_guards_fail_closed(self):
        from backend.cloud.circuit_breaker import CircuitBreaker
        from backend.cloud.org_guard import organisation_allowed
        from backend.updater import should_trigger_reconnect_check
        breaker = CircuitBreaker(failure_limit=2, cool_down_s=30)
        self.assertTrue(breaker.allow(0))
        breaker.record_failure(0)
        breaker.record_failure(0)
        self.assertFalse(breaker.allow(10))
        self.assertTrue(breaker.allow(31))
        self.assertFalse(organisation_allowed('', 'abc')['allowed'])
        self.assertFalse(organisation_allowed('abc', 'xyz')['allowed'])
        self.assertTrue(organisation_allowed('abc', 'abc')['allowed'])
        self.assertTrue(should_trigger_reconnect_check(False, True, False))
        self.assertFalse(should_trigger_reconnect_check(True, True, False))
        self.assertFalse(should_trigger_reconnect_check(False, True, True))

    def test_second_launch_raises_the_open_window_and_stays_quiet_without_one(self):
        from desktop.utils.instance_window import resolve_second_launch
        raised = []
        self.assertEqual(
            resolve_second_launch(True, lambda: 42, raised.append),
            'raised',
        )
        self.assertEqual(raised, [42])
        self.assertEqual(resolve_second_launch(True, lambda: 0, raised.append), 'quiet')
        self.assertEqual(resolve_second_launch(False, lambda: 42, raised.append), 'start')

    def test_web_exposes_return_and_write_off(self):
        path = os.path.join(ROOT, 'web', 'web_routes.py')
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn("/api/sales/<int:sale_id>/return", source)
        self.assertIn("api.return_sale(", source)
        self.assertIn("/api/debts/<int:invoice_id>/write-off", source)
        self.assertIn("api.write_off_debt(", source)


if __name__ == '__main__':
    unittest.main()
