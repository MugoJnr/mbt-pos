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


if __name__ == "__main__":
    unittest.main()
