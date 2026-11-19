"""Other during a backdate opens a box the cashier can type into."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_ISOLATION = tempfile.mkdtemp(prefix="mbt-backdate-other-")
os.environ["MBT_DATA_ROOT"] = _ISOLATION
os.environ["APPDATA"] = os.path.join(_ISOLATION, "roaming")
os.environ["LOCALAPPDATA"] = os.path.join(_ISOLATION, "local")
os.environ["PROGRAMDATA"] = os.path.join(_ISOLATION, "programdata")
os.environ["MBT_TEST_INSTANCE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TillOtherReasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        from desktop.utils.option_lists import BACKDATE_REASONS
        from desktop.utils.select_controls import ReasonDialog
        return ReasonDialog(
            title="Backdating request",
            prompt="Why is this sale for an earlier day?",
            reasons=BACKDATE_REASONS,
        )

    def test_other_opens_a_box_and_keeps_the_typed_sentence(self):
        from PyQt5.QtWidgets import QDialog, QLineEdit, QPushButton
        dlg = self._dialog()
        dlg.show()
        other = next(btn for btn in dlg.findChildren(QPushButton) if btn.text() == "Other")
        box = dlg.findChild(QLineEdit, "mbtBackdateOther")
        self.assertTrue(box.isHidden())
        other.click()
        self.assertFalse(box.isHidden())
        self.assertTrue(box.isVisible())
        box.setText("the shop was closed")
        self.assertEqual(dlg.reason(), "Other: the shop was closed")
        dlg._accept()
        self.assertEqual(dlg.result(), QDialog.Accepted)

    def test_a_listed_reason_does_not_ask_for_a_written_one(self):
        from PyQt5.QtWidgets import QLineEdit, QPushButton
        dlg = self._dialog()
        dlg.show()
        listed = next(
            btn for btn in dlg.findChildren(QPushButton) if btn.text() == "Transaction entered late"
        )
        box = dlg.findChild(QLineEdit, "mbtBackdateOther")
        listed.click()
        self.assertTrue(box.isHidden())
        self.assertEqual(dlg.reason(), "Transaction entered late")

    def test_blank_other_is_not_saved(self):
        from PyQt5.QtWidgets import QDialog, QPushButton
        dlg = self._dialog()
        other = next(btn for btn in dlg.findChildren(QPushButton) if btn.text() == "Other")
        other.click()
        dlg._accept()
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        self.assertIn("write what happened", dlg._error.text().lower())


if __name__ == "__main__":
    unittest.main()
