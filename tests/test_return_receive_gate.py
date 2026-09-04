"""P11 return sale + V05 receive stock gates."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _Base(unittest.TestCase):
    PIN = '135790'

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
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'admin'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
            db.execute(
                "UPDATE users SET role='superadmin' WHERE id=?",
                (self.api._user_id,),
            )
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'superadmin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Ret Widget', 'RW1', 100.0, 40.0, 50, 5),
        )
        from desktop.utils.security import _pin_hash
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key,value) VALUES (?,?)",
            ('superadmin_pin_hash', _pin_hash(self.PIN)),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False


class ReturnSaleGate(_Base):
    def test_negative_quantity_and_client_totals_are_not_trusted(self):
        denied = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Ret Widget', 'sku': 'RW1',
                'quantity': -5, 'unit_price': 100.0, 'discount': 0,
                'total': -500.0,
            }],
            'subtotal': -500, 'total': -500,
            'payment_method': 'Cash', 'amount_paid': 0,
        })
        self.assertIn('error', denied)
        db = self.ac._db()
        self.assertEqual(
            float(db.execute(
                "SELECT stock FROM products WHERE id=1").fetchone()['stock']),
            50.0,
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        db.close()

        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Ret Widget', 'sku': 'RW1',
                'quantity': 2, 'unit_price': 100.0, 'discount': 10,
                'total': 1.0,
            }],
            'subtotal': 1, 'discount': 10, 'tax': 999, 'total': 1,
            'payment_method': 'Cash', 'amount_paid': 190,
        })
        self.assertTrue(created.get('success'), created)
        db = self.ac._db()
        sale = db.execute(
            "SELECT subtotal,discount,tax,total FROM sales WHERE id=?",
            (created['sale_id'],),
        ).fetchone()
        line = db.execute(
            "SELECT total FROM sale_items WHERE sale_id=?",
            (created['sale_id'],),
        ).fetchone()
        db.close()
        self.assertEqual(float(sale['subtotal']), 200.0)
        self.assertEqual(float(sale['discount']), 10.0)
        self.assertEqual(float(sale['tax']), 0.0)
        self.assertEqual(float(sale['total']), 190.0)
        self.assertEqual(float(line['total']), 190.0)

    def test_partial_return_restocks_and_nets_revenue(self):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Ret Widget', 'sku': 'RW1',
                'quantity': 4, 'unit_price': 100.0, 'discount': 0, 'total': 400.0,
            }],
            'subtotal': 400, 'total': 400, 'payment_method': 'Cash',
            'amount_paid': 400, 'change_amount': 0,
        })
        self.assertTrue(created.get('success'), created)
        sale_id = int(created['sale_id'])
        lookup = self.api.get_sale_for_return(created['receipt_number'])
        self.assertTrue(lookup.get('success'), lookup)
        line_id = int(lookup['items'][0]['id'])

        mid = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        self.ac._db().close()
        self.assertEqual(mid, 46.0)

        ret = self.api.return_sale(
            sale_id,
            [{'sale_item_id': line_id, 'quantity': 1}],
            'customer changed mind',
            refund_method='Cash',
            pin=self.PIN,
        )
        self.assertTrue(ret.get('success'), ret)
        self.assertAlmostEqual(float(ret['refund_total']), 100.0, places=2)

        db = self.ac._db()
        stock = float(db.execute(
            "SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        returned_qty = float(db.execute(
            "SELECT returned_qty FROM sale_items WHERE id=?", (line_id,)
        ).fetchone()['returned_qty'])
        ret_status = db.execute(
            "SELECT status, total FROM sales WHERE id=?",
            (ret['return_sale_id'],),
        ).fetchone()
        sale_day = db.execute(
            "SELECT date(created_at) AS d FROM sales WHERE id=?", (sale_id,)
        ).fetchone()['d']
        moves = db.execute(
            "SELECT COUNT(*) AS c FROM stock_movements "
            "WHERE movement_type='RETURN_RESTORE' AND product_id=1"
        ).fetchone()['c']
        db.close()

        self.assertEqual(stock, 47.0)
        self.assertEqual(returned_qty, 1.0)
        self.assertEqual(ret_status['status'], 'return')
        self.assertAlmostEqual(float(ret_status['total']), -100.0, places=2)
        self.assertGreaterEqual(int(moves), 1)

        summary = (self.api.get_report_summary(sale_day, sale_day) or {}).get('summary') or {}
        # 400 completed - 100 return = 300 net revenue
        self.assertAlmostEqual(float(summary.get('total_revenue') or 0), 300.0, places=2)

        # Over-return denied
        deny = self.api.return_sale(
            sale_id,
            [{'sale_item_id': line_id, 'quantity': 4}],
            'too much',
            pin=self.PIN,
        )
        self.assertIn('error', deny)

    def test_duplicate_return_line_is_rejected_atomically(self):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Ret Widget', 'sku': 'RW1',
                'quantity': 5, 'unit_price': 100.0, 'discount': 0,
                'total': 500.0,
            }],
            'subtotal': 500, 'total': 500, 'payment_method': 'Cash',
            'amount_paid': 500,
        })
        lookup = self.api.get_sale_for_return(created['receipt_number'])
        line_id = int(lookup['items'][0]['id'])
        denied = self.api.return_sale(
            created['sale_id'],
            [
                {'sale_item_id': line_id, 'quantity': 4},
                {'sale_item_id': line_id, 'quantity': 4},
            ],
            'duplicate payload',
            pin=self.PIN,
        )
        self.assertIn('error', denied)
        db = self.ac._db()
        self.assertEqual(
            float(db.execute(
                "SELECT stock FROM products WHERE id=1").fetchone()['stock']),
            45.0,
        )
        self.assertEqual(
            float(db.execute(
                "SELECT returned_qty FROM sale_items WHERE id=?",
                (line_id,),
            ).fetchone()['returned_qty']),
            0.0,
        )
        db.close()

    def test_cashier_cannot_return(self):
        created = self.api.create_sale({
            'items': [{
                'product_id': 1, 'product_name': 'Ret Widget', 'sku': 'RW1',
                'quantity': 1, 'unit_price': 100.0, 'discount': 0, 'total': 100.0,
            }],
            'subtotal': 100, 'total': 100, 'payment_method': 'Cash',
            'amount_paid': 100, 'change_amount': 0,
        })
        lookup = self.api.get_sale_for_return(created['receipt_number'])
        line_id = int(lookup['items'][0]['id'])
        self.api._role = 'cashier'
        denied = self.api.return_sale(
            created['sale_id'],
            [{'sale_item_id': line_id, 'quantity': 1}],
            'nope',
        )
        self.assertIn('error', denied)


class ReceiveStockGate(_Base):
    def test_receive_increases_stock_with_supplier(self):
        sup = self.api.create_supplier({'name': 'Acme Supplies', 'phone': '0700111222'})
        self.assertTrue(sup.get('success'), sup)
        before = float(self.ac._db().execute(
            "SELECT stock FROM products WHERE id=1").fetchone()['stock'])
        self.ac._db().close()

        # Receiving raises on-hand, so it needs no PIN step-up — only the role.
        res = self.api.receive_stock(
            1, 10, supplier_id=int(sup['id']), notes='delivery #1')
        self.assertTrue(res.get('success'), res)
        self.assertEqual(float(res['new_stock']), before + 10)

        db = self.ac._db()
        move = db.execute(
            "SELECT movement_type, reason FROM stock_movements "
            "WHERE product_id=1 AND movement_type='PURCHASE' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        sid = db.execute(
            "SELECT supplier_id FROM products WHERE id=1"
        ).fetchone()['supplier_id']
        db.close()
        self.assertEqual(move['movement_type'], 'PURCHASE')
        self.assertIn('Acme', move['reason'] or '')
        self.assertEqual(int(sid), int(sup['id']))

    def test_manager_cannot_receive(self):
        self.api._role = 'manager'
        denied = self.api.receive_stock(1, 5)
        self.assertIn('error', denied)


if __name__ == '__main__':
    unittest.main()
