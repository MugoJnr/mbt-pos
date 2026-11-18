"""Product cards must show the stock from the latest catalog load."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtWidgets import QApplication

from desktop.utils.pos_components import ProductGrid


class PosStockBadgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_repeat_populate_updates_the_stock_badge(self):
        grid = ProductGrid()
        grid.set_currency("KES")
        sugar = {
            "id": 1, "name": "Sugar", "sku": "QA-SUGAR",
            "price": 150, "stock": 16, "unit": "pcs", "category": "Shop",
        }
        oil = {
            "id": 2, "name": "Cooking oil", "sku": "QA-OIL",
            "price": 320, "stock": 8, "unit": "pcs", "category": "Shop",
        }
        grid.populate([oil, sugar], columns=2)
        grid.populate([{**oil, "stock": 8}, {**sugar, "stock": 15}], columns=2)
        badges = []
        for i in range(grid._grid.count()):
            card = grid._grid.itemAt(i).widget()
            badges.append(card._badge.text())
        self.assertIn("8 left", badges)
        self.assertIn("15 left", badges)
        self.assertNotIn("16 left", badges)
        names = []
        for i in range(grid._grid.count()):
            card = grid._grid.itemAt(i).widget()
            names.append(card._badge.accessibleName())
        self.assertIn("15 left", names)
        self.assertNotIn("16 left", names)


if __name__ == "__main__":
    unittest.main()
