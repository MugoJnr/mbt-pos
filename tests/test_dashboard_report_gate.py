"""D01/D07 + R01/R03: dashboard/report KPIs reflect create_sale + date filters."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DashboardReportGate(unittest.TestCase):
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
            ('Dash Widget', 'DW1', 100.0, 40.0, 50, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _sale(self, total=100.0, qty=1):
        return self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Dash Widget',
                'sku': 'DW1',
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
        })

    def _sale_day(self, sale_id: int) -> str:
        db = self.ac._db()
        try:
            return db.execute(
                "SELECT date(created_at) AS d FROM sales WHERE id=?", (sale_id,)
            ).fetchone()['d']
        finally:
            db.close()

    def test_d01_kpi_matches_sale_revenue(self):
        created = self._sale(250.0)
        self.assertTrue(created.get('success'), created)
        sale_day = self._sale_day(int(created['sale_id']))

        # Revenue before this sale on that calendar day (only this sale exists)
        after = (self.api.get_report_summary(sale_day, sale_day) or {}).get('summary') or {}
        self.assertAlmostEqual(float(after.get('total_revenue') or 0), 250.0, places=2)
        self.assertAlmostEqual(float(after.get('collected_revenue') or 0), 250.0, places=2)
        self.assertEqual(int(after.get('total_transactions') or 0), 1)

    def test_d07_period_filter_changes_range(self):
        created = self._sale(175.0)
        self.assertTrue(created.get('success'), created)
        sale_id = int(created['sale_id'])
        sale_day = date.fromisoformat(self._sale_day(sale_id))
        other_day = sale_day - timedelta(days=1)

        # Move sale to other_day so ranges diverge cleanly
        db = self.ac._db()
        db.execute(
            "UPDATE sales SET created_at=? WHERE id=?",
            (other_day.isoformat() + 'T12:00:00', sale_id),
        )
        db.commit()
        db.close()

        day_s = (self.api.get_report_summary(
            str(sale_day), str(sale_day)) or {}).get('summary') or {}
        other_s = (self.api.get_report_summary(
            str(other_day), str(other_day)) or {}).get('summary') or {}
        span_s = (self.api.get_report_summary(
            str(other_day), str(sale_day)) or {}).get('summary') or {}

        self.assertAlmostEqual(float(other_s.get('total_revenue') or 0), 175.0, places=2)
        self.assertAlmostEqual(float(day_s.get('total_revenue') or 0), 0.0, places=2)
        self.assertAlmostEqual(float(span_s.get('total_revenue') or 0), 175.0, places=2)
        self.assertNotEqual(
            float(day_s.get('total_revenue') or 0),
            float(other_s.get('total_revenue') or 0),
        )

    def test_r01_r03_report_summary_date_integrity(self):
        created = self._sale(88.0)
        self.assertTrue(created.get('success'), created)
        sale_day = date.fromisoformat(self._sale_day(int(created['sale_id'])))
        far = sale_day - timedelta(days=30)

        empty = (self.api.get_report_summary(
            str(far), str(far)) or {}).get('summary') or {}
        self.assertEqual(float(empty.get('total_revenue') or 0), 0.0)
        self.assertEqual(int(empty.get('total_transactions') or 0), 0)

        hit = (self.api.get_report_summary(
            str(sale_day), str(sale_day)) or {}).get('summary') or {}
        self.assertAlmostEqual(float(hit.get('total_revenue') or 0), 88.0, places=2)
        self.assertEqual(int(hit.get('total_transactions') or 0), 1)
        self.assertAlmostEqual(float(hit.get('collected_revenue') or 0), 88.0, places=2)


if __name__ == '__main__':
    unittest.main()
