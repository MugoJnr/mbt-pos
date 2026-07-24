"""Business day / backdate / copy-sale gates."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SaleBusinessDayTests(unittest.TestCase):
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
        self.api._role = 'manager'
        self.api._user_id = 1
        self.api._username = 'mgr'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ('mgr', 'x:y', 'manager'),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Biz Widget', 'BW1', 100.0, 40.0, 200, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _payload(self, total=100.0, qty=1, **extra):
        data = {
            'items': [{
                'product_id': 1,
                'product_name': 'Biz Widget',
                'sku': 'BW1',
                'quantity': qty,
                'unit_price': float(total) / max(qty, 1),
                'discount': 0,
                'total': float(total),
            }],
            'subtotal': float(total),
            'discount': 0,
            'tax': 0,
            'total': float(total),
            'payment_method': 'Cash',
            'amount_paid': float(total),
            'change_amount': 0,
        }
        data.update(extra)
        return data

    def test_default_sale_uses_today(self):
        from desktop.utils.shop_time import shop_today
        res = self.api.create_sale(self._payload(50.0))
        self.assertTrue(res.get('success'), res)
        sale = self.api.get_sale(int(res['sale_id']))
        self.assertEqual(sale.get('sale_date'), shop_today().isoformat())
        listed = self.api.get_sales(shop_today().isoformat(), shop_today().isoformat())
        self.assertTrue(any(int(s['id']) == int(res['sale_id']) for s in listed))

    def test_manager_can_backdate(self):
        from desktop.utils.shop_time import shop_today
        yesterday = (shop_today() - timedelta(days=1)).isoformat()
        res = self.api.create_sale(self._payload(75.0, sale_date=yesterday))
        self.assertTrue(res.get('success'), res)
        self.assertEqual(res.get('sale_date'), yesterday)
        sale = self.api.get_sale(int(res['sale_id']))
        self.assertEqual(sale.get('sale_date'), yesterday)
        self.assertTrue(str(sale.get('created_at') or '').startswith(yesterday))
        # Reports / day filter
        day_sales = self.api.get_sales(yesterday, yesterday)
        self.assertTrue(any(int(s['id']) == int(res['sale_id']) for s in day_sales))
        summary = (self.api.get_report_summary(yesterday, yesterday) or {}).get('summary') or {}
        self.assertAlmostEqual(float(summary.get('total_revenue') or 0), 75.0, places=2)
        # Audit
        db = self.ac._db()
        try:
            actions = {
                r['action'] for r in db.execute(
                    "SELECT action FROM audit_log WHERE action IN "
                    "('BACKDATE_SALE','CREATE_SALE')"
                ).fetchall()
            }
        finally:
            db.close()
        self.assertIn('BACKDATE_SALE', actions)
        self.assertIn('CREATE_SALE', actions)

    def test_cashier_cannot_backdate(self):
        from desktop.utils.shop_time import shop_today
        self.api._role = 'cashier'
        self.api._username = 'cash'
        yesterday = (shop_today() - timedelta(days=1)).isoformat()
        res = self.api.create_sale(self._payload(40.0, sale_date=yesterday))
        self.assertFalse(res.get('success'))
        self.assertIn('Manager', res.get('error') or '')
        db = self.ac._db()
        try:
            denied = db.execute(
                "SELECT COUNT(*) AS n FROM audit_log WHERE action='BUSINESS_DAY_DENIED'"
            ).fetchone()['n']
        finally:
            db.close()
        self.assertGreaterEqual(int(denied), 1)

    def test_future_date_rejected(self):
        from desktop.utils.shop_time import shop_today
        future = (shop_today() + timedelta(days=2)).isoformat()
        res = self.api.create_sale(self._payload(10.0, sale_date=future))
        self.assertFalse(res.get('success'))
        self.assertIn('future', (res.get('error') or '').lower())

    def test_copy_lines_shape_and_merge(self):
        """Copy helpers produce cart-ready lines (dialog logic mirror)."""
        from desktop.utils.shop_time import shop_today
        yesterday = (shop_today() - timedelta(days=1)).isoformat()
        a = self.api.create_sale(self._payload(100.0, qty=2, sale_date=yesterday))
        b = self.api.create_sale(self._payload(50.0, qty=1, sale_date=yesterday))
        self.assertTrue(a.get('success') and b.get('success'), (a, b))
        sale_a = self.api.get_sale(int(a['sale_id']))
        items = []
        for it in sale_a.get('items') or []:
            items.append({
                'product_id': it.get('product_id'),
                'product_name': it.get('product_name'),
                'sku': it.get('sku') or '',
                'quantity': float(it.get('quantity') or 0),
                'unit_price': float(it.get('unit_price') or 0),
                'discount': float(it.get('discount') or 0),
                'total': float(it.get('total') or 0),
            })
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['quantity'], 2.0)
        # Day merge: two sales of same product → combined qty
        day_items = []
        for sid in (a['sale_id'], b['sale_id']):
            sale = self.api.get_sale(int(sid))
            for it in sale.get('items') or []:
                day_items.append({
                    'product_id': it.get('product_id'),
                    'unit_price': float(it.get('unit_price') or 0),
                    'quantity': float(it.get('quantity') or 0),
                    'discount': float(it.get('discount') or 0),
                    'total': float(it.get('total') or 0),
                    'product_name': it.get('product_name'),
                    'sku': it.get('sku') or '',
                })
        merged = {}
        for it in day_items:
            key = (it.get('product_id'), round(float(it.get('unit_price') or 0), 4))
            if key not in merged:
                merged[key] = dict(it)
            else:
                m = merged[key]
                m['quantity'] = round(float(m['quantity']) + float(it['quantity']), 2)
                m['total'] = round(float(m['total']) + float(it['total']), 2)
        self.assertEqual(len(merged), 1)
        only = list(merged.values())[0]
        self.assertEqual(only['quantity'], 3.0)
        self.assertAlmostEqual(only['total'], 150.0, places=2)

    def test_permission_matrix_business_day(self):
        from desktop.utils.security import can_set_business_day, has_permission
        from roles import ROLE_CASHIER, ROLE_MANAGER, ROLE_ADMIN, ROLE_SUPERADMIN, ROLE_VIEWER

        def u(role):
            return {'user': {'role': role}}

        self.assertFalse(can_set_business_day(u(ROLE_CASHIER)))
        self.assertFalse(can_set_business_day(u(ROLE_VIEWER)))
        self.assertTrue(can_set_business_day(u(ROLE_MANAGER)))
        self.assertTrue(can_set_business_day(u(ROLE_ADMIN)))
        self.assertTrue(can_set_business_day(u(ROLE_SUPERADMIN)))
        self.assertTrue(has_permission(u(ROLE_MANAGER), 'sales.business_day'))


if __name__ == '__main__':
    unittest.main()
