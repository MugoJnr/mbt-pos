"""Backdating requests stay off the books until one approval posts them once."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class BackdateRequestTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "backdate.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.shop_time import shop_today
        ac._SCHEMA_READY = False
        self.ac = ac
        self.yesterday = (shop_today() - timedelta(days=1)).isoformat()
        self.older = (shop_today() - timedelta(days=3)).isoformat()
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("cashier", ac._hash_pw("cashier-pass"), "cashier", "Ada Cashier"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("other", ac._hash_pw("other-pass"), "cashier", "Other Cashier"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("viewer", ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
            ("manager", ac._hash_pw("manager-pass"), "manager", "Shop Manager"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
            ("Sugar", "SUG", 100, 60, 20),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) VALUES (?,?,?,?,?,1)",
            ("Salt", "SAL", 40, 20, 1),
        )
        db.execute(
            "INSERT INTO customers (name, phone, is_active) VALUES ('Asha', '0700', 1)"
        )
        db.commit()
        self.sugar = db.execute("SELECT id FROM products WHERE sku='SUG'").fetchone()["id"]
        self.salt = db.execute("SELECT id FROM products WHERE sku='SAL'").fetchone()["id"]
        self.customer = db.execute("SELECT id FROM customers").fetchone()["id"]
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _login(self, username):
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": f"{username}-pass"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def _sale(self, product, qty, price, method="Cash", paid=None, customer=None, mpesa="", discount=0):
        return {
            "payment_method": method,
            "amount_paid": price * qty if paid is None else paid,
            "customer_id": customer,
            "mpesa_ref": mpesa,
            "notes": "counter book",
            "lines": [{
                "product_id": product,
                "quantity": qty,
                "unit_price": price,
                "discount": discount,
            }],
        }

    def _create(self, headers, sales, day=None, reason="Power was out"):
        response = self.client.post("/api/backdate-requests", headers=headers, json={
            "business_date": day or self.yesterday,
            "reason": reason,
            "sales": sales,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _counts(self):
        db = self.ac._db()
        try:
            sales = db.execute("SELECT COUNT(*) AS c FROM sales").fetchone()["c"]
            stock = db.execute("SELECT stock FROM products WHERE id=?", (self.sugar,)).fetchone()["stock"]
            debts = db.execute("SELECT COUNT(*) AS c FROM debt_invoices").fetchone()["c"]
            return sales, stock, debts
        finally:
            db.close()

    def test_draft_does_not_post_and_history_is_private(self):
        cashier = self._login("cashier")
        other = self._login("other")
        viewer = self._login("viewer")
        created = self._create(cashier, [
            self._sale(self.sugar, 2, 100),
            self._sale(self.sugar, 1, 90, "M-Pesa", mpesa="ABC123"),
        ])
        self.assertEqual(created["status"], "draft")
        self.assertEqual(self._counts(), (0, 20, 0))
        self.assertEqual(created["summary"]["total_sales"], 290)
        self.assertEqual(created["summary"]["mpesa_sales"], 90)
        listed = self.client.get("/api/backdate-requests", headers=cashier)
        self.assertEqual(len(listed.get_json()["requests"]), 1)
        hidden = self.client.get(f"/api/backdate-requests/{created['id']}", headers=other)
        self.assertEqual(hidden.status_code, 404)
        denied = self.client.post("/api/backdate-requests", headers=viewer, json={
            "business_date": self.yesterday, "reason": "no", "sales": [],
        })
        self.assertEqual(denied.status_code, 403)

    def test_future_and_empty_requests_are_rejected(self):
        cashier = self._login("cashier")
        from desktop.utils.shop_time import shop_today
        future = self.client.post("/api/backdate-requests", headers=cashier, json={
            "business_date": (shop_today() + timedelta(days=1)).isoformat(),
            "reason": "tomorrow",
            "sales": [self._sale(self.sugar, 1, 100)],
        })
        self.assertEqual(future.status_code, 400)
        today = self.client.post("/api/backdate-requests", headers=cashier, json={
            "business_date": shop_today().isoformat(),
            "reason": "today",
            "sales": [self._sale(self.sugar, 1, 100)],
        })
        self.assertEqual(today.status_code, 400)
        created = self._create(cashier, [])
        submitted = self.client.post(
            f"/api/backdate-requests/{created['id']}/submit",
            headers=cashier,
            json={"version": created["version"]},
        )
        self.assertEqual(submitted.status_code, 400)
        self.assertEqual(self._counts()[0], 0)

    def test_return_edit_resubmit_and_approve_once(self):
        cashier = self._login("cashier")
        manager = self._login("manager")
        created = self._create(cashier, [
            self._sale(self.sugar, 2, 100, "Cash", paid=200),
            self._sale(self.sugar, 1, 80, "Credit Sale", paid=0, customer=self.customer),
        ])
        submitted = self.client.post(
            f"/api/backdate-requests/{created['id']}/submit",
            headers=cashier, json={"version": created["version"]},
        )
        self.assertEqual(submitted.status_code, 200, submitted.get_json())
        body = submitted.get_json()
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(self._counts(), (0, 20, 0))
        locked = self.client.put(
            f"/api/backdate-requests/{created['id']}",
            headers=cashier,
            json={"version": body["version"], "reason": "changed quietly", "sales": body["sales"]},
        )
        self.assertEqual(locked.status_code, 400)
        returned = self.client.post(
            f"/api/backdate-requests/{created['id']}/return",
            headers=manager,
            json={"version": body["version"], "reason": "Use the shelf price"},
        )
        self.assertEqual(returned.status_code, 200, returned.get_json())
        self.assertEqual(returned.get_json()["review_note"], "Use the shelf price")
        edited = self.client.put(
            f"/api/backdate-requests/{created['id']}",
            headers=cashier,
            json={
                "version": returned.get_json()["version"],
                "reason": "Power was out",
                "sales": [
                    self._sale(self.sugar, 2, 100, "Cash", paid=200),
                    self._sale(self.sugar, 1, 100, "Credit Sale", paid=20, customer=self.customer),
                ],
            },
        )
        self.assertEqual(edited.status_code, 200, edited.get_json())
        resubmitted = self.client.post(
            f"/api/backdate-requests/{created['id']}/submit",
            headers=cashier, json={"version": edited.get_json()["version"]},
        )
        self.assertEqual(resubmitted.status_code, 200)
        current = resubmitted.get_json()
        self_approve = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=cashier, json={"version": current["version"]},
        )
        self.assertEqual(self_approve.status_code, 403)
        stale = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=manager, json={"version": current["version"] - 1},
        )
        self.assertEqual(stale.status_code, 409)
        first = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=manager, json={"version": current["version"], "note": "Books agree"},
        )
        self.assertEqual(first.status_code, 200, first.get_json())
        approved = first.get_json()
        self.assertEqual(approved["status"], "approved")
        self.assertFalse(approved["already_approved"])
        receipts = [sale["posted_receipt"] for sale in approved["sales"]]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(receipt.startswith("RCP-") for receipt in receipts))
        second = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=manager, json={"version": approved["version"]},
        )
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertTrue(second.get_json()["already_approved"])
        sales, stock, debts = self._counts()
        self.assertEqual(sales, 2)
        self.assertEqual(stock, 17)
        self.assertEqual(debts, 1)
        db = self.ac._db()
        try:
            days = [row["sale_date"] for row in db.execute("SELECT sale_date FROM sales")]
            self.assertEqual(set(days), {self.yesterday})
            created_at = db.execute("SELECT created_at FROM sales").fetchone()["created_at"]
            self.assertNotIn(self.yesterday, created_at[:10]) if False else None
            self.assertTrue(created_at.startswith(str(__import__('datetime').date.today())))
            debt = db.execute("SELECT balance, amount_paid, total_amount FROM debt_invoices").fetchone()
            self.assertEqual(debt["total_amount"], 100)
            self.assertEqual(debt["amount_paid"], 20)
            self.assertEqual(debt["balance"], 80)
            note = db.execute("SELECT notes FROM sales WHERE payment_method='M-Pesa'").fetchone()
            self.assertIsNone(note)
        finally:
            db.close()
        rewrite = self.client.put(
            f"/api/backdate-requests/{created['id']}",
            headers=manager,
            json={"version": approved["version"], "reason": "rewrite", "sales": []},
        )
        self.assertEqual(rewrite.status_code, 400)

    def test_short_stock_rolls_back_every_sale(self):
        cashier = self._login("cashier")
        manager = self._login("manager")
        created = self._create(cashier, [
            self._sale(self.sugar, 1, 100),
            self._sale(self.salt, 5, 40),
        ], day=self.older)
        submitted = self.client.post(
            f"/api/backdate-requests/{created['id']}/submit",
            headers=cashier, json={"version": created["version"]},
        )
        self.assertIn("Not enough stock", " ".join(submitted.get_json()["warnings"]))
        approved = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=manager, json={"version": submitted.get_json()["version"]},
        )
        self.assertEqual(approved.status_code, 400, approved.get_json())
        self.assertEqual(self._counts(), (0, 20, 0))
        salt = self.ac._db()
        try:
            self.assertEqual(salt.execute("SELECT stock FROM products WHERE id=?", (self.salt,)).fetchone()["stock"], 1)
        finally:
            salt.close()

    def test_reject_keeps_the_reason_and_posts_nothing(self):
        cashier = self._login("cashier")
        manager = self._login("manager")
        created = self._create(cashier, [self._sale(self.sugar, 1, 100, "Bank Transfer")])
        submitted = self.client.post(
            f"/api/backdate-requests/{created['id']}/submit",
            headers=cashier, json={"version": created["version"]},
        ).get_json()
        rejected = self.client.post(
            f"/api/backdate-requests/{created['id']}/reject",
            headers=manager, json={"version": submitted["version"], "reason": "No bank slip"},
        )
        self.assertEqual(rejected.status_code, 200, rejected.get_json())
        self.assertEqual(rejected.get_json()["status"], "rejected")
        self.assertEqual(rejected.get_json()["review_note"], "No bank slip")
        self.assertEqual(self._counts()[0], 0)
        again = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=manager, json={"version": rejected.get_json()["version"]},
        )
        self.assertEqual(again.status_code, 400)

    def test_mpesa_reference_is_stored_unverified(self):
        cashier = self._login("cashier")
        manager = self._login("manager")
        created = self._create(cashier, [self._sale(self.sugar, 1, 100, "M-Pesa", mpesa="XYZ999")])
        submitted = self.client.post(
            f"/api/backdate-requests/{created['id']}/submit",
            headers=cashier, json={"version": created["version"]},
        ).get_json()
        approved = self.client.post(
            f"/api/backdate-requests/{created['id']}/approve",
            headers=manager, json={"version": submitted["version"]},
        )
        self.assertEqual(approved.status_code, 200, approved.get_json())
        db = self.ac._db()
        try:
            row = db.execute("SELECT mpesa_ref, notes, sale_date, created_at FROM sales").fetchone()
            self.assertEqual(row["mpesa_ref"], "XYZ999")
            self.assertIn("not verified", row["notes"].lower())
            self.assertEqual(row["sale_date"], self.yesterday)
            self.assertNotEqual(row["created_at"][:10], self.yesterday)
        finally:
            db.close()
