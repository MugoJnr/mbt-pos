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
        self.assertGreaterEqual(CART_LIST_HARD_MIN, cart_viewport_px(3))
        self.assertLess(CART_LIST_HARD_MIN, five)
        for lid in (LAYOUT_CHECKOUT_PRO, LAYOUT_PRODUCT_EXPLORER, LAYOUT_RETAIL_CLASSIC):
            self.assertGreaterEqual(
                CART_MIN_HEIGHTS[lid][0], five,
                f'{lid} normal cart floor must fit five rows')

    def test_product_toolbar_wraps_on_narrow_catalog(self):
        from PyQt5.QtWidgets import (
            QApplication, QComboBox, QLineEdit, QPushButton)
        from desktop.pos.panel_factory import SearchToolbar

        app = QApplication.instance() or QApplication([])
        toolbar = SearchToolbar()
        search = QLineEdit()
        category = QComboBox()
        layout = QComboBox()
        refresh = QPushButton('Refresh')
        focus = QPushButton('Focus')
        toolbar.setup(search, category, layout, refresh, focus)

        toolbar.resize(420, 100)
        toolbar._apply_layout(force=True, width=420)
        app.processEvents()
        self.assertEqual(toolbar._row2.count(), 2)
        self.assertGreater(category.maximumWidth(), 220)
        self.assertGreater(layout.maximumWidth(), 168)

        toolbar.resize(900, 80)
        toolbar._apply_layout(force=True, width=900)
        app.processEvents()
        self.assertEqual(toolbar._row2.count(), 0)
        self.assertEqual(category.minimumWidth(), 220)
        self.assertEqual(category.maximumWidth(), 220)
        self.assertEqual(layout.minimumWidth(), 168)
        self.assertEqual(layout.maximumWidth(), 168)
        toolbar.close()

    def test_pinned_totals_are_one_non_overlapping_row(self):
        from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLineEdit
        from desktop.utils.pos_components import SummaryCard

        app = QApplication.instance() or QApplication([])
        card = SummaryCard()
        discount_row = QHBoxLayout()
        discount = QLineEdit('0.00')
        card.disc_edit = discount
        card._disc_row = discount_row
        discount_row.addWidget(card.disc_label)
        discount_row.addStretch()
        discount_row.addWidget(discount)
        card._body.insertLayout(2, discount_row)

        card.set_pinned_strip(True)
        card.resize(400, card.sizeHint().height())
        card.show()
        app.processEvents()

        self.assertTrue(card._pinned_row_w.isVisible())
        self.assertFalse(card._sub_lbl._row_w.isVisible())
        self.assertFalse(card._sep.isVisible())
        self.assertLessEqual(card.sizeHint().height(), 68)
        widgets = [
            card._sub_lbl._row_cap, card._sub_lbl, card.disc_label,
            discount, card._total_hdr, card._tot_lbl,
        ]
        geometries = [widget.geometry() for widget in widgets]
        for left, right in zip(geometries, geometries[1:]):
            self.assertLessEqual(left.right(), right.left())
        card.close()


if __name__ == '__main__':
    unittest.main()
