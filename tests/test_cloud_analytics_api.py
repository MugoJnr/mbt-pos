"""Focused tests for Portal cloud analytics API helpers and contracts."""
from __future__ import annotations

import inspect
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from backend.cloud import platform_service as ps


try:
    NAIROBI = ZoneInfo('Africa/Nairobi')
except Exception:
    from datetime import timedelta, timezone as _tz
    NAIROBI = _tz(timedelta(hours=3), name='Africa/Nairobi')


class TestAnalyticsDateBounds(unittest.TestCase):
    def test_single_day_inclusive_nairobi(self):
        start, end, start_iso, end_iso = ps.analytics_day_bounds('2026-07-21', '2026-07-21')
        self.assertEqual(start, '2026-07-21')
        self.assertEqual(end, '2026-07-21')
        start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
        self.assertEqual(start_dt.astimezone(NAIROBI).strftime('%Y-%m-%d %H:%M'), '2026-07-21 00:00')
        self.assertEqual(end_dt.astimezone(NAIROBI).strftime('%Y-%m-%d %H:%M'), '2026-07-22 00:00')
        self.assertLess(start_dt, end_dt)

    def test_range_swaps_inverted_dates(self):
        start, end, start_iso, end_iso = ps.analytics_day_bounds('2026-07-25', '2026-07-21')
        self.assertEqual(start, '2026-07-21')
        self.assertEqual(end, '2026-07-25')
        self.assertLess(start_iso, end_iso)

    def test_invalid_date_raises(self):
        with self.assertRaises(ValueError):
            ps.analytics_day_bounds('21-07-2026', '21-07-2026')


class TestAnalyticsCollectedRevenue(unittest.TestCase):
    def test_unpaid_credit_excluded_from_collected(self):
        sale = {
            'status': 'completed',
            'payment_method': 'credit sale',
            'amount_paid': 0,
            'change_amount': 0,
            'total': 1000,
        }
        self.assertTrue(ps.analytics_is_unpaid_credit(sale))
        self.assertEqual(ps.analytics_sale_collected_amount(sale), 0.0)

    def test_cash_sale_uses_paid_minus_change(self):
        sale = {
            'status': 'completed',
            'payment_method': 'cash',
            'amount_paid': 1050,
            'change_amount': 50,
            'total': 1000,
        }
        self.assertEqual(ps.analytics_sale_collected_amount(sale), 1000.0)

    def test_voided_sale_collects_nothing(self):
        sale = {
            'status': 'voided',
            'payment_method': 'cash',
            'amount_paid': 500,
            'change_amount': 0,
            'total': 500,
        }
        self.assertTrue(ps.analytics_is_void(sale))
        self.assertEqual(ps.analytics_sale_collected_amount(sale), 0.0)


class TestAnalyticsRoleRedaction(unittest.TestCase):
    def test_manager_forbidden_from_cost_and_phone(self):
        row = {
            'invoice_number': 'DI-1',
            'customer_name': 'Ada',
            'customer_phone': '0700',
            'national_id': '12345678',
            'payment_reference': 'MPX',
            'balance': 200,
            'cost_price': 50,
            'gross_profit': 20,
        }
        cleaned = ps.analytics_redact_payload(row, can_see_finance=False, role='manager')
        self.assertNotIn('national_id', cleaned)
        self.assertNotIn('payment_reference', cleaned)
        self.assertNotIn('cost_price', cleaned)
        self.assertNotIn('gross_profit', cleaned)
        self.assertIsNone(cleaned.get('customer_phone'))
        self.assertEqual(cleaned.get('customer_name'), 'Ada')
        self.assertEqual(cleaned.get('balance'), 200)

    def test_owner_keeps_finance_fields_strips_sensitive(self):
        row = {
            'cost_price': 40,
            'gross_profit': 10,
            'national_id': '999',
            'payment_reference': 'REF',
            'customer_phone': '0711',
        }
        cleaned = ps.analytics_redact_payload(row, can_see_finance=True, role='owner')
        self.assertEqual(cleaned.get('cost_price'), 40)
        self.assertEqual(cleaned.get('gross_profit'), 10)
        self.assertEqual(cleaned.get('customer_phone'), '0711')
        self.assertNotIn('national_id', cleaned)
        self.assertNotIn('payment_reference', cleaned)

    def test_cashier_role_denied(self):
        with self.assertRaises(PermissionError):
            ps.analytics_require_role({'role': 'cashier'})
        with self.assertRaises(PermissionError):
            ps.analytics_require_role({'role': 'member'})

    def test_manager_and_owner_allowed(self):
        role, finance = ps.analytics_require_role({'role': 'manager'})
        self.assertEqual(role, 'manager')
        self.assertFalse(finance)
        role, finance = ps.analytics_require_role({'role': 'owner'})
        self.assertTrue(finance)
        role, finance = ps.analytics_require_role({'role': 'platform_admin'})
        self.assertTrue(finance)


class TestAnalyticsPagination(unittest.TestCase):
    def test_page_size_capped_at_100(self):
        page, size = ps.analytics_parse_page({'page': '2', 'page_size': '500'})
        self.assertEqual(page, 2)
        self.assertEqual(size, 100)

    def test_sort_clause_deterministic(self):
        clause = ps.analytics_sort_clause(
            'total', 'desc',
            allowed={'total', 'source_created_at', 'source_id'},
        )
        self.assertIn('order=total.desc', clause)
        self.assertIn('source_id.asc', clause)
        self.assertIn('device_id.asc', clause)


