"""Portal profit must equal the till's FIFO profit. A missing cost is not profit."""
import sqlite3
import unittest

from backend.cloud.owner_profit import allocate_sale_profits, apply_product_card_costs
from backend.cloud_backup.sync_manager import serialize_entity_payload
from desktop.utils.security import has_permission
from desktop.utils.stock_layers import (
    add_layer,
    backfill_sale_line_costs,
    batch_price_sale_review,
    consume_layer,
    period_profit,
    quote_chosen_batches,
    quote_customer_lines,
    quote_fifo_sell_prices,
    record_sale_cost,
    restore_sale_layers,
    restore_sale_product_qty,
    set_batch_sell_price,
    stamp_sale_costs,
)


def _shop():
    db = sqlite3.connect(':memory:')
    db.execute(
        "CREATE TABLE sales ("
        "id INTEGER PRIMARY KEY, sale_date TEXT, created_at TEXT, status TEXT, total REAL)"
    )
    db.execute(
        "CREATE TABLE sale_items ("
        "id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER, "
        "product_name TEXT, quantity REAL, unit_price REAL, discount REAL, total REAL)"
    )
    return db


def _portal_sale(sale_id, total, method='cash', paid=None, status='completed'):
    if paid is None:
        paid = total
    return {
        'device_id': 'shop',
        'source_id': str(sale_id),
        'payment_method': method,
        'total': total,
        'amount_paid': paid,
        'change_amount': 0,
        'status': status,
        'source_created_at': '2026-11-02T10:00:00+03:00',
    }


def _portal_line(db, sale_id):
    row = db.execute(
        "SELECT quantity, total, unit_cost, costed_qty, line_cost, "
        "COALESCE(returned_qty, 0) FROM sale_items WHERE sale_id=?",
        (sale_id,),
    ).fetchone()
    return {
        'device_id': 'shop',
        'sale_source_id': str(sale_id),
        'quantity': row[0],
        'total': row[1],
        'unit_cost': row[2],
        'costed_qty': row[3],
        'line_cost': row[4],
        'returned_qty': row[5],
        'product_name': 'Maize',
    }


