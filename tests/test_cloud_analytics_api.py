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
        self.assertFalse(summary['cost_data_incomplete'])
        self.assertEqual(summary['cost_data_status'], 'complete')

    def test_overview_flags_cost_crushing_products(self):
        """Sold SKUs with COGS ≥ revenue must surface Needs Attention (all orgs)."""
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 1400, 'amount_paid': 1400,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T10:00:00+03:00',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
            if table == 'cloud_sale_items':
                return [
                    {
                        'device_id': 'd1', 'sale_source_id': '1',
                        'product_source_id': '312', 'product_name': 'D.A.P Fertilizer',
                        'category': 'Farm', 'quantity': 10, 'total': 1400,
                        'unit_cost': 1270, 'source_id': 'si1',
                    },
                ]
            if table == 'cloud_products':
                return [
                    {
                        'device_id': 'd1', 'source_id': '312', 'name': 'D.A.P Fertilizer',
                        'cost_price': 1270, 'price': 140, 'stock': 5, 'min_stock': 1,
                        'is_active': True,
                    },
                ]
            return []

        with mock.patch.object(ps, 'analytics_fetch_all', side_effect=fake_fetch), \
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-07-21T16:00:00Z'), \
             mock.patch.object(ps, 'analytics_shop_presence', return_value={
                 'pc_online': True, 'pc_status': 'online', 'online_device_count': 1,
                 'device_count': 1, 'online_devices': [], 'offline_devices': [],
                 'last_seen_at': '2026-07-21T16:00:00Z',
                 'last_sync_at': '2026-07-21T16:00:00Z',
                 'sync_freshness': 'fresh', 'sync_age_seconds': 10,
                 'data_label': 'Live', 'is_live_data': True,
             }):
            result = ps.analytics_overview('org-1', start='2026-07-21', end='2026-07-21')

        summary = result['summary']
        self.assertEqual(summary['cost_crushing_product_count'], 1)
        self.assertEqual(summary['cost_crushing_sample'], 'D.A.P Fertilizer')
        self.assertLess(summary['gross_profit'], 0)
        self.assertTrue(
            any(a.get('id') == 'cost-crushing' for a in result['attention']),
        )
        self.assertEqual(result['worst_profit_products'][0]['name'], 'D.A.P Fertilizer')
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 1000, 'amount_paid': 1000,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T10:00:00+03:00',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
            if table == 'cloud_sale_items':
                return [
                    {
                        'device_id': 'd1', 'sale_source_id': '1', 'product_id': '9',
                        'product_name': 'Milk', 'category': 'Dairy', 'quantity': 2,
                        'total': 1000, 'unit_cost': 0, 'source_id': 'si1',
                    },
                ]
            if table == 'cloud_products':
                return [
                    {
                        'device_id': 'd1', 'source_id': '9', 'name': 'Milk',
                        'cost_price': 0, 'stock': 5, 'min_stock': 1, 'is_active': True,
                    },
                ]
            return []

        with mock.patch.object(ps, 'analytics_fetch_all', side_effect=fake_fetch), \
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-07-21T16:00:00Z'), \
             mock.patch.object(ps, 'analytics_shop_presence', return_value={
                 'pc_online': True, 'pc_status': 'online', 'online_device_count': 1,
                 'device_count': 1, 'online_devices': [], 'offline_devices': [],
                 'last_seen_at': '2026-07-21T16:00:00Z',
                 'last_sync_at': '2026-07-21T16:00:00Z',
                 'sync_freshness': 'fresh', 'sync_age_seconds': 10,
                 'data_label': 'Live', 'is_live_data': True,
             }):
            result = ps.analytics_overview('org-1', start='2026-07-21', end='2026-07-21')

        summary = result['summary']
        self.assertEqual(summary['gross_sales'], 1000.0)
        self.assertTrue(summary['cost_data_incomplete'])
        self.assertEqual(summary['cost_data_status'], 'incomplete')
        self.assertEqual(summary['lines_missing_cost'], 1)
        # Missing cost → KSh 0 COGS (same as POS reports); still show range profit.
        self.assertEqual(summary['gross_profit'], 1000.0)
        self.assertEqual(summary['cost_of_goods'], 0.0)
        self.assertEqual(summary['gross_margin_pct'], 100.0)
        self.assertEqual(result['by_day'][0]['gross_profit'], 1000.0)
        self.assertTrue(
            any(a.get('id') == 'cost-incomplete' for a in result['attention']),
        )

    def test_overview_partial_profit_when_some_lines_have_product_cost(self):
        """Inventory cost on some lines must still produce a partial profit KPI."""
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 1500, 'amount_paid': 1500,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T10:00:00+03:00',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
            if table == 'cloud_sale_items':
                return [
                    {
                        'device_id': 'd1', 'sale_source_id': '1',
                        'product_source_id': '9', 'product_name': 'Milk',
                        'category': 'Dairy', 'quantity': 2, 'total': 1000,
                        'unit_cost': 0, 'source_id': 'si1',
                    },
                    {
                        'device_id': 'd1', 'sale_source_id': '1',
                        'product_source_id': 'orphan', 'product_name': 'Unknown',
                        'category': 'Other', 'quantity': 1, 'total': 500,
                        'unit_cost': 0, 'source_id': 'si2',
                    },
                ]
            if table == 'cloud_products':
                return [
                    {
                        'device_id': 'd1', 'source_id': '9', 'name': 'Milk',
                        'cost_price': 40, 'stock': 5, 'min_stock': 1,
                        'is_active': True,
                    },
                ]
            return []

        with mock.patch.object(ps, 'analytics_fetch_all', side_effect=fake_fetch), \
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-07-21T16:00:00Z'), \
             mock.patch.object(ps, 'analytics_shop_presence', return_value={
                 'pc_online': True, 'pc_status': 'online', 'online_device_count': 1,
                 'device_count': 1, 'online_devices': [], 'offline_devices': [],
                 'last_seen_at': '2026-07-21T16:00:00Z',
                 'last_sync_at': '2026-07-21T16:00:00Z',
                 'sync_freshness': 'fresh', 'sync_age_seconds': 10,
                 'data_label': 'Synced', 'is_live_data': True,
             }):
            result = ps.analytics_overview('org-1', start='2026-07-21', end='2026-07-21')

        summary = result['summary']
        self.assertEqual(summary['cost_data_status'], 'incomplete')
        self.assertTrue(summary['cost_data_incomplete'])
        self.assertEqual(summary['lines_with_cost'], 1)
        self.assertEqual(summary['lines_missing_cost'], 1)
        # Milk COGS 80 + orphan COGS 0 → profit 1500 - 80 = 1420 for full range
        self.assertEqual(summary['gross_profit'], 1420.0)
        self.assertEqual(summary['cost_of_goods'], 80.0)
        self.assertEqual(result['by_day'][0]['gross_profit'], 1420.0)

    def test_overview_hides_profit_when_sales_have_no_line_items(self):
        """Sales without synced items must not surface as KSh 0 profit."""
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 11400, 'amount_paid': 11400,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-09-08T10:00:00+03:00',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
            if table == 'cloud_sale_items':
                return []
            if table == 'cloud_products':
                return [
                    {
                        'device_id': 'd1', 'source_id': '9', 'name': 'Widget',
                        'cost_price': 10, 'stock': 0, 'min_stock': 1, 'is_active': True,
                    },
                ]
            return []

        with mock.patch.object(ps, 'analytics_fetch_all', side_effect=fake_fetch), \
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-09-08T16:00:00Z'), \
             mock.patch.object(ps, 'analytics_shop_presence', return_value={
                 'pc_online': False, 'pc_status': 'offline', 'online_device_count': 0,
                 'device_count': 1, 'online_devices': [], 'offline_devices': [],
                 'last_seen_at': '2026-09-08T16:00:00Z',
                 'last_sync_at': '2026-09-08T16:00:00Z',
                 'sync_freshness': 'stale', 'sync_age_seconds': 40000,
                 'data_label': 'Stale sync', 'is_live_data': False,
             }):
            result = ps.analytics_overview('org-1', start='2026-09-08', end='2026-09-09')

        summary = result['summary']
        self.assertEqual(summary['gross_sales'], 11400.0)
        self.assertEqual(summary['transactions'], 1)
        self.assertTrue(summary['cost_data_incomplete'])
        self.assertEqual(summary['cost_data_status'], 'no_items')
        self.assertEqual(summary['gross_profit'], 0.0)
        self.assertEqual(summary['gross_margin_pct'], 0.0)
        self.assertIsNotNone(summary['cost_data_message'])
        self.assertTrue(
            any(a.get('id') == 'cost-incomplete' for a in result['attention']),
        )

    def test_overview_uses_product_cost_fallback_when_line_cost_zero(self):
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 1000, 'amount_paid': 1000,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T10:00:00+03:00',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
            if table == 'cloud_sale_items':
                return [
                    {
                        'device_id': 'd1', 'sale_source_id': '1', 'product_id': '77',
                        'product_name': 'Milk', 'category': 'Dairy', 'quantity': 2,
                        'total': 1000, 'unit_cost': 0, 'source_id': 'si1',
                    },
                ]
            if table == 'cloud_products':
                return [
                    {
                        'device_id': 'd1', 'source_id': '77', 'name': 'Milk',
                        'cost_price': 40, 'stock': 5, 'min_stock': 1, 'is_active': True,
                    },
                ]
            return []

        with mock.patch.object(ps, 'analytics_fetch_all', side_effect=fake_fetch), \
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-07-21T16:00:00Z'), \
             mock.patch.object(ps, 'analytics_shop_presence', return_value={
                 'pc_online': True, 'pc_status': 'online', 'online_device_count': 1,
                 'device_count': 1, 'online_devices': [], 'offline_devices': [],
                 'last_seen_at': '2026-07-21T16:00:00Z',
                 'last_sync_at': '2026-07-21T16:00:00Z',
                 'sync_freshness': 'fresh', 'sync_age_seconds': 10,
                 'data_label': 'Live', 'is_live_data': True,
             }):
            result = ps.analytics_overview('org-1', start='2026-07-21', end='2026-07-21')

        summary = result['summary']
        self.assertFalse(summary['cost_data_incomplete'])
        self.assertEqual(summary['cost_data_status'], 'complete')
        self.assertEqual(summary['cost_of_goods'], 80.0)
        self.assertEqual(summary['gross_profit'], 920.0)
        self.assertEqual(summary['gross_margin_pct'], 92.0)


