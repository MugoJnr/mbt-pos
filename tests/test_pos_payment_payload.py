"""A card or cash sale must not resubmit a leftover M-Pesa code."""
from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS = os.path.join(ROOT, "web", "dashboard-ui", "src", "routes", "pos.tsx")


class PosPaymentPayloadTests(unittest.TestCase):
    def test_other_methods_do_not_send_the_mpesa_code(self):
        with open(POS, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('(payment === "M-Pesa" || payment === "Split")', text)
        self.assertIn(": undefined,", text)
        self.assertNotIn(
            "mpesa_ref: mpesaCode || (mpesaPayment?.state === \"verified\" ? mpesaPayment.receipt_code : undefined),",
            text,
        )


if __name__ == "__main__":
    unittest.main()
