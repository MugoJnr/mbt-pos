"""Two separate processes try to sell the last unit of one product."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _sell(data_root: str, token: str) -> dict:
    os.environ['MBT_DATA_ROOT'] = data_root
    os.environ['PROGRAMDATA'] = os.path.join(data_root, 'programdata')
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from desktop.utils.api_client import APIClient
    api = APIClient()
    api._role = 'cashier'
    api._user_id = 1
    api._username = 'cashier'
    return api.create_sale({
        'items': [{
            'product_id': 1,
            'product_name': 'Last Unit',
            'sku': 'LAST-1',
            'quantity': 1,
            'unit_price': 40,
            'discount': 0,
            'total': 40,
        }],
        'subtotal': 40,
        'total': 40,
        'payment_method': 'Cash',
        'amount_paid': 40,
        'change_amount': 0,
        'client_token': token,
    })


class TwoProcessLastUnitTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'data', 'mbt_pos.db')
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (1,'cashier','x:y','cashier')"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES ('Last Unit','LAST-1',40,10,1,0)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _stock(self):
        db = self.ac._db()
        try:
            return float(db.execute("SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        finally:
            db.close()

    def _race_once(self, round_no: int):
        db = self.ac._db()
        db.execute("UPDATE products SET stock=1 WHERE id=1")
        db.commit()
        db.close()
        procs = []
        for side in ('a', 'b'):
            procs.append(subprocess.run(
                [sys.executable, os.path.abspath(__file__), 'sell', self._tmpdir.name, f'race-{round_no}-{side}'],
                check=False,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            ))
        results = []
        for proc in procs:
            self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
            results.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        wins = [row for row in results if row.get('success')]
        self.assertEqual(len(wins), 1, results)
        self.assertEqual(self._stock(), 0)
        db = self.ac._db()
        try:
            sales = db.execute(
                "SELECT COUNT(*) FROM sales WHERE status='completed'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(int(sales), round_no)

    def test_eight_races_sell_the_last_unit_once(self):
        for round_no in range(1, 9):
            self._race_once(round_no)


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'sell':
        outcome = _sell(sys.argv[2], sys.argv[3])
        print(json.dumps({
            'success': bool(outcome.get('success')),
            'error': outcome.get('error') or '',
        }))
    else:
        unittest.main()
