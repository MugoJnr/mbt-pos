"""Owner-portal profit splits, debt ageing, and protected report files."""
import unittest
from datetime import date, datetime, timezone

from backend.cloud import platform_service as ps
from backend.cloud.owner_profit import (
    allocate_sale_profits,
    build_text_pdf,
    debt_ageing,
    logical_debt_status,
    movement_is_delivery,
    normalize_sections,
    previous_window,
    report_lines,
    supplier_name_from_reason,
    sync_freshness,
)
from backend.report_file_encryption import pdf_opens, seal_pdf, xlsx_opens, seal_xlsx_file


def _sale(source, method, total, paid, status='completed', when='2026-10-31T10:00:00+03:00'):
    return {
        'device_id': 'd1',
        'source_id': source,
        'payment_method': method,
        'total': total,
        'amount_paid': paid,
        'change_amount': 0,
        'status': status,
        'source_created_at': when,
    }


def _line(sale_id, total, qty, unit_cost):
    return {
        'device_id': 'd1',
        'sale_source_id': sale_id,
        'quantity': qty,
        'unit_cost': unit_cost,
        'total': total,
        'product_name': 'Item',
    }


class ProfitScenarios(unittest.TestCase):
    def test_fully_paid_sale_is_collected_profit(self):
        # Scenario A: 1000 paid in full, cost 400, profit 600.
        sales = [_sale('1', 'cash', 1000, 1000)]
        items = [_line('1', 1000, 1, 400)]
        result = allocate_sale_profits(sales, items, [])
        self.assertEqual(result['gross_profit'], 600)
        self.assertEqual(result['gross_profit_fully_paid'], 600)
        self.assertEqual(result['gross_profit_credit'], 0)
        self.assertEqual(result['gross_profit_collected'], 600)
        self.assertEqual(result['gross_profit_outstanding'], 0)
        self.assertEqual(len(result['sales']), 1)

    def test_credit_sale_is_not_collected(self):
        # Scenario B: 1000 entirely on credit.
        sales = [_sale('2', 'credit sale', 1000, 0)]
        items = [_line('2', 1000, 1, 400)]
        invoice = [{
            'device_id': 'd1', 'sale_source_id': '2', 'balance': 1000, 'status': 'pending',
        }]
        result = allocate_sale_profits(sales, items, invoice)
        self.assertEqual(result['gross_profit_credit'], 600)
        self.assertEqual(result['gross_profit_outstanding'], 600)
        self.assertEqual(result['gross_profit_collected'], 0)

    def test_part_payment_splits_profit_with_the_cash(self):
        # Scenario C: 1000 sale, 400 cash, 600 still owed. Profit 600.
        sales = [_sale('3', 'part payment', 1000, 400)]
        items = [_line('3', 1000, 1, 400)]
        invoice = [{
            'device_id': 'd1', 'sale_source_id': '3', 'balance': 600, 'status': 'partial',
        }]
        result = allocate_sale_profits(sales, items, invoice)
        self.assertEqual(result['gross_profit_part_payment'], 600)
        self.assertEqual(result['gross_profit_collected'], 240)
        self.assertEqual(result['gross_profit_outstanding'], 360)
        self.assertEqual(
            result['gross_profit_collected'] + result['gross_profit_outstanding'],
            result['gross_profit'],
        )

    def test_repayment_moves_profit_without_a_new_sale(self):
        # Scenario D: after a 200 repayment the invoice balance is 800.
        sales = [_sale('2', 'credit sale', 1000, 0)]
        items = [_line('2', 1000, 1, 400)]
        invoice = [{
            'device_id': 'd1', 'sale_source_id': '2', 'balance': 800, 'status': 'partial',
        }]
        result = allocate_sale_profits(sales, items, invoice)
        self.assertEqual(len(result['sales']), 1)
        self.assertEqual(result['gross_profit'], 600)
        self.assertEqual(result['gross_profit_collected'], 120)
        self.assertEqual(result['gross_profit_outstanding'], 480)

    def test_settled_invoice_has_no_outstanding_profit(self):
        # Scenario E: remaining debt paid off. Balance is now zero.
        sales = [_sale('2', 'credit sale', 1000, 0)]
        items = [_line('2', 1000, 1, 400)]
        invoice = [{
            'device_id': 'd1', 'sale_source_id': '2', 'balance': 0, 'status': 'paid',
        }]
        result = allocate_sale_profits(sales, items, invoice)
        self.assertEqual(result['gross_profit_collected'], 600)
        self.assertEqual(result['gross_profit_outstanding'], 0)
        self.assertEqual(result['gross_profit'], 600)

    def test_void_is_excluded_but_the_function_keeps_other_sales(self):
        sales = [
            _sale('1', 'cash', 1000, 1000),
            _sale('9', 'cash', 1000, 1000, status='voided'),
        ]
        items = [_line('1', 1000, 1, 400), _line('9', 1000, 1, 400)]
        result = allocate_sale_profits(sales, items, [])
        self.assertEqual(result['gross_profit'], 600)
        self.assertEqual(len(result['sales']), 1)


