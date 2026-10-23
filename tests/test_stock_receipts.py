import sqlite3
import unittest

from web.web_routes import stock_receipt_rows


class StockReceiptRows(unittest.TestCase):
    def test_purchase_keeps_supplier_and_note(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY, name TEXT, sku TEXT, barcode TEXT,
                category TEXT, unit TEXT, price REAL, cost_price REAL,
                stock REAL, min_stock REAL
            );
            CREATE TABLE suppliers (
                id INTEGER PRIMARY KEY, name TEXT, phone TEXT, notes TEXT
            );
            CREATE TABLE stock_movements (
                id INTEGER PRIMARY KEY, product_id INTEGER, product_name TEXT,
                movement_type TEXT, qty_before REAL, qty_change REAL, qty_after REAL,
                reference TEXT, reason TEXT, username TEXT, created_at TEXT
            );
            """
        )
        db.execute(
            "INSERT INTO products VALUES (19, 'QA-STOCK', 'QA', 'BC19', 'General', 'pcs', 25, 0, 6, 5)"
        )
        db.execute(
            "INSERT INTO suppliers VALUES (3, 'QA Supplies Ltd', '0712000111', 'Delivery note DN-1735')"
        )
        db.execute(
            """INSERT INTO stock_movements VALUES
               (1, 19, 'QA-STOCK', 'PURCHASE', 4, 2, 6, 'RECEIVE_sup=3',
                'Received from Supplier: QA Supplies Ltd — Invoice INV-QA-1735',
                'admin', '2026-10-17 04:46:13')"""
        )
        db.execute(
            """INSERT INTO stock_movements VALUES
               (2, 19, 'QA-STOCK', 'SALE', 6, -1, 5, 'RCP', 'sold', 'admin', '2026-10-17')"""
        )
        rows = stock_receipt_rows(db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["supplier_name"], "QA Supplies Ltd")
        self.assertEqual(rows[0]["supplier_phone"], "0712000111")
        self.assertEqual(rows[0]["supplier_notes"], "Delivery note DN-1735")
        self.assertEqual(rows[0]["qty_change"], 2)
        self.assertEqual(rows[0]["price"], 25)
        self.assertEqual(rows[0]["category"], "General")
        self.assertEqual(rows[0]["barcode"], "BC19")
        self.assertIn("INV-QA-1735", rows[0]["reason"])


if __name__ == "__main__":
    unittest.main()
