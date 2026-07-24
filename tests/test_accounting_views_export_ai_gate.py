"""F02–F04 accounting views/P&L integrity, R02 export smoke, AI01/AI02/D06, U04."""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class AccountingViewsExportAiGate(unittest.TestCase):
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
        self.api._role = 'admin'
        self.api._user_id = 1
        self.api._username = 'admin'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
            db.execute(
                "UPDATE users SET role='admin' WHERE id=?", (self.api._user_id,)
            )
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'admin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_f02_f03_f04_cash_mpesa_bank_and_pnl_integrity(self):
        today = str(date.today())
        dash = self.api.accounting_dashboard() or {}
        for key in ('cash_balance', 'mpesa_balance', 'bank_balance', 'month_expenses'):
            self.assertIn(key, dash)

        for code in ('1000', '1010', '1020'):
            book = self.api.accounting_cash_book(code, today, today) or {}
            self.assertIn('balance', book)
            self.assertNotIn('error', book)

        before = self.api.accounting_pnl(today, today) or {}
        exp_before = float(before.get('total_expenses') or 0)

        created = self.api.accounting_create_expense({
            'amount': 123.45,
            'description': 'P&L integrity gate',
            'account_code': '6000',
            'pay_from_code': '1000',
            'expense_date': today,
        })
        self.assertTrue(created.get('success'), created)

        after = self.api.accounting_pnl(today, today) or {}
        exp_after = float(after.get('total_expenses') or 0)
        self.assertAlmostEqual(exp_after, exp_before + 123.45, places=2)
        self.assertIn('net_profit', after)

        cash = self.api.accounting_cash_book('1000', today, today) or {}
        # Expense credits cash — balance should reflect activity lines
        self.assertTrue(isinstance(cash.get('lines'), list) or 'balance' in cash)

    def test_r02_export_excel_and_html_printable(self):
        try:
            from backend.export_engine import (
                export_sales_report, export_sales_report_html,
            )
        except ImportError as e:
            self.skipTest(f'export deps missing: {e}')

        sales = [{
            'id': 1,
            'receipt_number': 'R-GATE-1',
            'created_at': f'{date.today()} 10:00:00',
            'cashier_name': 'admin',
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Cash',
            'item_count': 1,
        }]
        items = {1: [{
            'product_name': 'Gate Item',
            'sku': 'G1',
            'quantity': 1,
            'unit_price': 100.0,
            'discount': 0,
            'total': 100.0,
        }]}

        xlsx_out = os.path.join(self._tmpdir.name, 'sales_gate.xlsx')
        xlsx_path = export_sales_report(
            sales_data=sales,
            items_by_sale=items,
            shop_name='Gate Shop',
            start_date=str(date.today()),
            end_date=str(date.today()),
            output_path=xlsx_out,
        )
        self.assertTrue(xlsx_path)
        self.assertTrue(os.path.isfile(xlsx_path))
        self.assertGreater(os.path.getsize(xlsx_path), 0)

        html_out = os.path.join(self._tmpdir.name, 'sales_gate.html')
        html_path = export_sales_report_html(
            sales_data=sales,
            items_by_sale=items,
            shop_name='Gate Shop',
            start_date=str(date.today()),
            end_date=str(date.today()),
            output_path=html_out,
            currency='KES',
            generated_by='gate',
        )
        self.assertTrue(html_path)
        self.assertTrue(os.path.isfile(html_path))
        self.assertGreater(os.path.getsize(html_path), 0)
        with open(html_path, encoding='utf-8') as f:
            html = f.read()
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('R-GATE-1', html)
        self.assertIn('@media print', html)
        self.assertIn('Print', html)

        # Honest: printable HTML exists; no reportlab/native PDF writer required
        import backend.export_engine as ee
        src = inspect.getsource(ee)
        self.assertIn('def export_sales_report_html', src)
        self.assertNotIn('reportlab', src.lower())

    def test_ai01_context_permission_filter(self):
        from desktop.utils.ai.context import build_context
        from desktop.utils.security import has_permission

        cashier = {'id': 2, 'username': 'c', 'role': 'cashier'}
        admin = {'id': 1, 'username': 'admin', 'role': 'admin'}

        self.assertFalse(has_permission(cashier, 'accounting.view'))
        self.assertTrue(has_permission(admin, 'accounting.view'))

        c_acct = build_context(self.api, cashier, 'accounting')
        a_acct = build_context(self.api, admin, 'accounting')
        c_notes = ' '.join(c_acct.get('notes') or []).lower()
        self.assertTrue(
            'denied' in c_notes or 'limited' in c_notes,
            c_acct,
        )
        self.assertFalse(
            (c_acct.get('snapshot') or {}).get('accounting', {}).get('available'),
            c_acct,
        )
        a_notes = ' '.join(a_acct.get('notes') or []).lower()
        self.assertNotIn('accounting context denied', a_notes)
        self.assertTrue(
            (a_acct.get('snapshot') or {}).get('accounting', {}).get('available'),
            a_acct,
        )

        # Cashier sales context must not leak accounting snapshot keys
        c_sales = build_context(self.api, cashier, 'sales')
        self.assertNotIn('accounting', c_sales.get('snapshot') or {})

        # Cashier has reports.view_basic → reports module allowed (no limited note)
        c_reports = build_context(self.api, cashier, 'reports')
        c_rep_notes = ' '.join(c_reports.get('notes') or []).lower()
        self.assertNotIn('limited context', c_rep_notes)

        a_reports = build_context(self.api, admin, 'reports')
        a_rep_notes = ' '.join(a_reports.get('notes') or []).lower()
        self.assertNotIn('limited context', a_rep_notes)

    def test_ai02_d06_dashboard_insights_local_no_fabricate(self):
        from desktop.utils.ai.insights import get_dashboard_insights, _CACHE

        _CACHE.update({'ts': 0.0, 'data': None, 'user': ''})
        data = get_dashboard_insights(
            self.api, {'id': 1, 'username': 'admin', 'role': 'admin'}, force=True)
        self.assertIn('summary', data)
        self.assertIn(data.get('source'), ('local', 'ai'))
        # Dashboard tab wires _load_ai_insights → get_dashboard_insights
        dash_path = os.path.join(
            ROOT, 'desktop', 'tabs', 'dashboard_tab.py')
        with open(dash_path, encoding='utf-8') as f:
            src = f.read()
        self.assertIn('get_dashboard_insights', src)
        self.assertIn('_load_ai_insights', src)
        low = (data.get('summary') or '').lower()
        self.assertNotIn('placeholder revenue', low)
        self.assertNotIn('fake total', low)

    def test_u04_sales_footer_settings_debt_touch_targets(self):
        # Checkout chrome lives in panel_factory (shared across layouts)
        panel_path = os.path.join(ROOT, 'desktop', 'pos', 'panel_factory.py')
        with open(panel_path, encoding='utf-8') as f:
            src = f.read()
        # Footer action buttons constructed at height ≥40
        self.assertIn("DangerBtn('Clear', 40)", src)
        self.assertIn("SecondaryBtn('Hold', 40)", src)
        self.assertIn("SecondaryBtn('Resume', 40)", src)
        self.assertIn("SecondaryBtn('Preview', 40)", src)
        self.assertIn("PrimaryBtn('$  Complete Sale', 56)", src)
        self.assertIn('setMinimumHeight(56)', src)
        # Focus / maximize control (U04 touch ≥40) — session-only chrome toggle
        self.assertIn("SecondaryBtn('Focus', 40)", src)
        sales_path = os.path.join(ROOT, 'desktop', 'tabs', 'sales_tab.py')
        with open(sales_path, encoding='utf-8') as f:
            sales = f.read()
        self.assertIn('focus_mode_toggled', sales)
        self.assertIn('set_focus_mode', sales)

        settings_path = os.path.join(ROOT, 'desktop', 'tabs', 'settings_tab.py')
        with open(settings_path, encoding='utf-8') as f:
            settings = f.read()
        self.assertIn("PrimaryBtn('Save Changes', 40)", settings)
        self.assertIn("PrimaryBtn('Save All Settings', 50)", settings)

        debt_path = os.path.join(ROOT, 'desktop', 'tabs', 'debt_tab.py')
        with open(debt_path, encoding='utf-8') as f:
            debt = f.read()
        self.assertIn("PrimaryBtn('+ Collect Payment', 40)", debt)
        self.assertIn("PrimaryBtn('Collect Payment', 42)", debt)
        # Row action Collect/History bumped to ≥40
        self.assertIn("pay_btn.setMinimumHeight(40)", debt)
        self.assertIn("view_btn.setMinimumHeight(40)", debt)
        self.assertIn('_edit_sale_btn', debt)
        self.assertIn('Edit Sale', debt)


if __name__ == '__main__':
    unittest.main()
