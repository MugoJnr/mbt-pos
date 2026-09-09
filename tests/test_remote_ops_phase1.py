"""Phase 1 Remote Ops — command handlers, allowlist, unknown rejection."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT UNIQUE,
            category TEXT,
            price REAL NOT NULL DEFAULT 0,
            cost_price REAL DEFAULT 0,
            stock REAL DEFAULT 0,
            min_stock INTEGER DEFAULT 5,
            unit TEXT DEFAULT 'pcs',
            barcode TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'cashier',
            full_name TEXT,
            email TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            movement_type TEXT NOT NULL,
            qty_before REAL NOT NULL,
            qty_change REAL NOT NULL,
            qty_after REAL NOT NULL,
            reference TEXT,
            reason TEXT,
            user_id INTEGER,
            username TEXT,
            device_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            module TEXT,
            details TEXT,
            ip_address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()


class RemoteOpsPhase1Handlers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, 'shop.db')
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        _schema(conn)
        conn.execute(
            "INSERT INTO products (name, price, cost_price, stock, barcode) "
            "VALUES ('Widget', 100, 40, 10, 'W1')"
        )
        conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active) "
            "VALUES ('cashier1', 'hash', 'cashier', 1)"
        )
        conn.commit()
        conn.close()
        from backend.cloud.command_center import CommandCenter
        self.cc = CommandCenter(db_path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_product_price_and_cost(self):
        ok, msg, detail = self.cc.execute_local('update_product', {
            'product_id': 1,
            'fields': {'price': 150, 'cost_price': 55},
        })
        self.assertTrue(ok, msg)
        self.assertEqual(detail['fields'], ['cost_price', 'price'])
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT price, cost_price FROM products WHERE id=1'
        ).fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE action='REMOTE_UPDATE_PRODUCT'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 150)
        self.assertEqual(row[1], 55)
        self.assertIsNotNone(audit)

    def test_adjust_stock_signed_quantity(self):
        ok, msg, detail = self.cc.execute_local('adjust_stock', {
            'product_id': 1,
            'quantity': -3,
            'reason': 'Damaged / Spoiled',
            'notes': 'shelf check',
        })
        self.assertTrue(ok, msg)
        self.assertEqual(detail['new_stock'], 7)
        self.assertEqual(detail['qty_change'], -3)
        conn = sqlite3.connect(self.db_path)
        stock = conn.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]
        mov = conn.execute(
            "SELECT movement_type, qty_change FROM stock_movements"
        ).fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE action='REMOTE_STOCK_ADJUSTED'"
        ).fetchone()
        conn.close()
        self.assertEqual(stock, 7)
        self.assertEqual(mov[0], 'REMOTE_ADJUST')
        self.assertEqual(mov[1], -3)
        self.assertIsNotNone(audit)

    def test_adjust_stock_requires_reason(self):
        ok, msg, _ = self.cc.execute_local('adjust_stock', {
            'product_id': 1,
            'quantity': 2,
        })
        self.assertFalse(ok)
        self.assertIn('reason', msg.lower())

    def test_set_user_active_disable(self):
        ok, msg, detail = self.cc.execute_local('set_user_active', {
            'username': 'cashier1',
            'is_active': False,
        })
        self.assertTrue(ok, msg)
        self.assertFalse(detail['is_active'])
        conn = sqlite3.connect(self.db_path)
        active = conn.execute(
            'SELECT is_active FROM users WHERE username=?', ('cashier1',)
        ).fetchone()[0]
        audit = conn.execute(
            "SELECT action FROM audit_log WHERE action='REMOTE_SET_USER_ACTIVE'"
        ).fetchone()
        conn.close()
        self.assertEqual(active, 0)
        self.assertIsNotNone(audit)

    def test_unknown_command_rejected_on_issue(self):
        with self.assertRaises(ValueError):
            self.cc.issue_command('org', 'dev', 'create_sale', {})

    def test_unknown_handler_execute(self):
        ok, msg, _ = self.cc.execute_local('create_sale', {})
        self.assertFalse(ok)
        self.assertIn('No handler', msg)

    def test_command_allowlist_includes_phase1(self):
        from backend.cloud.command_center import COMMANDS
        for cmd in (
            'update_product', 'adjust_stock', 'set_user_active',
            'reset_user_pin', 'restart_sync', 'update_now',
        ):
            self.assertIn(cmd, COMMANDS)

    def test_update_product_rejects_stock_field(self):
        ok, msg, _ = self.cc.execute_local('update_product', {
            'product_id': 1,
            'stock': 99,
            'fields': {'stock': 99},
        })
        self.assertFalse(ok)
        self.assertIn('adjust_stock', msg)

    def test_restart_services_clear_failure(self):
        ok, msg, detail = self.cc.execute_local(
            'restart_services', {'_command_name': 'restart_services'},
        )
        self.assertFalse(ok)
        self.assertIn('Not implemented', msg)
        self.assertFalse(detail.get('implemented'))

    def test_idempotent_skip_set_includes_ops(self):
        from backend.cloud.command_center import _IDEMPOTENT_SKIP_COMPLETED
        self.assertIn('adjust_stock', _IDEMPOTENT_SKIP_COMPLETED)
        self.assertIn('set_user_active', _IDEMPOTENT_SKIP_COMPLETED)
        self.assertIn('update_product', _IDEMPOTENT_SKIP_COMPLETED)


class RemoteOpsAllowlistRoutes(unittest.TestCase):
    def test_web_routes_have_remote_ops_endpoints(self):
        path = os.path.join(ROOT, 'web', 'web_routes.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("/api/cloud/remote-ops/product", src)
        self.assertIn("/api/cloud/remote-ops/stock", src)
        self.assertIn("/api/cloud/remote-ops/user", src)
        self.assertIn("def cloud_list_commands", src)
        self.assertIn("methods=['GET']", src)

    def test_platform_service_helpers(self):
        from backend.cloud import platform_service as ps
        self.assertTrue(callable(ps.list_remote_commands))
        self.assertTrue(callable(ps.issue_remote_ops_command))


if __name__ == '__main__':
    unittest.main()
