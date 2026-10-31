import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.shop_update import classify_release


class UpdateCompareTests(unittest.TestCase):
    def test_numeric_compare_and_states(self):
        available = classify_release("3.1.70", {"version": "3.1.71", "notes": "Till fix", "released": "2026-10-28", "compatible": True}, reachable=True)
        self.assertEqual(available["state"], "available")
        self.assertIn("3.1.71", available["message"])
        self.assertFalse(available["installed"])
        older = classify_release("3.1.70", {"version": "3.1.9"}, reachable=True)
        self.assertEqual(older["state"], "current")
        self.assertEqual(classify_release("3.1.70", None, reachable=False)["state"], "unavailable")
        self.assertEqual(classify_release("", {"version": "3.1.71"}, reachable=True)["state"], "invalid")
        self.assertEqual(classify_release("3.1.70", {"version": "soon"}, reachable=True)["state"], "invalid")
        blocked = classify_release("3.1.70", {"version": "9.0.0", "compatible": False}, reachable=True)
        self.assertEqual(blocked["state"], "incompatible")
        self.assertEqual(blocked["action"], "")
        self.assertEqual(blocked["download_url"], "")


class DirectVoidTests(unittest.TestCase):
    def test_superadmin_voids_directly_and_others_cannot(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = os.path.join(tmp.name, "void.db")
        os.environ["MBT_DATA_ROOT"] = tmp.name
        os.environ["MBT_UPDATE_FEED_JSON"] = json.dumps({
            "version": "9.9.9",
            "notes": "Controlled test release",
            "released": "2026-10-28",
            "compatible": True,
            "source": "controlled test feed",
        })
        patches = [
            patch("mbt_paths.get_db_path", return_value=db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=db_path),
        ]
        for item in patches:
            item.start()
        try:
            import desktop.utils.api_client as ac
            ac._SCHEMA_READY = False
            db = ac._db()
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
                ("owner", ac._hash_pw("owner-pass"), "superadmin", "Owner"),
            )
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
                ("cashier", ac._hash_pw("cashier-pass"), "cashier", "Cashier"),
            )
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
                ("admin", ac._hash_pw("admin-pass"), "admin", "Admin"),
            )
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name, is_active) VALUES (?,?,?,?,1)",
                ("viewer", ac._hash_pw("viewer-pass"), "viewer", "Viewer"),
            )
            db.execute(
                "INSERT INTO sales (receipt_number, cashier_id, cashier_name, subtotal, discount, tax, total, "
                "payment_method, amount_paid, status, sale_date, created_at) "
                "VALUES ('RCP-DIRECT-1', 1, 'Owner', 50, 0, 0, 50, 'cash', 50, 'completed', '2026-10-27', '2026-10-27T10:00:00')"
            )
            db.execute(
                "INSERT INTO sales (receipt_number, cashier_id, cashier_name, subtotal, discount, tax, total, "
                "payment_method, amount_paid, status, sale_date, created_at) "
                "VALUES ('RCP-REQ-1', 2, 'Cashier', 20, 0, 0, 20, 'cash', 20, 'completed', '2026-10-27', '2026-10-27T11:00:00')"
            )
            db.commit()
            db.close()
            import backend.app as appmod
            appmod.DB_PATH = db_path
            client = appmod.app.test_client()

            def login(username, password):
                response = client.post("/api/auth/login", json={"username": username, "password": password})
                self.assertEqual(response.status_code, 200, response.get_json())
                return {"Authorization": f"Bearer {response.get_json()['token']}"}

            cashier = login("cashier", "cashier-pass")
            admin = login("admin", "admin-pass")
            viewer = login("viewer", "viewer-pass")
            owner = login("owner", "owner-pass")

            denied = client.post("/api/sales/1/void-now", json={"reason": "Wrong item"}, headers=cashier)
            self.assertEqual(denied.status_code, 403)
            denied_admin = client.post("/api/sales/1/void-now", json={"reason": "Wrong item"}, headers=admin)
            self.assertEqual(denied_admin.status_code, 403)

            asked = client.post("/api/sales/void-request", json={"receipt_number": "RCP-DIRECT-1", "reason": "Please void"}, headers=cashier)
            self.assertEqual(asked.status_code, 200, asked.get_json())
            request_id = asked.get_json()["id"]

            voided = client.post("/api/sales/1/void-now", json={"reason": "Wrong item rung"}, headers=owner)
            self.assertEqual(voided.status_code, 200, voided.get_json())
            self.assertEqual(voided.get_json().get("sale_status"), "voided")
            again = client.post("/api/sales/1/void-now", json={"reason": "Wrong item rung"}, headers=owner)
            self.assertEqual(again.status_code, 409)

            check = ac._db()
            status = check.execute("SELECT status FROM sales WHERE id=1").fetchone()["status"]
            self.assertEqual(status, "voided")
            audit = check.execute("SELECT action, details FROM audit_log WHERE action='VOID_SALE'").fetchone()
            self.assertIn("Wrong item rung", audit["details"])
            closed = check.execute("SELECT status FROM cc_approvals WHERE id=?", (request_id,)).fetchone()["status"]
            self.assertEqual(closed, "cancelled")
            check.close()

            hidden = client.get("/api/void-requests", headers=viewer)
            self.assertEqual(hidden.status_code, 403)
            feed = client.get("/api/updates/status", headers=owner)
            self.assertEqual(feed.status_code, 200, feed.get_json())
            self.assertEqual(feed.get_json()["state"], "available")
            self.assertEqual(feed.get_json()["available_version"], "9.9.9")
            self.assertFalse(feed.get_json()["installed"])

            second = client.post("/api/sales/void-request", json={"receipt_number": "RCP-REQ-1", "reason": "Customer changed"}, headers=cashier)
            self.assertEqual(second.status_code, 200, second.get_json())
            second_id = second.get_json()["id"]
            returned = client.post(f"/api/void-requests/{second_id}/return", json={"note": "Add the product name"}, headers=owner)
            self.assertEqual(returned.status_code, 200, returned.get_json())
            saved = client.put(f"/api/void-requests/{second_id}", json={"reason": "Customer returned the oil"}, headers=cashier)
            self.assertEqual(saved.status_code, 200, saved.get_json())
            sent = client.post(f"/api/void-requests/{second_id}/resubmit", headers=cashier)
            self.assertEqual(sent.status_code, 200, sent.get_json())
            detail = client.get(f"/api/void-requests/{second_id}", headers=owner)
            body = detail.get_json()
            self.assertEqual(body["status"], "pending")
            self.assertEqual(body["original_reason"], "Customer changed")
            self.assertEqual(body["current_reason"], "Customer returned the oil")
            self.assertEqual(body["receipt"]["status"], "completed")
        finally:
            os.environ.pop("MBT_UPDATE_FEED_JSON", None)
            for item in patches:
                item.stop()
            tmp.cleanup()
