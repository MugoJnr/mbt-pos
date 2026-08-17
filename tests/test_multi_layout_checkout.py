"""Unit tests for multi-layout checkout (shared panels, no duplicated logic)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class LayoutIdsTests(unittest.TestCase):
    def test_normalize(self):
        from desktop.pos.layout_ids import (
            normalize_layout_id, LAYOUT_CHECKOUT_PRO, LAYOUT_RETAIL_CLASSIC,
            LAYOUT_SIMPLE_COUNTER, DEFAULT_CHECKOUT_LAYOUT,
        )
        self.assertEqual(normalize_layout_id('checkout_pro'), LAYOUT_CHECKOUT_PRO)
        self.assertEqual(normalize_layout_id('Checkout Pro'), LAYOUT_CHECKOUT_PRO)
        self.assertEqual(normalize_layout_id('retail'), LAYOUT_RETAIL_CLASSIC)
        self.assertEqual(normalize_layout_id(''), DEFAULT_CHECKOUT_LAYOUT)
        self.assertEqual(normalize_layout_id('nope'), DEFAULT_CHECKOUT_LAYOUT)
        self.assertEqual(normalize_layout_id('product_explorer'), LAYOUT_SIMPLE_COUNTER)
        self.assertEqual(normalize_layout_id('simple counter'), LAYOUT_SIMPLE_COUNTER)


class MultiLayoutSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'mbt_pos.db'
        if not db.exists():
            raise unittest.SkipTest(f'no local db at {db}')
        from desktop.utils.api_client import APIClient
        from desktop.tabs.sales_tab import SalesTab
        cls.api = APIClient(str(db))
        cls.tab = SalesTab(
            cls.api,
            {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'T'},
            str(db),
            lambda: {},
        )
        cls.panel_ids = (
            id(cls.tab._product_panel),
            id(cls.tab._sale_panel),
            id(cls.tab._actions_panel),
            id(cls.tab._cart_list),
            id(cls.tab._pay_seg),
            id(cls.tab._charge_btn),
        )

    def test_switch_reuses_same_widgets(self):
        from desktop.pos.layout_ids import (
            LAYOUT_CHECKOUT_PRO, LAYOUT_RETAIL_CLASSIC, LAYOUT_SIMPLE_COUNTER,
        )
        tab = self.tab
        tab.cart = [{
            'product_id': 1, 'product_name': 'A', 'sku': 'A', 'category': 'General',
            'quantity': 1, 'unit_price': 50, 'discount': 0, 'total': 50,
        }]
        tab._cart_select_idx = 0
        tab._refresh_cart()
        for lid in (LAYOUT_RETAIL_CLASSIC, LAYOUT_CHECKOUT_PRO, LAYOUT_SIMPLE_COUNTER):
            tab.set_checkout_layout(lid)
            self.assertEqual(tab._checkout_layout, lid)
            self.assertEqual(len(tab.cart), 1)
            self.assertEqual(
                (
                    id(tab._product_panel),
                    id(tab._sale_panel),
                    id(tab._actions_panel),
                    id(tab._cart_list),
                    id(tab._pay_seg),
                    id(tab._charge_btn),
                ),
                self.panel_ids,
            )

    def test_checkout_pro_has_three_columns(self):
        from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO
        from PyQt5.QtWidgets import QSplitter
        tab = self.tab
        tab.set_checkout_layout(LAYOUT_CHECKOUT_PRO)
        lay = tab._shell.layout()
        self.assertEqual(lay.count(), 1)
        split = lay.itemAt(0).widget()
        self.assertIsInstance(split, QSplitter)
        self.assertEqual(split.count(), 3)
        self.assertIs(split.widget(0), tab._product_panel)
        self.assertIs(split.widget(1), tab._sale_panel)
        self.assertIs(split.widget(2), tab._actions_panel)

    def test_product_columns_pro_fits_width(self):
        from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO
        tab = self.tab
        tab.set_checkout_layout(LAYOUT_CHECKOUT_PRO)
        grid = tab._prod_grid
        self.assertGreaterEqual(grid.columns_for_width(700), 2)
        self.assertEqual(grid.columns_for_width(280), 1)


if __name__ == '__main__':
    unittest.main()
