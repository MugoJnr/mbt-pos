"""Cashier dashboard copy must not call an own-receipt list the shop list."""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CashierReceiptScopeCopyTests(unittest.TestCase):
    def test_web_dashboard_separates_shop_total_from_own_receipts(self):
        path = os.path.join(ROOT, "web", "dashboard-ui", "src", "routes", "index.tsx")
        text = open(path, encoding="utf-8").read()
        self.assertIn('label={canFinance ? "Total sales" : "Shop sales"}', text)
        self.assertIn("shop receipt${txns === 1 ? \"\" : \"s\"} · all cashiers", text)
        self.assertIn("Your receipts · ${sales.length}", text)
        self.assertIn('receipt{sales.length === 1 ? "" : "s"} for this login.', text)
        self.assertIn("The shop sold {KES(revenue)} across {txns}", text)
        self.assertNotIn("Including credit sales · ${txns} receipts · the list below is yours", text)

    def test_web_reports_do_not_fetch_or_export_for_a_cashier(self):
        path = os.path.join(ROOT, "web", "dashboard-ui", "src", "routes", "reports.tsx")
        text = open(path, encoding="utf-8").read()
        self.assertIn('reportActions.includes("reports.view_all")', text)
        self.assertIn("enabled: canOpenReports", text)
        self.assertIn("retry: false", text)
        self.assertIn("if (!canOpenReports || data?.error)", text)
        self.assertIn("This report is not available for your login.", text)
        denial = text.split("if (!canOpenReports || data?.error)", 1)[1].split("if (dataQ.isPending", 1)[0]
        self.assertNotIn("Excel", denial)
        self.assertNotIn("No sales in range", denial)
        self.assertNotIn("KES(0)", denial)

    def test_desktop_dashboard_labels_the_cashier_list_as_theirs(self):
        path = os.path.join(ROOT, "desktop", "tabs", "dashboard_tab.py")
        text = open(path, encoding="utf-8").read()
        self.assertIn("self._k_sales.set_label('Shop sales')", text)
        self.assertIn("The list below is yours.", text)
        self.assertIn("Your receipts · {n}", text)
        self.assertIn("No receipts of yours for {span}", text)
        self.assertIn("if int(row.get('cashier_id') or 0) == uid", text)
        self.assertIn("not has_permission(source, 'sales.view_all')", text)
