"""SearchableSelect drives the Adjust Stock product picker.

Rebuilding the combobox model while its popup view is visible is a native
crash on Windows, and clear() silently wipes the query an editable line edit
is still holding.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication  # noqa: E402

from desktop.utils.select_controls import SearchableSelect  # noqa: E402


PRODUCTS = [
    ('Sugar 1kg  (stock: 12)', 1),
    ('Sugar 2kg  (stock: 4)', 2),
    ('Salt 500g  (stock: 30)', 3),
    ('Soap Bar  (stock: 7)', 4),
    ('Rice 5kg  (stock: 2)', 5),
]


class SearchableSelectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _select(self):
        widget = SearchableSelect(placeholder='Search product…')
        widget.set_items(PRODUCTS)
        return widget

    def test_typed_query_survives_filtering(self):
        widget = self._select()
        widget.show()
        self.app.processEvents()
        line = widget.lineEdit()
        self.assertIsNotNone(line)

        line.setText('sugar')
        widget._apply_filter()

        self.assertEqual(line.text(), 'sugar')
        labels = [widget.itemText(i) for i in range(widget.count())]
        self.assertEqual(len(labels), 2)
        self.assertTrue(all('Sugar' in label for label in labels))
        widget.close()

    def test_filter_does_not_force_a_filtered_out_selection(self):
        widget = self._select()
        widget.show()
        self.app.processEvents()
        widget.set_value(5)  # Rice
        self.assertEqual(widget.current_value(), 5)

        widget.lineEdit().setText('sugar')
        widget._apply_filter()

        self.assertEqual(widget.lineEdit().text(), 'sugar')
        self.assertIsNone(widget.current_value())
        widget.close()

    def test_model_is_not_rebuilt_behind_a_visible_popup(self):
        widget = self._select()
        widget.show()
        self.app.processEvents()
        widget.showPopup()
        self.app.processEvents()

        widget.lineEdit().setText('sa')
        widget._apply_filter()
        self.app.processEvents()

        labels = [widget.itemText(i) for i in range(widget.count())]
        self.assertEqual(labels, ['Salt 500g  (stock: 30)'])
        widget.close()

    def test_repeated_keystrokes_never_lose_the_query(self):
        widget = self._select()
        widget.show()
        self.app.processEvents()
        line = widget.lineEdit()
        for query in ('s', 'su', 'sug', 'suga', 'sugar', 'sugar '):
            line.setText(query)
            widget._apply_filter()
            self.app.processEvents()
            self.assertEqual(line.text(), query)
        widget.close()

    def test_clearing_the_query_restores_full_list_and_selection(self):
        widget = self._select()
        widget.show()
        self.app.processEvents()
        widget.set_value(3)
        line = widget.lineEdit()

        line.setText('sugar')
        widget._apply_filter()
        line.setText('')
        widget._apply_filter()

        labels = [widget.itemText(i) for i in range(widget.count())]
        self.assertEqual(len(labels), len(PRODUCTS))
        self.assertEqual(widget.current_value(), 3)
        widget.close()

    def test_no_matches_reports_empty_selection(self):
        widget = self._select()
        widget.show()
        self.app.processEvents()
        widget.lineEdit().setText('zzzz')
        widget._apply_filter()

        self.assertEqual(widget.count(), 1)
        self.assertEqual(widget.itemText(0), 'No matches')
        self.assertIsNone(widget.current_value())
        widget.close()


if __name__ == '__main__':
    unittest.main()
