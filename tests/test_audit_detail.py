import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.audit_detail import describe_event, parse_changes, redact


class AuditDetailTests(unittest.TestCase):
    def test_before_and_after_come_only_from_the_recorded_text(self):
        changes = parse_changes("pid=4 price 150->180, name Sugar->Brown sugar")
        self.assertEqual(changes[0]["field"], "price")
        self.assertEqual(changes[0]["before"], "150")
        self.assertEqual(changes[0]["after"], "180")
        event = describe_event({"id": 9, "action": "UPDATE_PRODUCT", "details": "pid=4 price 150->180"})
        self.assertEqual(event["role_at_event"], "Not recorded")
        self.assertEqual(event["changes"][0]["after"], "180")

    def test_secrets_in_the_text_are_masked(self):
        self.assertIn("[masked]", redact("password=hunter2 token=abc.def"))
        self.assertNotIn("hunter2", redact("password=hunter2"))

    def test_detail_api_is_read_only_and_role_checked(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = os.path.join(tmp.name, "audit.db")
        os.environ["MBT_DATA_ROOT"] = tmp.name
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
                "INSERT INTO products (name, sku, price, stock, is_active) VALUES ('Audit Rice', 'AUD-R', 100, 5, 1)"
            )
            pid = db.execute("SELECT id FROM products").fetchone()["id"]
            db.execute(
                "INSERT INTO audit_log (user_id, username, action, module, details) VALUES (?,?,?,?,?)",
                (1, "owner", "UPDATE_PRODUCT", "inventory", f"pid={pid} price 100->125, password=secret"),
            )
            db.execute(
                "INSERT INTO audit_log (user_id, username, action, module, details) VALUES (?,?,?,?,?)",
                (1, "owner", "UPDATE_PRODUCT", "inventory", f"pid={pid} stock 5->4"),
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
            denied = client.get("/api/audit/1", headers=cashier)
            self.assertEqual(denied.status_code, 403)
            owner = login("owner", "owner-pass")
            detail = client.get("/api/audit/1", headers=owner)
            self.assertEqual(detail.status_code, 200, detail.get_json())
            body = detail.get_json()
            self.assertEqual(body["id"], 1)
            self.assertEqual(body["changes"][0]["after"], "125")
            self.assertNotIn("secret", body["details"])
            self.assertEqual(body["linked"]["record"]["name"], "Audit Rice")
            self.assertEqual(len(body["related"]), 1)
            missing = client.get("/api/audit/99", headers=owner)
            self.assertEqual(missing.status_code, 404)
            edited = client.put("/api/audit/1", headers=owner, json={"details": "changed"})
            self.assertEqual(edited.status_code, 405)
            ac._SCHEMA_READY = False
        finally:
            for item in patches:
                item.stop()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
