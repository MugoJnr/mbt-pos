"""Cashier receipts, void review, buying-price warnings, and staff identity.

Disposable database only. The live shop database is not opened.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CashierReceiptAuditRegressionTests(unittest.TestCase):
    PIN = "246810"

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "regression.db")
        os.environ["MBT_TEST_INSTANCE"] = "1"
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.security import _pin_hash
        ac._SCHEMA_READY = False
        self.ac = ac
        granted = json.dumps(["dashboard", "sales", "receipts", "inventory", "consumption"])
        revoked = json.dumps(["dashboard", "sales", "inventory", "consumption"])
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, tab_permissions) "
            "VALUES (?,?,?,?,1,?)",
            ("qa_owner", ac._hash_pw("owner-pass"), "superadmin", "QA Owner", "[]"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, tab_permissions) "
            "VALUES (?,?,?,?,1,?)",
            ("qa_admin", ac._hash_pw("admin-pass"), "admin", "QA Administrator", "[]"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, tab_permissions) "
            "VALUES (?,?,?,?,1,?)",
            ("qa_alice", ac._hash_pw("alice-pass"), "cashier", "QA Cashier Alice", granted),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active, tab_permissions) "
            "VALUES (?,?,?,?,1,?)",
            ("qa_brian", ac._hash_pw("brian-pass"), "cashier", "QA Cashier Brian", revoked),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, cost_confirmed, stock, min_stock, is_active) "
            "VALUES ('QA Priced', 'QA-PRICED', 50, 20, 1, 10, 1, 1)"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, cost_confirmed, stock, min_stock, is_active) "
            "VALUES ('QA Missing Cost', 'QA-MISSING', 40, NULL, 0, 3, 1, 1)"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, cost_confirmed, stock, min_stock, is_active) "
            "VALUES ('QA Zero Cost', 'QA-ZERO', 30, 0, 0, 2, 1, 1)"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('superadmin_pin_hash', ?)",
            (_pin_hash(self.PIN),),
        )
        db.commit()
        self.product_id = db.execute("SELECT id FROM products WHERE sku='QA-PRICED'").fetchone()["id"]
        self.alice_id = db.execute("SELECT id FROM users WHERE username='qa_alice'").fetchone()["id"]
        self.brian_id = db.execute("SELECT id FROM users WHERE username='qa_brian'").fetchone()["id"]
        self.admin_id = db.execute("SELECT id FROM users WHERE username='qa_admin'").fetchone()["id"]
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _login(self, username, password):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        return {"Authorization": f"Bearer {body['token']}"}, body["user"]

    def _sell(self, headers, quantity=1):
        response = self.client.post(
            "/api/sales",
            headers=headers,
            json={
                "items": [{
                    "product_id": self.product_id,
                    "quantity": quantity,
                    "price": 50,
                }],
                "total": 50 * quantity,
                "amount_paid": 50 * quantity,
                "payment_method": "Cash",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_receipts_search_void_identity_and_cost_warnings(self):
        alice_headers, alice = self._login("qa_alice", "alice-pass")
        brian_headers, brian = self._login("qa_brian", "brian-pass")
        admin_headers, admin = self._login("qa_admin", "admin-pass")
        owner_headers, owner = self._login("qa_owner", "owner-pass")
        self.assertIn("receipts", alice["tab_permissions"])
        self.assertNotIn("receipts", brian["tab_permissions"])
        self.assertIn("sales.request_void", alice["effective_permissions"])
        self.assertNotIn("sales.void", alice["effective_permissions"])
        self.assertNotIn("inventory.view_cost", alice["effective_permissions"])
        self.assertNotIn("reports.view_all", alice["effective_permissions"])

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        alice_sale = self._sell(alice_headers)
        brian_sale = self._sell(brian_headers)
        reject_sale = self._sell(alice_headers)

        db = self.ac._db()
        db.execute(
            "UPDATE sales SET sale_date=?, receipt_number=? WHERE id=?",
            (yesterday, "RCP-HIST-1", int(alice_sale["sale_id"])),
        )
        db.commit()
        stored = db.execute(
            "SELECT cashier_id, cashier_name FROM sales WHERE id=?",
            (int(alice_sale["sale_id"]),),
        ).fetchone()
        brian_row = db.execute(
            "SELECT cashier_id, cashier_name, receipt_number FROM sales WHERE id=?",
            (int(brian_sale["sale_id"]),),
        ).fetchone()
        db.execute(
            "UPDATE users SET full_name=? WHERE id=?",
            ("QA Cashier Alice Renamed", self.alice_id),
        )
        db.commit()
        db.close()
        self.assertEqual(int(stored["cashier_id"]), int(self.alice_id))
        self.assertEqual(stored["cashier_name"], "QA Cashier Alice")
        self.assertEqual(int(brian_row["cashier_id"]), int(self.brian_id))
        self.assertEqual(brian_row["cashier_name"], "QA Cashier Brian")

        blocked = self.client.get(
            f"/api/receipts?start={today}&end={today}", headers=brian_headers,
        )
        self.assertEqual(blocked.status_code, 403, blocked.get_json())
        blocked_detail = self.client.get(
            f"/api/receipts/sale/{alice_sale['sale_id']}", headers=brian_headers,
        )
        self.assertEqual(blocked_detail.status_code, 403, blocked_detail.get_json())

        default_list = self.client.get(
            f"/api/receipts?start={today}&end={today}", headers=alice_headers,
        )
        self.assertEqual(default_list.status_code, 200, default_list.get_json())
        default_body = default_list.get_json()
        default_refs = [row["reference"] for row in default_body["receipts"] if row["kind"] == "sale"]
        self.assertNotIn("RCP-HIST-1", default_refs)
        self.assertIn(brian_row["receipt_number"], default_refs)
        self.assertFalse(default_body.get("searched_all_dates"))
        again = self.client.get(
            f"/api/receipts?start={today}&end={today}", headers=alice_headers,
        )
        self.assertEqual(
            [row["reference"] for row in again.get_json()["receipts"]],
            [row["reference"] for row in default_body["receipts"]],
        )

        found = self.client.get(
            f"/api/receipts?start={today}&end={today}&q=RCP-HIST-1",
            headers=alice_headers,
        )
        self.assertEqual(found.status_code, 200, found.get_json())
        found_body = found.get_json()
        self.assertTrue(found_body.get("searched_all_dates"))
        self.assertEqual(
            [row["reference"] for row in found_body["receipts"] if row["kind"] == "sale"],
            ["RCP-HIST-1"],
        )
        by_product = self.client.get(
            f"/api/receipts?start={today}&end={today}&q=QA%20Priced",
            headers=alice_headers,
        )
        product_refs = [row["reference"] for row in by_product.get_json()["receipts"]]
        self.assertIn("RCP-HIST-1", product_refs)

        detail = self.client.get(
            f"/api/receipts/sale/{alice_sale['sale_id']}", headers=alice_headers,
        )
        self.assertEqual(detail.status_code, 200, detail.get_json())
        opened = detail.get_json()
        self.assertEqual(opened["reference"], "RCP-HIST-1")
        self.assertNotIn("cost", opened.get("header") or {})
        for line in opened.get("lines") or []:
            self.assertNotIn("unit_cost", line)
            self.assertNotIn("profit", line)
        owner_detail = self.client.get(
            f"/api/receipts/sale/{alice_sale['sale_id']}", headers=owner_headers,
        )
        self.assertEqual(owner_detail.status_code, 200, owner_detail.get_json())

        direct = self.client.post(
            f"/api/sales/{alice_sale['sale_id']}/void-now",
            headers=alice_headers,
            json={"reason": "Cashier must not void directly"},
        )
        self.assertEqual(direct.status_code, 403, direct.get_json())
        admin_direct = self.client.post(
            f"/api/sales/{alice_sale['sale_id']}/void-now",
            headers=admin_headers,
            json={"reason": "Admin must not void directly"},
        )
        self.assertEqual(admin_direct.status_code, 403, admin_direct.get_json())

        requested = self.client.post(
            "/api/sales/void-request",
            headers=alice_headers,
            json={"receipt_number": "RCP-HIST-1", "reason": "Wrong item on yesterday's receipt"},
        )
        self.assertEqual(requested.status_code, 200, requested.get_json())
        request_id = int(requested.get_json()["id"])
        duplicate = self.client.post(
            "/api/sales/void-request",
            headers=alice_headers,
            json={"receipt_number": "RCP-HIST-1", "reason": "Sent twice"},
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.get_json())
        self.assertTrue(duplicate.get_json().get("duplicate"))
        self.assertEqual(int(duplicate.get_json()["id"]), request_id)

        db = self.ac._db()
        approval = db.execute(
            "SELECT requested_by, requested_by_id, status FROM cc_approvals WHERE id=?",
            (request_id,),
        ).fetchone()
        stock_before = float(db.execute(
            "SELECT stock FROM products WHERE id=?", (self.product_id,)
        ).fetchone()["stock"])
        db.close()
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(int(approval["requested_by_id"]), int(self.alice_id))
        self.assertEqual(approval["requested_by"], "qa_alice")

        cashier_review = self.client.post(
            f"/api/approvals/{request_id}/approve",
            headers=alice_headers,
            json={"pin": self.PIN, "note": "Cashier cannot approve"},
        )
        self.assertEqual(cashier_review.status_code, 403, cashier_review.get_json())

        approved = self.client.post(
            f"/api/approvals/{request_id}/approve",
            headers=admin_headers,
            json={"pin": self.PIN, "note": "Approved by QA Administrator"},
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())
        repeated = self.client.post(
            f"/api/approvals/{request_id}/approve",
            headers=admin_headers,
            json={"pin": self.PIN, "note": "Approved again"},
        )
        self.assertIn(repeated.status_code, (200, 400), repeated.get_json())

        reject_request = self.client.post(
            "/api/sales/void-request",
            headers=alice_headers,
            json={"sale_id": reject_sale["sale_id"], "reason": "Customer kept the goods"},
        )
        self.assertEqual(reject_request.status_code, 200, reject_request.get_json())
        reject_id = int(reject_request.get_json()["id"])
        rejected = self.client.post(
            f"/api/approvals/{reject_id}/reject",
            headers=admin_headers,
            json={"note": "Sale stands"},
        )
        self.assertEqual(rejected.status_code, 200, rejected.get_json())

        db = self.ac._db()
        voided = db.execute(
            "SELECT status FROM sales WHERE id=?", (int(alice_sale["sale_id"]),)
        ).fetchone()["status"]
        kept = db.execute(
            "SELECT status FROM sales WHERE id=?", (int(reject_sale["sale_id"]),)
        ).fetchone()["status"]
        stock_after = float(db.execute(
            "SELECT stock FROM products WHERE id=?", (self.product_id,)
        ).fetchone()["stock"])
        review = db.execute(
            "SELECT status, reviewed_by, reviewed_by_id FROM cc_approvals WHERE id=?",
            (request_id,),
        ).fetchone()
        rejection = db.execute(
            "SELECT status, reviewed_by_id FROM cc_approvals WHERE id=?",
            (reject_id,),
        ).fetchone()
        void_count = db.execute(
            "SELECT COUNT(*) FROM sale_edits WHERE sale_id=? AND edit_type='VOID'",
            (int(alice_sale["sale_id"]),),
        ).fetchone()[0]
        actor_after_rename = db.execute(
            "SELECT cashier_id FROM sales WHERE id=?", (int(alice_sale["sale_id"]),)
        ).fetchone()["cashier_id"]
        db.close()
        self.assertEqual(voided, "voided")
        self.assertEqual(kept, "completed")
        self.assertEqual(int(void_count), 1)
        self.assertEqual(stock_after, stock_before + 1)
        self.assertEqual(review["status"], "approved")
        self.assertEqual(int(review["reviewed_by_id"]), int(self.admin_id))
        self.assertEqual(review["reviewed_by"], "qa_admin")
        self.assertEqual(rejection["status"], "rejected")
        self.assertEqual(int(rejection["reviewed_by_id"]), int(self.admin_id))
        self.assertEqual(int(actor_after_rename), int(self.alice_id))

        from desktop.utils.cost_health import classify
        self.assertIn("missing_price", classify(None, 0, 3, 0, 0))
        self.assertIn("zero_review", classify(0, 0, 2, 0, 0))
        self.assertNotIn("missing_price", classify(20, 1, 10, 10, 200))
        self.assertIn("invalid_price", classify("not-a-price", 0, 1, 0, 0))

        cashier_products = self.client.get("/api/products", headers=alice_headers)
        self.assertEqual(cashier_products.status_code, 200, cashier_products.get_json())
        self.assertNotIn("cost_price", cashier_products.get_json()[0])
        self.assertEqual(self.client.get("/api/audit", headers=alice_headers).status_code, 403)
        audit = self.client.get("/api/audit?q=VOID_SALE", headers=owner_headers)
        self.assertEqual(audit.status_code, 200, audit.get_json())
        rows = audit.get_json()
        self.assertTrue(rows)
        event_id = int(rows[0]["id"])
        self.assertTrue(rows[0].get("username"))
        self.assertNotEqual(rows[0].get("username"), "Cashier")
        opened_event = self.client.get(f"/api/audit/{event_id}", headers=owner_headers)
        self.assertEqual(opened_event.status_code, 200, opened_event.get_json())
        event = opened_event.get_json()
        self.assertEqual(int(event["id"]), event_id)
        self.assertEqual(event["action"], "VOID_SALE")
        self.assertTrue(event.get("user_id") or event.get("username"))
        self.assertIn("RCP-HIST-1", event.get("details") or "")

        locked = sqlite3.connect(self._db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            locked.execute("UPDATE audit_log SET details='rewritten' WHERE id=?", (event_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            locked.execute("DELETE FROM audit_log WHERE id=?", (event_id,))
        locked.close()

        from backend.audit_detail import audit_sections
        labels = [title for title, _rows in audit_sections(event)]
        self.assertEqual(labels, ["Event", "Staff", "What was recorded", "Before and after"])
        staff = dict(audit_sections(event)[1][1])
        self.assertEqual(staff["Account"], event.get("username"))
        self.assertNotEqual(staff["Account"], "Cashier")

        self.assertEqual(alice["full_name"], "QA Cashier Alice")
        self.assertEqual(brian["role"], "cashier")
        self.assertEqual(admin["role"], "admin")
        self.assertEqual(owner["role"], "superadmin")
        evidence_dir = os.path.join(ROOT, "qa_evidence", "cashier_receipts_audit_20261120")
        os.makedirs(evidence_dir, exist_ok=True)
        with open(os.path.join(evidence_dir, "api_run.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "accounts": {
                    "qa_alice": self.alice_id,
                    "qa_brian": self.brian_id,
                    "qa_admin": self.admin_id,
                },
                "historical_receipt": "RCP-HIST-1",
                "historical_sale_id": int(alice_sale["sale_id"]),
                "brian_receipt": brian_row["receipt_number"],
                "brian_sale_id": int(brian_sale["sale_id"]),
                "rejected_sale_id": int(reject_sale["sale_id"]),
                "approved_void_request_id": request_id,
                "rejected_void_request_id": reject_id,
                "void_edit_count": int(void_count),
                "stock_before_void": stock_before,
                "stock_after_void": stock_after,
                "audit_event_id": event_id,
                "audit_username": rows[0].get("username"),
                "business_date_excluded": yesterday,
                "default_list_date": today,
            }, handle, indent=2)
