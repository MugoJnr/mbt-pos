"""All Receipts lists the records a role is allowed to open."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ReceiptsCentreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "receipts.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "admin"
        db = ac._db()
        db.execute(
            "INSERT INTO users (id,username,password_hash,role) VALUES (1,'admin','x:y','superadmin')"
        )
        db.execute(
            "INSERT INTO products (name, sku, barcode, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?,?)",
            ("Centre Soap", "CENT-SOAP", "6161888001", 100, 60, 10, 1),
        )
        db.commit()
        db.close()
        self.api.create_sale({
            "items": [{"product_id": 1, "quantity": 2, "unit_price": 100}],
            "subtotal": 200,
            "total": 200,
            "payment_method": "Cash",
            "amount_paid": 200,
            "status": "completed",
            "client_token": "receipts-centre-1",
        })

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_same_day_sale_sorts_above_an_earlier_iso_timestamp(self):
        from backend.receipts_centre import list_receipts
        db = self.ac._db()
        db.execute(
            "UPDATE sales SET created_at=?, sale_date=? WHERE id=1",
            ("2026-10-30 09:37:57", "2026-10-30"),
        )
        db.execute(
            """INSERT INTO stock_consumptions
               (reference_no, date, reason, total_cost, created_by_name, created_at)
               VALUES (?,?,?,?,?,?)""",
            ("AUTO-SORT", "2026-10-30", "Shop use", 30, "qa-cashier", "2026-10-30T02:24:29"),
        )
        db.commit()
        listed = list_receipts(db, can_sales=True, can_consumption=True)
        db.close()
        refs = [item["reference"] for item in listed["receipts"]]
        self.assertGreater(refs.index("AUTO-SORT"), refs.index(listed["receipts"][0]["reference"]))
        self.assertTrue(str(listed["receipts"][0]["reference"]).startswith("RCP-"))

    def test_sale_is_listed_with_name_and_line_total(self):
        from backend.receipts_centre import list_receipts, receipt_detail
        db = self.ac._db()
        listed = list_receipts(db, can_sales=True, query="RCP-")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["receipts"][0]["kind"], "sale")
        self.assertIn("Centre Soap", listed["receipts"][0]["summary"])
        detail = receipt_detail(db, "sale", listed["receipts"][0]["id"], show_cost=False)
        db.close()
        self.assertEqual(detail["lines"][0]["product_name"], "Centre Soap")
        self.assertAlmostEqual(float(detail["lines"][0]["total"]), 200.0, places=2)
        self.assertIsNone(detail["debt"])

    def test_credit_receipt_shows_the_saved_tender_and_debt(self):
        from backend.receipts_centre import receipt_detail
        db = self.ac._db()
        db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('Ada Buyer', '0700', 1)")
        db.commit()
        customer_id = db.execute("SELECT id FROM customers").fetchone()["id"]
        db.close()
        sale = self.api.create_sale({
            "items": [{"product_id": 1, "quantity": 1, "unit_price": 100}],
            "subtotal": 100,
            "total": 100,
            "payment_method": "part payment",
            "amount_paid": 40,
            "customer_id": customer_id,
            "payment_tenders": [
                {"method": "Cash", "amount": 40},
                {"method": "Credit", "amount": 60},
            ],
            "client_token": "receipts-credit",
        })
        self.assertTrue(sale.get("success"), sale)
        db = self.ac._db()
        detail = receipt_detail(db, "sale", sale["sale_id"], show_cost=False)
        db.close()
        self.assertEqual(detail["customer"]["name"], "Ada Buyer")
        self.assertIn("Cash", [row["method"] for row in detail["tenders"]])
        self.assertAlmostEqual(float(detail["debt"]["balance"]), 60.0, places=2)

    def test_voided_sale_stays_in_the_list(self):
        from backend.receipts_centre import list_receipts
        self.api.void_sale(1, "Listed while voided")
        db = self.ac._db()
        listed = list_receipts(db, can_sales=True)
        db.close()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["receipts"][0]["display_status"], "voided")

    def test_cashier_query_does_not_include_hidden_kinds(self):
        from backend.receipts_centre import list_receipts
        db = self.ac._db()
        listed = list_receipts(db, can_sales=True, kind="consumption")
        db.close()
        self.assertEqual(listed["total"], 0)

    def test_exact_receipt_is_found_after_a_thousand_newer_sales(self):
        from backend.receipts_centre import list_receipts, receipt_detail
        db = self.ac._db()
        db.execute(
            "UPDATE sales SET receipt_number=?, sale_date=?, created_at=? WHERE id=1",
            ("RCP-OLD-MONTHS", "2026-01-15", "2026-01-15 08:00:00"),
        )
        db.executemany(
            """INSERT INTO sales
               (receipt_number, created_at, sale_date, cashier_name, subtotal, total,
                amount_paid, status, payment_method)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (f"RCP-NEW-{index}", "2026-11-26 12:00:00", "2026-11-26", "qa",
                 1, 1, 1, "completed", "Cash")
                for index in range(1100)
            ],
        )
        db.execute(
            """INSERT INTO sale_edits
               (sale_id, edit_type, field_name, old_value, new_value, reason, edited_by_name)
               VALUES (1, 'NOTE', 'customer', 'Ada', 'Ada Buyer', 'Name corrected', 'QA Cashier')"""
        )
        db.commit()
        listed = list_receipts(
            db, can_sales=True, query="RCP-OLD-MONTHS",
            start="2026-11-26", end="2026-11-26",
        )
        self.assertTrue(listed["searched_all_dates"])
        self.assertEqual(
            [row["reference"] for row in listed["receipts"] if row["kind"] == "sale"],
            ["RCP-OLD-MONTHS"],
        )
        detail = receipt_detail(db, "sale", 1, show_cost=False)
        db.close()
        self.assertTrue(any(
            item.get("edited_by_name") == "QA Cashier" and item.get("old_value") == "Ada"
            for item in detail["history"]
        ))

    def test_supplier_delivery_and_payment_search_across_dates(self):
        from backend.receipts_centre import list_receipts, receipt_detail
        from desktop.utils.supplier_payables import ensure_schema
        db = self.ac._db()
        ensure_schema(db)
        db.execute("INSERT INTO suppliers (name, phone) VALUES ('Old Mill', '0700')")
        supplier_id = db.execute("SELECT id FROM suppliers").fetchone()["id"]
        db.execute(
            """INSERT INTO stock_receipts
               (receipt_number, supplier_id, reference_note, grand_total, username, created_at, effective_date)
               VALUES ('GRN-OLD-1', ?, 'January flour', 500, 'storeman', '2026-02-02 09:00:00', '2026-02-02')""",
            (supplier_id,),
        )
        receipt_id = db.execute("SELECT id FROM stock_receipts").fetchone()["id"]
        db.execute(
            """INSERT INTO stock_receipt_lines
               (receipt_id, product_name, quantity, unit_cost, line_total)
               VALUES (?, 'Flour', 10, 50, 500)""",
            (receipt_id,),
        )
        db.execute(
            """INSERT INTO supplier_payments
               (payment_number, supplier_id, amount, method, reference, username, paid_at, created_at)
               VALUES ('SPY-OLD-1', ?, 500, 'Cash', 'GRN-OLD-1', 'owner', '2026-02-03', '2026-02-03 10:00:00')""",
            (supplier_id,),
        )
        db.commit()
        delivery = list_receipts(
            db, can_inventory=True, can_finance=False, query="GRN-OLD-1",
            start="2026-11-26", end="2026-11-26",
        )
        payment = list_receipts(
            db, can_finance=True, query="SPY-OLD-1",
            start="2026-11-26", end="2026-11-26",
        )
        hidden = list_receipts(
            db, can_sales=True, query="SPY-OLD-1",
            start="2026-11-26", end="2026-11-26",
        )
        opened = receipt_detail(db, "supplier", receipt_id, show_cost=False)
        owner = receipt_detail(db, "supplier", receipt_id, show_cost=True)
        db.close()
        self.assertEqual(delivery["receipts"][0]["reference"], "GRN-OLD-1")
        self.assertIsNone(delivery["receipts"][0]["amount"])
        self.assertEqual(payment["receipts"][0]["kind"], "supplier_payment")
        self.assertEqual(hidden["total"], 0)
        self.assertNotIn("unit_cost", opened["lines"][0])
        self.assertIn("unit_cost", owner["lines"][0])

    def test_exact_receipt_is_found_after_a_thousand_newer_sales(self):
        from backend.receipts_centre import list_receipts, receipt_detail
        db = self.ac._db()
        db.execute(
            "UPDATE sales SET receipt_number=?, sale_date=?, created_at=? WHERE id=1",
            ("RCP-OLD-MONTHS", "2026-01-15", "2026-01-15 08:00:00"),
        )
        db.executemany(
            """INSERT INTO sales
               (receipt_number, created_at, sale_date, cashier_name, total, status,
                payment_method, subtotal, amount_paid)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (f"RCP-NEW-{index}", "2026-11-26 12:00:00", "2026-11-26", "qa",
                 1, "completed", "Cash", 1, 1)
                for index in range(1100)
            ],
        )
        db.execute(
            """INSERT INTO sale_edits
               (sale_id, edit_type, field_name, old_value, new_value, reason, edited_by_name)
               VALUES (1, 'NOTE', 'customer', 'Walk-in', 'Ada Buyer', 'Name added', 'QA Cashier')"""
        )
        db.commit()
        listed = list_receipts(
            db, can_sales=True, query="RCP-OLD-MONTHS",
            start="2026-11-26", end="2026-11-26",
        )
        self.assertTrue(listed["searched_all_dates"])
        self.assertEqual(
            [row["reference"] for row in listed["receipts"] if row["kind"] == "sale"],
            ["RCP-OLD-MONTHS"],
        )
        detail = receipt_detail(db, "sale", 1, show_cost=False)
        db.close()
        self.assertEqual(detail["reference"], "RCP-OLD-MONTHS")
        self.assertTrue(any(item.get("edit_type") == "NOTE" for item in detail["history"]))
        self.assertNotIn("cost", detail["header"])

    def test_supplier_delivery_and_payment_stay_separate_and_hidden_from_a_cashier(self):
        from backend.receipts_centre import list_receipts
        from desktop.utils.supplier_payables import ensure_schema
        db = self.ac._db()
        ensure_schema(db)
        db.execute("INSERT INTO suppliers (name, phone) VALUES ('Old Mill', '0700')")
        supplier_id = db.execute("SELECT id FROM suppliers").fetchone()["id"]
        db.execute(
            """INSERT INTO stock_receipts
               (receipt_number, supplier_id, grand_total, username, created_at, effective_date)
               VALUES ('GRN-OLD-1', ?, 500, 'store', '2026-02-02 09:00:00', '2026-02-02')""",
            (supplier_id,),
        )
        receipt_id = db.execute("SELECT id FROM stock_receipts").fetchone()["id"]
        db.execute(
            """INSERT INTO stock_receipt_lines (receipt_id, product_name, quantity, unit_cost, line_total)
               VALUES (?, 'Flour', 10, 50, 500)""",
            (receipt_id,),
        )
        db.execute(
            """INSERT INTO supplier_payments
               (payment_number, supplier_id, amount, method, reference, username, created_at, status)
               VALUES ('SP-OLD-1', ?, 200, 'Cash', 'CHQ-9', 'owner', '2026-03-03 09:00:00', 'posted')""",
            (supplier_id,),
        )
        db.commit()
        hidden = list_receipts(
            db, can_inventory=True, can_finance=False, query="GRN-OLD-1",
            start="2026-11-26", end="2026-11-26",
        )
        self.assertEqual(
            [row["reference"] for row in hidden["receipts"]],
            ["GRN-OLD-1"],
        )
        self.assertIsNone(hidden["receipts"][0]["amount"])
        paid = list_receipts(
            db, can_finance=True, query="SP-OLD-1",
            start="2026-11-26", end="2026-11-26",
        )
        db.close()
        self.assertEqual([row["reference"] for row in paid["receipts"]], ["SP-OLD-1"])
        self.assertEqual(paid["receipts"][0]["kind"], "supplier_payment")
        self.assertEqual(paid["receipts"][0]["party"], "Old Mill")


if __name__ == "__main__":
    unittest.main()
