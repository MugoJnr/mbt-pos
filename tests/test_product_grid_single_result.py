"""Regression: search "1 of 1" must keep the ProductCard in the viewport.

Checkout Pro sets per-row minimum heights. Clearing widgets without resetting
those mins left a tall empty grid after filtering 48→1, so the scroll offset
stayed at the bottom (footer hint visible) while the sole card sat off-screen.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ProductGridSingleResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_filter_48_to_1_keeps_card_in_viewport(self):
        from PyQt5.QtWidgets import QScrollArea
        from PyQt5.QtCore import Qt
        from desktop.utils.pos_components import ProductGrid, ProductCard

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.resize(420, 400)
        scroll.show()

        grid = ProductGrid()
        grid.set_pro_density(True)
        scroll.setWidget(grid)

        many = [
            {
                'id': i,
                'name': f'Product {i} Fertilizer Extra Long Name',
                'sku': f'SKU-{i:04d}',
                'price': 10 + i,
                'stock': 5,
                'unit': 'pcs',
                'category': 'A — Dewormers',
            }
            for i in range(48)
        ]
        grid.populate(many, columns=1, chunked=False)
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        self.app.processEvents()

        one = [{
            'id': 99,
            'name': 'Evaminor Plus 125ml',
            'sku': 'A-0022',
            'price': 450,
            'stock': 10,
            'unit': 'pcs',
            'category': 'A — Dewormers',
        }]
        grid.populate(one, columns=1, chunked=False)
        self.app.processEvents()
        for _ in range(5):
            self.app.processEvents()

        cards = grid.findChildren(ProductCard)
        self.assertEqual(len(cards), 1)
        self.assertEqual(grid._grid.count(), 1)
        self.assertIn('1', grid._hint.text())
        self.assertIn('1', grid._hint.text().split('of')[0])

        card = cards[0]
        self.assertGreater(card.width(), 0)
        self.assertGreater(card.height(), 0)
        self.assertTrue(card.isVisible())

        # Ghost row mins must be gone — content should fit the viewport.
        self.assertLessEqual(grid.height(), scroll.viewport().height() + 80)
        self.assertEqual(scroll.verticalScrollBar().value(), 0)

        top_left = card.mapTo(scroll.viewport(), card.rect().topLeft())
        self.assertGreaterEqual(top_left.y(), -2)
        self.assertLess(top_left.y(), scroll.viewport().height())
        self.assertEqual(card._display_name, 'Evaminor Plus 125ml')

    def test_sales_tab_empty_overlay_hidden_for_one_hit(self):
        from desktop.utils.pos_components import ProductGrid, ProductCard
        from PyQt5.QtWidgets import QLabel, QWidget, QVBoxLayout, QScrollArea
        from PyQt5.QtCore import Qt

        # Lightweight stand-in for SalesTab overlay logic
        class _Tab(QWidget):
            def __init__(self):
                super().__init__()
                self._product_panel = self
                lay = QVBoxLayout(self)
                self._prod_scroll = QScrollArea(self)
                self._prod_scroll.setWidgetResizable(True)
                self._prod_grid = ProductGrid()
                self._prod_grid.set_pro_density(True)
                self._prod_scroll.setWidget(self._prod_grid)
                lay.addWidget(self._prod_scroll)
                self._empty = QLabel(self)
                self._empty.setText('No products.')
                self._empty.hide()

            def _show_empty_overlay(self, visible: bool):
                from desktop.tabs.sales_tab import SalesTab
                SalesTab._show_empty_overlay(self, visible)

        tab = _Tab()
        tab.resize(480, 600)
        tab.show()
        self.app.processEvents()

        prod = {
            'id': 22,
            'name': 'Evaminor Plus 125ml',
            'sku': 'A-0022',
            'price': 450,
            'stock': 10,
            'unit': 'pcs',
            'category': 'A — Dewormers',
        }
        tab._prod_grid.populate([prod], columns=1, chunked=False)
        tab._show_empty_overlay(True)  # must refuse to cover results
        self.app.processEvents()

        self.assertFalse(tab._empty.isVisible())
        cards = tab._prod_grid.findChildren(ProductCard)
        self.assertEqual(len(cards), 1)
        self.assertGreater(cards[0].height(), 0)


if __name__ == '__main__':
    unittest.main()