class TestAnalyticsLineCostHelpers(unittest.TestCase):
    def test_resolve_prefers_positive_unit_cost(self):
        cost = ps.analytics_resolve_line_unit_cost(
            {'unit_cost': 12, 'product_id': '1', 'device_id': 'd'},
            {('d', '1'): 99.0},
        )
        self.assertEqual(cost, 12.0)

    def test_resolve_falls_back_to_product_cost(self):
        cost = ps.analytics_resolve_line_unit_cost(
            {'unit_cost': 0, 'product_id': '1', 'device_id': 'd'},
            {('d', '1'): 40.0},
        )
        self.assertEqual(cost, 40.0)

    def test_resolve_uses_product_source_id_and_org_wide_fallback(self):
        cost = ps.analytics_resolve_line_unit_cost(
            {
                'unit_cost': None,
                'product_source_id': '42',
                'device_id': 'new-device',
            },
            {('*', '42'): 55.0, ('old-device', '42'): 55.0},
        )
        self.assertEqual(cost, 55.0)

    def test_resolve_falls_back_to_product_name(self):
        cost = ps.analytics_resolve_line_unit_cost(
            {
                'unit_cost': 0,
                'product_name': 'Maize Flour 2kg',
                'device_id': 'd',
            },
            {('name', 'maize flour 2kg'): 180.0},
        )
        self.assertEqual(cost, 180.0)

    def test_resolve_returns_none_when_incomplete(self):
        self.assertIsNone(ps.analytics_resolve_line_unit_cost(
            {'unit_cost': 0, 'product_id': '1', 'device_id': 'd'},
            {('d', '1'): 0.0},
        ))
        self.assertIsNone(ps.analytics_resolve_line_unit_cost(
            {'unit_cost': None, 'product_id': 'missing', 'device_id': 'd'},
            {},
        ))


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

    def test_default_range_helper_present(self):
        self.assertIn('def _analytics_default_range', self.routes_src)
        self.assertIn('_analytics_default_range()', self.routes_src)
        # Overview/sales must not hard-default to a single calendar day.
        overview = self.routes_src[
            self.routes_src.index('def cloud_analytics_overview'):
            self.routes_src.index('def cloud_analytics_sales')
        ]
        self.assertNotIn("datetime.now().strftime('%Y-%m-%d')", overview)
        self.assertIn('_analytics_default_range()', overview)


