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
        self.assertEqual(qty_step_for_unit(""), 1)
        self.assertEqual(qty_step_for_unit(None), 1)
        self.assertEqual(qty_step_for_unit("kg"), 0.25)
        self.assertEqual(round(1 + qty_step_for_unit("pcs"), 2), 2)
        self.assertEqual(round(1 + qty_step_for_unit("kg"), 2), 1.25)


if __name__ == "__main__":
    unittest.main()
