"""Reports reconciliation, money-column sizing, empty states, PDF and role gates.

Defects covered:
  * the Sales List showed a voided sale the KPI summary excluded
  * Original/Final money columns truncated at a fixed 90/100px
  * empty report/debt/finance tables rendered as blank grids
  * direct PDF export produced no reconciled document
  * write controls stayed visible for roles that cannot use them
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QTableWidget, QTableWidgetItem  # noqa: E402

APP = QApplication.instance() or QApplication([])

SALES = [
    {'id': 1, 'receipt_number': 'R-1', 'total': 1000.0, 'status': 'completed'},
    {'id': 2, 'receipt_number': 'R-2', 'total': 250.0, 'status': 'return'},
    {'id': 3, 'receipt_number': 'R-3', 'total': 900.0, 'status': 'voided'},
    {'id': 4, 'receipt_number': 'R-4', 'total': 400.0, 'status': None},
]


class SaleStatusPredicateTests(unittest.TestCase):
    def test_voided_sales_are_excluded_everywhere(self):
        from desktop.tabs.reports_tab import is_reportable_sale, reportable_sales
        kept = reportable_sales(SALES)
        self.assertEqual([s['receipt_number'] for s in kept],
                         ['R-1', 'R-2', 'R-4'])
        self.assertFalse(is_reportable_sale({'status': 'VOIDED'}))
        self.assertTrue(is_reportable_sale({'status': ' Completed '}))
        self.assertTrue(is_reportable_sale({}))

    def test_table_and_export_use_the_same_predicate(self):
        """Both the Sales List and the exports must filter identically."""
        path = os.path.join(ROOT, 'desktop', 'tabs', 'reports_tab.py')
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        self.assertGreaterEqual(source.count('reportable_sales(self.api.get_sales('), 3)

    def test_table_rows_reconcile_with_summary_total(self):
        from desktop.tabs.reports_tab import reportable_sales
        kept = reportable_sales(SALES)
        self.assertAlmostEqual(sum(s['total'] for s in kept), 1650.0)
        self.assertNotIn(900.0, [s['total'] for s in kept])


class MoneyColumnSizingTests(unittest.TestCase):
    def _table(self, values):
        table = QTableWidget(len(values), 1)
        for row, text in enumerate(values):
            table.setItem(row, 0, QTableWidgetItem(text))
        return table

    def test_fit_columns_widens_for_long_money_values(self):
        from desktop.utils.widgets import fit_columns_to_content
        table = self._table(['KES 250.00', 'KES 12,345,678.90'])
        table.setColumnWidth(0, 90)
        fit_columns_to_content(table, (0,))
        width = table.columnWidth(0)
        metrics = table.fontMetrics()
        needed = metrics.horizontalAdvance('KES 12,345,678.90')
        self.assertGreaterEqual(width, needed)
        table.deleteLater()

    def test_fit_columns_respects_a_maximum_cap(self):
        from desktop.utils.widgets import fit_columns_to_content
        table = self._table(['KES ' + '9' * 400])
        fit_columns_to_content(table, (0,), cap=420)
        self.assertLessEqual(table.columnWidth(0), 420)
        table.deleteLater()

    def test_money_cells_get_full_value_tooltips(self):
        from desktop.utils.widgets import apply_cell_tooltips
        table = self._table(['KES 1,234,567.00'])
        apply_cell_tooltips(table)
        self.assertEqual(table.item(0, 0).toolTip(), 'KES 1,234,567.00')
        table.deleteLater()

    def test_reports_money_columns_are_not_fixed_pixels(self):
        path = os.path.join(ROOT, 'desktop', 'tabs', 'reports_tab.py')
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        self.assertIn('QHeaderView.Interactive', source)
        self.assertIn('fit_columns_to_content', source)


class EmptyStateTests(unittest.TestCase):
    def test_overlay_appears_only_while_the_table_is_empty(self):
        from desktop.utils.widgets import attach_table_empty_state
        table = QTableWidget(0, 2)
        table.resize(400, 200)
        overlay = attach_table_empty_state(
            table, 'reports', 'No sales yet',
            'Run a report for a period with sales.')
        table.show()
        APP.processEvents()
        # isHidden(), not isVisible(): the overlay must follow the row count
        # regardless of whether the offscreen table itself got mapped.
        self.assertFalse(overlay.widget.isHidden())

        table.insertRow(0)
        table.setItem(0, 0, QTableWidgetItem('R-1'))
        APP.processEvents()
        self.assertTrue(overlay.widget.isHidden())

        table.setRowCount(0)
        APP.processEvents()
        self.assertFalse(overlay.widget.isHidden())
        table.close()
        table.deleteLater()

    def test_attaching_twice_reuses_one_overlay(self):
        from desktop.utils.widgets import attach_table_empty_state
        table = QTableWidget(0, 1)
        first = attach_table_empty_state(table, 'reports', 'Empty')
        second = attach_table_empty_state(table, 'reports', 'Empty')
        self.assertIs(first, second)
        table.deleteLater()

    def test_tabs_with_reported_blank_grids_attach_empty_states(self):
        for parts in (('desktop', 'tabs', 'reports_tab.py'),
                      ('desktop', 'tabs', 'debt_tab.py'),
                      ('desktop', 'tabs', 'finance_tab.py')):
            path = os.path.join(ROOT, *parts)
            with open(path, 'r', encoding='utf-8') as fh:
                source = fh.read()
            self.assertIn('attach_table_empty_state', source, parts[-1])


class DirectPdfExportTests(unittest.TestCase):
    SUMMARY = {
        'total_revenue': 1650.0,
        'total_transactions': 3,
        'avg_transaction': 550.0,
        'total_discounts': 0.0,
    }

    def test_pdf_is_a_valid_non_empty_document(self):
        from backend.report_export_service import export_sales_report_pdf
        from desktop.tabs.reports_tab import reportable_sales
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'report.pdf')
            path = export_sales_report_pdf(
                reportable_sales(SALES), self.SUMMARY,
                shop_name='Test Shop', start_date='2026-09-01',
                end_date='2026-09-02', output_path=out, currency='KES',
            )
            self.assertEqual(path, out)
            with open(path, 'rb') as fh:
                data = fh.read()
        self.assertGreater(len(data), 600)
        self.assertTrue(data.startswith(b'%PDF-1.'))
        self.assertTrue(data.rstrip().endswith(b'%%EOF'))
        self.assertIn(b'/Type /Catalog', data)
        self.assertIn(b'startxref', data)

    def test_pdf_totals_reconcile_with_the_kpi_summary(self):
        from backend.report_export_service import sales_pdf_lines
        from desktop.tabs.reports_tab import reportable_sales
        kept = reportable_sales(SALES)
        lines = sales_pdf_lines(kept, self.SUMMARY, currency='KES')
        body = '\n'.join(lines)
        self.assertIn('Revenue: KES 1,650.00', body)
        self.assertIn('Transactions: 3', body)
        self.assertIn(f'Receipts ({len(kept)} reportable sales)', body)
        # The voided receipt must not be listed.
        self.assertNotIn('R-3', body)

    def test_multi_page_reports_declare_every_page(self):
        from backend.report_export_service import build_report_pdf
        data = build_report_pdf(
            'Sales Report', 'Test Shop', '2026-09-01 to 2026-09-02',
            [f'line {i}' for i in range(300)])
        self.assertGreater(data.count(b'/Type /Page\n')
                           + data.count(b'/Type /Page '), 1)
        self.assertTrue(data.rstrip().endswith(b'%%EOF'))

    def test_web_export_delegates_to_the_shared_builder(self):
        path = os.path.join(ROOT, 'web', 'web_routes.py')
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        self.assertIn('build_report_pdf', source)


class RoleGateTests(unittest.TestCase):
    """Write controls must follow has_permission, not hard-coded role names."""

    ROLES = ('superadmin', 'admin', 'manager', 'cashier', 'viewer')

    def _user(self, role):
        return {'user': {'id': 1, 'username': role, 'role': role}, 'role': role}

    def test_reports_export_permission_matches_visible_controls(self):
        from desktop.utils.security import has_permission
        allowed = {r for r in self.ROLES
                   if has_permission(self._user(r), 'reports.export')}
        self.assertIn('admin', allowed)
        self.assertIn('superadmin', allowed)
        self.assertNotIn('cashier', allowed)

    def test_viewer_can_reach_accounting_reports(self):
        from desktop.tabs.finance_tab import _can_see_reports
        self.assertTrue(_can_see_reports(self._user('viewer')))
        self.assertTrue(_can_see_reports(self._user('admin')))

    def test_finance_tab_has_no_hard_coded_role_tuples_for_reports(self):
        path = os.path.join(ROOT, 'desktop', 'tabs', 'finance_tab.py')
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        start = source.index('def _can_see_reports')
        block = source[start:start + 600]
        # _can() is the module's has_permission wrapper.
        self.assertIn("_can(user, 'accounting.view_reports')", block)
        self.assertNotIn("'manager'", block)

    def test_debt_write_actions_are_permission_gated(self):
        from desktop.utils.security import has_permission
        cashier = self._user('cashier')
        self.assertFalse(has_permission(cashier, 'debt.customer_manage'))
        # Credit-sale quick customer creation must still work for a cashier.
        self.assertTrue(has_permission(cashier, 'debt.create'))

    def test_gated_tabs_use_the_central_helpers(self):
        for parts in (('desktop', 'tabs', 'debt_tab.py'),
                      ('desktop', 'tabs', 'finance_tab.py'),
                      ('desktop', 'tabs', 'reports_tab.py'),
                      ('desktop', 'tabs', 'notes_tab.py')):
            path = os.path.join(ROOT, *parts)
            with open(path, 'r', encoding='utf-8') as fh:
                source = fh.read()
            self.assertIn('has_permission', source, parts[-1])

    def test_notes_read_only_role_cannot_write(self):
        """A viewer holding notes.view_all must not get Save/Delete/New."""
        from desktop.utils.security import has_permission
        self.assertFalse(has_permission(self._user('viewer'), 'notes.own'))
        path = os.path.join(ROOT, 'desktop', 'tabs', 'notes_tab.py')
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        self.assertIn("self._can_write = has_permission(user, 'notes.own')", source)
        for guard in ('self._add_btn.setVisible(self._can_write)',
                      'self._sv.setVisible(self._can_write)',
                      'self._dl.setVisible(self._can_write)'):
            self.assertIn(guard, source)
        # Every write path re-checks before touching the API.
        for method in ('def _save', 'def _toggle_pin', 'def _delete'):
            start = source.index(method)
            self.assertIn('_can_edit_note()', source[start:start + 400], method)


if __name__ == '__main__':
    unittest.main()
