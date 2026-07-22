"""AI03: no fabricated money/stock placeholders in AI prompt paths."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Hardcoded demo figures that must not appear as AI "answers"
_FABRICATED_PATTERNS = (
    r'\bKES\s*1[,.]?234[,.]?56\b',
    r'\b\$9{3,}\b',
    r'\bexample revenue\b',
    r'\bfake\s+total\b',
    r'\bplaceholder\s+(revenue|stock|kpi)\b',
)


class AiNoFabricateTests(unittest.TestCase):
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
            ('AI Widget', 'AI1', 70.0, 30.0, 12, 5),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_system_prompt_forbids_invented_numbers(self):
        from desktop.utils.ai.prompts import build_system_prompt, load_library

        lib = load_library(force=True)
        general = ((lib.get('domains') or {}).get('general') or {}).get('system') or ''
        self.assertIn('Never invent', general)

        prompt = build_system_prompt('dashboard', 'manager')
        low = prompt.lower()
        self.assertIn('never invent', low)
        self.assertIn('fabricate', low)
        for pat in _FABRICATED_PATTERNS:
            self.assertIsNone(re.search(pat, prompt, re.I), pat)

    def test_heuristic_insights_use_real_sale_total(self):
        from desktop.utils.ai.insights import _heuristic_insights, _CACHE

        _CACHE.update({'ts': 0.0, 'data': None, 'user': ''})
        created = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'AI Widget',
                'sku': 'AI1',
                'quantity': 2,
                'unit_price': 70.0,
                'discount': 0,
                'total': 140.0,
            }],
            'subtotal': 140.0,
            'total': 140.0,
            'payment_method': 'Cash',
            'amount_paid': 140.0,
            'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        sale_id = int(created['sale_id'])
        db = self.ac._db()
        sale_day = db.execute(
            "SELECT date(created_at) AS d FROM sales WHERE id=?", (sale_id,)
        ).fetchone()['d']
        db.close()

        sales = self.api.get_sales(start=sale_day, end=sale_day) or []
        self.assertGreaterEqual(len(sales), 1)
        # Force heuristic onto the sale day (UTC vs local date.today skew)
        self.api.get_sales = lambda start=None, end=None, **kw: sales

        data = _heuristic_insights(
            self.api, {'id': 1, 'username': 'mgr', 'role': 'manager'})
        summary = data.get('summary') or ''
        self.assertIn('140', summary.replace(',', ''))
        self.assertEqual(data.get('source'), 'local')
        for pat in _FABRICATED_PATTERNS:
            self.assertIsNone(re.search(pat, summary, re.I), pat)


if __name__ == '__main__':
    unittest.main()