class DebtAndSync(unittest.TestCase):
    def test_ageing_buckets(self):
        today = date(2026, 10, 31)
        rows = [
            {'balance': 10, 'status': 'pending', 'due_date': '2026-11-15'},
            {'balance': 20, 'status': 'pending', 'due_date': '2026-10-01'},
            {'balance': 0, 'status': 'paid', 'due_date': '2026-01-01'},
        ]
        ageing = debt_ageing(rows, today=today)
        self.assertEqual(ageing['current'], 10)
        self.assertEqual(ageing['days_1_30'], 20)
        self.assertEqual(ageing['count'], 2)
        self.assertEqual(ageing['detail']['current']['customers'], 1)
        self.assertEqual(ageing['detail']['days_1_30']['invoices'], 1)
        self.assertEqual(ageing['total_outstanding'], 30)

    def test_open_partial_paid_overdue_labels(self):
        today = date(2026, 10, 31)
        self.assertEqual(logical_debt_status({'balance': 5, 'amount_paid': 0, 'status': 'pending', 'due_date': '2026-12-01'}, today=today), 'open')
        self.assertEqual(logical_debt_status({'balance': 5, 'amount_paid': 2, 'status': 'partial', 'due_date': '2026-12-01'}, today=today), 'partial')
        self.assertEqual(logical_debt_status({'balance': 0, 'status': 'paid'}, today=today), 'paid')
        self.assertEqual(logical_debt_status({'balance': 5, 'amount_paid': 0, 'status': 'pending', 'due_date': '2026-10-01'}, today=today), 'overdue')

    def test_missing_sync_is_not_a_success(self):
        fresh = sync_freshness(None)
        self.assertEqual(fresh['state'], 'never')
        self.assertTrue(fresh['stale'])

    def test_old_sync_is_stale(self):
        fresh = sync_freshness(
            '2026-01-01T00:00:00+00:00',
            now=datetime(2026, 10, 31, tzinfo=timezone.utc),
        )
        self.assertEqual(fresh['state'], 'stale')

    def test_previous_window_matches_length(self):
        self.assertEqual(previous_window('2026-10-25', '2026-10-31'), ('2026-10-18', '2026-10-24'))

    def test_supplier_name_comes_from_the_delivery_note(self):
        self.assertEqual(
            supplier_name_from_reason('Received from Supplier: QA Audit Supplier'),
            'QA Audit Supplier',
        )
        self.assertTrue(movement_is_delivery({
            'movement_type': 'receive', 'qty_change': 2, 'reason': '',
        }))


class ScenarioHRoleRedaction(unittest.TestCase):
    """Scenario H from the owner-portal brief: a manager must not receive cost or phone."""

    def test_manager_api_payload_drops_profit_cost_and_phone(self):
        cleaned = ps.analytics_redact_payload({
            'gross_profit': 600,
            'gross_profit_outstanding': 360,
            'stock_value': 80,
            'cost_price': 40,
            'customer_phone': '0700000000',
            'supplier_phone': '0711111111',
            'customer_name': 'Ada',
            'balance': 600,
        }, can_see_finance=False, role='manager')
        self.assertNotIn('gross_profit', cleaned)
        self.assertNotIn('gross_profit_outstanding', cleaned)
        self.assertNotIn('stock_value', cleaned)
        self.assertNotIn('cost_price', cleaned)
        self.assertIsNone(cleaned.get('customer_phone'))
        self.assertIsNone(cleaned.get('supplier_phone'))
        self.assertEqual(cleaned.get('customer_name'), 'Ada')
        self.assertEqual(cleaned.get('balance'), 600)


class ReportSections(unittest.TestCase):
    def test_only_selected_sections_are_written(self):
        summary = {
            'gross_sales': 1000, 'transactions': 1, 'avg_sale': 1000,
            'collected_revenue': 400, 'collected_from_sales': 400, 'debt_collected': 0,
            'gross_profit': 600,
        }
        sections = normalize_sections(['sales_overview', 'collections', 'not-a-section'])
        blocks = report_lines(summary, {}, sections)
        titles = [title for title, _lines in blocks]
        self.assertEqual(titles, ['Sales overview', 'Revenue and collections'])
        text = '\n'.join(line for _title, lines in blocks for line in lines)
        self.assertNotIn('Gross profit', text)

    def test_password_opens_pdf_and_wrong_password_does_not(self):
        raw = build_text_pdf(['Gross sales: 1,000.00', 'Collected revenue: 400.00'])
        sealed = seal_pdf(raw, 'Portal-Export-1')
        self.assertIn('Gross sales', pdf_opens(sealed, 'Portal-Export-1'))
        with self.assertRaises(Exception):
            pdf_opens(sealed, 'wrong-password')

    def test_password_opens_xlsx(self):
        import os
        import tempfile
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['Gross sales: 1000'])
        tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
        tmp.close()
        book.save(tmp.name)
        try:
            sealed = seal_xlsx_file(tmp.name, 'Portal-Export-1')
        finally:
            os.remove(tmp.name)
        opened = xlsx_opens(sealed, 'Portal-Export-1')
        self.assertTrue(opened.startswith(b'PK'))
        with self.assertRaises(Exception):
            xlsx_opens(sealed, 'wrong-password')


if __name__ == '__main__':
    unittest.main()
