"""Atomic supplier GRN receiving, permissions, history and retry safety."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


class SupplierPurchaseBatchTests(unittest.TestCase):
    PIN = '482610'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, 'supplier-batch.db')
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
        self.p1 = self._product('Dairy Feed', 'FEED-1', 220, 170)
        self.p2 = self._product('Mineral Mix', 'MIN-1', 150, 90)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self.ac._SCHEMA_READY_PATH = None
        self.tmp.cleanup()

    def _product(self, name, sku, price, cost):
        result = self.api.create_product({
            'name': name, 'sku': sku, 'price': price, 'cost_price': cost,
            'stock': 0, 'unit': 'pcs',
        })
        self.assertTrue(result.get('success'), result)
        return int(result['id'])

    def _supplier_as_cashier(self):
        self.api._role = 'cashier'
        result = self.api.create_supplier({
            'name': 'Acme Animal Supplies', 'phone': '0700111222',
        })
        self.assertTrue(result.get('success'), result)
        return int(result['id'])

    def _delivery(self, supplier_id, txn='delivery-once', second_pid=None):
        return {
            'client_txn_id': txn,
            'supplier_id': supplier_id,
            'reference': 'INV-ACME-441',
            'delivery_date': '2026-09-17',
            'notes': 'morning truck',
            'items': [
                {'product_id': self.p1, 'quantity': 10, 'unit_cost': 180},
                {'product_id': second_pid or self.p2, 'quantity': 4, 'unit_cost': 95},
            ],
        }

    def test_cashier_receives_many_products_as_one_supplier_grn(self):
        supplier_id = self._supplier_as_cashier()
        result = self.api.receive_purchase(self._delivery(supplier_id))
        self.assertTrue(result.get('success'), result)
        self.assertEqual(result['line_count'], 2)
        self.assertEqual(result['purchase_number'], 'GRN-20260917-0001')
        self.assertEqual(result['total'], 2180)

        db = self.ac._db()
        purchase_count = db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0]
        item_count = db.execute('SELECT COUNT(*) FROM purchase_items').fetchone()[0]
        movements = db.execute(
            "SELECT reference, movement_type FROM stock_movements ORDER BY id"
        ).fetchall()
        products = db.execute(
            'SELECT id,stock,cost_price,supplier_id FROM products ORDER BY id'
        ).fetchall()
        audit = db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='RECEIVE_PURCHASE'"
        ).fetchone()[0]
        journal = db.execute(
            "SELECT id FROM journal_entries WHERE source_module='purchase' "
            "AND source_id=? AND entry_type='purchase'",
            (str(result['purchase_id']),),
        ).fetchone()
        journal_lines = db.execute(
            "SELECT account_code,debit,credit FROM journal_lines "
            "WHERE journal_id=? ORDER BY line_no",
            (journal['id'],),
        ).fetchall()
        db.close()
        self.assertEqual(purchase_count, 1)
        self.assertEqual(item_count, 2)
        self.assertEqual(
            [(r['reference'], r['movement_type']) for r in movements],
            [('GRN-20260917-0001', 'PURCHASE'), ('GRN-20260917-0001', 'PURCHASE')],
        )
        self.assertEqual(
            [(float(r['stock']), float(r['cost_price']), int(r['supplier_id'])) for r in products],
            [(10.0, 180.0, supplier_id), (4.0, 95.0, supplier_id)],
        )
        self.assertEqual(audit, 1)
        self.assertEqual(
            [(r['account_code'], float(r['debit']), float(r['credit'])) for r in journal_lines],
            [('1200', 2180.0, 0.0), ('2000', 0.0, 2180.0)],
        )

        history = self.api.get_purchases(supplier_id=supplier_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(int(history[0]['line_count']), 2)
        detail = self.api.get_purchase(int(result['purchase_id']))
        self.assertEqual(len(detail['purchase']['items']), 2)

    def test_cashier_can_register_first_time_product_with_buy_and_sell_price(self):
        self.api._role = 'cashier'
        created = self.api.create_product({
            'name': 'First Time Product', 'sku': 'FIRST-1',
            'price': 250, 'cost_price': 180, 'stock': 12,
        })
        self.assertTrue(created.get('success'), created)
        self.assertEqual(created.get('stock'), 0)
        db = self.ac._db()
        row = db.execute(
            'SELECT price,cost_price,stock FROM products WHERE id=?',
            (created['id'],),
        ).fetchone()
        db.close()
        self.assertEqual(
            (float(row['price']), float(row['cost_price']), float(row['stock'])),
            (250.0, 180.0, 0.0),
        )
        missing_cost = self.api.create_product({
            'name': 'Incomplete Product', 'price': 100, 'cost_price': 0,
        })
        self.assertIn('Buying price', missing_cost.get('error', ''))

    def test_client_transaction_retry_never_receives_twice(self):
        supplier_id = self._supplier_as_cashier()
        first = self.api.receive_purchase(self._delivery(supplier_id))
        second = self.api.receive_purchase(self._delivery(supplier_id))
        self.assertTrue(first.get('success'), first)
        self.assertTrue(second.get('idempotent'), second)
        db = self.ac._db()
        counts = (
            db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0],
            db.execute('SELECT COUNT(*) FROM purchase_items').fetchone()[0],
            db.execute('SELECT COUNT(*) FROM stock_movements').fetchone()[0],
        )
        stocks = [r[0] for r in db.execute('SELECT stock FROM products ORDER BY id')]
        db.close()
        self.assertEqual(counts, (1, 2, 2))
        self.assertEqual(stocks, [10.0, 4.0])

    def test_invalid_second_line_rolls_back_entire_delivery(self):
        supplier_id = self._supplier_as_cashier()
        result = self.api.receive_purchase(
            self._delivery(supplier_id, txn='rollback', second_pid=999999)
        )
        self.assertEqual(result.get('status'), 404)
        db = self.ac._db()
        self.assertEqual(db.execute('SELECT COUNT(*) FROM purchases').fetchone()[0], 0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM purchase_items').fetchone()[0], 0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM stock_movements').fetchone()[0], 0)
        self.assertEqual(
            [r[0] for r in db.execute('SELECT stock FROM products ORDER BY id')],
            [0.0, 0.0],
        )
        db.close()

    def test_viewer_cannot_register_supplier_or_receive(self):
        self.api._role = 'viewer'
        denied_supplier = self.api.create_supplier({'name': 'Denied'})
        denied_receive = self.api.receive_purchase({
            'supplier_id': 1,
            'items': [{'product_id': self.p1, 'quantity': 1, 'unit_cost': 10}],
        })
        self.assertEqual(denied_supplier.get('status'), 403)
        self.assertEqual(denied_receive.get('status'), 403)

    def test_only_admin_or_owner_can_adjust_and_pin_is_always_required(self):
        for role in ('cashier', 'manager', 'viewer'):
            self.api._role = role
            denied = self.api.adjust_stock(
                self.p1, 'add', 1, 'count correction',
                pin=self.PIN, expected_stock=0,
            )
            self.assertEqual(denied.get('status'), 403, (role, denied))
        self.api._role = 'admin'
        no_pin = self.api.adjust_stock(
            self.p1, 'add', 1, 'count correction', pin='', expected_stock=0,
        )
        self.assertEqual(no_pin.get('status'), 403)
        allowed = self.api.adjust_stock(
            self.p1, 'add', 1, 'count correction',
            pin=self.PIN, expected_stock=0,
        )
        self.assertTrue(allowed.get('success'), allowed)

    def test_inventory_failures_read_as_human_guidance_not_bug_output(self):
        """A shop user must never be shown exception text, SQL or internal ids."""
        supplier_id = self._supplier_as_cashier()
        jargon = (
            'traceback', 'sqlite', 'integrityerror', 'valueerror', 'typeerror',
            'exception', 'nonetype', 'constraint', 'errno', 'status 500',
            'insert into', 'select *', 'where id=', 'unique(', '#',
        )
        failures = [
            self.api.receive_purchase({'supplier_id': 0, 'items': []}),
            self.api.receive_purchase({'supplier_id': supplier_id, 'items': []}),
            self.api.receive_purchase({
                'supplier_id': supplier_id,
                'items': [{'product_id': self.p1, 'quantity': 0, 'unit_cost': 10}],
            }),
            self.api.receive_purchase({
                'supplier_id': supplier_id,
                'items': [
                    {'product_id': self.p1, 'quantity': 1, 'unit_cost': 10},
                    {'product_id': self.p1, 'quantity': 2, 'unit_cost': 10},
                ],
            }),
            # Deleted/unknown product on a line must name the line, not the row id.
            self.api.receive_purchase({
                'supplier_id': supplier_id,
                'items': [
                    {'product_id': self.p1, 'quantity': 1, 'unit_cost': 10},
                    {'product_id': 987654, 'quantity': 1, 'unit_cost': 10},
                ],
            }),
            self.api.receive_purchase({
                'supplier_id': supplier_id,
                'delivery_date': 'yesterday',
                'items': [{'product_id': self.p1, 'quantity': 1, 'unit_cost': 10}],
            }),
            self.api.create_product({'name': '', 'price': 10, 'cost_price': 5}),
            self.api.create_product({'name': 'No Cost', 'price': 10, 'cost_price': 0}),
            self.api.adjust_stock(self.p1, 'sideways', 1, 'correction', pin=self.PIN),
            self.api.adjust_stock(self.p1, 'remove', 99999, 'damage', pin=self.PIN),
            self.api.adjust_stock(self.p1, 'add', 1, '', pin=self.PIN),
            self.api.receive_stock(self.p1, 0),
            self.api.receive_stock(987654, 5),
            self.api.create_supplier({'name': ''}),
        ]
        for result in failures:
            message = str((result or {}).get('error') or '')
            self.assertTrue(message, result)
            self.assertRegex(message, r'^[A-Z]', message)
            self.assertNotIn('  ', message)
            for token in jargon:
                self.assertNotIn(token, message.lower(), message)

        line_error = self.api.receive_purchase({
            'supplier_id': supplier_id,
            'items': [
                {'product_id': self.p1, 'quantity': 1, 'unit_cost': 10},
                {'product_id': 987654, 'quantity': 1, 'unit_cost': 10},
            ],
        })
        self.assertIn('line 2', line_error['error'])
        self.assertIn('Nothing was received', line_error['error'])

    def test_web_and_cloud_contract_expose_grouped_supplier_history(self):
        root = Path(__file__).resolve().parents[1]
        ui = (
            root / 'web' / 'dashboard-ui' / 'src' / 'components'
            / 'supplier-deliveries.tsx'
        ).read_text(encoding='utf-8')
        routes = (root / 'web' / 'web_routes.py').read_text(encoding='utf-8')
        self.assertIn('Receive all as one', ui)
        self.assertIn('Register supplier', ui)
        self.assertIn('Delivery total', ui)
        self.assertIn("client_txn_id: clientTxnId", ui)
        self.assertIn('Register first-time product', ui)
        self.assertIn('you never type it twice', ui)
        self.assertIn('onProductCreated', ui)
        self.assertNotIn('onAddProduct', ui)
        self.assertIn("@web.route('/api/purchases', methods=['GET', 'POST'])", routes)
        self.assertIn("@web.route('/api/suppliers', methods=['GET', 'POST'])", routes)
        from backend.cloud_backup.sync_manager import ENTITY_FIELD_ALLOWLIST
        self.assertIn('purchase_number', ENTITY_FIELD_ALLOWLIST['purchase'])
        self.assertIn('qty_before', ENTITY_FIELD_ALLOWLIST['purchase_item'])


if __name__ == '__main__':
    unittest.main()
