"""Sale documents stay saved when the printer fails, and keep their original numbers."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

_ISOLATION = tempfile.mkdtemp(prefix="mbt-doc-iso-")
os.environ["MBT_DATA_ROOT"] = _ISOLATION
os.environ["APPDATA"] = _ISOLATION
os.environ["LOCALAPPDATA"] = _ISOLATION
os.environ["PROGRAMDATA"] = _ISOLATION
os.environ["MBT_TEST_INSTANCE"] = "1"
os.makedirs(os.path.join(_ISOLATION, "data"), exist_ok=True)
open(os.path.join(_ISOLATION, "data", ".initialized"), "a").close()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DocumentPolicyUnitTests(unittest.TestCase):
    def test_policy_c_follows_payment_status(self):
        from printing.sale_documents import resolve_document_kind, payment_standing
        self.assertEqual(payment_standing(1000, 1000), "paid")
        self.assertEqual(payment_standing(1000, 600), "partial")
        self.assertEqual(payment_standing(1000, 0), "unpaid")
        self.assertEqual(resolve_document_kind("C", "paid"), "receipt")
        self.assertEqual(resolve_document_kind("C", "partial"), "invoice")
        self.assertEqual(resolve_document_kind("C", "unpaid"), "invoice")
        self.assertEqual(resolve_document_kind("A", "unpaid"), "receipt")
        self.assertEqual(resolve_document_kind("B", "paid"), "invoice")
        self.assertEqual(resolve_document_kind("D", "partial"), "invoice")
        self.assertEqual(resolve_document_kind("D", "paid"), "receipt")
        self.assertEqual(resolve_document_kind("E", "paid", "invoice"), "invoice")


class SaleDocumentShopTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "docs.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        os.environ["MBT_TEST_INSTANCE"] = "1"
        os.environ["MBT_PRINTER_SIMULATE"] = "fail"
        os.makedirs(os.path.join(self._tmpdir.name, "data"), exist_ok=True)
        open(os.path.join(self._tmpdir.name, "data", ".initialized"), "a").close()
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("docadmin", ac._hash_pw("doc-pass"), "superadmin", "Doc Admin"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES ('Soap', 'SOAP', 1000, 400, 50, 1)"
        )
        db.execute("INSERT INTO customers (name, phone, is_active) VALUES ('Amina', '0711000000', 1)")
        db.commit()
        self.user_id = db.execute("SELECT id FROM users WHERE username='docadmin'").fetchone()["id"]
        self.customer_id = db.execute("SELECT id FROM customers").fetchone()["id"]
        self.product_id = db.execute("SELECT id FROM products").fetchone()["id"]
        db.close()

    def tearDown(self):
        os.environ.pop("MBT_PRINTER_SIMULATE", None)
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _api(self):
        api = self.ac.APIClient()
        api._user_id = self.user_id
        api._username = "docadmin"
        api._role = "superadmin"
        return api

    def _sale(self, **extra):
        payload = {
            "items": [{
                "product_id": self.product_id,
                "product_name": "Soap",
                "quantity": 1,
                "unit_price": 1000,
                "discount": 0,
                "total": 1000,
            }],
            "subtotal": 1000,
            "discount": 0,
            "tax": 0,
            "total": 1000,
            "original_total": 1000,
            "customer_id": self.customer_id,
        }
        payload.update(extra)
        return payload

    def _count(self, sql):
        db = self.ac._db()
        try:
            return db.execute(sql).fetchone()[0]
        finally:
            db.close()

    def test_printer_failure_keeps_one_sale_and_retry_does_not_duplicate(self):
        api = self._api()
        created = api.create_sale(self._sale(
            payment_method="Cash",
            amount_paid=1000,
            cash_paid=1000,
            client_token="cash-once",
        ))
        self.assertTrue(created.get("success"), created)
        self.assertEqual(created.get("document_kind"), "receipt")
        before = self._count("SELECT COUNT(*) FROM sales")
        first = api.print_sale_document(created["sale_id"], automatic=False)
        second = api.print_sale_document(created["sale_id"], automatic=False, reprint=True)
        after = self._count("SELECT COUNT(*) FROM sales")
        self.assertEqual(before, 1)
        self.assertEqual(after, 1)
        self.assertFalse(first.get("printed"))
        self.assertIn("Sale saved successfully. Printer unavailable.", first.get("message") or "")
        self.assertFalse(second.get("printed"))
        self.assertTrue(second.get("sales_unchanged"))
        doc = api.sale_document(created["sale_id"], reprint=True)
        self.assertEqual(doc["number"], created["receipt_number"])
        self.assertIn("REPRINT", doc["text"])
        self.assertIn(created["receipt_number"], doc["text"])

    def test_part_pay_invoice_and_later_payment_receipt_do_not_add_a_sale(self):
        api = self._api()
        created = api.create_sale(self._sale(
            payment_method="part payment",
            amount_paid=600,
            cash_paid=600,
            client_token="part-600",
            payment_tenders=[
                {"method": "Cash", "amount": 600, "status": "confirmed"},
                {"method": "Credit", "amount": 400, "status": "outstanding"},
            ],
        ))
        self.assertTrue(created.get("success"), created)
        self.assertEqual(created.get("document_kind"), "invoice")
        doc = api.sale_document(created["sale_id"])
        self.assertEqual(doc["kind"], "invoice")
        self.assertEqual(doc["amount_paid"], 600)
        self.assertEqual(doc["outstanding"], 400)
        self.assertIn("600.00", doc["text"])
        self.assertIn("400.00", doc["text"])
        self.assertIn("BALANCE DUE", doc["text"])
        sales_before = self._count("SELECT COUNT(*) FROM sales")
        paid = api.record_debt_payment(created["debt"]["invoice_id"], 400, "Cash", notes="balance")
        self.assertTrue(paid.get("success"), paid)
        sales_after = self._count("SELECT COUNT(*) FROM sales")
        self.assertEqual(sales_before, sales_after)
        payment = api.payment_document(paid["payment_receipt"])
        self.assertEqual(payment["kind"], "payment_receipt")
        self.assertEqual(payment["previous_outstanding"], 400)
        self.assertEqual(payment["amount_paid"], 400)
        self.assertEqual(payment["outstanding"], 0)
        self.assertIn("Not a new sale", payment["text"])
        self.assertNotEqual(payment["number"], created["receipt_number"])
        settled = api.sale_document(created["sale_id"])
        self.assertEqual(settled["outstanding"], 0)
        self.assertIn("PAID", settled["text"])

    def test_policy_change_does_not_rewrite_the_saved_document(self):
        api = self._api()
        created = api.create_sale(self._sale(
            payment_method="Cash",
            amount_paid=1000,
            cash_paid=1000,
            client_token="policy-cash",
        ))
        self.assertEqual(created.get("document_kind"), "receipt")
        number = created["receipt_number"]
        saved = api.update_settings({
            "document_policy": "B",
            "printer_name": "Front desk",
            "printer_connection": "LAN",
            "paper_size": "58",
        })
        self.assertTrue(saved.get("success"), saved)
        again = self._api().get_settings()
        self.assertEqual(again.get("document_policy"), "B")
        self.assertEqual(again.get("printer_name"), "Front desk")
        self.assertEqual(again.get("paper_size"), "58")
        db = self.ac._db()
        kind = db.execute(
            "SELECT issued_document_kind, issued_document_number, total, amount_paid FROM sales WHERE id=?",
            (created["sale_id"],),
        ).fetchone()
        db.close()
        self.assertEqual(kind["issued_document_kind"], "receipt")
        self.assertEqual(kind["issued_document_number"], number)
        changed = api.set_sale_document_kind(created["sale_id"], "invoice")
        self.assertTrue(changed.get("changed"), changed)
        self.assertEqual(changed["number"], number)
        db = self.ac._db()
        after = db.execute(
            "SELECT total, amount_paid, issued_document_kind FROM sales WHERE id=?",
            (created["sale_id"],),
        ).fetchone()
        db.close()
        self.assertEqual(after["issued_document_kind"], "invoice")
        self.assertEqual(after["total"], 1000)
        self.assertEqual(after["amount_paid"], 1000)
        reprint = api.sale_document(created["sale_id"], reprint=True)
        self.assertEqual(reprint["number"], number)
        self.assertTrue(reprint["text"].startswith(" ") or "REPRINT" in reprint["text"])
        pdf = __import__("printing.sale_documents", fromlist=["document_pdf"]).document_pdf(reprint)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(number.encode(), pdf)

    def test_unpaid_credit_is_an_invoice_and_split_is_a_receipt(self):
        api = self._api()
        api.update_settings({"document_policy": "C"})
        credit = api.create_sale(self._sale(
            payment_method="credit sale",
            amount_paid=0,
            client_token="credit-full",
        ))
        self.assertTrue(credit.get("success"), credit)
        self.assertEqual(credit.get("document_kind"), "invoice")
        unpaid = api.sale_document(credit["sale_id"])
        self.assertEqual(unpaid["outstanding"], 1000)
        self.assertEqual(unpaid["amount_paid"], 0)
        split = api.create_sale(self._sale(
            payment_method="Mixed",
            amount_paid=1000,
            client_token="split-full",
            payment_tenders=[
                {"method": "Cash", "amount": 400, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 600, "status": "confirmed"},
            ],
        ))
        self.assertTrue(split.get("success"), split)
        self.assertEqual(split.get("document_kind"), "receipt")
        shown = api.sale_document(split["sale_id"])
        self.assertIn("M-Pesa", shown["text"])
        self.assertIn("400.00", shown["text"])
        self.assertIn("600.00", shown["text"])
        self.assertNotEqual(credit["receipt_number"], split["receipt_number"])


if __name__ == "__main__":
    unittest.main()
