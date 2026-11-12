"""An open request list refreshes quietly and does not treat a failed refresh as current."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox

from desktop.tabs.backdate_dialog import BackdateDialog


class _Api:
    def __init__(self):
        self.mode = "ok"

    def list_backdate_requests(self, filters=None):
        if self.mode == "down":
            return {"error": "The shop could not be reached."}
        return {
            "requests": [{
                "id": 15,
                "reference": "BDR-KEEP",
                "cashier_name": "QA Cashier",
                "business_date": "2026-11-10",
                "status": "approved",
                "reason": "kept",
                "summary": {"total_sales": 200},
            }],
        }

    def get_backdate_request(self, request_id):
        return {
            "id": request_id,
            "reference": "BDR-KEEP",
            "status": "approved",
            "cashier_name": "QA Cashier",
            "business_date": "2026-11-10",
            "summary": {"total_sales": 200},
            "sales": [],
        }


class RequestQueueRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_quiet_refresh_keeps_the_open_request_and_does_not_pop_a_warning(self):
        api = _Api()
        dialog = BackdateDialog(api, {"id": 2, "role": "manager", "username": "manager1"})
        dialog._current = {"id": 15, "status": "approved"}
        dialog.receipt.setPlainText("Keep this receipt on screen.")
        warnings = []
        QMessageBox.warning = lambda *args, **kwargs: warnings.append(args)
        api.mode = "down"
        dialog._refresh_quiet()
        self.assertEqual(dialog.receipt.toPlainText(), "Keep this receipt on screen.")
        self.assertIn("out of date", dialog.freshness.text())
        self.assertEqual(warnings, [])
        self.assertEqual(dialog._timer.interval(), 20000)
        dialog.close()
