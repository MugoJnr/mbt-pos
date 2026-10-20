"""A01–A03: Live Dashboard approvals are status-only; command poller contract.

`_review_approval` is Flask-wrapped. We gate without Flask by reading
`web_routes.py` source + UI honesty copy, and by exercising CommandCenter
local execute paths that do not need cloud.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WEB_ROUTES = os.path.join(ROOT, 'web', 'web_routes.py')


class ApprovalsStatusOnlyGate(unittest.TestCase):
    def test_review_approval_executes_through_the_service(self):
        with open(WEB_ROUTES, encoding='utf-8') as fh:
            full = fh.read()
        start = full.find('def _review_approval(')
        self.assertGreaterEqual(start, 0)
        end = full.find('def approve_approval(', start)
        self.assertGreater(end, start)
        src = full[start:end]
        self.assertIn('execute_approval', src)
        self.assertIn("_push_notification", src)
        self.assertNotIn('issue_command', src)
        self.assertNotIn('execute_local', src)

    def test_approvals_ui_honesty_labels(self):
        path = os.path.join(
            ROOT, 'web', 'dashboard-ui', 'src', 'routes', 'approvals.tsx',
        )
        with open(path, encoding='utf-8') as fh:
            ui = fh.read()
        self.assertIn('runs that action once', ui)
        self.assertIn('Super-Admin PIN', ui)
        self.assertNotIn('updates queue status only', ui)

    def test_a02_reject_and_escalate_paths(self):
        with open(WEB_ROUTES, encoding='utf-8') as fh:
            routes = fh.read()
        self.assertIn("/api/approvals/<int:aid>/reject", routes)
        self.assertIn("/api/approvals/<int:aid>/approve", routes)
        self.assertIn("/api/approvals/<int:aid>/escalate", routes)
        client = open(
            os.path.join(ROOT, 'desktop', 'utils', 'api_client.py'), encoding='utf-8'
        ).read()
        self.assertIn("'escalated'", client)
        self.assertIn("'expired'", client)
        start = routes.find('def _review_approval(')
        end = routes.find('def approve_approval(', start)
        review = routes[start:end]
        self.assertIn('execute_approval', review)
        self.assertIn('escalate', review.lower())

    def test_a03_command_center_poller_contract(self):
        from backend.cloud.command_center import COMMANDS, CommandCenter

        self.assertIn('force_sync', COMMANDS)
        self.assertIn('run_backup', COMMANDS)
        cc = CommandCenter(db_path=':memory:')
        self.assertTrue(callable(cc.start_poller))
        self.assertTrue(callable(cc.stop_poller))
        self.assertTrue(callable(cc.issue_command))
        self.assertTrue(callable(cc.poll_pending))
        with self.assertRaises(ValueError):
            cc.issue_command('org', 'dev', 'not_a_real_command', {})
        ok, msg, _ = cc.execute_local('no_such_handler', {})
        self.assertFalse(ok)
        self.assertIn('No handler', msg)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = os.path.join(tmp, 'cmd.db')
            conn = sqlite3.connect(db_path)
            conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY)')
            conn.commit()
            conn.close()
            cc2 = CommandCenter(db_path=db_path)
            ok2, msg2, detail = cc2.execute_local('verify_database', {})
            self.assertTrue(ok2, msg2)
            self.assertIsInstance(detail, dict)

        main_path = os.path.join(ROOT, 'desktop', 'main.py')
        with open(main_path, encoding='utf-8') as fh:
            main_src = fh.read()
        self.assertIn('start_poller', main_src)
        self.assertIn('get_command_center', main_src)

    def test_sales_return_wired(self):
        sales = open(
            os.path.join(ROOT, 'desktop', 'tabs', 'sales_tab.py'), encoding='utf-8'
        ).read()
        panel = open(
            os.path.join(ROOT, 'desktop', 'pos', 'panel_factory.py'), encoding='utf-8'
        ).read()
        self.assertIn('_open_return_sale', sales)
        self.assertIn('prompt_return_sale', sales)
        self.assertIn('Return / Exchange', panel)
        self.assertIn('_open_return_sale', panel)
        self.assertIn('def return_sale', open(
            os.path.join(ROOT, 'desktop', 'utils', 'api_client.py'), encoding='utf-8'
        ).read())


if __name__ == '__main__':
    unittest.main()