class TestAnalyticsOrgIsolationHelpers(unittest.TestCase):
    def test_sales_query_always_includes_org_filter(self):
        _s, _e, start_iso, end_iso = ps.analytics_day_bounds('2026-07-21', '2026-07-21')
        q = ps._sales_base_query('org-abc', start_iso, end_iso)
        self.assertIn('org_id=eq.org-abc', q)
        self.assertIn('source_created_at=gte.', q)
        self.assertIn('source_created_at=lt.', q)


class TestShopPresenceAndAttention(unittest.TestCase):
    def test_offline_stale_not_labeled_live(self):
        now = datetime(2026, 9, 9, 12, 0, tzinfo=NAIROBI)
        devices = [
            {
                'id': 'd1',
                'device_id': 'PC-1',
                'computer_name': 'Front till',
                'approval_status': 'approved',
                'is_active': True,
                'last_seen_at': '2026-09-09T06:00:00Z',  # >5 min ago
                'last_sync_at': '2026-09-08T10:00:00Z',  # stale
            },
        ]
        with mock.patch.object(ps, 'list_devices_for_org', return_value=devices):
            presence = ps.analytics_shop_presence('org-1', now=now.astimezone())
        self.assertFalse(presence['pc_online'])
        self.assertEqual(presence['pc_status'], 'offline')
        self.assertEqual(presence['sync_freshness'], 'stale')
        self.assertFalse(presence['is_live_data'])
        self.assertNotEqual(presence['data_label'].lower(), 'live')
        self.assertNotIn('live', presence['data_label'].lower())

    def test_online_fresh_is_synced_not_fake_live_word_on_stale_path(self):
        now = datetime(2026, 9, 9, 12, 0, tzinfo=NAIROBI)
        devices = [
            {
                'id': 'd1',
                'device_id': 'PC-1',
                'computer_name': 'Front till',
                'approval_status': 'approved',
                'is_active': True,
                'last_seen_at': now.astimezone().isoformat(),
                'last_sync_at': now.astimezone().isoformat(),
            },
        ]
        with mock.patch.object(ps, 'list_devices_for_org', return_value=devices):
            presence = ps.analytics_shop_presence('org-1', now=now.astimezone())
        self.assertTrue(presence['pc_online'])
        self.assertEqual(presence['sync_freshness'], 'fresh')
        self.assertTrue(presence['is_live_data'])
        self.assertEqual(presence['data_label'], 'Synced')

    def test_attention_rules_include_overdue_and_stock(self):
        presence = {
            'pc_online': False,
            'device_count': 1,
            'sync_freshness': 'stale',
            'sync_age_seconds': 7200,
        }
        summary = {
            'overdue_count': 2,
            'debt_overdue': 1500,
            'out_of_stock_count': 1,
            'low_only_count': 1,
        }
        items = ps.analytics_build_attention(
            summary=summary,
            low_stock=[{'name': 'Milk', 'stock': 2}],
            presence=presence,
        )
        ids = {i['id'] for i in items}
        self.assertIn('sync-stale', ids)
        self.assertIn('pc-offline', ids)
        self.assertIn('debt-overdue', ids)
        self.assertIn('stock-out', ids)
        self.assertIn('stock-low', ids)

    def test_attention_cost_crushing_products(self):
        items = ps.analytics_build_attention(
            summary={
                'cost_crushing_product_count': 2,
                'cost_crushing_profit_drag': -16667.5,
                'cost_crushing_sample': 'D.A.P Fertilizer per kg',
            },
            low_stock=[],
            presence={'pc_online': True, 'device_count': 1, 'sync_freshness': 'fresh'},
        )
        crush = next(i for i in items if i['id'] == 'cost-crushing')
        self.assertEqual(crush['severity'], 'warning')
        self.assertEqual(crush['action'], 'inventory')
        self.assertIn('2 products', crush['title'])
        self.assertIn('cost ≥ sell', crush['title'])
        self.assertIn('D.A.P', crush['detail'])
        self.assertIn('real number', crush['detail'])


class TestAnalyticsSearchRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.routes_src = Path(__file__).resolve().parents[1].joinpath(
            'web', 'web_routes.py',
        ).read_text(encoding='utf-8')

    def test_search_route_registered_and_authorized(self):
        self.assertIn('/api/cloud/analytics/search', self.routes_src)
        start = self.routes_src.index('def cloud_analytics_search')
        chunk = self.routes_src[start:start + 1200]
        self.assertIn('_analytics_authorize()', chunk)

    def test_common_args_accept_search_alias(self):
        self.assertIn("request.args.get('search')", self.routes_src)
        self.assertIn("request.args.get('payment_method')", self.routes_src)


class TestOverviewIncludesPresence(unittest.TestCase):
    def test_overview_exposes_presence_and_attention(self):
        sales = [
            {
                'device_id': 'd1', 'source_id': '1', 'status': 'completed',
                'payment_method': 'cash', 'total': 1000, 'amount_paid': 1000,
                'change_amount': 0, 'discount': 0, 'tax': 0,
                'source_created_at': '2026-07-21T10:00:00+03:00',
            },
        ]

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            if table == 'cloud_sales':
                return sales
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
             mock.patch.object(ps, 'analytics_last_sync_at', return_value='2026-07-21T16:00:00Z'), \
             mock.patch.object(ps, 'analytics_shop_presence', return_value={
                 'pc_online': False,
                 'pc_status': 'offline',
                 'online_device_count': 0,
                 'device_count': 1,
                 'online_devices': [],
                 'offline_devices': [],
                 'last_seen_at': None,
                 'last_sync_at': '2026-07-21T16:00:00Z',
                 'sync_freshness': 'stale',
                 'sync_age_seconds': 90000,
                 'data_label': 'Stale sync',
                 'is_live_data': False,
             }):
            result = ps.analytics_overview('org-1', start='2026-07-21', end='2026-07-21')

        self.assertIn('presence', result)
        self.assertIn('attention', result)
        self.assertIn('recent_sales', result)
        self.assertFalse(result['presence']['is_live_data'])
        self.assertIn('gross_profit', result['by_day'][0])
        self.assertEqual(result['by_day'][0]['gross_profit'], 920.0)


