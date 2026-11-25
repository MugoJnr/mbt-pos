"""Piece goods increase by one. Weight and volume keep the shop wheel step."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class PieceQuantityTests(unittest.TestCase):
    def test_piece_steps_by_one_and_weight_keeps_the_wheel(self):
        from desktop.utils.pos_components import qty_step_for_unit
        self.assertEqual(qty_step_for_unit("pcs"), 1)
        self.assertEqual(qty_step_for_unit(""), 0.01)
        self.assertEqual(qty_step_for_unit(None), 0.01)
        self.assertEqual(qty_step_for_unit("kg"), 0.25)
        self.assertEqual(qty_step_for_unit("cm"), 0.25)
        self.assertEqual(qty_step_for_unit("metre"), 0.25)
        self.assertEqual(round(1 + qty_step_for_unit("pcs"), 2), 2)
        self.assertEqual(round(1 + qty_step_for_unit("kg"), 2), 1.25)
        self.assertEqual(qty_step_for_unit("pcs", decimal_qty=1), 0.25)

    def test_piece_fractions_are_refused_and_kilograms_stay_exact(self):
        from desktop.utils.quantities import QuantityError, parse_quantity
        for raw in ("0.25", "0.5", "0.75", "1.25", "2.50"):
            self.assertEqual(parse_quantity(raw, "kg"), float(raw))
        for raw in ("0.5", "1.25"):
            with self.assertRaises(QuantityError) as refused:
                parse_quantity(raw, "pcs")
            self.assertIn("whole", str(refused.exception).lower())
            self.assertNotEqual(str(refused.exception), "1")
        self.assertEqual(parse_quantity("2", "pcs"), 2.0)
        self.assertEqual(parse_quantity("2.0", "piece"), 2.0)
        for raw in ("0.25", "0.5", "0.75", "1.25", "1.5", "2.5", "10"):
            self.assertEqual(parse_quantity(raw, "pcs", decimal_qty=1), float(raw))
        with self.assertRaises(QuantityError):
            parse_quantity("0.5", "kg", decimal_qty=0)

    def test_scroll_interval_scales_a_mouse_notch_and_leaves_a_touchpad(self):
        from desktop.utils.wheel_scroll import set_wheel_scroll_interval, wheel_notch_pixels
        self.assertEqual(set_wheel_scroll_interval(5), 5)
        self.assertEqual(wheel_notch_pixels(120, 0, 5, 16), -80)
        self.assertEqual(wheel_notch_pixels(-240, 0, 2, 16), 64)
        self.assertIsNone(wheel_notch_pixels(120, 30, 5, 16))
        self.assertEqual(set_wheel_scroll_interval(0), 5)
        self.assertEqual(set_wheel_scroll_interval(3), 3)


if __name__ == "__main__":
    unittest.main()
