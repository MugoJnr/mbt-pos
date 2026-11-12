"""POS catalog and checkout layout — no display, no shop database."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Before any mbt import, keep this process off the live shop database.
_ISOLATION = tempfile.mkdtemp(prefix='mbt-pos-layout-')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['MBT_TEST_INSTANCE'] = '1'
os.environ['MBT_DATA_ROOT'] = _ISOLATION
os.environ['APPDATA'] = _ISOLATION
os.environ['LOCALAPPDATA'] = _ISOLATION
os.environ['PROGRAMDATA'] = _ISOLATION

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QGridLayout, QLabel, QVBoxLayout, QWidget,
)

from desktop.pos.checkout_pro_chrome import (
    SaleTypeGroup, reflow_secondary_actions, secondary_action_columns,
)
from desktop.pos.layouts.splitters import HARD_MIN_WIDTHS
from desktop.pos.layout_ids import LAYOUT_PRODUCT_EXPLORER
from desktop.pos.panel_factory import BusinessDayBar, SearchToolbar
from desktop.utils.nav_icons import icon_refresh
from desktop.utils.pos_components import CustomerCard, PaymentSegment, ProductGrid
from desktop.utils.theme import ThemeManager
from desktop.utils.widgets import IconBtn, PrimaryBtn, SecondaryBtn


def _app():
    app = QApplication.instance() or QApplication([])
    ThemeManager.apply(False, app)
    return app


def _activate(widget, width, height):
    widget.resize(width, height)
    lay = widget.layout()
    if lay is not None:
        lay.activate()
    widget.resize(width, height)
    if lay is not None:
        lay.activate()


def _products(n=4):
    return [
        {
            'id': i, 'name': f'Item {i} Long Product Name', 'sku': f'SKU-{i}',
            'price': 120 + i, 'stock': 4, 'unit': 'pcs', 'category': 'General',
        }
        for i in range(n)
    ]


class CatalogLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _grid(self, width):
        grid = ProductGrid()
        _activate(grid, width, 480)
        inner_m = grid._grid.contentsMargins()
        inner = width - inner_m.left() - inner_m.right()
        cols = grid.columns_for_width(inner)
        grid.populate(_products(), columns=cols)
        _activate(grid, width, 480)
        grid._grid.activate()
        cards = []
        for i in range(grid._grid.count()):
            w = grid._grid.itemAt(i).widget()
            if w is not None:
                cards.append(w)
        return grid, cols, cards, inner

    def test_narrow_catalog_stretches_one_card(self):
        grid, cols, cards, inner = self._grid(500)
        self.assertEqual(cols, 1)
        self.assertGreaterEqual(len(cards), 1)
        card = cards[0]
        self.assertGreaterEqual(card.width(), inner - 8)
        self.assertGreater(card.width(), 320)

    def test_wide_catalog_fits_two_cards(self):
        grid, cols, cards, inner = self._grid(580)
        self.assertGreaterEqual(cols, 2)
        self.assertGreaterEqual(len(cards), 2)
        m = grid._grid.contentsMargins()
        right_limit = grid.width() - m.right()
        self.assertLessEqual(cards[1].geometry().right(), right_limit + 1)
        self.assertGreaterEqual(cards[1].width(), 200)
        self.assertLess(cards[0].geometry().right(), cards[1].geometry().left())


class BusinessDayBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _bar(self, width):
        from desktop.utils.shop_time import shop_today
        shell = QWidget()
        lay = QVBoxLayout(shell)
        bar = BusinessDayBar(shell)
        de = QDateEdit()
        today = shop_today()
        de.setDate(QDate(today.year, today.month, today.day))
        view = SecondaryBtn('View day', 32)
        copy = SecondaryBtn('Copy sale…', 32)
        today_btn = SecondaryBtn('Today', 32)
        warn = QLabel('')
        bar.setup(None, de, (
            (today_btn, 'Today', 'Today'),
            (view, 'View', 'View day'),
            (copy, 'Copy', 'Copy sale…'),
        ), warn)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(bar)
        shell._keep = (view, copy, today_btn, de, warn)
        shell.resize(width, 160)
        bar.resize(width, 80)
        bar._apply_layout(force=True, width=width)
        bar.layout().activate()
        return shell, bar, view, copy

    def test_medium_bar_keeps_actions_on_one_row(self):
        _shell, bar, view, copy = self._bar(500)
        picker = bar._picker
        self.assertLess(abs(view.geometry().y() - picker.geometry().y()), 12)
        self.assertLess(abs(copy.geometry().y() - picker.geometry().y()), 12)
        self.assertLessEqual(copy.geometry().right(), 500)
        self.assertLess(picker.width(), 220)
        self.assertFalse(bar._mode[1])

    def test_narrow_bar_stacks_without_a_huge_date(self):
        _shell, bar, view, copy = self._bar(220)
        picker = bar._picker
        self.assertTrue(bar._mode[1])
        self.assertLess(picker.width(), 180)
        self.assertLessEqual(view.geometry().right(), 220)
        self.assertLessEqual(copy.geometry().right(), 220)


class CheckoutRailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_payment_and_actions_fit_right_rail_minimum(self):
        rail = HARD_MIN_WIDTHS[LAYOUT_PRODUCT_EXPLORER][1]
        self.assertGreaterEqual(rail, 200)

        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(8, 4, 8, 4)
        cust = CustomerCard()
        new_btn = SecondaryBtn('+ New Customer', 36)
        new_btn.setObjectName('posNewCustBtn')
        cust.set_pro_row(True, new_btn)
        pay = PaymentSegment()
        pay.set_compact(True)
        sale = SaleTypeGroup()
        sale.set_grid(2)
        buttons = []
        tab = type('Tab', (), {})()
        for name, label in (
            ('_clr_btn', 'Clear'), ('_hold_btn', 'Hold'), ('_resume_btn', 'Resume'),
            ('_prv_btn', 'Preview'), ('_reprint_btn', 'Reprint'),
            ('_void_btn', 'Void'), ('_returns_help_btn', 'Returns'),
        ):
            b = SecondaryBtn(label, 36)
            setattr(tab, name, b)
            buttons.append(b)
        grid = QGridLayout()
        tab._checkout_sec_row = grid
        tab._sec_action_cols = None
        charge = PrimaryBtn('$  Complete Sale', 56)
        charge.setMinimumWidth(0)
        lay.addWidget(cust)
        lay.addWidget(pay)
        lay.addWidget(sale)
        lay.addLayout(grid)
        lay.addWidget(charge)

        for width in (rail, 366):
            _activate(host, width, 640)
            cust.fit_width(width - 16)
            pay.fit_width(width - 16)
            sale.fit_width(width - 16)
            reflow_secondary_actions(tab, width - 16)
            _activate(host, width, 640)
            pay.layout().activate()
            self.assertLessEqual(cust.minimumSizeHint().width(), width)
            self.assertLessEqual(pay.minimumSizeHint().width(), width)
            self.assertLessEqual(sale.minimumSizeHint().width(), width)
            self.assertLessEqual(secondary_action_columns(buttons, width - 16) * 80, width * 4)
            split = pay._btns['Mixed']
            self.assertLessEqual(split.geometry().right(), width)
            self.assertGreater(split.width(), 24)
            preview = tab._prv_btn
            self.assertLessEqual(preview.geometry().right(), width)
            self.assertGreaterEqual(preview.width(), preview.fontMetrics().horizontalAdvance('Preview'))
            self.assertLessEqual(new_btn.geometry().right(), width)
            self.assertGreater(new_btn.width(), 40)
            self.assertLessEqual(charge.geometry().right(), width)
            self.assertGreater(charge.height(), 40)
            self.assertIn('Complete Sale', charge.text())


class SearchToolbarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_narrow_toolbar_keeps_controls_inside(self):
        from PyQt5.QtWidgets import QLineEdit
        bar = SearchToolbar()
        search = QLineEdit()
        search.setPlaceholderText('Search')
        category = QComboBox()
        category.addItem('All Categories')
        category.addItem('A very long category name')
        layout = QComboBox()
        layout.addItem('Product Explorer')
        layout.addItem('Retail Classic')
        refresh = IconBtn('', 40, 40)
        focus = SecondaryBtn('Focus', 40)
        bar.setup(search, category, layout, refresh, focus)
        bar._apply_layout(force=True, width=280)
        bar.resize(280, 180)
        bar.layout().activate()
        for widget in (refresh, focus, category, layout, search):
            self.assertGreaterEqual(widget.geometry().x(), 0)
            self.assertLessEqual(widget.geometry().right(), 280)
            self.assertGreater(widget.width(), 20)


class RefreshIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_refresh_icon_is_not_only_an_arc(self):
        icon = icon_refresh(18)
        image = icon.pixmap(18, 18).toImage()
        # The arrow head sits in the top-right. An arc-only "C" leaves that
        # corner empty; a readable refresh mark paints pixels there.
        opaque = 0
        for y in range(0, 8):
            for x in range(10, 18):
                if image.pixelColor(x, y).alpha() > 40:
                    opaque += 1
        self.assertGreaterEqual(opaque, 8)


if __name__ == '__main__':
    unittest.main()