class FifoPortalProfit(unittest.TestCase):
    def test_blended_batches_match_the_till(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 300)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (1, 1, 7, 'Maize', 3, 300)"
        )
        self.assertTrue(add_layer(db, 7, 2, 40, 'receipt', 'a').get('success'))
        self.assertTrue(add_layer(db, 7, 2, 70, 'receipt', 'b').get('success'))
        recorded = record_sale_cost(db, 7, 3, sale_id=1, reference='RCP-1')
        self.assertEqual(recorded['cogs'], 150.0)
        line = db.execute(
            "SELECT unit_cost, costed_qty, line_cost FROM sale_items WHERE id=1"
        ).fetchone()
        self.assertEqual(line[1], 3.0)
        self.assertEqual(line[2], 150.0)
        self.assertEqual(line[0], 50.0)

        till = period_profit(db, '2026-11-02', '2026-11-02')
        portal = allocate_sale_profits(
            [_portal_sale(1, 300)], [_portal_line(db, 1)], [],
        )
        self.assertEqual(portal['gross_profit'], till['profit'])
        self.assertEqual(portal['cost_of_goods'], till['cogs'])
        self.assertEqual(portal['uncosted_sales'], till['uncosted_revenue'])
        self.assertEqual(portal['gross_profit'], 150.0)
        self.assertEqual(portal['gross_profit_fully_paid'], 150.0)
        self.assertEqual(
            portal['gross_profit_collected'] + portal['gross_profit_outstanding'],
            portal['gross_profit'],
        )

    def test_uncovered_quantity_is_not_turned_into_profit(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 300)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (1, 1, 7, 'Maize', 3, 300)"
        )
        self.assertTrue(add_layer(db, 7, 1, 40, 'receipt', 'a').get('success'))
        record_sale_cost(db, 7, 3, sale_id=1, reference='RCP-1')
        till = period_profit(db, '2026-11-02', '2026-11-02')
        portal = allocate_sale_profits(
            [_portal_sale(1, 300)], [_portal_line(db, 1)], [],
        )
        self.assertEqual(till['profit'], 60.0)
        self.assertEqual(till['uncosted_revenue'], 200.0)
        self.assertEqual(portal['gross_profit'], till['profit'])
        self.assertEqual(portal['cost_of_goods'], till['cogs'])
        self.assertEqual(portal['uncosted_sales'], till['uncosted_revenue'])
        self.assertNotEqual(portal['gross_profit'], 300.0)

    def test_a_return_keeps_only_the_goods_still_sold(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 200)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (1, 1, 7, 'Maize', 2, 200)"
        )
        self.assertTrue(add_layer(db, 7, 2, 50, 'receipt', 'a').get('success'))
        record_sale_cost(db, 7, 2, sale_id=1, reference='RCP-1')
        restored = restore_sale_product_qty(db, 1, 7, 1)
        self.assertTrue(restored.get('success'), restored)
        db.execute("UPDATE sale_items SET returned_qty=1 WHERE id=1")
        stamp_sale_costs(db, 1)
        till = period_profit(db, '2026-11-02', '2026-11-02')
        portal = allocate_sale_profits(
            [_portal_sale(1, 200)], [_portal_line(db, 1)], [],
        )
        self.assertEqual(till['profit'], 50.0)
        self.assertEqual(portal['gross_profit'], 50.0)
        self.assertEqual(portal['uncosted_sales'], 0.0)

    def test_a_void_removes_the_snapshot(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 100)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (1, 1, 7, 'Maize', 1, 100)"
        )
        self.assertTrue(add_layer(db, 7, 1, 30, 'receipt', 'a').get('success'))
        record_sale_cost(db, 7, 1, sale_id=1, reference='RCP-1')
        restore_sale_layers(db, 1)
        line = db.execute("SELECT unit_cost, line_cost FROM sale_items WHERE id=1").fetchone()
        self.assertIsNone(line[0])
        self.assertIsNone(line[1])
        portal = allocate_sale_profits(
            [_portal_sale(1, 100, status='voided')], [_portal_line(db, 1)], [],
        )
        self.assertEqual(portal['gross_profit'], 0.0)

    def test_backfill_is_idempotent_and_a_new_shop_gets_the_columns(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 80)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (1, 1, 7, 'Maize', 2, 80)"
        )
        self.assertTrue(add_layer(db, 7, 2, 15, 'receipt', 'a').get('success'))
        record_sale_cost(db, 7, 2, sale_id=1, reference='RCP-1')
        db.execute("UPDATE sale_items SET unit_cost=NULL, costed_qty=NULL, line_cost=NULL")
        first = backfill_sale_line_costs(db)
        second = backfill_sale_line_costs(db)
        self.assertEqual(first['updated'], 1)
        self.assertEqual(second['updated'], 0)
        line = db.execute("SELECT line_cost FROM sale_items").fetchone()
        self.assertEqual(line[0], 30.0)
        cols = {row[1] for row in db.execute("PRAGMA table_info(sale_items)").fetchall()}
        self.assertTrue({'unit_cost', 'costed_qty', 'line_cost', 'returned_qty'} <= cols)

    def test_two_lines_of_one_product_are_not_costed_twice(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 300)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (1, 1, 7, 'Maize', 1, 100)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, total) "
            "VALUES (2, 1, 7, 'Maize', 1, 200)"
        )
        self.assertTrue(add_layer(db, 7, 2, 40, 'receipt', 'a').get('success'))
        record_sale_cost(db, 7, 1, sale_id=1, reference='RCP-1')
        record_sale_cost(db, 7, 1, sale_id=1, reference='RCP-1')
        costs = db.execute("SELECT line_cost FROM sale_items ORDER BY id").fetchall()
        self.assertEqual([row[0] for row in costs], [40.0, 40.0])
        self.assertEqual(sum(row[0] for row in costs), 80.0)

    def test_a_missing_cloud_cost_is_not_the_sales_total(self):
        portal = allocate_sale_profits(
            [_portal_sale(1, 280701)],
            [{
                'device_id': 'shop',
                'sale_source_id': '1',
                'quantity': 12,
                'total': 280701,
                'unit_cost': None,
                'product_name': 'Unguarded',
            }],
            [],
        )
        self.assertEqual(portal['gross_profit'], 0.0)
        self.assertEqual(portal['uncosted_sales'], 280701.0)
        self.assertEqual(portal['uncosted_lines'], 1)

    def test_credit_profit_uses_the_fifo_cost(self):
        portal = allocate_sale_profits(
            [_portal_sale(2, 1000, method='credit sale', paid=0)],
            [{
                'device_id': 'shop',
                'sale_source_id': '2',
                'quantity': 1,
                'total': 1000,
                'unit_cost': 400,
                'costed_qty': 1,
                'line_cost': 400,
            }],
            [{
                'device_id': 'shop',
                'sale_source_id': '2',
                'balance': 1000,
                'status': 'pending',
            }],
        )
        self.assertEqual(portal['gross_profit'], 600.0)
        self.assertEqual(portal['gross_profit_credit'], 600.0)
        self.assertEqual(portal['gross_profit_outstanding'], 600.0)
        self.assertNotEqual(portal['gross_profit_credit'], 1000.0)

    def test_the_product_card_is_not_the_cost_of_a_sale(self):
        items = [{
            'device_id': 'shop',
            'product_source_id': '7',
            'sale_source_id': '1',
            'quantity': 2,
            'total': 1000,
            'unit_cost': None,
            'cost_price': 40,
        }]
        products = [
            {'device_id': 'shop', 'source_id': '7', 'cost_price': 40},
            {'device_id': 'other-shop', 'source_id': '7', 'cost_price': 5},
        ]
        self.assertEqual(apply_product_card_costs(items, products), 0)
        result = allocate_sale_profits([_portal_sale(1, 1000)], items, [])
        self.assertEqual(result['cost_of_goods'], 0.0)
        self.assertEqual(result['gross_profit'], 0.0)
        self.assertEqual(result['uncosted_sales'], 1000.0)

    def test_two_delivery_prices_stay_on_their_own_batches(self):
        db = _shop()
        db.execute(
            "INSERT INTO sales VALUES (1, '2026-11-02', '2026-11-02 10:00:00', 'completed', 8400)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_id, product_name, quantity, unit_price, total) "
            "VALUES (1, 1, 7, 'Maize', 120, 70, 8400)"
        )
        self.assertTrue(add_layer(db, 7, 100, 40, 'receipt', 'old').get('success'))
        self.assertTrue(add_layer(db, 7, 100, 55, 'receipt', 'new', purchase_unit_cost=55).get('success'))
        recorded = record_sale_cost(db, 7, 120, sale_id=1, reference='RCP-120')
        self.assertEqual(recorded['cogs'], 5100.0)
        layers = db.execute(
            "SELECT source_id, remaining_qty, unit_cost FROM cost_layers ORDER BY id"
        ).fetchall()
        self.assertEqual([tuple(row) for row in layers], [('old', 0.0, 40.0), ('new', 80.0, 55.0)])
        line = _portal_line(db, 1)
        line['cost_price'] = 55
        result = allocate_sale_profits([_portal_sale(1, 8400)], [line], [])
        self.assertEqual(result['cost_of_goods'], 5100.0)
        self.assertEqual(result['gross_profit'], 3300.0)

    def test_a_synced_sale_cost_wins_over_the_product_card(self):
        items = [{
            'device_id': 'shop',
            'product_source_id': '7',
            'sale_source_id': '1',
            'quantity': 1,
            'total': 1000,
            'unit_cost': 10,
            'line_cost': 10,
        }]
        apply_product_card_costs(items, [
            {'device_id': 'shop', 'source_id': '7', 'cost_price': 400},
        ])
        result = allocate_sale_profits([_portal_sale(1, 1000)], items, [])
        self.assertEqual(result['cost_of_goods'], 10.0)
        self.assertEqual(result['gross_profit'], 990.0)

    def test_a_zero_without_a_batch_is_unknown_not_the_card_price(self):
        items = [{
            'device_id': 'shop',
            'product_source_id': '7',
            'sale_source_id': '1',
            'quantity': 2,
            'total': 1000,
            'unit_cost': 0,
            'cost_price': 40,
        }]
        self.assertEqual(apply_product_card_costs(items, [
            {'device_id': 'shop', 'source_id': '7', 'cost_price': 40},
        ]), 0)
        result = allocate_sale_profits([_portal_sale(1, 1000)], items, [])
        self.assertEqual(result['cost_of_goods'], 0.0)
        self.assertEqual(result['gross_profit'], 0.0)
        self.assertEqual(result['uncosted_sales'], 1000.0)

    def test_free_stock_with_a_recorded_zero_cost_is_profit(self):
        items = [{
            'device_id': 'shop',
            'sale_source_id': '1',
            'quantity': 2,
            'total': 200,
            'unit_cost': 0,
            'costed_qty': 2,
            'line_cost': 0,
        }]
        result = allocate_sale_profits([_portal_sale(1, 200)], items, [])
        self.assertEqual(result['cost_of_goods'], 0.0)
        self.assertEqual(result['gross_profit'], 200.0)
        self.assertEqual(result['uncosted_sales'], 0.0)

    def test_a_blank_buying_price_is_still_not_profit(self):
        items = [{
            'device_id': 'shop',
            'product_source_id': '8',
            'sale_source_id': '1',
            'quantity': 1,
            'total': 80,
            'unit_cost': None,
        }]
        self.assertEqual(apply_product_card_costs(items, [
            {'device_id': 'shop', 'source_id': '8', 'cost_price': 0},
        ]), 0)
        result = allocate_sale_profits([_portal_sale(1, 80)], items, [])
        self.assertEqual(result['gross_profit'], 0.0)
        self.assertEqual(result['uncosted_sales'], 80.0)

    def test_sync_sends_the_snapshot_and_skips_a_blank_cost(self):
        sent = serialize_entity_payload('sale_item', {
            'id': 4,
            'sale_id': 1,
            'product_id': 7,
            'product_name': 'Maize',
            'quantity': 3,
            'unit_price': 100,
            'unit_cost': 50,
            'costed_qty': 3,
            'line_cost': 150,
            'returned_qty': 0,
            'discount': 0,
            'total': 300,
        })
        self.assertEqual(sent['unit_cost'], 50)
        self.assertEqual(sent['line_cost'], 150)
        self.assertEqual(sent['costed_qty'], 3)
        blank = serialize_entity_payload('sale_item', {
            'id': 5, 'sale_id': 1, 'quantity': 1, 'total': 10, 'unit_cost': None,
        })
        self.assertNotIn('unit_cost', blank)

    def test_a_custom_batch_price_survives_a_product_price_change(self):
        db = _shop()
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, price REAL)")
        db.execute("INSERT INTO products VALUES (7, 70)")
        first = add_layer(db, 7, 100, 40, 'receipt', 'old')
        second = add_layer(db, 7, 100, 55, 'receipt', 'new')
        priced = set_batch_sell_price(db, second['id'], 90, username='edmus')
        self.assertTrue(priced.get('success'))
        self.assertEqual(priced['warning'], '')
        db.execute("UPDATE products SET price=80 WHERE id=7")
        quote = quote_fifo_sell_prices(db, 7, 120, 80)
        self.assertEqual(
            [(part['quantity'], part['unit_price'], part['price_mode']) for part in quote['segments']],
            [(100, 80, 'normal'), (20, 90, 'custom')],
        )
        self.assertEqual(quote['total'], 9800.0)
        cleared = set_batch_sell_price(db, second['id'], None)
        self.assertEqual(cleared['price_mode'], 'normal')
        again = quote_fifo_sell_prices(db, 7, 20, 80)
        self.assertEqual(again['segments'][0]['unit_price'], 80)
        low = set_batch_sell_price(db, first['id'], 10)
        self.assertIn('below the landed cost', low['warning'])

    def test_a_custom_batch_price_splits_the_sale_before_payment(self):
        db = _shop()
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
        db.execute("INSERT INTO products VALUES (7, 'Oil', 70)")
        older = add_layer(db, 7, 20, 40, 'receipt', 'older')
        newer = add_layer(db, 7, 50, 50, 'receipt', 'newer')
        set_batch_sell_price(db, newer['id'], 65)
        self.assertIsNone(batch_price_sale_review(db, [{
            'product_id': 7, 'quantity': 10, 'unit_price': 60,
        }]))
        review = batch_price_sale_review(db, [{
            'product_id': 7, 'quantity': 35, 'unit_price': 70,
        }])
        self.assertEqual(review['code'], 'batch_price_review')
        parts = [(part['quantity'], part['unit_price']) for part in review['lines'][0]['segments']]
        self.assertEqual(parts, [(20, 70.0), (15, 65.0)])
        self.assertEqual(review['lines'][0]['expected'], 2375.0)
        shown = quote_customer_lines(db, 7, 35, 70, 'Oil')
        self.assertEqual(
            [(line['label'], line['quantity'], line['unit_price']) for line in shown['lines']],
            [('Oil · B001', 20, 70.0), ('Oil · B002', 15, 65.0)],
        )
        self.assertEqual(shown['total'], 2375.0)
        self.assertIsNone(batch_price_sale_review(db, [
            {'product_id': 7, 'quantity': 20, 'unit_price': 70},
            {'product_id': 7, 'quantity': 15, 'unit_price': 65},
        ]))
        self.assertFalse(has_permission({'role': 'cashier'}, 'inventory.batch_price'))
        self.assertTrue(has_permission({'role': 'admin'}, 'inventory.batch_price'))
        self.assertFalse(has_permission({'role': 'cashier'}, 'inventory.sales.override_fifo'))
        self.assertTrue(has_permission({'role': 'admin'}, 'inventory.sales.override_fifo'))
        chosen = quote_chosen_batches(db, 7, [{'layer_id': newer['id'], 'quantity': 10}], 70, 'Oil')
        self.assertEqual(chosen['lines'][0]['label'], 'Oil · B002')
        self.assertEqual(chosen['lines'][0]['unit_price'], 65.0)
        self.assertEqual(chosen['fifo_lines'][0]['label'], 'Oil')
        self.assertEqual(chosen['fifo_lines'][0]['allocations'][0]['batch_ref'], 'B001')
        taken = consume_layer(db, newer['id'], 10, sale_id=1, reference='RCP-O')
        self.assertTrue(taken.get('success'))
        left = db.execute("SELECT remaining_qty FROM cost_layers WHERE id=?", (older['id'],)).fetchone()
        self.assertEqual(float(left[0]), 20.0)
