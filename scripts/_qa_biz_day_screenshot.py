"""Minimal Qt harness — render BusinessDayBar and save screenshot."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtCore import QDate, Qt, QTimer
from PyQt5.QtWidgets import QApplication, QDateEdit, QVBoxLayout, QWidget

from desktop.utils.theme import ThemeManager
from desktop.pos.panel_factory import BusinessDayBar
from desktop.utils.widgets import SecondaryBtn


def main() -> int:
    out_dir = os.path.abspath(
        os.path.join(ROOT, '..', '..', '.cursor', 'projects', 'c-Users-mugoj-OneDrive-Desktop-MBT-POS', 'assets')
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'biz_day_picker_3057.png')

    app = QApplication(sys.argv)
    ThemeManager.apply(False, app)

    shell = QWidget()
    shell.setObjectName('posProductPanel')
    shell.setAttribute(Qt.WA_StyledBackground, True)
    shell.setMinimumWidth(720)
    shell.setStyleSheet('QWidget#posProductPanel{background:#16213A;}')
    lay = QVBoxLayout(shell)

    bar = BusinessDayBar(shell)
    de = QDateEdit()
    de.setCalendarPopup(True)
    de.setDisplayFormat('yyyy-MM-dd')
    de.setDate(QDate(2026, 8, 16))
    de.setMinimumHeight(34)
    today = SecondaryBtn('Today', 32)
    view = SecondaryBtn('View day', 32)
    copy = SecondaryBtn('Copy sale…', 32)
    from PyQt5.QtWidgets import QLabel
    warn = QLabel('')
    warn.setObjectName('posBizDayWarn')
    bar.setup(None, de, (
        (today, 'Today', 'Today'),
        (view, 'View', 'View day'),
        (copy, 'Copy', 'Copy sale…'),
    ), warn)
    lay.addWidget(bar)
    shell.show()
    shell.raise_()

    def grab() -> None:
        pix = bar.grab()
        pix.save(out_path)
        print(f'SAVED {out_path} size={pix.width()}x{pix.height()}')
        app.quit()

    QTimer.singleShot(400, grab)
    return app.exec_()


if __name__ == '__main__':
    raise SystemExit(main())
