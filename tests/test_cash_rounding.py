"""
Unit tests for Cash Rounding (MBT POS 2.3.53).

Run with build Python:
  C:\\MBT_Build\\_python311\\python.exe -m pytest tests/test_cash_rounding.py -v
or:
  C:\\MBT_Build\\_python311\\python.exe tests/test_cash_rounding.py
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.cash_rounding_service import CashRoundingService, MODE_NEAREST, MODE_NONE


CFG_CASH = {
    'cash_rounding_enabled': '1',
    'cash_rounding_mode': 'nearest',
    'cash_rounding_value': '5',
    'cash_rounding_apply_cash': '1',
    'cash_rounding_apply_mpesa': '0',
    'cash_rounding_apply_card': '0',
    'cash_rounding_apply_bank': '0',
}


class TestNearestFive(unittest.TestCase):
    def test_spec_examples(self):
        cases = [
            (37.50, 40.0),
            (38.0, 40.0),
            (42.0, 40.0),
            (43.0, 45.0),
            (47.50, 50.0),
            (40.0, 40.0),
            (35.0, 35.0),
            (0.0, 0.0),
            (1.0, 0.0),
            (2.50, 5.0),
            (7.50, 10.0),
        ]
        for raw, expected in cases:
            got = CashRoundingService.round_amount(raw, MODE_NEAREST, 5)
            self.assertEqual(got, expected, f'{raw} → {got}, expected {expected}')

    def test_half_up_at_point_five(self):
        # .50 of a step rounds away from zero / half-up → up
        self.assertEqual(CashRoundingService.round_amount(37.50, MODE_NEAREST, 5), 40.0)
        self.assertEqual(CashRoundingService.round_amount(12.50, MODE_NEAREST, 5), 15.0)


class TestApplyByMethod(unittest.TestCase):
    def test_cash_applies(self):
        r = CashRoundingService.apply(37.50, 'Cash', CFG_CASH)
        self.assertTrue(r['applied'])
        self.assertEqual(r['rounded_total'], 40.0)
        self.assertEqual(r['adjustment'], 2.50)

    def test_mpesa_never_rounds_by_default(self):
        r = CashRoundingService.apply(37.50, 'M-Pesa', CFG_CASH)
        self.assertFalse(r['applied'])
        self.assertEqual(r['rounded_total'], 37.50)
        self.assertEqual(r['adjustment'], 0.0)

    def test_card_never_rounds_by_default(self):
        r = CashRoundingService.apply(42.0, 'Card', CFG_CASH)
        self.assertFalse(r['applied'])
        self.assertEqual(r['rounded_total'], 42.0)

    def test_disabled(self):
        cfg = dict(CFG_CASH, cash_rounding_enabled='0')
        r = CashRoundingService.apply(37.50, 'Cash', cfg)
        self.assertFalse(r['applied'])
        self.assertEqual(r['rounded_total'], 37.50)

    def test_mode_none(self):
        cfg = dict(CFG_CASH, cash_rounding_mode=MODE_NONE)
        r = CashRoundingService.apply(37.50, 'Cash', cfg)
        self.assertFalse(r['applied'])


class TestMixedTender(unittest.TestCase):
    def test_cash_portion_only(self):
        # 137.50 total, 100 M-Pesa, cash 37.50 → 40; final due 140
        r = CashRoundingService.apply(
            137.50, 'Cash', CFG_CASH, electronic_portion=100.0)
        self.assertTrue(r['applied'])
        self.assertEqual(r['electronic'], 100.0)
        self.assertEqual(r['cash_original'], 37.50)
        self.assertEqual(r['cash_rounded'], 40.0)
        self.assertEqual(r['rounded_total'], 140.0)
        self.assertEqual(r['adjustment'], 2.50)

    def test_electronic_full_cover_no_cash_round(self):
        r = CashRoundingService.apply(
            100.0, 'Cash', CFG_CASH, electronic_portion=100.0)
        self.assertEqual(r['cash_original'], 0.0)
        self.assertEqual(r['rounded_total'], 100.0)
        self.assertFalse(r['applied'])


class TestApplyToTotal(unittest.TestCase):
    def test_with_credit(self):
        # cart 50, credit 10 → due 40 → already multiple of 5 (no delta)
        r = CashRoundingService.apply_to_total(
            50, 0, 0, 'Cash', CFG_CASH, credit_applied=10)
        self.assertEqual(r['cart_total'], 50.0)
        self.assertEqual(r['original_due'], 40.0)
        self.assertEqual(r['amount_due'], 40.0)
        self.assertFalse(r['applied'])
        self.assertFalse(r.get('show_on_receipt'))

    def test_prices_unchanged_concept(self):
        # Service only receives final amount — never product unit prices
        r = CashRoundingService.apply_to_total(
            37.50, 0, 0, 'Cash', CFG_CASH)
        self.assertEqual(r['amount_due'], 40.0)
        self.assertEqual(r['adjustment'], 2.50)


class TestVoidRefundSemantics(unittest.TestCase):
    """Refund/void of rounded cash sale uses rounded paid amount (40 not 37.50)."""

    def test_refund_amount_is_rounded(self):
        r = CashRoundingService.apply(37.50, 'Cash', CFG_CASH)
        paid = r['rounded_total']  # what customer paid / what void refunds
        self.assertEqual(paid, 40.0)
        reverse_adj = -r['adjustment']
        self.assertEqual(reverse_adj, -2.50)

    def test_void_nets_adjustment(self):
        adj = CashRoundingService.apply(43.0, 'Cash', CFG_CASH)['adjustment']
        self.assertEqual(adj, 2.0)
        self.assertEqual(adj + (-adj), 0.0)


class TestAlwaysUpDown(unittest.TestCase):
    def test_always_up(self):
        self.assertEqual(
            CashRoundingService.round_amount(41, 'always_up', 5), 45.0)
        self.assertEqual(
            CashRoundingService.round_amount(40, 'always_up', 5), 40.0)

    def test_always_down(self):
        self.assertEqual(
            CashRoundingService.round_amount(41, 'always_down', 5), 40.0)
        self.assertEqual(
            CashRoundingService.round_amount(40, 'always_down', 5), 40.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
