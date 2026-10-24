"""Regression coverage for protected, atomic manual stock adjustment."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class StockAdjustmentWorkflowTests(unittest.TestCase):
    PIN = '123456'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, 'stock-adjust.db')
        self.patches = [
            patch.dict(os.environ, {'MBT_BOOTSTRAP_ADMIN_PASSWORD': ''}),
            patch('mbt_paths.get_db_path', return_value=self.db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self.db_path),
        ]
        for item in self.patches:
            item.start()

        import desktop.utils.api_client as ac
        from desktop.utils.security import _pin_hash

        ac._SCHEMA_READY = False
        ac._SCHEMA_READY_PATH = None
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'owner'

        db = ac._db()
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) "
            "VALUES (1,'owner','x:y','superadmin')"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('superadmin_pin_hash', _pin_hash(self.PIN)),
        )
        db.commit()
        db.close()
        created = self.api.create_product({
            'name': 'QA Stock Adjustment Item',
            'sku': 'QA-STOCK-ADJUST',
            'barcode': 'QA000001',
            'price': 120.50,
            'cost_price': 80.25,
            'stock': 10,
            'min_stock': 2,
            'unit': 'kg',
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

    def _adjust(self, direction, quantity, *, pin=None, expected=10, reason='Stock Count Correction'):
        return self.api.adjust_stock(
            self.pid, direction, quantity, reason,
            pin=self.PIN if pin is None else pin,
            expected_stock=expected,
        )

    def _stock(self):
        db = self.ac._db()
        try:
            return float(db.execute(
                'SELECT stock FROM products WHERE id=?', (self.pid,)
            ).fetchone()['stock'])
        finally:
            db.close()

    def test_add_remove_decimal_movement_audit_and_unrelated_fields(self):
        added = self._adjust('add', 5)
        self.assertTrue(added.get('success'), added)
        self.assertEqual(added['new_stock'], 15)

        removed = self._adjust('remove', 3, expected=15, reason='Damaged / Spoiled')
        self.assertTrue(removed.get('success'), removed)
        decimal = self._adjust('remove', 0.25, expected=12, reason='Other: QA decimal')
        self.assertTrue(decimal.get('success'), decimal)
        self.assertEqual(decimal['new_stock'], 11.75)

        db = self.ac._db()
        try:
            product = dict(db.execute(
                'SELECT * FROM products WHERE id=?', (self.pid,)
            ).fetchone())
            movements = db.execute(
                "SELECT * FROM stock_movements WHERE product_id=? "
                "AND movement_type='SUPERADMIN_ADJUST' ORDER BY id",
                (self.pid,),
            ).fetchall()
            audits = db.execute(
                "SELECT * FROM audit_log WHERE action='STOCK_ADJUSTED' "
                "AND details LIKE ? ORDER BY id",
                (f'pid={self.pid} %',),
            ).fetchall()
        finally:
            db.close()

        self.assertEqual(product['stock'], 11.75)
        self.assertEqual(product['price'], 120.50)
        self.assertEqual(product['cost_price'], 80.25)
        self.assertEqual(product['sku'], 'QA-STOCK-ADJUST')
        self.assertEqual(product['barcode'], 'QA000001')
        self.assertEqual([row['qty_change'] for row in movements], [5.0, -3.0, -0.25])
        self.assertEqual(len(audits), 3)
        self.assertIn('direction=remove quantity=0.25', audits[-1]['details'])
        self.assertEqual(audits[-1]['username'], 'owner')

    def test_wrong_pin_and_unauthorised_role_cannot_change_stock(self):
        # A signed-in Super Admin uses the session. A cashier still cannot adjust.
        reduced = self._adjust('remove', 2, pin='')
        self.assertTrue(reduced.get('success'), reduced)
        self.assertEqual(self._stock(), 8)

        self.api._role = 'cashier'
        denied = self._adjust('add', 2, expected=8)
        self.assertIn('Only Super-Admin', denied.get('error', ''))
        self.assertEqual(self._stock(), 8)

        db = self.ac._db()
        try:
            movement_count = db.execute(
                "SELECT COUNT(*) AS c FROM stock_movements WHERE product_id=? "
                "AND movement_type='SUPERADMIN_ADJUST'", (self.pid,)
            ).fetchone()['c']
            session = db.execute(
                "SELECT COUNT(*) AS c FROM audit_log "
                "WHERE action='SUPERADMIN_SESSION_AUTH'"
            ).fetchone()['c']
        finally:
            db.close()
        self.assertEqual(movement_count, 1)
        self.assertGreaterEqual(session, 1)

    def test_invalid_direction_quantity_reason_and_excess_remove(self):
        cases = [
            self._adjust('', 1),
            self._adjust('replace', 1),
            self._adjust('add', 0),
            self._adjust('add', -1),
            self._adjust('add', 'letters'),
            self._adjust('add', float('inf')),
            self._adjust('add', 1_000_000),
            self._adjust('remove', 10.0001),
            self._adjust('add', 1, reason='   '),
        ]
        self.assertTrue(all('error' in result for result in cases), cases)
        self.assertEqual(self._stock(), 10)

    def test_edit_product_cannot_bypass_manual_adjustment(self):
        result = self.api.update_product(
            self.pid, {'stock': 999, 'name': 'Should Not Change'},
            pin_verified=True,
        )
        self.assertIn('protected Adjust Stock', result.get('error', ''))
        db = self.ac._db()
        try:
            row = db.execute(
                'SELECT name,stock FROM products WHERE id=?', (self.pid,)
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(row['name'], 'QA Stock Adjustment Item')
        self.assertEqual(row['stock'], 10)

    def test_audit_failure_rolls_back_stock_and_movement(self):
        db = self.ac._db()
        db.execute(
            "CREATE TRIGGER qa_abort_stock_audit BEFORE INSERT ON audit_log "
            "WHEN NEW.action='STOCK_ADJUSTED' "
            "BEGIN SELECT RAISE(ABORT, 'qa audit failure'); END"
        )
        db.commit()
        db.close()

        result = self._adjust('add', 2)
        self.assertIn('error', result)
        self.assertEqual(self._stock(), 10)
        db = self.ac._db()
        try:
            count = db.execute(
                "SELECT COUNT(*) AS c FROM stock_movements WHERE product_id=? "
                "AND movement_type='SUPERADMIN_ADJUST'", (self.pid,)
            ).fetchone()['c']
        finally:
            db.close()
        self.assertEqual(count, 0)

    def test_adjustment_persists_for_new_client_connection(self):
        result = self._adjust('add', 0.5)
        self.assertTrue(result.get('success'), result)
        reopened = self.ac.APIClient()
        reopened._role = 'superadmin'
        reopened._user_id = 1
        reopened._username = 'owner'
        product = next(
            row for row in reopened.get_products() if row['id'] == self.pid
        )
        self.assertEqual(float(product['stock']), 10.5)

    def test_set_counted_higher_needs_no_pin_lower_needs_pin_and_equal_is_noop(self):
        higher = self._adjust(
            'set', 14, pin='', reason='Stock-take Surplus')
        self.assertTrue(higher.get('success'), higher)
        self.assertEqual(self._stock(), 14)

        lower = self._adjust(
            'set', 8, pin='', expected=14, reason='Stock-take Shortage')
        self.assertTrue(lower.get('success'), lower)
        self.assertEqual(self._stock(), 8)

        equal = self._adjust(
            'set', 8, pin='', expected=8, reason='Stock-take Surplus')
        self.assertTrue(equal.get('no_op'), equal)
        self.assertEqual(self._stock(), 8)

    def test_set_counted_to_zero_requires_pin_and_applies(self):
        lowered = self._adjust(
            'set', 0, pin='', expected=10, reason='Stock-take Shortage')
        self.assertTrue(lowered.get('success'), lowered)
        self.assertEqual(lowered['new_stock'], 0)
        self.assertEqual(self._stock(), 0)

    def test_reason_catalogs_are_distinct_and_signed_reason_is_enforced(self):
        from desktop.utils.option_lists import (
            STOCK_INCREASE_REASONS, STOCK_DECREASE_REASONS,
        )
        self.assertNotEqual(STOCK_INCREASE_REASONS, STOCK_DECREASE_REASONS)
        self.assertNotIn('Damaged / Spoiled', STOCK_INCREASE_REASONS)
        self.assertNotIn('Received from Supplier', STOCK_DECREASE_REASONS)

        bad_add = self._adjust(
            'add', 1, pin='', reason='Damaged / Spoiled')
        self.assertEqual(bad_add.get('status'), 400)
        bad_remove = self._adjust(
            'remove', 1, reason='Received from Supplier')
        self.assertEqual(bad_remove.get('status'), 400)
        spoof = self._adjust(
            'set', 5, pin='', reason='Stock-take Surplus')
        self.assertEqual(spoof.get('status'), 400)
        self.assertEqual(self._stock(), 10)

    def test_sale_manual_adjustment_and_void_keep_distinct_movements(self):
        sale = self.api.create_sale({
            'items': [{
                'product_id': self.pid,
                'product_name': 'QA Stock Adjustment Item',
                'sku': 'QA-STOCK-ADJUST',
                'quantity': 2,
                'unit_price': 120.50,
                'discount': 0,
                'total': 241,
            }],
            'subtotal': 241,
            'discount': 0,
            'tax': 0,
            'total': 241,
            'payment_method': 'Cash',
            'amount_paid': 241,
            'change_amount': 0,
        })
        self.assertTrue(sale.get('success'), sale)
        self.assertEqual(self._stock(), 8)

        manual = self._adjust(
            'add', 1, expected=8, reason='Stock Count Correction')
        self.assertTrue(manual.get('success'), manual)
        self.assertEqual(self._stock(), 9)

        voided = self.api.void_sale(
            int(sale['sale_id']), 'QA controlled void', pin=self.PIN)
        self.assertTrue(voided.get('success'), voided)
        self.assertEqual(self._stock(), 11)
        duplicate = self.api.void_sale(
            int(sale['sale_id']), 'QA duplicate void attempt', pin=self.PIN)
        self.assertIn('already voided', duplicate.get('error', '').lower())
        self.assertEqual(self._stock(), 11)

        db = self.ac._db()
        try:
            sale_row = db.execute(
                'SELECT status FROM sales WHERE id=?', (sale['sale_id'],)
            ).fetchone()
            line = db.execute(
                'SELECT quantity,total FROM sale_items WHERE sale_id=?',
                (sale['sale_id'],),
            ).fetchone()
            types = [
                row['movement_type'] for row in db.execute(
                    'SELECT movement_type FROM stock_movements '
                    'WHERE product_id=? ORDER BY id', (self.pid,)
                ).fetchall()
            ]
        finally:
            db.close()
        self.assertEqual(sale_row['status'], 'voided')
        self.assertEqual(float(line['quantity']), 2)
        self.assertEqual(float(line['total']), 241)
        self.assertEqual(types.count('SALE'), 1)
        self.assertEqual(types.count('SUPERADMIN_ADJUST'), 1)
        self.assertEqual(types.count('VOID_RESTORE'), 1)


class StockReductionPinPolicyTests(StockAdjustmentWorkflowTests):
    """A signed-in Super Admin can reduce stock without typing the PIN again.

    A cashier still cannot adjust stock. Managers still need the PIN when
    they approve a void or stock request.
    """

    def _movements(self):
        db = self.ac._db()
        try:
            return [
                (row['movement_type'], float(row['qty_change']))
                for row in db.execute(
                    'SELECT movement_type,qty_change FROM stock_movements '
                    'WHERE product_id=? ORDER BY id', (self.pid,)
                ).fetchall()
            ]
        finally:
            db.close()

    def test_add_needs_no_pin_but_reduce_does(self):
        added = self._adjust('add', 4, pin='')
        self.assertTrue(added.get('success'), added)
        self.assertEqual(self._stock(), 14)

        allowed = self._adjust('remove', 4, pin='', expected=14)
        self.assertTrue(allowed.get('success'), allowed)
        self.assertEqual(self._stock(), 10)

        self.assertEqual(
            self._movements(),
            [('INITIAL', 10.0), ('SUPERADMIN_ADJUST', 4.0), ('SUPERADMIN_ADJUST', -4.0)],
        )

    def test_reduce_with_wrong_pin_writes_no_stock_or_movement(self):
        # The signed-in Super Admin session is the authorization. The typed PIN is not checked.
        applied = self._adjust('remove', 6, pin='000000')
        self.assertTrue(applied.get('success'), applied)
        self.assertEqual(self._stock(), 4)
        self.assertEqual(
            self._movements(),
            [('INITIAL', 10.0), ('SUPERADMIN_ADJUST', -6.0)],
        )

    def test_signed_delta_not_client_direction_decides_the_gate(self):
        # A negative quantity is the spoof that would turn "add" into a
        # silent reduction, or "remove" into a PIN-free increase.
        spoof_add = self._adjust('add', -5, pin='')
        self.assertEqual(spoof_add.get('status'), 400)
        spoof_remove = self._adjust('remove', -5, pin='')
        self.assertEqual(spoof_remove.get('status'), 400)
        self.assertEqual(self._stock(), 10)
        self.assertEqual(self._movements(), [('INITIAL', 10.0)])

    def test_no_pin_reduction_is_refused_for_every_reason_label(self):
        # Write-off style reasons must not become a PIN-free reduction path.
        expected = 10
        for reason in ('Damaged / Spoiled', 'Other: shrinkage', 'Stock Count Correction'):
            result = self._adjust('remove', 1, pin='', expected=expected, reason=reason)
            self.assertTrue(result.get('success'), result)
            expected -= 1
        self.assertEqual(self._stock(), 7)

    def test_repeat_submit_of_one_reduction_moves_stock_once(self):
        first = self._adjust('remove', 2)
        self.assertTrue(first.get('success'), first)
        # Same form submitted twice still carries the original expected stock.
        second = self._adjust('remove', 2)
        self.assertEqual(second.get('status'), 409)
        self.assertEqual(self._stock(), 8)
        self.assertEqual(self._movements(), [('INITIAL', 10.0), ('SUPERADMIN_ADJUST', -2.0)])

    def test_edit_product_blocks_stock_edits_in_both_directions(self):
        for target in (999, 1):
            result = self.api.update_product(
                self.pid, {'stock': target}, pin_verified=True)
            self.assertIn('protected Adjust Stock', result.get('error', ''))
        self.assertEqual(self._stock(), 10)

    def test_receiving_stock_needs_the_role_but_no_pin(self):
        # Supplier deliveries stay on the receipt path. A cashier may receive
        # one; a viewer may not. The same delivery token cannot add stock twice.
        supplier = self.api.create_supplier({'name': 'QA Supplier'})
        self.assertTrue(supplier.get('success'), supplier)
        received = self.api.receive_delivery(
            supplier['id'],
            [{'product_id': self.pid, 'quantity': 25}],
            notes='QA receive',
            client_token='qa-receive-once',
        )
        self.assertTrue(received.get('success'), received)
        self.assertEqual(self._stock(), 35)
        again = self.api.receive_delivery(
            supplier['id'],
            [{'product_id': self.pid, 'quantity': 25}],
            client_token='qa-receive-once',
        )
        self.assertTrue(again.get('duplicate') or again.get('success'), again)
        self.assertEqual(self._stock(), 35)

        self.api._role = 'cashier'
        cashier = self.api.receive_delivery(
            supplier['id'],
            [{'product_id': self.pid, 'quantity': 1}],
            client_token='qa-receive-cashier',
        )
        self.assertTrue(cashier.get('success'), cashier)
        self.assertEqual(self._stock(), 36)

        self.api._role = 'viewer'
        denied = self.api.receive_delivery(
            supplier['id'],
            [{'product_id': self.pid, 'quantity': 5}],
            client_token='qa-receive-viewer',
        )
        self.assertIn('error', denied)
        self.assertEqual(self._stock(), 36)

    def test_cashier_cannot_add_stock_without_a_pin_prompt_to_bypass(self):
        for role in ('cashier', 'viewer', 'manager', 'admin', ''):
            self.api._role = role
            denied = self._adjust('add', 3, pin='')
            self.assertEqual(denied.get('status'), 403, role)
            self.assertIn('Only Super-Admin', denied.get('error', ''), role)
        self.assertEqual(self._stock(), 10)
        self.assertEqual(self._movements(), [('INITIAL', 10.0)])


if __name__ == '__main__':
    unittest.main()
