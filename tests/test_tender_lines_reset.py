"""Clearing split-tender lines must return. The last-row replacement used to
loop forever inside TenderLines.reset and freeze the till.
"""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from desktop.pos.tender_lines import TenderLines


class TenderLinesResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_reset_returns_one_mpesa_line(self):
        board = TenderLines()
        board.add_line('Cash', 40)
        board.add_line('Card', 60)
        board.reset()
        self.assertEqual(len(board._rows), 1)
        self.assertEqual(board._rows[0]['method'].currentText(), 'M-Pesa')
        self.assertEqual(board._rows[0]['amount'].value(), 0)

    def test_removing_the_last_line_keeps_one_blank_row(self):
        board = TenderLines()
        self.assertEqual(len(board._rows), 1)
        board._remove(0)
        self.assertEqual(len(board._rows), 1)


if __name__ == '__main__':
    unittest.main()
