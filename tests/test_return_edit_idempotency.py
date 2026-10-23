"""A repeated return or sale edit must not move stock twice."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ReturnAndEditIdempotency(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'shop.db')
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
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'owner'
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES ('owner','x:y','superadmin')"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES ('Widget','W1',100,40,50,1)"
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

    def _sale(self, qty=4):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Widget', 'sku': 'W1',
                'quantity': qty, 'unit_price': 100, 'discount': 0, 'total': qty * 100,
            }],
            'subtotal': qty * 100, 'discount': 0, 'tax': 0, 'total': qty * 100,
            'payment_method': 'Cash', 'amount_paid': qty * 100, 'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        lookup = self.api.get_sale_for_return(created['receipt_number'])
        return int(created['sale_id']), int(lookup['items'][0]['id'])

    def test_return_token_applies_once_and_rejects_a_different_payload(self):
        sale_id, line_id = self._sale()
        self.assertEqual(self._stock(), 46)
        bad = self.api.return_sale(
            sale_id, [{'sale_item_id': line_id, 'quantity': -1}], 'bad',
            client_token='ret-1',
        )
        self.assertEqual(bad.get('status'), 400)
        self.assertEqual(self._stock(), 46)
        first = self.api.return_sale(
            sale_id, [{'sale_item_id': line_id, 'quantity': 1}], 'changed mind',
            client_token='ret-1',
        )
        self.assertTrue(first.get('success'), first)
        self.assertEqual(self._stock(), 47)
        again = self.api.return_sale(
            sale_id, [{'sale_item_id': line_id, 'quantity': 1}], 'changed mind',
            client_token='ret-1',
        )
        self.assertTrue(again.get('duplicate'))
        self.assertEqual(again.get('return_sale_id'), first.get('return_sale_id'))
        self.assertEqual(self._stock(), 47)
        clash = self.api.return_sale(
            sale_id, [{'sale_item_id': line_id, 'quantity': 2}], 'changed mind',
            client_token='ret-1',
        )
        self.assertEqual(clash.get('status'), 409)
        self.assertEqual(self._stock(), 47)
        db = self.ac._db()
        try:
            returns = db.execute(
                "SELECT COUNT(*) FROM sales WHERE status='return'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(returns, 1)

    def test_concurrent_return_with_one_token_restocks_once(self):
        sale_id, line_id = self._sale()
        results = []

        def attempt():
            api = self.ac.APIClient()
            api._role = 'manager'
            api._user_id = 1
            api._username = 'owner'
            results.append(api.return_sale(
                sale_id, [{'sale_item_id': line_id, 'quantity': 1}], 'once',
                client_token='ret-race',
            ))

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        successes = [row for row in results if row.get('success') and not row.get('duplicate')]
        duplicates = [row for row in results if row.get('duplicate')]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(self._stock(), 47)

    def test_edit_token_does_not_repeat_the_stock_movement(self):
        sale_id, _line_id = self._sale()
        payload = {
            'reason': 'Customer took fewer',
            'items': [{
                'product_id': 1, 'product_name': 'Widget', 'sku': 'W1',
                'quantity': 2, 'unit_price': 100, 'discount': 0,
            }],
            'discount': 0, 'payment_method': 'Cash', 'amount_paid': 200, 'total': 200,
            'client_token': 'edit-1',
        }
        first = self.api.edit_sale(sale_id, payload)
        self.assertTrue(first.get('success'), first)
        self.assertEqual(self._stock(), 48)
        again = self.api.edit_sale(sale_id, dict(payload))
        self.assertTrue(again.get('duplicate'), again)
        self.assertEqual(self._stock(), 48)
        other = dict(payload)
        other['total'] = 100
        other['amount_paid'] = 100
        other['items'] = [{
            'product_id': 1, 'product_name': 'Widget', 'sku': 'W1',
            'quantity': 1, 'unit_price': 100, 'discount': 0,
        }]
        clash = self.api.edit_sale(sale_id, other)
        self.assertEqual(clash.get('status'), 409)
        self.assertEqual(self._stock(), 48)
        db = self.ac._db()
        try:
            edits = db.execute(
                "SELECT COUNT(*) FROM sale_edits WHERE sale_id=? AND edit_type='EDIT_ITEMS'",
                (sale_id,),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(edits, 1)


if __name__ == '__main__':
    unittest.main()
