"""HTTP routes must enforce roles and authoritative sale validation."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class BackendSecurityGates(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'http.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch(
                'desktop.utils.api_client.get_db_path',
                return_value=self._db_path,
            ),
        ]
        for item in self._patches:
            item.start()

        import desktop.utils.api_client as ac
        import backend.app as backend

        ac._SCHEMA_READY = False
        self.ac = ac
        self.backend = backend
        self._old_backend_path = backend.DB_PATH
        backend.DB_PATH = self._db_path

        db = ac._db()
        db.execute(
            "INSERT INTO users "
            "(username,password_hash,full_name,role,is_active) "
            "VALUES (?,?,?,?,1)",
            ('cashier_gate', 'x:y', 'Cashier Gate', 'cashier'),
        )
        self.cashier_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO products "
            "(name,sku,price,cost_price,stock,min_stock) VALUES (?,?,?,?,?,?)",
            ('HTTP Widget', 'HTTP-1', 100, 40, 10, 2),
        )
        self.product_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO users "
            "(username,password_hash,full_name,role,is_active,tab_permissions) "
            "VALUES (?,?,?,?,1,?)",
            (
                'manager_gate', 'x:y', 'Manager Gate', 'manager',
                '["dashboard","sales","inventory","reports","debt"]',
            ),
        )
        self.manager_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO customers (name,phone,credit_limit,is_active) "
            "VALUES (?,?,?,1)",
            ('HTTP Customer', '0712345678', 100000),
        )
        self.customer_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('superadmin_pin_hash', 'must-never-leak'),
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('currency_symbol', 'KES'),
        )
        db.execute(
            "INSERT INTO sales "
            "(receipt_number,cashier_id,cashier_name,subtotal,total,status) "
            "VALUES (?,?,?,?,?,'completed')",
            ('OWN-HTTP', self.cashier_id, 'Cashier Gate', 100, 100),
        )
        self.own_sale_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO sales "
            "(receipt_number,cashier_id,cashier_name,subtotal,total,status) "
            "VALUES (?,?,?,?,?,'completed')",
            ('OTHER-HTTP', self.manager_id, 'Manager Gate', 200, 200),
        )
        self.other_sale_id = int(
            db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
        db.close()

        self.token = backend.jwt.encode({
            'user_id': self.cashier_id,
            'username': 'cashier_gate',
            'role': 'cashier',
            'iat': int(time.time()),
            'exp': int(time.time()) + 600,
        }, backend.SECRET_KEY, algorithm='HS256')
        self.client = backend.app.test_client()
        self.headers = {'Authorization': f'Bearer {self.token}'}
        manager_token = backend.jwt.encode({
            'user_id': self.manager_id,
            'username': 'manager_gate',
            'role': 'manager',
            'iat': int(time.time()),
            'exp': int(time.time()) + 600,
        }, backend.SECRET_KEY, algorithm='HS256')
        self.manager_headers = {
            'Authorization': f'Bearer {manager_token}',
        }

    def tearDown(self):
        self.backend.DB_PATH = self._old_backend_path
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def test_cashier_cannot_mutate_catalog_or_sync_queue(self):
        self.assertEqual(self.client.post(
            '/api/products',
            json={'name': 'Unauthorized', 'price': 1},
            headers=self.headers,
        ).status_code, 403)
        self.assertEqual(self.client.delete(
            f'/api/products/{self.product_id}',
            headers=self.headers,
        ).status_code, 403)
        self.assertEqual(self.client.get(
            '/api/sync/pending', headers=self.headers,
        ).status_code, 403)
        self.assertEqual(self.client.post(
            '/api/sync/mark-sent',
            json={'ids': [1]},
            headers=self.headers,
        ).status_code, 403)

    def test_negative_http_sale_is_rejected_without_stock_change(self):
        response = self.client.post('/api/sales', json={
            'items': [{
                'product_id': self.product_id,
                'product_name': 'HTTP Widget',
                'sku': 'HTTP-1',
                'quantity': -5,
                'unit_price': 100,
                'discount': 0,
                'total': -500,
            }],
            'subtotal': -500,
            'total': -500,
            'payment_method': 'Cash',
            'amount_paid': 0,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400, response.get_json())
        db = self.ac._db()
        self.assertEqual(
            float(db.execute(
                "SELECT stock FROM products WHERE id=?",
                (self.product_id,),
            ).fetchone()['stock']),
            10.0,
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 2)
        db.close()

    def test_web_debt_writer_rejects_cashier_and_orphan_invoice(self):
        payload = {
            'customer_id': self.customer_id,
            'total_amount': 50000,
            'amount_paid': 0,
        }
        cashier = self.client.post(
            '/api/debt/invoices', json=payload, headers=self.headers)
        self.assertEqual(cashier.status_code, 403, cashier.get_json())
        manager = self.client.post(
            '/api/debt/invoices', json=payload, headers=self.manager_headers)
        self.assertEqual(manager.status_code, 400, manager.get_json())
        self.assertIn('sale', (manager.get_json() or {}).get('error', '').lower())
        db = self.ac._db()
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM debt_invoices").fetchone()[0], 0)
        db.close()

    def test_settings_response_strips_secrets(self):
        response = self.client.get('/api/settings', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json() or {}
        self.assertEqual(body.get('currency_symbol'), 'KES')
        self.assertNotIn('superadmin_pin_hash', body)

    def test_cashier_summary_is_own_scope_and_reports_stay_denied(self):
        params = '?start=2000-01-01&end=2999-12-31'
        cashier = self.client.get(
            '/api/reports/summary' + params, headers=self.headers)
        self.assertEqual(cashier.status_code, 200, cashier.get_json())
        body = cashier.get_json() or {}
        self.assertEqual(body.get('scope'), 'own')
        # Own sale is 100; the manager's 200 must not appear anywhere.
        self.assertEqual(body['summary']['total_transactions'], 1)
        self.assertAlmostEqual(body['summary']['total_revenue'], 100.0)
        self.assertEqual(
            sum(row['total'] for row in body['by_payment']), 100.0)

        manager = self.client.get(
            '/api/reports/summary' + params, headers=self.manager_headers)
        self.assertEqual(manager.status_code, 200, manager.get_json())
        mbody = manager.get_json() or {}
        self.assertEqual(mbody.get('scope'), 'all')
        self.assertEqual(mbody['summary']['total_transactions'], 2)
        self.assertAlmostEqual(mbody['summary']['total_revenue'], 300.0)

        # The richer report surfaces remain closed to the cashier.
        cashier_html = self.client.get(
            '/api/reports/html', headers=self.headers)
        self.assertEqual(
            cashier_html.status_code, 403, cashier_html.get_json())
        manager_html = self.client.get(
            '/api/reports/html', headers=self.manager_headers)
        self.assertEqual(manager_html.status_code, 200)

    def test_cashier_sale_history_is_own_account_only(self):
        response = self.client.get(
            '/api/sales?start=2000-01-01&end=2999-12-31',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        receipts = {row['receipt_number'] for row in response.get_json()}
        self.assertEqual(receipts, {'OWN-HTTP'})
        other = self.client.get(
            f'/api/sales/{self.other_sale_id}', headers=self.headers)
        self.assertEqual(other.status_code, 403, other.get_json())


if __name__ == '__main__':
    unittest.main()
