"""Shared receipt layout and direct printing, including a virtual printer."""
from __future__ import annotations

import os
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest

_PORT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PORT not in sys.path:
    sys.path.insert(0, _PORT)

_ROOT = tempfile.mkdtemp(prefix="mbt-receipt-")
os.environ["MBT_DATA_ROOT"] = _ROOT
os.environ["APPDATA"] = os.path.join(_ROOT, "appdata")
os.environ["LOCALAPPDATA"] = os.path.join(_ROOT, "localappdata")
os.environ["PROGRAMDATA"] = os.path.join(_ROOT, "programdata")
os.environ["MBT_TEST_INSTANCE"] = "1"
os.makedirs(os.path.join(_ROOT, "data"), exist_ok=True)
open(os.path.join(_ROOT, "data", ".initialized"), "w").close()

EVIDENCE = r"C:\MBT_Build\qa-receipts-20261111\evidence\renders"


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE system_settings (key TEXT, value TEXT);
        CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, unit TEXT, sku TEXT);
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY, receipt_number TEXT, total REAL, amount_paid REAL,
            status TEXT, created_at TEXT, sale_date TEXT, cashier_name TEXT,
            payment_method TEXT, discount REAL, tax REAL, change_amount REAL,
            customer_name TEXT, customer_phone TEXT, customer_id INTEGER,
            payment_tenders TEXT, electronic_paid REAL, cash_paid REAL, mpesa_ref TEXT
        );
        CREATE TABLE sale_items (
            id INTEGER PRIMARY KEY, sale_id INTEGER, product_name TEXT, quantity REAL,
            unit TEXT, unit_price REAL, discount REAL, total REAL
        );
        CREATE TABLE debt_invoices (
            id INTEGER PRIMARY KEY, sale_id INTEGER, status TEXT, invoice_number TEXT,
            total_amount REAL, amount_paid REAL, balance REAL, due_date TEXT,
            customer_name TEXT, customer_phone TEXT
        );
        CREATE TABLE debt_payments (
            id INTEGER PRIMARY KEY, invoice_id INTEGER, payment_receipt TEXT, amount REAL,
            payment_method TEXT, notes TEXT, created_at TEXT, cashier_name TEXT,
            balance_before REAL, balance_after REAL, reversed INTEGER
        );
        CREATE TABLE stock_consumptions (
            id INTEGER PRIMARY KEY, reference_no TEXT, date TEXT, created_at TEXT,
            created_by_name TEXT, department_id INTEGER, taken_by TEXT, reason TEXT,
            notes TEXT, voided INTEGER, total_cost REAL, void_reason TEXT
        );
        CREATE TABLE stock_consumption_items (
            id INTEGER PRIMARY KEY, consumption_id INTEGER, product_id INTEGER,
            product_name TEXT, quantity REAL, unit TEXT, unit_cost REAL, total_cost REAL
        );
        CREATE TABLE stock_movements (id INTEGER PRIMARY KEY, movement_type TEXT, reference TEXT);
        """
    )
    conn.execute("INSERT INTO system_settings (key, value) VALUES ('shop_name', 'QA Shop')")
    conn.execute("INSERT INTO system_settings (key, value) VALUES ('paper_size', '80')")
    conn.execute("INSERT INTO departments (id, name) VALUES (1, 'Kitchen')")
    return conn


class ReceiptPrintingTests(unittest.TestCase):
    def test_58_and_80_keep_every_line_inside_the_paper(self):
        from printing.sheet import columns_for, sale_item_lines
        items = [
            {"product_name": "Sugar", "quantity": 2, "unit": "kg", "unit_price": 80, "total": 160},
            {"product_name": "Very long cooking oil name that must wrap on narrow paper", "quantity": 1.25, "unit": "kg", "unit_price": 100, "total": 125},
            {"product_name": "Bar soap", "quantity": 3, "unit": "pcs", "unit_price": 55, "total": 165},
        ]
        for paper in ("58", "80"):
            width = columns_for(paper)
            lines = sale_item_lines(items, width)
            self.assertTrue(lines)
            self.assertTrue(all(len(line) <= width for line in lines), lines)
            self.assertIn("1.25 kg", "\n".join(lines))

    def test_consumption_is_not_a_sale_and_hides_cost_from_a_cashier(self):
        from printing.direct import render_text
        db = _db()
        db.execute(
            """INSERT INTO stock_consumptions
               (id, reference_no, date, created_at, created_by_name, department_id, taken_by, reason, notes, voided, total_cost)
               VALUES (1, 'AUTO-000009', '2026-11-10', '2026-11-11T09:00:00', 'cashier1', 1, 'Kitchen', 'Office Use', 'Tea', 0, 9876.54)"""
        )
        db.execute(
            """INSERT INTO stock_consumption_items
               (id, consumption_id, product_id, product_name, quantity, unit, unit_cost, total_cost)
               VALUES (1, 1, 2, 'Sugar', 0.25, 'kg', 80, 9876.54)"""
        )
        db.commit()
        hidden = render_text(db, "consumption", 1, {"role": "cashier"})
        text = hidden["text"]
        self.assertIn("INTERNAL CONSUMPTION", text)
        self.assertIn("No customer payment", text)
        self.assertIn("2026-11-10", text)
        self.assertNotIn("9876.54", text)
        self.assertNotIn("Amount paid", text)
        shown = render_text(db, "consumption", 1, {"role": "admin"})
        self.assertIn("9,876.54", shown["text"])
        self.assertEqual(render_text(db, "consumption", 1, {"role": ""}).get("status"), 403)

    def test_sale_layout_shows_split_payment_credit_and_void_without_changing_rows(self):
        from printing.direct import render_text, submit
        db = _db()
        db.execute(
            """INSERT INTO sales
               (id, receipt_number, total, amount_paid, status, created_at, sale_date, cashier_name,
                payment_method, discount, tax, change_amount, customer_name, payment_tenders, cash_paid, electronic_paid)
               VALUES (1, 'RCP-100', 280, 280, 'completed', '2026-11-11T10:00:00', '2026-11-10', 'cashier1',
                       'mixed', 0, 0, 20, 'Amina',
                       '[{"method":"Cash","amount":100,"status":"confirmed"},{"method":"M-Pesa","amount":180,"status":"confirmed"}]',
                       100, 180)"""
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_name, quantity, unit, unit_price, discount, total) VALUES (1, 1, 'Sugar', 2, 'kg', 80, 0, 160)"
        )
        db.execute(
            "INSERT INTO sale_items (id, sale_id, product_name, quantity, unit, unit_price, discount, total) VALUES (2, 1, 'Cooking oil', 1, 'pcs', 120, 0, 120)"
        )
        db.commit()
        text = render_text(db, "sale", 1, {"role": "cashier"})["text"]
        self.assertIn("Business date:", text)
        self.assertIn("Cash", text)
        self.assertIn("M-Pesa", text)
        self.assertLessEqual(max(len(line) for line in text.splitlines()), 48)
        before = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        sink = os.path.join(_ROOT, "job.bin")
        os.environ["MBT_PRINTER_SINK"] = sink
        try:
            first = submit(db, "sale", 1, {"role": "cashier"}, reprint=True)
            size = os.path.getsize(sink)
            second = submit(db, "sale", 1, {"role": "cashier"}, reprint=False)
        finally:
            os.environ.pop("MBT_PRINTER_SINK", None)
        self.assertTrue(first.get("printed"))
        self.assertTrue(first.get("unchanged"))
        self.assertTrue(second.get("duplicate"))
        self.assertEqual(os.path.getsize(sink), size)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], before)
        self.assertEqual(db.execute("SELECT total FROM sales WHERE id=1").fetchone()[0], 280)

    def test_virtual_printer_receives_the_real_bytes_and_a_dead_printer_fails(self):
        from printing.printer_engine import print_document_bytes, text_to_escpos
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        server.settimeout(3)
        port = server.getsockname()[1]
        found = {}

        def accept():
            while "data" not in found:
                try:
                    conn, _addr = server.accept()
                except OSError:
                    return
                conn.settimeout(1)
                data = b""
                try:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                except OSError:
                    pass
                conn.close()
                if b"HELLO" in data:
                    found["data"] = data

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        payload = text_to_escpos("HELLO\nSugar", "RCP-100")
        outcome = print_document_bytes(
            {"printer_connection": "LAN", "printer_host": f"127.0.0.1:{port}", "printer_language": "escpos"},
            payload, label="RCP-100", text="HELLO\nSugar",
        )
        thread.join(3)
        server.close()
        self.assertTrue(outcome.get("printed"))
        self.assertIn(b"\x1b@", found.get("data") or b"")
        self.assertIn(b"HELLO", found.get("data") or b"")
        self.assertIn(b"\x1d", found.get("data") or b"")
        missing = print_document_bytes(
            {"printer_connection": "LAN", "printer_host": "127.0.0.1:1", "printer_language": "escpos"},
            payload, label="RCP-404", text="HELLO",
        )
        self.assertFalse(missing.get("printed"))
        self.assertEqual(missing.get("status"), "failed")
        windows = print_document_bytes(
            {"printer_connection": "Windows", "printer_name": "MBT Missing Printer", "printer_language": "escpos"},
            payload, label="RCP-WIN", text="HELLO",
        )
        self.assertFalse(windows.get("printed"))
        self.assertNotEqual(windows.get("status"), "submitted")

    def test_rendered_samples_are_saved(self):
        from PIL import Image, ImageDraw, ImageFont
        from printing.direct import render_text
        from printing.sheet import columns_for, consumption_lines, sale_item_lines
        os.makedirs(EVIDENCE, exist_ok=True)
        db = _db()
        db.execute("UPDATE system_settings SET value='58' WHERE key='paper_size'")
        db.execute(
            """INSERT INTO stock_consumptions
               (id, reference_no, date, created_at, created_by_name, department_id, taken_by, reason, notes, voided, total_cost, void_reason)
               VALUES (2, 'AUTO-000001', '2026-11-10', '2026-11-11T09:00:00', 'admin', 1, 'Kitchen', 'Production', 'Long note for the office tea and the staff lunch that must stay on the slip', 1, 20, 'Entered twice')"""
        )
        db.execute(
            """INSERT INTO stock_consumption_items
               (id, consumption_id, product_id, product_name, quantity, unit, unit_cost, total_cost)
               VALUES (2, 2, 2, 'Sugar', 0.25, 'kg', 80, 20)"""
        )
        db.commit()
        samples = {
            "58-items": "\n".join(sale_item_lines([
                {"product_name": "Sugar", "quantity": 2, "unit": "kg", "unit_price": 80, "total": 160},
            ], columns_for("58"))),
            "80-items": "\n".join(sale_item_lines([
                {"product_name": "Cooking oil with a long shelf name", "quantity": 1, "unit": "pcs", "unit_price": 120, "total": 120},
                {"product_name": "Bar soap", "quantity": 3, "unit": "pcs", "unit_price": 55, "total": 165},
            ], columns_for("80"))),
            "consumption-void": render_text(db, "consumption", 2, {"role": "admin"})["text"],
        }
        font = ImageFont.load_default()
        for name, text in samples.items():
            lines = text.splitlines() or [""]
            image = Image.new("RGB", (560, 16 * (len(lines) + 2)), "white")
            draw = ImageDraw.Draw(image)
            for index, line in enumerate(lines):
                draw.text((8, 8 + index * 14), line, fill="black", font=font)
            image.save(os.path.join(EVIDENCE, f"{name}.png"))
            self.assertTrue(os.path.getsize(os.path.join(EVIDENCE, f"{name}.png")) > 100)
        voided = samples["consumption-void"]
        self.assertIn("VOIDED", voided)
        self.assertIn("INTERNAL CONSUMPTION", voided)
        self.assertNotIn("Amount paid", voided)


if __name__ == "__main__":
    unittest.main()
