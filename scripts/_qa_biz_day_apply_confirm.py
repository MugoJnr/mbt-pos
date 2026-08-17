"""QA — confirm business-day calendar pick updates button + _business_day.

Usage:  python scripts/_qa_biz_day_apply_confirm.py
Out:    QA_SCREENSHOTS_CONFIRM/biz_day_applied_*.png
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parents[3] / "QA_SCREENSHOTS_CONFIRM"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from desktop.utils.api_client import APIClient
    from desktop.tabs.sales_tab import SalesTab
    from desktop.utils.date_controls import apply_shop_day_edit
    from desktop.utils.shop_time import shop_today

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    db = ROOT / "data" / "mbt_pos.db"
    api = APIClient(str(db))
    user = {"id": 1, "username": "admin", "role": "superadmin", "full_name": "QA"}

    tab = SalesTab(api, user, str(db), lambda: {})
    tab.resize(900, 700)
    tab.show()
    for _ in range(40):
        app.processEvents()

    today = shop_today()
    yesterday = today - timedelta(days=1)

    # Before pick — should be today
    before_iso = tab._business_day_iso()
    bar = tab._business_day_bar
    bar.show()
    for _ in range(20):
        app.processEvents()

    before_path = OUT / "biz_day_before_pick.png"
    bar.grab().save(str(before_path), "PNG")

    # Simulate calendar dialog OK — same path as _BizDayButton._pick_date
    apply_shop_day_edit(tab._biz_date, yesterday, today=today, block_signals=False)
    for _ in range(30):
        app.processEvents()

    after_iso = tab._business_day_iso()
    warn_text = (tab._biz_warn.text() or "").strip()
    btn_text = bar._picker.text()

    after_path = OUT / "biz_day_after_pick_yesterday.png"
    bar.grab().save(str(after_path), "PNG")

    full_path = OUT / "biz_day_pos_screen_after_pick.png"
    tab.grab().save(str(full_path), "PNG")

    ok = (
        before_iso == today.isoformat()
        and after_iso == yesterday.isoformat()
        and tab._business_day == yesterday
        and yesterday.isoformat() in btn_text
        and "not today" in warn_text.lower()
    )

    report = {
        "version": "3.0.59",
        "before_business_day": before_iso,
        "after_business_day": after_iso,
        "button_text": btn_text,
        "warn_text": warn_text,
        "passed": ok,
        "screenshots": [
            str(before_path),
            str(after_path),
            str(full_path),
        ],
    }
    (OUT / "biz_day_apply_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    tab.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
