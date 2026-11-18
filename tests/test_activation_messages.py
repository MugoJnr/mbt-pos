"""Shop-owner wording for activation failures. No network and no licence store."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from licensing.activation_messages import explain_activation_failure


class ActivationMessageTests(unittest.TestCase):
    def test_network_failure_does_not_look_like_a_revoked_licence(self):
        text = explain_activation_failure(
            "HTTPSConnectionPool(host='portal.mugobyte.com'): Max retries exceeded"
        )
        self.assertIn("did not answer", text)
        self.assertIn("no extra computer seat", text)
        self.assertNotIn("revoked", text.lower())

    def test_full_plan_tells_the_owner_to_release_a_computer(self):
        text = explain_activation_failure(
            "License reserved for this email has no free device seat"
        )
        self.assertIn("already in use", text)
        self.assertIn("release", text.lower())

    def test_unverified_email_does_not_ask_for_a_cashier_account(self):
        text = explain_activation_failure("Email verification required")
        self.assertIn("not confirmed", text)
        self.assertIn("Cashiers do not", text)

    def test_expired_and_revoked_keep_the_shop_records(self):
        self.assertIn("records", explain_activation_failure("License is expired"))
        self.assertIn("unchanged", explain_activation_failure("License is revoked"))

    def test_success_text_is_not_rewritten(self):
        done = "Cloud license activated! Plan: Monthly (30 days)"
        self.assertEqual(explain_activation_failure(done), done)

    def test_vague_failure_gets_a_next_step(self):
        text = explain_activation_failure("Activation failed")
        self.assertNotEqual(text, "Activation failed")
        self.assertIn("try again", text.lower())


if __name__ == "__main__":
    unittest.main()
