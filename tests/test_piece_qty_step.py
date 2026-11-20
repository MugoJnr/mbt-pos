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


if __name__ == "__main__":
    unittest.main()
