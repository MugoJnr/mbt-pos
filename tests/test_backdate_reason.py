"""A past date needs a chosen reason before it can wait for approval."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.dated_actions import consider
from desktop.utils.shop_time import shop_today


def cashier():
    return {
        "id": 9,
        "username": "qa_cashier",
        "role": "cashier",
        "permission_grants": [],
        "permission_denials": [],
    }


class BackdateReasonTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.yesterday = (shop_today() - timedelta(days=1)).isoformat()

    def test_past_date_without_a_reason_is_refused(self):
        result = consider(
            self.db, cashier(), "consumption", self.yesterday,
            {"client_token": "no-reason", "reason": "Cleaning"},
        )
        self.assertEqual(result["status"], 400)
        self.assertIn("reason", result["error"].lower())
        self.assertIsNone(
            self.db.execute("SELECT id FROM dated_action_requests").fetchone()
        )

    def test_other_without_an_explanation_is_refused(self):
        result = consider(
            self.db, cashier(), "expense", self.yesterday,
            {"client_token": "other-only", "backdate_reason": "Other"},
        )
        self.assertEqual(result["status"], 400)

    def test_chosen_reason_is_kept_for_the_reviewer(self):
        result = consider(
            self.db, cashier(), "supplier_delivery", self.yesterday,
            {
                "client_token": "with-reason",
                "backdate_reason": "Supplier delivery recorded late",
            },
        )
        self.assertTrue(result["pending_approval"])
        self.assertEqual(result["backdate_reason"], "Supplier delivery recorded late")
        self.assertFalse(result["posted"])


if __name__ == "__main__":
    unittest.main()
