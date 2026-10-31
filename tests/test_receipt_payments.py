import unittest

from desktop.utils.payment_tenders import explain_sale_payments, payment_slip_text


class ReceiptPaymentTests(unittest.TestCase):
    def test_sample_split_keeps_tendered_cash_and_shows_change(self):
        slip = explain_sale_payments({
            "total": 55,
            "amount_paid": 55,
            "change_amount": 20,
            "cash_paid": 20,
            "payment_method": "Cash + M-Pesa",
            "payment_tenders": [
                {"method": "Cash", "amount": 40, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 35, "status": "confirmed"},
            ],
        })
        self.assertEqual([line["amount"] for line in slip["lines"]], [40, 35])
        self.assertEqual(slip["lines"][0]["kind"], "tendered")
        self.assertEqual(slip["lines"][1]["kind"], "allocated")
        self.assertEqual(slip["sale_total"], 55)
        self.assertEqual(slip["amount_tendered"], 75)
        self.assertEqual(slip["amount_collected"], 55)
        self.assertEqual(slip["change"], 20)
        self.assertEqual(slip["outstanding"], 0)
        self.assertTrue(slip["consistent"])
        self.assertIn("20.00", slip["note"])
        text = payment_slip_text(slip)
        self.assertIn("Cash", text)
        self.assertIn("M-Pesa", text)
        self.assertNotIn("Cash + M-Pesa", text)

    def test_credit_is_not_collected(self):
        slip = explain_sale_payments({
            "total": 2000,
            "amount_paid": 1000,
            "change_amount": 0,
            "payment_tenders": [
                {"method": "Cash", "amount": 300, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 500, "status": "confirmed"},
                {"method": "Card", "amount": 200, "status": "confirmed"},
                {"method": "Credit", "amount": 1000, "status": "outstanding"},
            ],
        })
        self.assertEqual(slip["amount_collected"], 1000)
        self.assertEqual(slip["credit"], 1000)
        self.assertEqual(slip["outstanding"], 1000)
        self.assertEqual(slip["amount_tendered"], 1000)
        self.assertTrue(slip["consistent"])

    def test_over_collection_without_change_is_flagged(self):
        slip = explain_sale_payments({
            "total": 55,
            "amount_paid": 75,
            "change_amount": 0,
            "payment_tenders": [
                {"method": "Cash", "amount": 40, "status": "confirmed"},
                {"method": "M-Pesa", "amount": 35, "status": "confirmed"},
            ],
        })
        self.assertFalse(slip["consistent"])
        self.assertIn("more than the sale total", slip["warning"])

    def test_plain_cash_sale(self):
        slip = explain_sale_payments({
            "total": 100,
            "amount_paid": 100,
            "change_amount": 0,
            "payment_method": "Cash",
            "payment_tenders": [{"method": "Cash", "amount": 100, "status": "confirmed"}],
        })
        self.assertEqual(slip["lines"][0]["kind"], "allocated")
        self.assertEqual(slip["amount_collected"], 100)
        self.assertEqual(slip["outstanding"], 0)
        self.assertTrue(slip["consistent"])


if __name__ == "__main__":
    unittest.main()
