"""Restock lists stay separate from stock, deliveries, and sales."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def actor(role, user_id=1, name="qa", grants=None, shop="local"):
    return {
        "id": user_id,
        "username": name,
        "role": role,
        "shop_id": shop,
        "permission_grants": list(grants or []),
        "permission_denials": [],
    }


class RestockRequestTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "restock.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        os.environ["MBT_TEST_INSTANCE"] = "1"
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
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("buyer", ac._hash_pw("buyer-pass"), "manager", "QA Buyer"),
        )
        db.commit()
        db.close()
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "qa-admin"
        self.admin = actor("admin", 1, "QA Admin")
        self.sugar = self._product("QA Sugar 1kg", "packet", "SUG001")
        self.oil = self._product("QA Cooking Oil 1L", "litre", "OIL001")
        self.soap = self._product("QA Bar Soap", "pcs", "SOAP01")

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _conn(self):
        return self.ac._db()

    def _product(self, name, unit, sku, stock=40, cost=20):
        created = self.api.create_product({
            "name": name, "sku": sku, "barcode": sku, "price": 100,
            "cost_price": cost, "stock": stock, "unit": unit, "min_stock": 5,
        })
        self.assertTrue(created.get("success"), created)
        return created["id"]

    def _stock(self, product_id):
        db = self._conn()
        try:
            row = db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()
            return float(row["stock"])
        finally:
            db.close()

    def _movements(self):
        db = self._conn()
        try:
            return db.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
        finally:
            db.close()

    def _call(self, fn, *args):
        db = self._conn()
        try:
            result = fn(db, *args)
            if result.get("success"):
                db.commit()
            else:
                db.rollback()
            return result
        finally:
            db.close()

    def test_lists_stay_independent_and_do_not_change_stock(self):
        from backend import restock_requests as restock
        before = self._stock(self.sugar)
        movements = self._movements()
        first = self._call(restock.create_request, self.admin, {"name": "General Shop Restock", "priority": "normal"})
        second = self._call(restock.create_request, self.admin, {"name": "Urgent Items", "priority": "urgent"})
        self.assertTrue(first["success"], first)
        self.assertTrue(first["request"]["reference"].startswith("RST-"))
        self.assertNotEqual(first["request"]["reference"], second["request"]["reference"])
        added = self._call(restock.add_line, self.admin, first["request"]["id"], {
            "version": first["request"]["version"], "product_id": self.sugar, "quantity": 20, "notes": "Any brand",
        })
        self.assertTrue(added["success"], added)
        other = self._call(restock.add_line, self.admin, second["request"]["id"], {
            "version": second["request"]["version"], "product_id": self.sugar, "quantity": 4,
        })
        changed = self._call(restock.update_line, self.admin, first["request"]["id"], added["request"]["lines"][0]["id"], {
            "version": added["request"]["version"], "quantity": 25,
        })
        self.assertEqual(changed["request"]["lines"][0]["quantity"], 25)
        again = self._call(restock.get_request, self.admin, second["request"]["id"])
        self.assertEqual(again["request"]["lines"][0]["quantity"], 4)
        self.assertEqual(self._stock(self.sugar), before)
        self.assertEqual(self._movements(), movements)
        duplicate = self._call(restock.add_line, self.admin, first["request"]["id"], {
            "version": changed["request"]["version"], "product_id": self.sugar, "quantity": 1,
        })
        self.assertEqual(duplicate.get("status"), 409)
        merged = self._call(restock.add_line, self.admin, first["request"]["id"], {
            "version": changed["request"]["version"], "product_id": self.sugar, "quantity": 1, "merge": True,
        })
        self.assertEqual(merged["request"]["lines"][0]["quantity"], 26)
        self.assertEqual(self._stock(self.sugar), before)

    def test_validation_permissions_snapshot_and_purchase_do_not_receive_stock(self):
        from backend import restock_requests as restock
        cashier = actor("cashier", 9, "Cashier")
        denied = self._call(restock.create_request, cashier, {"name": "Cashier list"})
        self.assertEqual(denied.get("status"), 403)
        granted = actor("cashier", 9, "Cashier", grants=["restock.create"])
        own = self._call(restock.create_request, granted, {"name": "Cashier draft"})
        self.assertTrue(own["success"], own)
        hidden = self._call(restock.get_request, granted, 1 if own["request"]["id"] != 1 else 2)
        shop = self._call(restock.create_request, self.admin, {"name": "Drinks Restock & Co <shop>"})
        self._call(restock.add_line, self.admin, shop["request"]["id"], {
            "version": shop["request"]["version"], "product_id": self.oil, "quantity": 1.5,
        })
        seen = self._call(restock.get_request, granted, shop["request"]["id"])
        self.assertEqual(seen.get("status"), 404)
        empty = self._call(restock.submit_request, self.admin, own["request"]["id"], own["request"]["version"])
        self.assertIn("at least one product", empty["error"].lower())
        own_line = self._call(restock.add_line, granted, own["request"]["id"], {
            "version": own["request"]["version"], "product_id": self.sugar, "quantity": 2,
        })
        self.assertTrue(own_line["success"], own_line)
        blocked = self._call(restock.submit_request, granted, own["request"]["id"], own_line["request"]["version"])
        self.assertEqual(blocked.get("status"), 403)
        current = self._call(restock.get_request, self.admin, shop["request"]["id"])
        bad_qty = self._call(restock.add_line, self.admin, shop["request"]["id"], {
            "version": current["request"]["version"], "product_id": self.soap, "quantity": 1.5,
        })
        self.assertIn("whole", bad_qty["error"].lower())
        zero = self._call(restock.add_line, self.admin, shop["request"]["id"], {
            "version": current["request"]["version"], "product_id": self.soap, "quantity": 0,
        })
        self.assertTrue(zero.get("error"))
        added = self._call(restock.add_line, self.admin, shop["request"]["id"], {
            "version": current["request"]["version"], "product_id": self.soap, "quantity": 30,
        })
        submitted = self._call(restock.submit_request, self.admin, shop["request"]["id"], added["request"]["version"])
        self.assertEqual(submitted["request"]["status"], "ready")
        self.assertEqual(submitted["request"]["snapshot"]["lines"][0]["quantity"], 1.5)
        edited = self._call(restock.update_line, self.admin, shop["request"]["id"], added["request"]["lines"][0]["line_id"], {
            "version": submitted["request"]["version"], "quantity": 9,
        })
        self.assertIn("draft", edited["error"].lower())
        snap = self._call(restock.get_request, self.admin, shop["request"]["id"])
        self.assertEqual(snap["request"]["snapshot"]["lines"][0]["quantity"], 1.5)
        buyer = self._call(restock.assign_request, self.admin, shop["request"]["id"], {
            "version": snap["request"]["version"], "buyer_user_id": 2,
        })
        self.assertEqual(buyer["request"]["status"], "assigned")
        again = self._call(restock.assign_request, self.admin, shop["request"]["id"], {
            "version": buyer["request"]["version"], "buyer_user_id": 2,
        })
        db = self._conn()
        try:
            notes = db.execute(
                "SELECT COUNT(*) FROM restock_events WHERE request_id=? AND kind='notified'",
                (shop["request"]["id"],),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(notes, 1)
        line = again["request"]["lines"][0]
        before = self._stock(self.oil)
        partial = self._call(restock.record_purchase, self.admin, shop["request"]["id"], {
            "version": again["request"]["version"],
            "lines": [{
                "id": line["id"], "purchased_qty": 1, "unavailable_qty": 0.5,
                "notes": "Supplier had one litre", "purchase_date": "2026-11-17",
            }],
        })
        self.assertEqual(partial["request"]["status"], "partial_purchased")
        self.assertEqual(partial["request"]["lines"][0]["outstanding_qty"], 0.5)
        self.assertEqual(self._stock(self.oil), before)
        self.assertNotIn("unit_price", self._call(restock.get_request, actor("viewer", 3, "Viewer"), shop["request"]["id"])["request"]["lines"][0])
        too_much = self._call(restock.record_purchase, self.admin, shop["request"]["id"], {
            "version": partial["request"]["version"],
            "lines": [{"id": line["id"], "purchased_qty": 5}],
        })
        self.assertIn("more", too_much["error"].lower())
        self.assertEqual(self._stock(self.oil), before)

    def test_goods_received_link_is_the_only_stock_change_and_revisions_stay_fixed(self):
        from backend import restock_requests as restock
        created = self._call(restock.create_request, self.admin, {"name": "Household Products"})
        added = self._call(restock.add_line, self.admin, created["request"]["id"], {
            "version": created["request"]["version"], "product_id": self.soap, "quantity": 10,
        })
        sent = self._call(restock.submit_request, self.admin, created["request"]["id"], added["request"]["version"])
        bought = self._call(restock.record_purchase, self.admin, created["request"]["id"], {
            "version": sent["request"]["version"],
            "lines": [{"id": sent["request"]["lines"][0]["id"], "purchased_qty": 10, "notes": "Bought the carton"}],
        })
        self.assertEqual(bought["request"]["status"], "purchased")
        self.assertEqual(self._stock(self.soap), 40)
        supplier = self.api.create_supplier({"name": "QA Restock Supplier", "phone": "0700000000"})
        self.assertTrue(supplier.get("success"), supplier)
        delivery = self.api.receive_stock(
            self.soap, 6, supplier_id=supplier["id"], unit_cost=18, client_token="restock-recv-1",
        )
        self.assertTrue(delivery.get("success"), delivery)
        self.assertEqual(self._stock(self.soap), 46)
        linked = self._call(restock.link_receipt, self.admin, created["request"]["id"], {
            "line_id": sent["request"]["lines"][0]["line_id"],
            "receipt_id": delivery["receipt_id"],
            "qty_accepted": 6,
            "qty_rejected": 0,
        })
        self.assertEqual(linked["request"]["status"], "partial_received", linked)
        self.assertEqual(linked["request"]["lines"][0]["purchased_not_received"], 4)
        self.assertEqual(self._stock(self.soap), 46)
        again = self.api.receive_stock(
            self.soap, 6, supplier_id=supplier["id"], unit_cost=18, client_token="restock-recv-1",
        )
        self.assertTrue(again.get("duplicate"), again)
        self.assertEqual(self._stock(self.soap), 46)
        db = self._conn()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE restock_revisions SET name='changed' WHERE request_id=?", (created["request"]["id"],))
            db.rollback()
        finally:
            db.close()
        copy = self._call(restock.duplicate_request, self.admin, created["request"]["id"])
        self.assertNotEqual(copy["request"]["id"], created["request"]["id"])
        self.assertEqual(copy["request"]["status"], "draft")
        self.assertEqual(copy["request"]["lines"][0]["quantity"], 10)
        renamed = self._call(restock.update_request, self.admin, copy["request"]["id"], {
            "version": copy["request"]["version"], "name": "Household copy",
        })
        original = self._call(restock.get_request, self.admin, created["request"]["id"])
        self.assertEqual(original["request"]["name"], "Household Products")
        self.assertEqual(renamed["request"]["name"], "Household copy")

    def test_other_shop_and_archived_search_and_conflict(self):
        from backend import restock_requests as restock
        created = self._call(restock.create_request, self.admin, {
            "name": "Weekly Shop Restock", "client_token": "same-token",
        })
        duplicate = self._call(restock.create_request, self.admin, {
            "name": "Weekly Shop Restock", "client_token": "same-token",
        })
        self.assertTrue(duplicate.get("duplicate"))
        self.assertEqual(duplicate["request"]["id"], created["request"]["id"])
        other = actor("admin", 1, "Other shop", shop="other-shop")
        missing = self._call(restock.get_request, other, created["request"]["id"])
        self.assertEqual(missing.get("status"), 404)
        stale = self._call(restock.update_request, self.admin, created["request"]["id"], {
            "version": 99, "name": "Stale name",
        })
        self.assertTrue(stale.get("conflict"))
        archived = self._call(restock.archive_request, self.admin, created["request"]["id"], created["request"]["version"])
        listed = self._call(restock.list_requests, self.admin, {})
        self.assertFalse(any(item["id"] == created["request"]["id"] for item in listed["requests"]))
        found = self._call(restock.list_requests, self.admin, {"archived": "1", "q": "weekly"})
        self.assertTrue(any(item["id"] == created["request"]["id"] for item in found["requests"]))
        reopened = self._call(restock.reopen_request, self.admin, created["request"]["id"], archived["request"]["version"])
        self.assertEqual(reopened["request"]["status"], "draft")
        document = self._call(restock.document_html, self.admin, created["request"]["id"])
        self.assertIn("NOT A SUPPLIER INVOICE", document["html"])
        self.assertIn("Weekly Shop Restock", document["html"])
        db = self._conn()
        try:
            db.execute("UPDATE products SET stock=1, min_stock=8 WHERE id=?", (self.sugar,))
            db.commit()
        finally:
            db.close()
        low = self._call(restock.suggestions, self.admin)
        self.assertTrue(low["success"], low)
        self.assertTrue(any(item["product_id"] == self.sugar for item in low["suggestions"]))
