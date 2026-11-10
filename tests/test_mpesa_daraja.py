"""Daraja response shapes. Documentation-derived, not captured live traffic."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.mpesa_daraja import normalise_stk_query


CHECKOUT = "ws_CO_191220191020363925"


def _callback(amount=100, receipt="NLJ7RT61SV", code=0, checkout=CHECKOUT, extra_item=None):
    items = [
        {"Name": "Amount", "Value": amount},
        {"Name": "MpesaReceiptNumber", "Value": receipt},
        {"Name": "TransactionDate", "Value": 20191219102115},
        {"Name": "PhoneNumber", "Value": 254708374149},
    ]
    if extra_item:
        items.append(extra_item)
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "29115-34620561-1",
                "CheckoutRequestID": checkout,
                "ResultCode": code,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {"Item": items},
            }
        }
    }


def _query(**extra):
    body = {
        "ResponseCode": "0",
        "ResponseDescription": "The service request has been accepted successsfully",
        "MerchantRequestID": "29115-34620561-1",
        "CheckoutRequestID": CHECKOUT,
        "ResultCode": "0",
        "ResultDesc": "The service request is processed successfully.",
        "provider": "daraja",
        "queried": True,
    }
    body.update(extra)
    return body


class DarajaNormaliser(unittest.TestCase):
    def test_query_plus_documented_callback_verifies(self):
        decision = normalise_stk_query(
            _query(callback_payload=_callback()),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(decision["state"], "verified")
        self.assertEqual(decision["verification"], "verified_daraja")
        self.assertEqual(decision["receipt"], "NLJ7RT61SV")

    def test_success_without_amount_or_receipt_stays_unresolved(self):
        missing_amount = normalise_stk_query(
            _query(callback_payload=_callback(amount=None, receipt="NLJ7RT61SV")),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(missing_amount["state"], "unresolved")
        missing_receipt = normalise_stk_query(
            _query(callback_payload=_callback(receipt="")),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(missing_receipt["state"], "unresolved")
        query_only = normalise_stk_query(_query(), intended_shillings=100, checkout_id=CHECKOUT)
        self.assertEqual(query_only["state"], "unresolved")

    def test_acknowledgement_and_disagreement_do_not_settle(self):
        ack = {
            "ResponseCode": "0",
            "ResponseDescription": "Accept the service request successfully.",
            "CheckoutRequestID": CHECKOUT,
            "MerchantRequestID": "29115-34620561-1",
            "provider": "daraja",
            "queried": False,
        }
        self.assertEqual(
            normalise_stk_query(ack, intended_shillings=100, checkout_id=CHECKOUT)["state"],
            "unresolved",
        )
        disagree = normalise_stk_query(
            _query(callback_payload=_callback(code=1032)),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(disagree["state"], "unresolved")
        self.assertNotEqual(disagree["verification"], "verified_daraja")

    def test_wrong_amount_wrong_prompt_and_duplicate_metadata(self):
        wrong = normalise_stk_query(
            _query(callback_payload=_callback(amount=1)),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(wrong["state"], "rejected")
        other = normalise_stk_query(
            _query(callback_payload=_callback(checkout="ws_CO_OTHER")),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(other["state"], "rejected")
        duplicate = _callback(extra_item={"Name": "Amount", "Value": 5})
        ambiguous = normalise_stk_query(
            _query(callback_payload=duplicate),
            intended_shillings=100,
            checkout_id=CHECKOUT,
        )
        self.assertEqual(ambiguous["state"], "unresolved")

    def test_cancel_timeout_and_failure(self):
        self.assertEqual(
            normalise_stk_query(_query(ResultCode="1032"), intended_shillings=100, checkout_id=CHECKOUT)["state"],
            "cancelled",
        )
        self.assertEqual(
            normalise_stk_query(_query(ResultCode="1037"), intended_shillings=100, checkout_id=CHECKOUT)["state"],
            "timeout",
        )
        self.assertEqual(
            normalise_stk_query(_query(ResultCode="1"), intended_shillings=100, checkout_id=CHECKOUT)["state"],
            "failed",
        )
        self.assertEqual(
            normalise_stk_query(_query(ResultCode=None), intended_shillings=100, checkout_id=CHECKOUT)["state"],
            "unresolved",
        )


if __name__ == "__main__":
    unittest.main()
