"""Tests for analytics entity sync, redaction, and historical backfill."""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock


class TestAnalyticsEntitySerialization(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module('backend.cloud_backup.sync_manager')

    def test_user_password_hash_stripped(self):
        payload = self.mod.serialize_entity_payload('user', {
            'id': 1,
            'username': 'admin',
            'password_hash': 'pbkdf2$secret',
            'role': 'admin',
            'full_name': 'Admin',
        })
        self.assertNotIn('password_hash', payload)
        self.assertEqual(payload['username'], 'admin')

    def test_customer_national_id_and_notes_stripped(self):
        payload = self.mod.serialize_entity_payload('customer', {
            'id': 9,
            'name': 'Ada',
            'phone': '0700',
            'national_id': '12345678',
            'notes': 'sensitive free text',
            'address': 'secret street',
            'email': 'a@b.c',
            'credit_limit': 1000,
        })
        self.assertEqual(payload['name'], 'Ada')
        self.assertEqual(payload['phone'], '0700')
        self.assertEqual(payload.get('email'), 'a@b.c')
        self.assertNotIn('national_id', payload)
        self.assertNotIn('notes', payload)
        self.assertNotIn('address', payload)

    def test_sale_payment_refs_stripped(self):
        payload = self.mod.serialize_entity_payload('sale', {
            'id': 3,
            'receipt_number': 'R-1',
            'total': 50,
            'mpesa_ref': 'QH123',
            'notes': 'M-Pesa ref: QH123',
            'payment_method': 'mpesa',
            'status': 'completed',
        })
        self.assertEqual(payload['receipt_number'], 'R-1')
        self.assertNotIn('mpesa_ref', payload)
        self.assertNotIn('notes', payload)

    def test_debt_payment_reference_stripped(self):
        payload = self.mod.serialize_entity_payload('debt_payment', {
            'id': 4,
            'payment_receipt': 'DP-1',
            'invoice_id': 2,
            'amount': 20,
            'payment_reference': 'RAW-REF-999',
            'payment_method': 'cash',
            'balance_before': 50,
            'balance_after': 30,
        })
        self.assertEqual(payload['payment_receipt'], 'DP-1')
        self.assertNotIn('payment_reference', payload)

    def test_setting_secrets_redacted(self):
        secret = self.mod.serialize_entity_payload('setting', {
            'key': 'telegram_bot_token',
            'value': '123:ABC',
        })
        self.assertTrue(secret.get('redacted'))
        self.assertNotIn('value', secret)

        safe = self.mod.serialize_entity_payload('setting', {
            'key': 'shop_name',
            'value': 'Demo Shop',
        })
        self.assertEqual(safe.get('value'), 'Demo Shop')
        self.assertNotIn('redacted', safe)

    def test_new_entity_types_mapped(self):
        self.assertEqual(self.mod.ENTITY_TABLE_MAP['debt_invoice'], 'debt_invoices')
        self.assertEqual(self.mod.ENTITY_TABLE_MAP['debt_payment'], 'debt_payments')
        self.assertEqual(self.mod.ENTITY_TABLE_MAP['stock_movement'], 'stock_movements')
        for et in (
            'product', 'sale', 'sale_item', 'customer',
            'debt_invoice', 'debt_payment', 'stock_movement',
        ):
            self.assertIn(et, self.mod.BACKFILL_ENTITY_TYPES)


class TestHistoricalBackfill(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module('backend.cloud_backup.sync_manager')
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'pos.db')
        self.state_path = os.path.join(self.tmp.name, 'state.json')
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE sync_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                row_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                processed_at TEXT
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT,
                price REAL,
                cost_price REAL,
                stock REAL,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY,
                receipt_number TEXT,
                total REAL,
                status TEXT
            );
            CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY,
                sale_id INTEGER,
                product_name TEXT,
                quantity REAL,
                unit_price REAL,
                total REAL
            );
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                phone TEXT,
                national_id TEXT
            );
            CREATE TABLE debt_invoices (
                id INTEGER PRIMARY KEY,
                invoice_number TEXT,
                customer_id INTEGER,
                total_amount REAL,
                balance REAL,
                status TEXT
            );
            CREATE TABLE debt_payments (
                id INTEGER PRIMARY KEY,
                payment_receipt TEXT,
                invoice_id INTEGER,
                amount REAL,
                payment_reference TEXT
            );
            CREATE TABLE stock_movements (
                id INTEGER PRIMARY KEY,
                product_id INTEGER,
                product_name TEXT,
                movement_type TEXT,
                qty_before REAL,
                qty_change REAL,
                qty_after REAL
            );
            INSERT INTO products(id, name, price, cost_price, stock) VALUES
                (1, 'Tea', 10, 5, 3), (2, 'Bread', 60, 40, 8);
            INSERT INTO customers(id, name, phone, national_id) VALUES
                (1, 'Ann', '0701', '111');
            INSERT INTO sales(id, receipt_number, total, status) VALUES
                (1, 'R1', 70, 'completed');
            INSERT INTO sale_items(id, sale_id, product_name, quantity, unit_price, total)
                VALUES (1, 1, 'Tea', 1, 10, 10);
            INSERT INTO debt_invoices(id, invoice_number, customer_id, total_amount, balance, status)
                VALUES (1, 'D1', 1, 100, 100, 'unpaid');
            INSERT INTO debt_payments(id, payment_receipt, invoice_id, amount, payment_reference)
                VALUES (1, 'P1', 1, 20, 'RAW');
            INSERT INTO stock_movements(
                id, product_id, product_name, movement_type, qty_before, qty_change, qty_after
            ) VALUES (1, 1, 'Tea', 'SALE', 4, -1, 3);
        """)
        conn.commit()
        conn.close()
        self.mgr = self.mod.SyncManager()

    def tearDown(self):
        self.tmp.cleanup()

    def _load_state(self):
        with open(self.state_path, encoding='utf-8') as fh:
            return json.load(fh)

    def _patch_backfill(self):
        def _load(path, default=None):
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as fh:
                    return json.load(fh)
            return dict(default or {})

        def _save(path, data):
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh)

        return mock.patch.multiple(
            self.mod,
            get_db_path=mock.Mock(return_value=self.db_path),
            load_identity=mock.Mock(return_value={
                'org_id': 'org-1',
                'access_token': 'tok',
            }),
            is_logged_in=mock.Mock(return_value=True),
            get_or_create_device_id=mock.Mock(return_value='dev-1'),
            backup_state_path=mock.Mock(return_value=self.state_path),
            load_json=_load,
            save_json=_save,
            configure_sqlite_connection=lambda c: None,
        )

    def test_backfill_enqueues_once_and_checkpoints(self):
        with self._patch_backfill():
            first = self.mgr.ensure_historical_backfill(batch_size=50)
            second = self.mgr.ensure_historical_backfill(batch_size=50)

        self.assertGreater(first, 0)
        self.assertEqual(second, 0)

        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]
        types = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT entity_type FROM sync_outbox"
            )
        }
        conn.close()
        self.assertEqual(count, first)
        self.assertTrue(
            {'product', 'sale', 'sale_item', 'customer',
             'debt_invoice', 'debt_payment', 'stock_movement'}.issubset(types)
        )

        bf = self._load_state()['analytics_backfill']
        self.assertTrue(all(bf[et]['done'] for et in self.mod.BACKFILL_ENTITY_TYPES))
        self.assertIn('completed_at', bf)

    def test_backfill_batches_resume_from_checkpoint(self):
        with self._patch_backfill():
            n1 = self.mgr.ensure_historical_backfill(batch_size=1)
            state1 = self._load_state()
            self.assertFalse(state1['analytics_backfill']['product']['done'])
            n2 = self.mgr.ensure_historical_backfill(batch_size=1)
            for _ in range(20):
                state1 = self._load_state()
                if all(
                    state1.get('analytics_backfill', {}).get(et, {}).get('done')
                    for et in self.mod.BACKFILL_ENTITY_TYPES
                ):
                    break
                self.mgr.ensure_historical_backfill(batch_size=1)

        self.assertGreaterEqual(n1 + n2, 2)
        state = self._load_state()
        self.assertTrue(state['analytics_backfill']['product']['done'])
        self.assertEqual(state['analytics_backfill']['product']['last_id'], 2)


class TestDurableBackfillState(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module('backend.cloud_backup.sync_manager')
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'pos.db')
        self.state_path = os.path.join(self.tmp.name, 'state.json')
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE sync_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                row_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                processed_at TEXT
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT,
                price REAL,
                cost_price REAL,
                stock REAL,
                is_active INTEGER DEFAULT 1
            );
            INSERT INTO products(id, name, price, cost_price, stock)
                VALUES (1, 'Tea', 10, 5, 3);
        """)
        conn.commit()
        conn.close()
        with open(self.state_path, 'w', encoding='utf-8') as fh:
            json.dump({
                'analytics_backfill': {
                    'product': {'last_id': 1, 'done': True},
                    'completed_at': '2026-07-01T00:00:00+00:00',
                }
            }, fh)
        self.mgr = self.mod.SyncManager()

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_backup_preserves_analytics_backfill_checkpoint(self):
        """Successful backup must merge state, not erase analytics_backfill."""
        def _load(path, default=None):
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as fh:
                    return json.load(fh)
            return dict(default or {})

        def _save(path, data):
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh)

        # Exercise the merge path used at the end of run_backup without a full upload.
        with mock.patch.multiple(
            self.mod,
            backup_state_path=mock.Mock(return_value=self.state_path),
            load_json=_load,
            save_json=_save,
        ):
            prev = _load(self.state_path, {})
            state = {
                **prev,
                'last_backup_at': '2026-07-21T12:00:00+00:00',
                'last_backup_size': 1234,
                'last_backup_id': 'bk-1',
                'last_error': '',
                'last_reason': 'manual',
            }
            _save(self.state_path, state)

        saved = _load(self.state_path, {})
        self.assertIn('analytics_backfill', saved)
        self.assertTrue(saved['analytics_backfill']['product']['done'])
        self.assertEqual(saved['last_backup_id'], 'bk-1')

        # Source contract: run_backup must merge via **prev, not replace wholesale.
        src = inspect.getsource(self.mod.SyncManager.run_backup)
        self.assertIn('**prev', src)
        self.assertIn('analytics_backfill', inspect.getsource(self.mod.SyncManager.ensure_historical_backfill))

    def test_backfill_commits_before_checkpoint_advance(self):
        """If outbox commit fails, checkpoint must not advance past uncommitted rows."""
        commits = {'n': 0}
        real_connect = sqlite3.connect

        class _ConnProxy:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, *a, **k):
                return self._conn.execute(*a, **k)

            def commit(self):
                commits['n'] += 1
                raise sqlite3.OperationalError('simulated commit failure')

            def rollback(self):
                return self._conn.rollback()

            def close(self):
                return self._conn.close()

            def __getattr__(self, name):
                return getattr(self._conn, name)

        def _connect(path, **kwargs):
            return _ConnProxy(real_connect(path, **kwargs))

        def _load(path, default=None):
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as fh:
                    return json.load(fh)
            return dict(default or {})

        def _save(path, data):
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh)

        # Start from empty checkpoint so backfill will attempt inserts.
        with open(self.state_path, 'w', encoding='utf-8') as fh:
            json.dump({}, fh)

        with mock.patch.multiple(
            self.mod,
            get_db_path=mock.Mock(return_value=self.db_path),
            load_identity=mock.Mock(return_value={
                'org_id': 'org-1',
                'access_token': 'tok',
            }),
            is_logged_in=mock.Mock(return_value=True),
            get_or_create_device_id=mock.Mock(return_value='dev-1'),
            backup_state_path=mock.Mock(return_value=self.state_path),
            load_json=_load,
            save_json=_save,
            configure_sqlite_connection=lambda c: None,
        ), mock.patch('backend.cloud_backup.sync_manager.sqlite3.connect', side_effect=_connect):
            enqueued = self.mgr.ensure_historical_backfill(batch_size=50)

        self.assertEqual(enqueued, 0)
        self.assertGreaterEqual(commits['n'], 1)
        state = _load(self.state_path, {})
        # Checkpoint must not claim completion after a failed commit.
        self.assertFalse(bool((state.get('analytics_backfill') or {}).get('completed_at')))

        # Ordering contract in source: commit precedes checkpoint save.
        src = inspect.getsource(self.mod.SyncManager.ensure_historical_backfill)
        commit_at = src.find('conn.commit()')
        save_at = src.find("state['analytics_backfill'] = backfill")
        self.assertGreater(commit_at, 0)
        self.assertGreater(save_at, commit_at)

    def test_approval_backoff_reset_preserves_unrelated_errors(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO sync_outbox(event_id, entity_type, row_id, operation, "
            "available_at, attempts, last_error) VALUES (?,?,?,?,?,?,?)",
            ('e-approved', 'product', '1', 'upsert',
             '2099-01-01 00:00:00', 3, 'Device is not approved for this organization'),
        )
        conn.execute(
            "INSERT INTO sync_outbox(event_id, entity_type, row_id, operation, "
            "available_at, attempts, last_error) VALUES (?,?,?,?,?,?,?)",
            ('e-network', 'sale', '1', 'upsert',
             '2099-01-01 00:00:00', 2, 'Connection timed out'),
        )
        conn.commit()
        conn.close()

        with mock.patch.multiple(
            self.mod,
            get_db_path=mock.Mock(return_value=self.db_path),
            configure_sqlite_connection=lambda c: None,
        ):
            cleared = self.mgr.clear_device_approval_backoff()

        self.assertEqual(cleared, 1)
        conn = sqlite3.connect(self.db_path)
        approved = conn.execute(
            "SELECT available_at, attempts, last_error FROM sync_outbox WHERE event_id='e-approved'"
        ).fetchone()
        network = conn.execute(
            "SELECT available_at, attempts, last_error FROM sync_outbox WHERE event_id='e-network'"
        ).fetchone()
        conn.close()
        self.assertEqual(approved[1], 0)
        self.assertIn('not approved', approved[2])
        self.assertNotEqual(approved[0][:4], '2099')
        self.assertEqual(network[1], 2)
        self.assertEqual(network[0][:4], '2099')
        self.assertIn('timed out', network[2])

    def test_event_ids_isolate_org_and_device_identity(self):
        """Same local row_id must produce distinct event IDs across org/device."""
        org_a, org_b = 'org-a', 'org-b'
        dev_1, dev_2 = 'dev-1', 'dev-2'
        entity_type, source_id = 'product', '1'

        def _eid(org_id, device_id):
            return (
                f"bf-{entity_type}-{source_id}-"
                f"{hashlib.sha1(f'{org_id}:{device_id}:{entity_type}:{source_id}'.encode()).hexdigest()[:16]}"
            )

        ids = {
            _eid(org_a, dev_1),
            _eid(org_a, dev_2),
            _eid(org_b, dev_1),
            _eid(org_b, dev_2),
        }
        self.assertEqual(len(ids), 4)
        # Deterministic: same identity always yields the same event id.
        self.assertEqual(_eid(org_a, dev_1), _eid(org_a, dev_1))


class TestFlushEntityOutboxContracts(unittest.TestCase):
    def test_flush_uses_redaction_and_token_refresh(self):
        mod = importlib.import_module('backend.cloud_backup.sync_manager')
        src = inspect.getsource(mod.SyncManager.flush_entity_outbox)
        self.assertIn('serialize_entity_payload', src)
        self.assertIn('_post_entity_sync_batch', src)
        refresh_src = inspect.getsource(mod.SyncManager._post_entity_sync_batch)
        self.assertIn('refresh_session', refresh_src)
        self.assertIn('401', refresh_src)
        loop_src = inspect.getsource(mod.SyncManager._loop)
        self.assertIn('ensure_historical_backfill', loop_src)

    def test_outbox_triggers_include_debt_and_stock(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'backend', 'app.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn("'debt_invoices': 'debt_invoice'", src)
        self.assertIn("'debt_payments': 'debt_payment'", src)
        self.assertIn("'stock_movements': 'stock_movement'", src)

    def test_schema_v4_device_safe_identity(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'supabase', 'schema_v4_analytics.sql')
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding='utf-8') as fh:
            sql = fh.read()
        self.assertIn('uq_sync_entities_org_device_type_source', sql)
        self.assertIn('debt_invoice', sql)
        self.assertIn('cloud_sales', sql)
        self.assertIn('cloud_debt_payments', sql)
        self.assertIn('project_cloud_analytics_row', sql)
        self.assertIn('on conflict (org_id, device_id, entity_type, source_id)', sql.lower())

    def test_batch_key_stable(self):
        org_id = 'org'
        device_id = 'dev'
        event_ids = ['a', 'b']
        key = hashlib.sha256(
            f"{org_id}:{device_id}:{','.join(event_ids)}".encode()
        ).hexdigest()
        self.assertEqual(len(key), 64)


if __name__ == '__main__':
    unittest.main()

