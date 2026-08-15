"""Cart cashier viewport must fit 5 table rows, not a one-line sliver."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CartViewportMath(unittest.TestCase):
    def test_five_rows_taller_than_one_line(self):
        from desktop.utils.pos_components import (
            CART_CASHIER_ROWS, CART_ROW_H, cart_viewport_px,
        )
        from desktop.pos.layouts.splitters import CART_LIST_HARD_MIN, CART_MIN_HEIGHTS
        from desktop.pos.layout_ids import (
            LAYOUT_CHECKOUT_PRO, LAYOUT_PRODUCT_EXPLORER, LAYOUT_RETAIL_CLASSIC,
        )

        self.assertEqual(CART_CASHIER_ROWS, 5)
        self.assertGreaterEqual(CART_ROW_H, 52)
        self.assertLessEqual(CART_ROW_H, 64)
        five = cart_viewport_px(5)
        self.assertGreaterEqual(five, 5 * CART_ROW_H)
        self.assertGreaterEqual(CART_LIST_HARD_MIN, five)
        for lid in (LAYOUT_CHECKOUT_PRO, LAYOUT_PRODUCT_EXPLORER, LAYOUT_RETAIL_CLASSIC):
            self.assertGreaterEqual(
                CART_MIN_HEIGHTS[lid][0], CART_LIST_HARD_MIN,
                f'{lid} cart floor too short')


if __name__ == '__main__':
    unittest.main()
