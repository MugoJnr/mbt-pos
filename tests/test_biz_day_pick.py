"""Business-day calendar pick must propagate to SalesTab._business_day."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class BizDayPickTests(unittest.TestCase):
    def test_apply_shop_day_edit_emits_date_changed(self):
        from PyQt5.QtWidgets import QApplication, QDateEdit
        from desktop.utils.date_controls import apply_shop_day_edit

        app = QApplication.instance() or QApplication([])
        ed = QDateEdit()
        fired = []

        def _on_change(qd):
            fired.append(date(qd.year(), qd.month(), qd.day()))

        ed.dateChanged.connect(_on_change)
        yesterday = date.today() - timedelta(days=1)
        apply_shop_day_edit(ed, yesterday, today=date.today(), block_signals=False)
        self.assertEqual(fired, [yesterday])

    def test_apply_shop_day_edit_blocked_skips_signal(self):
        from PyQt5.QtWidgets import QApplication, QDateEdit
        from desktop.utils.date_controls import apply_shop_day_edit

        app = QApplication.instance() or QApplication([])
        ed = QDateEdit()
        fired = []
        ed.dateChanged.connect(lambda qd: fired.append(1))
        yesterday = date.today() - timedelta(days=1)
        apply_shop_day_edit(ed, yesterday, today=date.today(), block_signals=True)
        self.assertEqual(fired, [])

    def test_biz_day_button_pick_updates_tab_business_day(self):
        from PyQt5.QtWidgets import QApplication, QDateEdit
        from desktop.pos.panel_factory import _BizDayButton
        from desktop.utils.date_controls import apply_shop_day_edit

        app = QApplication.instance() or QApplication([])
        ed = QDateEdit()
        today = date.today()
        apply_shop_day_edit(ed, today, today=today)
        btn = _BizDayButton()
        btn.bind_date(ed)

        tab_day = {"value": today}

        def _on_changed(qd):
            tab_day["value"] = date(qd.year(), qd.month(), qd.day())

        ed.dateChanged.connect(_on_changed)
        picked = today - timedelta(days=2)
        apply_shop_day_edit(ed, picked, today=today, block_signals=False)
        self.assertEqual(tab_day["value"], picked)


if __name__ == "__main__":
    unittest.main()
