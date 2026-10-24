"""Sale lines keep an explicit total and fill a missing name from the product."""
import sqlite3
import unittest

from backend.sale_lines import fill_sale_line


class SaleLineTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, sku TEXT)"
        )
        self.db.execute(
            "INSERT INTO products (id, name, sku) VALUES (1, 'Audit Candle', 'QA-CANDLE')"
        )

    def test_missing_total_and_name_come_from_the_product(self):
        line = fill_sale_line(self.db, {
            'product_id': 1,
            'quantity': 2,
            'unit_price': 40,
            'discount': 5,
        })
        self.assertEqual(line['product_name'], 'Audit Candle')
        self.assertEqual(line['sku'], 'QA-CANDLE')
        self.assertEqual(line['total'], 75.0)

    def test_explicit_zero_total_is_kept(self):
        line = fill_sale_line(self.db, {
            'product_id': 1,
            'product_name': 'Audit Candle',
            'sku': 'QA-CANDLE',
            'quantity': 1,
            'unit_price': 40,
            'total': 0,
        })
        self.assertEqual(line['total'], 0.0)

    def test_supplied_name_is_not_replaced(self):
        line = fill_sale_line(self.db, {
            'product_id': 1,
            'product_name': 'Receipt name',
            'quantity': 1,
            'unit_price': 10,
            'total': 10,
        })
        self.assertEqual(line['product_name'], 'Receipt name')
        self.assertEqual(line['sku'], 'QA-CANDLE')


if __name__ == '__main__':
    unittest.main()
