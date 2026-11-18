"""Receipt printing, a second delivery, and an open sale left untouched."""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.test_restock_requests import actor


class RestockPrintAndSaleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "restock.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        os.environ["MBT_TEST_INSTANCE"] = "1"
        os.environ.pop("MBT_PRINTER_SINK", None)
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
            ("owner", ac._hash_pw("owner-pass"), "admin", "QA Admin"),
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at) VALUES (?,?,?)",
            ("shop_name", "QA Restock Shop", "2026-11-17"),
        )
        db.commit()
        db.close()
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "QA Admin"
        self.admin = actor("admin", 1, "QA Admin")
        created = self.api.create_product({
            "name": "QA Bar Soap", "sku": "SOAP01", "barcode": "SOAP01",
            "price": 80, "cost_price": 45, "stock": 0, "unit": "pcs", "min_stock": 4,
        })
        self.soap = created["id"]

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _call(self, fn, *args):
        db = self.ac._db()
        try:
            result = fn(db, *args)
            if result.get("success"):
                db.commit()
            else:
                db.rollback()
            return result
        finally:
            db.close()

    def _stock(self):
        db = self.ac._db()
        try:
            return float(db.execute("SELECT stock FROM products WHERE id=?", (self.soap,)).fetchone()["stock"])
        finally:
            db.close()

    def _request(self):
        from backend import restock_requests as restock
        created = self._call(restock.create_request, self.admin, {"name": "General Shop Restock"})
        added = self._call(restock.add_line, self.admin, created["request"]["id"], {
            "version": created["request"]["version"], "product_id": self.soap, "quantity": 30,
        })
        sent = self._call(restock.submit_request, self.admin, created["request"]["id"], added["request"]["version"])
        return sent["request"]

    def test_thermal_text_keeps_quantities_on_both_widths(self):
        from backend import restock_requests as restock
        from printing.sale_documents import office_pdf
        request = self._request()
        for paper, width in (("58", 32), ("80", 48)):
            rendered = self._call(restock.document_text, self.admin, request["id"], paper)
            text = rendered["text"]
            flat = " ".join(line.strip() for line in text.splitlines())
            self.assertIn("RESTOCKING REQUEST", text)
            self.assertIn(
                "THIS IS A RESTOCKING REQUEST. IT IS NOT A SUPPLIER INVOICE OR GOODS RECEIVED NOTE.",
                flat,
            )
            self.assertIn("Asked: 30 pcs", text)
            self.assertTrue(all(len(line) <= width for line in text.splitlines()), text)
        long_name = "Household washing soap with a very long shelf name that must wrap"
        lines = [long_name] * 60
        blob = office_pdf(lines, request["reference"])
        self.assertTrue(blob.startswith(b"%PDF"))
        self.assertIn(b"Page 1 of", blob)
        self.assertIn(b"Page 2 of", blob)
        self.assertIn(request["reference"].encode(), blob)
        self.assertEqual(self._stock(), 0)

    def test_missing_printer_does_not_change_the_request_or_stock(self):
        from printing.printer_engine import print_document_bytes
        request = self._request()
        outcome = print_document_bytes(
            {"printer_name": "", "printer_connection": ""},
            b"restock",
            label=request["reference"],
            text="RESTOCKING REQUEST",
        )
        self.assertFalse(outcome.get("printed"))
        self.assertIn("printer", (outcome.get("message") or "").lower())
        sink = os.path.join(self._tmpdir.name, "printer.bin")
        os.environ["MBT_PRINTER_SINK"] = sink
        try:
            sent = print_document_bytes({}, b"RESTOCKING REQUEST\n", label=request["reference"], text="RESTOCKING REQUEST")
        finally:
            os.environ.pop("MBT_PRINTER_SINK", None)
        self.assertTrue(sent.get("printed"), sent)
        self.assertTrue(os.path.getsize(sink) > 0)
        self.assertEqual(self._stock(), 0)
        db = self.ac._db()
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        finally:
            db.close()

    def test_second_delivery_and_rejected_quantity_stay_separate(self):
        from backend import restock_requests as restock
        request = self._request()
        supplier = self.api.create_supplier({"name": "QA Restock Supplier", "phone": "0700000000"})
        first = self.api.receive_stock(self.soap, 6, supplier_id=supplier["id"], unit_cost=45, client_token="soap-6")
        linked = self._call(restock.link_receipt, self.admin, request["id"], {
            "line_id": request["lines"][0]["line_id"],
            "receipt_id": first["receipt_id"],
            "qty_accepted": 6,
            "qty_rejected": 1,
        })
        self.assertEqual(self._stock(), 6)
        self.assertEqual(linked["request"]["lines"][0]["received_qty"], 6)
        self.assertEqual(linked["request"]["lines"][0]["rejected_qty"], 1)
        second = self.api.receive_stock(self.soap, 4, supplier_id=supplier["id"], unit_cost=45, client_token="soap-4")
        again = self._call(restock.link_receipt, self.admin, request["id"], {
            "line_id": request["lines"][0]["line_id"],
            "receipt_id": second["receipt_id"],
            "qty_accepted": 4,
            "qty_rejected": 0,
        })
        self.assertEqual(self._stock(), 10)
        self.assertEqual(len(again["request"]["receipts"]), 2)
        self.assertEqual(again["request"]["lines"][0]["received_qty"], 10)
        self.assertEqual(again["request"]["lines"][0]["purchased_qty"], 0)
        fraction = self._call(restock.link_receipt, self.admin, request["id"], {
            "line_id": request["lines"][0]["line_id"],
            "receipt_id": second["receipt_id"],
            "qty_accepted": 1.5,
            "qty_rejected": 0,
        })
        self.assertIn("whole", fraction["error"].lower())
        self.assertEqual(self._stock(), 10)
        archived = self._call(restock.archive_request, self.admin, request["id"], again["request"]["version"])
        self.assertEqual(archived["request"]["status"], "archived")

    def test_open_sale_is_unchanged_while_a_list_is_edited(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt5.QtWidgets import QApplication, QWidget
        from desktop.dialogs.restock_dialog import RestockDialog
        app = QApplication.instance() or QApplication([])
        sale = QWidget()
        sale.cart = [
            {"product_id": self.soap, "product_name": "QA Bar Soap", "quantity": 2, "unit": "pcs",
             "unit_price": 80, "discount": 0, "total": 160},
            {"product_id": 99, "product_name": "QA Sugar 1kg", "quantity": 1, "unit": "packet",
             "unit_price": 150, "discount": 0, "total": 150},
        ]
        sale.payment = "Cash"
        sale.customer = "Walk-in"
        before = copy.deepcopy({"cart": sale.cart, "payment": sale.payment, "customer": sale.customer})
        dialog = RestockDialog(self.api, {"id": 1, "username": "QA Admin", "role": "admin", "shop_id": "local"}, sale)
        dialog.name.setText("Drinks Restock")
        dialog._new()
        self.assertEqual(sale.cart, before["cart"])
        self.assertEqual(sale.payment, "Cash")
        self.assertEqual(sale.customer, "Walk-in")
        dialog.close()
        app.processEvents()

    def test_desktop_and_web_backend_read_the_same_saved_list(self):
        from backend import restock_requests as restock
        created = self._call(restock.create_request, self.admin, {
            "name": "Shared shop list",
            "client_token": "shared-list-1",
        })
        first = created["request"]
        again = self._call(restock.create_request, self.admin, {
            "name": "Shared shop list",
            "client_token": "shared-list-1",
        })
        self.assertEqual(again["request"]["id"], first["id"])
        self.assertEqual(again.get("duplicate"), True)
        other = self.ac._db()
        try:
            listed = restock.list_requests(other, self.admin, {"q": "Shared shop"})
            other.rollback()
        finally:
            other.close()
        references = [row["reference"] for row in listed["requests"]]
        self.assertIn(first["reference"], references)
        reopened = self.ac._db()
        try:
            loaded = restock.get_request(reopened, self.admin, first["id"])
        finally:
            reopened.close()
        self.assertEqual(loaded["request"]["name"], "Shared shop list")
        self.assertEqual(loaded["request"]["status"], "draft")
