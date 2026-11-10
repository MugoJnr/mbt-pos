"""M-Pesa money rules on disposable shops. No Safaricom call and no live shop database."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _Lab(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.store = {"profiles": {}, "stk": {}, "pushes": 0}
        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def _json(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read(self):
                length = int(self.headers.get("Content-Length") or 0)
                if not length:
                    return {}
                return json.loads(self.rfile.read(length).decode() or "{}")

            def _tenant(self):
                return self.headers.get("X-Tenant-ID") or ""

            def do_GET(self):
                if urlparse(self.path).path == "/api/v1/health":
                    self._json(200, {"status": "ok"})
                    return
                self._json(404, {"detail": "not found"})

            def do_POST(self):
                path = urlparse(self.path).path
                body = self._read()
                tenant = self._tenant()
                if self.headers.get("Authorization") != "Bearer test-token":
                    self._json(401, {"detail": "Unauthorized"})
                    return
                if path == "/api/v1/profiles":
                    if "consumer_key" not in body or "passkey" not in body:
                        self._json(400, {"detail": "credentials required"})
                        return
                    profile_id = str(uuid.uuid4())
                    lab.store["profiles"][(tenant, profile_id)] = {
                        "status": "draft",
                        "key": body["consumer_key"],
                    }
                    self._json(201, {"id": profile_id, "status": "draft", "secrets_visible": False})
                    return
                if path.endswith("/activate"):
                    profile_id = path.split("/")[-2]
                    row = lab.store["profiles"].get((tenant, profile_id))
                    if not row:
                        self._json(404, {"detail": "Profile not found"})
                        return
                    row["status"] = "active"
                    self._json(200, {"id": profile_id, "status": "active"})
                    return
                if path.endswith("/authenticate"):
                    profile_id = path.split("/")[-2]
                    row = lab.store["profiles"].get((tenant, profile_id))
                    if not row:
                        self._json(404, {"detail": "Profile not found"})
                        return
                    self._json(200, {
                        "success": True,
                        "message": "Mock credentials accepted. Safaricom was not contacted.",
                        "provider": "mock",
                        "payment_created": False,
                    })
                    return
                if path.endswith("/stk-push"):
                    lab.store["pushes"] += 1
                    profile = lab.store["profiles"].get((tenant, body.get("profile_id")))
                    if not profile or profile["status"] != "active":
                        self._json(404, {"detail": "No active M-Pesa profile found for tenant"})
                        return
                    checkout = "ws_CO_MOCK_" + uuid.uuid4().hex[:12]
                    lab.store["stk"][(tenant, checkout)] = body
                    self._json(200, {
                        "merchant_request_id": "mock-merchant",
                        "checkout_request_id": checkout,
                        "response_code": "0",
                        "response_description": "Accepted. Not payment.",
                        "customer_message": "Prompt sent.",
                        "provider": "mock",
                        "duplicate": False,
                    })
                    return
                if path.endswith("/stk-query"):
                    checkout = body.get("checkout_request_id")
                    stored = lab.store["stk"].get((tenant, checkout))
                    if not stored:
                        self._json(404, {"detail": "Transaction not found"})
                        return
                    if not body.get("queried_by_client", True):
                        pass
                    phone = str(stored.get("phone") or "")
                    amount = stored.get("amount")
                    if phone.endswith("1000"):
                        code, receipt = "1032", None
                    elif phone.endswith("1004"):
                        code, receipt, amount = "0", "MOCKMISMAT", 1
                    elif phone.endswith("1008"):
                        self._json(200, {
                            "ResultCode": "0",
                            "ResultDesc": "The service request is processed successfully.",
                            "CheckoutRequestID": checkout,
                            "provider": "daraja",
                            "queried": True,
                            "callback_payload": {
                                "Body": {"stkCallback": {
                                    "MerchantRequestID": "29115-34620561-1",
                                    "CheckoutRequestID": checkout,
                                    "ResultCode": 0,
                                    "ResultDesc": "The service request is processed successfully.",
                                    "CallbackMetadata": {"Item": [
                                        {"Name": "Amount", "Value": amount},
                                        {"Name": "MpesaReceiptNumber", "Value": "QAH8RCPT"},
                                        {"Name": "PhoneNumber", "Value": phone},
                                    ]},
                                }}
                            },
                        })
                        return
                    elif phone.endswith("1009"):
                        self._json(200, {
                            "ResultCode": "0",
                            "ResultDesc": "The service request is processed successfully.",
                            "CheckoutRequestID": checkout,
                            "provider": "daraja",
                            "queried": True,
                        })
                        return
                    elif phone.endswith("1007"):
                        self._json(200, {
                            "ResultCode": "0",
                            "ResultDesc": "The service request is processed successfully.",
                            "CheckoutRequestID": checkout,
                            "provider": "daraja",
                            "queried": True,
                            "callback_payload": {
                                "Body": {"stkCallback": {
                                    "CheckoutRequestID": checkout,
                                    "ResultCode": 0,
                                    "CallbackMetadata": {"Item": [
                                        {"Name": "Amount", "Value": 1},
                                        {"Name": "MpesaReceiptNumber", "Value": "QAH7RCPT"},
                                    ]},
                                }}
                            },
                        })
                        return
                    else:
                        code, receipt = "0", "MOCK" + checkout[-6:].upper()
                    self._json(200, {
                        "ResultCode": code,
                        "ResultDesc": "queried",
                        "Amount": amount,
                        "MpesaReceiptNumber": receipt,
                        "provider": "mock",
                        "queried": True,
                    })
                    return
                self._json(404, {"detail": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


class MpesaMoneyRules(unittest.TestCase):
    def setUp(self):
        self.lab = _Lab()
        self.lab.start()
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.tmp.name, "shop.db")
        self.patches = [
            patch("mbt_paths.get_db_path", return_value=self.db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self.db_path),
            patch("backend.mpesa_service.get_db_path", return_value=self.db_path),
            patch("backend.mpesa_service.get_data_dir", return_value=self.tmp.name),
        ]
        for item in self.patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
            ("owner", "x:y", "superadmin"),
        )
        db.execute(
            "INSERT INTO products (name, sku, barcode, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?,?)",
            ("Soap", "MP-SOAP", "61610001", 100, 40, 20, 1),
        )
        db.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("daraja_gateway_url", f"http://127.0.0.1:{self.lab.port}"),
        )
        db.commit()
        db.close()
        from backend.mpesa_service import save_service_token
        save_service_token("test-token")
        self.owner = {"role": "superadmin", "username": "owner"}
        self.cashier = {"role": "cashier", "username": "cashier"}

    def tearDown(self):
        self.lab.stop()
        for item in self.patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self.tmp.cleanup()

    def _db(self):
        from backend.mpesa_service import connect
        return connect()

    def _profile(self, name="Till A", shortcode="111111"):
        from backend.mpesa_service import create_profile, set_profile_status
        db = self._db()
        try:
            created = create_profile(db, self.owner, {
                "name": name,
                "merchant_type": "till",
                "till_number": shortcode,
                "shortcode": shortcode,
                "business_name": name,
                "consumer_key": "mock:key",
                "consumer_secret": "mock:secret",
                "passkey": "mock:pass",
            })
            db.commit()
            active = set_profile_status(db, self.owner, created["id"], True, True)
            db.commit()
            return active
        finally:
            db.close()

    def _sale(self, **extra):
        payload = {
            "items": [{"product_id": 1, "quantity": 1, "unit_price": 100, "discount": 0}],
            "subtotal": 100,
            "discount": 0,
            "tax": 0,
            "total": 100,
            "payment_method": "M-Pesa",
            "amount_paid": 100,
            "change_amount": 0,
        }
        payload.update(extra)
        return self.api.create_sale(payload)

    def test_prompt_is_not_payment_until_query_matches(self):
        from backend.mpesa_service import poll_payment, start_stk
        profile = self._profile()
        self.assertNotIn("mock:key", json.dumps(profile))
        self.assertFalse(profile["secrets_visible"])
        db = self._db()
        try:
            first = start_stk(
                db, self.owner, phone="0711111111", amount=100, profile_id=profile["id"],
                sale_reference="SALE1", idempotency_key="same-key",
            )
            second = start_stk(
                db, self.owner, phone="0711111111", amount=100, profile_id=profile["id"],
                sale_reference="SALE1", idempotency_key="same-key",
            )
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(self.lab.store["pushes"], 1)
            self.assertEqual(first["state"], "prompt_sent")
            self.assertFalse(first["safaricom_confirmed"])
            self.assertNotEqual(first["state"], "verified")
            verified = poll_payment(db, self.owner, first["id"])
            self.assertEqual(verified["state"], "verified")
            self.assertEqual(verified["verification"], "verified_mock")
            self.assertTrue(verified["simulated"])
            self.assertFalse(verified["safaricom_confirmed"])
        finally:
            db.close()
        saved = self._sale(mpesa_payment_id=verified["id"], client_token="verified-1")
        self.assertTrue(saved.get("sale_id") or saved.get("id"), saved)
        sale_id = saved.get("sale_id") or saved.get("id")
        db = self._db()
        try:
            posted = db.execute(
                """SELECT jl.debit FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.journal_id
                   WHERE je.source_id=? AND jl.account_code='1010'""",
                (str(sale_id),),
            ).fetchone()
            self.assertIsNotNone(posted, "verified M-Pesa was not posted to account 1010")
            self.assertEqual(float(posted[0]), 100.0)
        finally:
            db.close()
        again = self._sale(mpesa_payment_id=verified["id"], client_token="verified-2")
        self.assertIn("already attached", again.get("error", "").lower())

    def test_unknown_result_is_not_sent_again(self):
        from backend.mpesa_service import start_stk
        profile = self._profile(shortcode="222222")
        self.lab.store["fail_next"] = True

        class Broken:
            pass

        original = self.lab.store
        # Close the socket path by pointing the shop at a closed port after the profile exists.
        db = self._db()
        db.execute("UPDATE system_settings SET value=? WHERE key='daraja_gateway_url'", ("http://127.0.0.1:9",))
        db.commit()
        try:
            unknown = start_stk(
                db, self.owner, phone="0711111111", amount=100, profile_id=profile["id"],
                sale_reference="SALE9", idempotency_key="lost-1",
            )
            self.assertEqual(unknown["state"], "unknown")
            pushes = self.lab.store["pushes"]
            again = start_stk(
                db, self.owner, phone="0711111111", amount=100, profile_id=profile["id"],
                sale_reference="SALE9", idempotency_key="lost-1",
            )
            self.assertEqual(again["id"], unknown["id"])
            self.assertEqual(self.lab.store["pushes"], pushes)
        finally:
            db.close()
        self.assertIs(original, self.lab.store)

    def test_shared_till_text_does_not_reuse_another_prompt(self):
        from backend.mpesa_service import start_stk
        profile = self._profile(shortcode="333333")
        db = self._db()
        try:
            first = start_stk(
                db, self.owner, phone="0711111111", amount=100, profile_id=profile["id"],
                sale_reference="TILL", idempotency_key="desk-1",
            )
            second = start_stk(
                db, self.cashier, phone="0722222222", amount=100, profile_id=profile["id"],
                sale_reference="TILL", idempotency_key="web-1",
            )
        finally:
            db.close()
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["sale_reference"], second["sale_reference"])
        self.assertTrue(first["sale_reference"].startswith("MP"))
        self.assertNotEqual(first["sale_reference"], "TILL")
        self.assertEqual(self.lab.store["pushes"], 2)

    def test_daraja_query_without_receipt_does_not_verify(self):
        from backend.mpesa_service import poll_payment, start_stk
        profile = self._profile(shortcode="444444")
        db = self._db()
        try:
            pending = start_stk(
                db, self.owner, phone="0711111009", amount=100, profile_id=profile["id"],
                sale_reference="WEB", idempotency_key="no-evidence",
            )
            polled = poll_payment(db, self.owner, pending["id"])
            self.assertEqual(polled["state"], "waiting")
            self.assertNotEqual(polled["verification"], "verified_daraja")
            self.assertFalse(polled["safaricom_confirmed"])
        finally:
            db.close()
        blocked = self._sale(mpesa_payment_id=pending["id"], client_token="no-evidence-sale")
        self.assertIn("not verified", blocked.get("error", "").lower())

    def test_documented_callback_amount_can_verify_and_a_mismatch_cannot(self):
        from backend.mpesa_service import poll_payment, start_stk
        profile = self._profile(shortcode="445544")
        db = self._db()
        try:
            good = start_stk(
                db, self.owner, phone="0711111008", amount=100, profile_id=profile["id"],
                sale_reference="", idempotency_key="daraja-good",
            )
            verified = poll_payment(db, self.owner, good["id"])
            self.assertEqual(verified["state"], "verified")
            self.assertEqual(verified["verification"], "verified_daraja")
            self.assertEqual(verified["receipt_code"], "QAH8RCPT")
            self.assertTrue(verified["safaricom_confirmed"])
            bad = start_stk(
                db, self.owner, phone="0711111007", amount=100, profile_id=profile["id"],
                sale_reference="", idempotency_key="daraja-bad",
            )
            rejected = poll_payment(db, self.owner, bad["id"])
            self.assertEqual(rejected["state"], "rejected")
            self.assertFalse(rejected["safaricom_confirmed"])
        finally:
            db.close()

    def test_incoming_1200_matches_the_mpesa_slice_not_the_sale_total(self):
        from backend.mpesa_service import match_incoming, record_incoming
        db = self._db()
        db.execute("UPDATE products SET price=3000, stock=5 WHERE id=1")
        db.commit()
        db.close()
        sale = self._sale(
            items=[{"product_id": 1, "quantity": 1, "unit_price": 3000, "discount": 0}],
            subtotal=3000, total=3000, amount_paid=3000, payment_method="Mixed",
            payment_tenders=[
                {"method": "Cash", "amount": 1000},
                {"method": "M-Pesa", "amount": 1200},
                {"method": "Bank", "amount": 800},
            ],
            client_token="split-3000",
        )
        sale_id = sale.get("sale_id") or sale.get("id")
        self.assertTrue(sale_id, sale)
        db = self._db()
        try:
            wrong = record_incoming(db, self.owner, {"provider_ref": "QAH3000", "amount": 3000})
            db.commit()
            with self.assertRaises(Exception) as caught:
                match_incoming(db, self.owner, wrong["id"], int(sale_id), "amount is the whole sale")
            self.assertIn("does not match", str(caught.exception).lower())
            incoming = record_incoming(db, self.owner, {"provider_ref": "QAH1200", "amount": 1200})
            db.commit()
            matched = match_incoming(db, self.owner, incoming["id"], int(sale_id), "mpesa slice")
            self.assertEqual(matched["state"], "matched")
            self.assertEqual(int(matched["sale_id"]), int(sale_id))
        finally:
            db.close()

    def test_duplicate_manual_code_and_cashier_boundary(self):
        from backend.mpesa_service import MpesaSaleError, create_profile
        first = self._sale(mpesa_ref="QAH9TEST", client_token="manual-1")
        self.assertTrue(first.get("sale_id") or first.get("id"), first)
        second = self._sale(mpesa_ref="QAH9TEST", client_token="manual-2")
        self.assertIn("already recorded", second.get("error", "").lower())
        db = self._db()
        try:
            with self.assertRaises(MpesaSaleError):
                create_profile(db, self.cashier, {
                    "name": "Nope",
                    "merchant_type": "till",
                    "shortcode": "333333",
                    "consumer_key": "mock:key",
                    "consumer_secret": "mock:secret",
                    "passkey": "mock:pass",
                })
            with self.assertRaises(MpesaSaleError):
                create_profile(db, self.owner, {
                    "name": "Live",
                    "merchant_type": "paybill",
                    "shortcode": "444444",
                    "environment": "production",
                    "consumer_key": "mock:key",
                    "consumer_secret": "mock:secret",
                    "passkey": "mock:pass",
                })
        finally:
            db.close()

    def test_other_shop_cannot_verify_this_prompt(self):
        from backend.mpesa_service import poll_payment, start_stk
        profile = self._profile(name="Shop A", shortcode="555555")
        db = self._db()
        try:
            payment = start_stk(
                db, self.owner, phone="0711111111", amount=100, profile_id=profile["id"],
                sale_reference="SHOP-A", idempotency_key="shop-a",
            )
            checkout = db.execute(
                "SELECT checkout_request_id FROM mpesa_payments WHERE id=?", (payment["id"],)
            ).fetchone()[0]
        finally:
            db.close()
        other_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        other_path = os.path.join(other_dir.name, "other.db")
        for item in self.patches:
            item.stop()
        other_patches = [
            patch("mbt_paths.get_db_path", return_value=other_path),
            patch("desktop.utils.api_client.get_db_path", return_value=other_path),
            patch("backend.mpesa_service.get_db_path", return_value=other_path),
            patch("backend.mpesa_service.get_data_dir", return_value=other_dir.name),
        ]
        for item in other_patches:
            item.start()
        self.ac._SCHEMA_READY = False
        other = self.ac.APIClient()
        other._role = "superadmin"
        other._user_id = 1
        other._username = "other"
        odb = self.ac._db()
        odb.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("daraja_gateway_url", f"http://127.0.0.1:{self.lab.port}"),
        )
        from backend.mpesa_service import ensure_tables, save_service_token
        ensure_tables(odb)
        odb.execute(
            """INSERT INTO mpesa_payments
               (id, idempotency_key, profile_id, kind, state, amount_shillings, checkout_request_id,
                verification, created_at, updated_at)
               VALUES ('copied','copied','x','stk','prompt_sent',100,?,'unverified','t','t')""",
            (checkout,),
        )
        odb.commit()
        odb.close()
        save_service_token("test-token")
        odb = self._db()
        try:
            result = poll_payment(odb, self.owner, "copied")
            self.assertNotEqual(result["state"], "verified")
            self.assertFalse(result["safaricom_confirmed"])
        finally:
            odb.close()
            for item in other_patches:
                item.stop()
            other_dir.cleanup()
            for item in self.patches:
                item.start()


if __name__ == "__main__":
    unittest.main()
