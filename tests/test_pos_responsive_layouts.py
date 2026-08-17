"""Real-widget regression checks for POS layout accessibility at small sizes."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PosResponsiveLayoutsTests(unittest.TestCase):
    """Critical checkout controls must remain available in every layout."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "pos-responsive.db")
        self.patches = [
            patch("mbt_paths.get_db_path", return_value=self.db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self.db_path),
        ]
        for item in self.patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._username = "qa_cashier"
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name) VALUES (?,?,?,?)",
            ("qa_cashier", "x:y", "superadmin", "QA Cashier"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ("Responsive QA Product", "RESP-QA", 125.0, 50.0, 100.0, 2.0),
        )
        db.commit()
        db.close()

        from desktop.tabs.sales_tab import SalesTab
        self.tab = SalesTab(
            self.api,
            {"id": 1, "username": "qa_cashier", "role": "superadmin"},
            self.db_path,
            lambda: {},
        )
        self.tab.refresh(force=True, defer_grid=False)
        self.tab.cart = [{
            "product_id": 1,
            "product_name": "Responsive QA Product",
            "sku": "RESP-QA",
            "category": "General",
            "quantity": 0.25,
            "unit_price": 125.0,
            "discount": 0.0,
            "total": 31.25,
        }]
        self.tab._recalc()
        self.tab._search.setText("Responsive")

    def tearDown(self):
        self.tab.close()
        self.tab.deleteLater()
        self.app.processEvents()
        for item in self.patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self.temp_dir.cleanup()

    def _assert_widget_on_tab(self, widget, label: str):
        from PyQt5.QtCore import QPoint

        self.assertTrue(widget.isVisible(), f"{label} is hidden")
        top_left = widget.mapTo(self.tab, QPoint(0, 0))
        rect = widget.rect().translated(top_left)
        self.assertTrue(
            self.tab.rect().intersects(rect),
            f"{label} is outside the POS viewport: {rect}",
        )

    def _assert_toolbar_controls_do_not_overlap(self):
        """A control can be technically visible yet unusable under a sibling."""
        controls = (
            (self.tab._search, "Product search"),
            (self.tab._cat, "Category"),
            (self.tab._layout_combo, "Layout"),
            (self.tab._refresh_btn, "Refresh"),
            (self.tab._focus_btn, "Focus"),
        )
        for widget, label in controls:
            self._assert_widget_on_tab(widget, label)
        for index, (first, first_label) in enumerate(controls):
            first_rect = first.geometry()
            for second, second_label in controls[index + 1:]:
                self.assertFalse(
                    first_rect.intersects(second.geometry()),
                    f"{first_label} overlaps {second_label}",
                )

    def _assert_summary_contents_fit(self):
        from PyQt5.QtCore import QPoint

        summary = self.tab._summary
        for widget, label in ((summary._sub_lbl, "Subtotal"),
                              (summary._tot_lbl, "Total due"),
                              (self.tab._disc, "Discount")):
            point = widget.mapTo(summary, QPoint(0, 0))
            rect = widget.rect().translated(point)
            self.assertTrue(
                summary.rect().contains(rect),
                f"{label} is clipped outside Order Summary: {rect}",
            )

    def test_critical_cashier_controls_survive_layout_and_size_changes(self):
        from desktop.pos.layout_ids import (
            LAYOUT_CHECKOUT_PRO,
            LAYOUT_SIMPLE_COUNTER,
            LAYOUT_RETAIL_CLASSIC,
        )

        # Includes 16:9, 4:3, square-ish, and the smallest supported desktop size.
        sizes = ((1920, 1080), (1600, 900), (1440, 900), (1366, 768),
                 (1280, 720), (1280, 1024), (1024, 768))
        for layout in (LAYOUT_SIMPLE_COUNTER, LAYOUT_RETAIL_CLASSIC,
                       LAYOUT_CHECKOUT_PRO):
            self.tab.set_checkout_layout(layout)
            for width, height in sizes:
                with self.subTest(layout=layout, size=f"{width}x{height}"):
                    self.tab.resize(width, height)
                    self.tab.show()
                    self.app.processEvents()

                    self._assert_widget_on_tab(self.tab._search, "Product search")
                    self._assert_widget_on_tab(self.tab._cart_list, "Cart")
                    self._assert_widget_on_tab(self.tab._summary, "Order total")
                    self._assert_widget_on_tab(self.tab._charge_btn, "Complete Sale")
                    self._assert_summary_contents_fit()
                    if layout != LAYOUT_CHECKOUT_PRO:
                        self._assert_toolbar_controls_do_not_overlap()
                    else:
                        # Pro deliberately uses its category-chip equivalent
                        # instead of the shared category combo.
                        self._assert_widget_on_tab(self.tab._layout_combo, "Layout")
                        self._assert_widget_on_tab(self.tab._cat_chips, "Category chips")
                    self.assertEqual(len(self.tab.cart), 1)
                    self.assertEqual(self.tab._search.text(), "Responsive")


if __name__ == "__main__":
    unittest.main()
