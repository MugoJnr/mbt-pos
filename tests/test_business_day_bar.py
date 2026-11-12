"""A past business day must update the caption without locking the till."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QApplication, QDateEdit, QLabel, QPushButton, QSplitter

from desktop.pos.panel_factory import BusinessDayBar


class BusinessDayBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_backdated_caption_does_not_recurse(self):
        bar = BusinessDayBar()
        edit = QDateEdit()
        edit.setDate(QDate(2026, 11, 11))
        buttons = [
            (QPushButton('Today'), 'Today', 'Today'),
            (QPushButton('View'), 'View', 'View day'),
            (QPushButton('Copy'), 'Copy', 'Copy sale…'),
        ]
        warn = QLabel('')
        bar.setup(None, edit, buttons, warn)
        bar.resize(640, 80)
        bar.show()
        edit.setDate(QDate(2026, 11, 10))
        self._app.processEvents()
        bar._layout_passes = 0
        for width in (480, 900, 520, 880, 500, 860, 640, 0, 640):
            bar.resize(width, 80)
            bar._apply_layout(force=True, width=width)
        self._app.processEvents()
        self.assertIn('BACKDATED', bar._picker.text())
        self.assertFalse(bar._applying)
        self.assertLess(int(getattr(bar, '_layout_passes', 0) or 0), 20)
        self.assertEqual(buttons[0][0].text(), 'Back to today')

    def test_splitter_date_change_returns(self):
        splitter = QSplitter()
        bar = BusinessDayBar()
        edit = QDateEdit()
        edit.setDate(QDate(2026, 11, 11))
        buttons = [
            (QPushButton('Today'), 'Today', 'Today'),
            (QPushButton('View'), 'View', 'View day'),
            (QPushButton('Copy'), 'Copy', 'Copy sale…'),
        ]
        bar.setup(None, edit, buttons, QLabel(''))
        splitter.addWidget(bar)
        splitter.addWidget(QLabel('cart'))
        splitter.resize(900, 160)
        splitter.show()
        edit.setDate(QDate(2026, 11, 10))
        for width in (480, 1100, 520, 900, 640):
            splitter.resize(width, 180)
            self._app.processEvents()
        self.assertIn('BACKDATED', bar._picker.text())
        self.assertFalse(bar._applying)
        self.assertFalse(getattr(bar, '_layout_queued', False))

    def test_long_warning_does_not_widen_the_bar(self):
        bar = BusinessDayBar()
        edit = QDateEdit()
        edit.setDate(QDate(2026, 11, 11))
        buttons = [
            (QPushButton('Today'), 'Today', 'Today'),
            (QPushButton('View'), 'View', 'View day'),
            (QPushButton('Copy'), 'Copy', 'Copy sale…'),
        ]
        warn = QLabel('Request only — ' + ('word ' * 80))
        bar.setup(None, edit, buttons, warn)
        bar.resize(480, 120)
        bar.show()
        edit.setDate(QDate(2026, 11, 10))
        for _ in range(8):
            self._app.processEvents()
        self.assertIn('BACKDATED', bar._picker.text())
        self.assertFalse(bar._applying)
        self.assertLessEqual(bar.minimumSizeHint().width(), 480)
        self.assertLessEqual(bar._note.minimumSizeHint().width(), 480)
        self.assertFalse(warn.isVisible())


if __name__ == '__main__':
    unittest.main()
