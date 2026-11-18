"""Daraja request construction and callback rules. No Safaricom call."""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.daraja_client import (
    DarajaClient,
    base_url,
    clear_token_cache,
    reconcile_stk,
    stk_password,
    stk_timestamp,
    transaction_type,
)


class DarajaRequestTests(unittest.TestCase):
    def test_password_timestamp_and_endpoints(self):
        moment = datetime(2016, 2, 16, 16, 56, 27, tzinfo=ZoneInfo("Africa/Nairobi"))
        stamp = stk_timestamp(moment)
        self.assertEqual(stamp, "20160216165627")
        password = stk_password("174379", "passkey", stamp)
        self.assertEqual(base64.b64decode(password).decode(), "174379passkey20160216165627")
        self.assertEqual(base_url("sandbox"), "https://sandbox.safaricom.co.ke")
        self.assertEqual(base_url("production"), "https://api.safaricom.co.ke")
        self.assertEqual(transaction_type("till"), "CustomerBuyGoodsOnline")
        self.assertEqual(transaction_type("paybill"), "CustomerPayBillOnline")

    def test_push_builds_a_sandbox_request_and_does_not_call_safaricom(self):
        clear_token_cache()
        seen = []

        class Response:
            def __init__(self, payload):
                self._raw = json.dumps(payload).encode()

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, timeout):
            seen.append((request.full_url, timeout, request.data))
            if "oauth" in request.full_url:
                return Response({"access_token": "token-not-for-logs", "expires_in": "3599"})
            return Response({
                "MerchantRequestID": "m-1",
                "CheckoutRequestID": "ws_CO_test",
                "ResponseCode": "0",
                "ResponseDescription": "Success. Request accepted for processing",
                "CustomerMessage": "Success. Request accepted for processing",
            })

        client = DarajaClient(
            environment="sandbox",
            consumer_key="key",
            consumer_secret="secret",
            shortcode="174379",
            passkey="passkey",
            merchant_type="paybill",
            party_b="174379",
            callback_url="https://example.test/api/daraja/stk/callback",
            opener=opener,
        )
        sent = client.stk_push(
            phone="254708374149", amount=100, account_reference="MBTTEST", description="Payment",
        )
        self.assertEqual(sent["response_code"], "0")
        self.assertNotIn("receipt", sent)
        self.assertTrue(seen[0][0].startswith("https://sandbox.safaricom.co.ke/oauth/"))
        self.assertTrue(seen[1][0].endswith("/mpesa/stkpush/v1/processrequest"))
        body = json.loads(seen[1][2].decode())
        self.assertEqual(body["Amount"], 100)
        self.assertEqual(body["TransactionType"], "CustomerPayBillOnline")
        self.assertEqual(body["PhoneNumber"], "254708374149")
        self.assertNotIn("secret", json.dumps({k: v for k, v in body.items() if k != "Password"}))

    def test_query_and_callback_must_agree(self):
        callback = {
            "Body": {"stkCallback": {
                "CheckoutRequestID": "ws_CO_1",
                "ResultCode": 0,
                "CallbackMetadata": {"Item": [
                    {"Name": "Amount", "Value": 100},
                    {"Name": "MpesaReceiptNumber", "Value": "QAH8RCPT"},
                ]},
            }}
        }
        agreed = reconcile_stk(
            query={"ResultCode": "0", "ResultDesc": "ok", "CheckoutRequestID": "ws_CO_1"},
            callback=callback, intended_shillings=100, checkout_id="ws_CO_1",
        )
        self.assertEqual(agreed["state"], "verified")
        self.assertEqual(agreed["verification"], "verified_daraja")
        disagreed = reconcile_stk(
            query={"ResultCode": "1032", "ResultDesc": "cancelled", "CheckoutRequestID": "ws_CO_1"},
            callback=callback, intended_shillings=100, checkout_id="ws_CO_1",
        )
        self.assertEqual(disagreed["state"], "unknown")
        self.assertNotEqual(disagreed["verification"], "verified_daraja")
        missing = reconcile_stk(
            query={"ResultCode": "0", "CheckoutRequestID": "ws_CO_1"},
            callback=None, intended_shillings=100, checkout_id="ws_CO_1",
        )
        self.assertEqual(missing["state"], "unresolved")


class CallbackSettlementTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = sqlite3.connect(os.path.join(self._tmpdir.name, "mpesa.db"))
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY)")
        from backend.mpesa_service import ensure_tables
        ensure_tables(self.db)
        self.db.execute(
            """INSERT INTO mpesa_payments
               (id, idempotency_key, kind, state, amount_shillings, checkout_request_id,
                verification, created_at, updated_at)
               VALUES ('pay-1','key-1','stk','prompt_sent',100,'ws_CO_1','unverified','t','t')"""
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def _callback(self, checkout="ws_CO_1", amount=100, receipt="QAH8RCPT"):
        return {
            "Body": {"stkCallback": {
                "CheckoutRequestID": checkout,
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {"Item": [
                    {"Name": "Amount", "Value": amount},
                    {"Name": "MpesaReceiptNumber", "Value": receipt},
                    {"Name": "PhoneNumber", "Value": 254708374149},
                ]},
            }}
        }

    def test_callback_does_not_settle_and_a_replay_does_not_duplicate(self):
        from backend.mpesa_service import apply_stk_callback
        first = apply_stk_callback(self.db, self._callback())
        self.db.commit()
        self.assertFalse(first["settled"])
        self.assertTrue(first["matched"])
        state = self.db.execute("SELECT state FROM mpesa_payments WHERE id='pay-1'").fetchone()[0]
        self.assertEqual(state, "prompt_sent")
        stored = self.db.execute("SELECT evidence_json FROM mpesa_payments WHERE id='pay-1'").fetchone()[0]
        self.assertNotIn("254708374149", stored)
        second = apply_stk_callback(self.db, self._callback())
        self.assertTrue(second["duplicate"])
        count = self.db.execute("SELECT COUNT(*) FROM mpesa_callbacks").fetchone()[0]
        self.assertEqual(count, 1)

    def test_unknown_and_malformed_callbacks_do_not_create_a_sale(self):
        from backend.mpesa_service import MpesaSaleError, apply_stk_callback
        unknown = apply_stk_callback(self.db, self._callback(checkout="ws_CO_other"))
        self.db.commit()
        self.assertFalse(unknown["matched"])
        self.assertFalse(unknown["settled"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)
        with self.assertRaises(MpesaSaleError):
            apply_stk_callback(self.db, {"no": "checkout"})

    def test_production_profile_stays_locked_without_go_live(self):
        from backend.mpesa_service import MpesaSaleError, create_profile
        actor = {"role": "admin", "username": "owner"}
        with self.assertRaises(MpesaSaleError) as raised:
            create_profile(self.db, actor, {
                "name": "Shop",
                "merchant_type": "paybill",
                "shortcode": "174379",
                "environment": "production",
                "callback_url": "https://shop.example/api/daraja/stk/callback",
                "consumer_key": "key",
                "consumer_secret": "secret",
                "passkey": "pass",
            })
        self.assertIn("locked", str(raised.exception).lower())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM mpesa_profiles").fetchone()[0], 0)