class TestAnalyticsSaleDetailLines(unittest.TestCase):
    """Portal receipt detail must load cloud_sale_items by sale_source_id only."""

    def test_sale_detail_query_uses_sale_source_id_not_sale_id(self):
        queries = []

        def fake_select(table, query, **kwargs):
            queries.append((table, query))
            if table == 'cloud_sales':
                return [{
                    'device_id': 'dev-1',
                    'source_id': '42',
                    'receipt_number': 'RCP-1',
                    'total': 100,
                    'cashier_name': 'Amina',
                    'payment_method': 'Cash',
                    'status': 'completed',
                }]
            if table == 'cloud_sale_items':
                return [{
                    'device_id': 'dev-1',
                    'sale_source_id': '42',
                    'source_id': 'si-1',
                    'product_name': 'Maize Flour 2kg',
                    'quantity': 2,
                    'unit_price': 50,
                    'discount': 0,
                    'total': 100,
                }]
            return []

        with mock.patch.object(ps, 'service_select_strict', side_effect=fake_select):
            sale = ps.analytics_sale_detail('org-1', 'dev-1', '42')

        item_queries = [q for t, q in queries if t == 'cloud_sale_items']
        self.assertEqual(len(item_queries), 1)
        self.assertIn('sale_source_id=eq.42', item_queries[0])
        self.assertNotIn('sale_id.eq', item_queries[0])
        self.assertEqual(len(sale['line_items']), 1)
        self.assertEqual(sale['line_items'][0]['product_name'], 'Maize Flour 2kg')
        self.assertEqual(sale['items'], sale['line_items'])


if __name__ == '__main__':
    unittest.main()
