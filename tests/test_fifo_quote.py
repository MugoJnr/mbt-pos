"""A consumption preview must price the oldest batches without writing them."""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FifoQuoteTests(unittest.TestCase):
    def test_twelve_point_two_five_uses_oldest_batches_and_writes_nothing(self):
        from desktop.utils.stock_layers import add_layer, quote_available_cost
        db = sqlite3.connect(":memory:")
        first = add_layer(db, 4, 10, 100, "purchase", "DEL-100")
        second = add_layer(db, 4, 10, 120, "purchase", "DEL-120")
        quote = quote_available_cost(db, 4, 12.25)
        self.assertAlmostEqual(quote["cogs"], 1270.0, places=2)
        self.assertAlmostEqual(quote["unit_cost"], 103.6735, places=4)
        self.assertAlmostEqual(quote["covered"], 12.25, places=2)
        self.assertAlmostEqual(quote["uncosted"], 0.0, places=4)
        rows = db.execute(
            "SELECT id, remaining_qty FROM cost_layers ORDER BY id"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [first["id"], second["id"]])
        self.assertEqual([row[1] for row in rows], [10, 10])
        db.close()