class TestAnalyticsOverviewAggregation(unittest.TestCase):
    def test_overview_separates_gross_collected_and_preserves_voids(self):
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 1000, 'amount_paid': 1000,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T10:00:00+03:00',
            },
            {
                'device_id': 'd1', 'source_id': '2', 'status': 'completed',
                'payment_method': 'credit sale', 'total': 500, 'amount_paid': 0,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T11:00:00+03:00',
            },
            {
                'device_id': 'd1', 'source_id': '3', 'status': 'voided',
                'payment_method': 'cash', 'total': 200, 'amount_paid': 200,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T12:00:00+03:00',
            },
        ]
        payments = [
            {'amount': 150, 'source_created_at': '2026-07-21T15:00:00+03:00', 'source_id': 'p1'},
        ]
        debts = [
            {
                'status': 'pending', 'balance': 500, 'due_date': '2026-07-01',
                'source_id': 'di1',
            },
        ]
        products = [
            {
                'name': 'Milk', 'stock': 2, 'min_stock': 5, 'cost_price': 40,
                'is_active': True, 'source_id': 'pr1',
            },
            {
                'name': 'Bread', 'stock': 0, 'min_stock': 3, 'cost_price': 50,
                'is_active': True, 'source_id': 'pr2',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
            if table == 'cloud_debt_payments':
                return payments
            if table == 'cloud_debt_invoices':
                return debts
            if table == 'cloud_products':
                return products
            if table == 'cloud_sale_items':
                return [
                    {
                        'device_id': 'd1', 'sale_source_id': '1', 'product_name': 'Milk',
                        'category': 'Dairy', 'quantity': 2, 'total': 1000,
                        'unit_cost': 40, 'source_id': 'si1',
                    },
                ]
            return []

        with mock.patch.object(ps, 'analytics_fetch_all', side_effect=fake_fetch), \
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-07-21T16:00:00Z'):
            result = ps.analytics_overview('org-1', start='2026-07-21', end='2026-07-21')

        summary = result['summary']
        self.assertEqual(summary['gross_sales'], 1500.0)
        self.assertEqual(summary['collected_from_sales'], 1000.0)
        self.assertEqual(summary['debt_collected'], 150.0)
        self.assertEqual(summary['collected_revenue'], 1150.0)
        self.assertEqual(summary['void_transactions'], 1)
        self.assertEqual(summary['transactions'], 2)
        self.assertEqual(summary['debt_outstanding'], 500.0)
        self.assertEqual(summary['debt_overdue'], 500.0)
        self.assertEqual(summary['out_of_stock_count'], 1)
        self.assertEqual(summary['low_only_count'], 1)
        self.assertGreaterEqual(summary['low_stock_count'], 2)
        self.assertEqual(summary['gross_profit'], 920.0)
        # Voided sale is excluded from gross but counted in void_* fields
        self.assertEqual(summary['void_revenue'], 200.0)


class TestAnalyticsRoutesContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.routes_src = Path(__file__).resolve().parents[1].joinpath(
            'web', 'web_routes.py',
        ).read_text(encoding='utf-8')

    def test_routes_registered(self):
        for path in (
            "/api/cloud/analytics/overview",
            "/api/cloud/analytics/sales",
            "/api/cloud/analytics/sales/<device_id>/<source_id>",
            "/api/cloud/analytics/debts",
            "/api/cloud/analytics/debt-payments",
            "/api/cloud/analytics/inventory",
            "/api/cloud/analytics/filters",
            "/api/cloud/analytics/export",
        ):
            self.assertIn(path, self.routes_src)

    def test_authorize_runs_before_service_queries(self):
        for name in (
            'cloud_analytics_overview',
            'cloud_analytics_sales',
            'cloud_analytics_sale_detail',
            'cloud_analytics_debts',
            'cloud_analytics_debt_payments',
            'cloud_analytics_inventory',
            'cloud_analytics_filters',
            'cloud_analytics_export',
        ):
            marker = f'def {name}'
            start = self.routes_src.index(marker)
            rest = self.routes_src[start:]
            nxt = rest.find('\n@web.route', 1)
            chunk = rest if nxt < 0 else rest[:nxt]
            self.assertIn('_analytics_authorize()', chunk, msg=name)
            # Org id must come from authorize before any cloud_* table helper runs.
            self.assertRegex(
                chunk,
                r'(?s)_analytics_authorize\(\).*analytics_',
                msg=name,
            )

    def test_service_select_strict_raises(self):
        src = inspect.getsource(ps.service_select_strict)
        self.assertIn('raise SupabaseError', src)
        after = src.split('if r.status_code')[1]
        self.assertIn('raise SupabaseError', after)

    def test_export_bound_constant(self):
        self.assertEqual(ps.ANALYTICS_EXPORT_MAX, 10_000)


class TestAnalyticsOrgIsolationHelpers(unittest.TestCase):
    def test_sales_query_always_includes_org_filter(self):
        _s, _e, start_iso, end_iso = ps.analytics_day_bounds('2026-07-21', '2026-07-21')
        q = ps._sales_base_query('org-abc', start_iso, end_iso)
        self.assertIn('org_id=eq.org-abc', q)
        self.assertIn('source_created_at=gte.', q)
        self.assertIn('source_created_at=lt.', q)


if __name__ == '__main__':
    unittest.main()
