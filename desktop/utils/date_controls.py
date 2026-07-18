"""
Shared date filter controls — ThemeManager tokens only.
MugoByte Technologies | mugobyte.com
"""
from __future__ import annotations

import os
from datetime import date as date_cls
from typing import Optional, Union

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QDateEdit, QHBoxLayout, QLabel, QWidget

from desktop.utils.theme import C, RADIUS, TOUCH_MIN, _assets_root

DATE_DISPLAY_FMT = 'dd MMM yyyy'
DATE_API_FMT = 'yyyy-MM-dd'
CONTROL_HEIGHT = max(40, TOUCH_MIN - 4)


def _as_qdate(value: Optional[Union[QDate, date_cls]] = None) -> QDate:
    if value is None:
        return QDate.currentDate()
    if isinstance(value, QDate):
        return value if value.isValid() else QDate.currentDate()
    if isinstance(value, date_cls):
        return QDate(value.year, value.month, value.day)
    return QDate.currentDate()


def _calendar_arrow_qss() -> str:
    path = os.path.join(_assets_root(), 'icons', 'calendar.svg')
    if os.path.isfile(path):
        url = path.replace('\\', '/')
        return (
            f'image: url("{url}"); width: 14px; height: 14px; '
            f'border: none; margin-right: 6px;'
        )
    return (
        'image: none; width: 0; height: 0; '
        'border-left: 5px solid transparent; '
        'border-right: 5px solid transparent; '
        f'border-top: 6px solid {C["muted"]}; margin-right: 8px;'
    )


def style_date_edit(d: QDateEdit) -> None:
    """Force live ThemeManager tokens onto a QDateEdit (fixes light/dark swap)."""
    r = RADIUS.get('md', 8)
    d.setStyleSheet(
        f"QDateEdit {{"
        f"background:{C['input']}; color:{C['text']};"
        f"border:1px solid {C['border2']}; border-radius:{r}px;"
        f"padding:6px 34px 6px 12px; font-size:13px;"
        f"min-height:28px; min-width:140px; }}"
        f"QDateEdit:focus {{ border-color:{C['gold']}; }}"
        f"QDateEdit::drop-down {{"
        f"subcontrol-origin:padding; subcontrol-position:center right;"
        f"width:30px; border:none; border-left:1px solid {C['border']};"
        f"background:transparent; }}"
        f"QDateEdit::drop-down:hover {{ background:{C['hover']}; }}"
        f"QDateEdit::down-arrow {{ {_calendar_arrow_qss()} }}"
    )


def make_date_edit(
    initial: Optional[Union[QDate, date_cls]] = None,
    height: int = CONTROL_HEIGHT,
    *,
    allow_future: bool = False,
    min_width: int = 148,
) -> QDateEdit:
    """Themed QDateEdit with calendar popup + visible calendar affordance."""
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat(DATE_DISPLAY_FMT)
    d.setDate(_as_qdate(initial))
    d.setMinimumHeight(height)
    d.setMinimumWidth(min_width)
    d.setMaximumWidth(max(min_width + 40, 200))
    d.setMinimumDate(QDate(2000, 1, 1))
    today = QDate.currentDate()
    d.setMaximumDate(today.addYears(5) if allow_future else today)
    d.setProperty('mbtDateEdit', True)
    style_date_edit(d)
    return d


def filter_label(text: str) -> QLabel:
    """Plain caption for filter toolbars — no pill border."""
    lbl = QLabel(text)
    lbl.setProperty('mbtFilterLabel', True)
    style_filter_label(lbl)
    return lbl


def style_filter_label(lbl: QLabel) -> None:
    from PyQt5.QtGui import QColor, QPalette
    # High-contrast caption — never inherit a stale light/dark color
    lbl.setStyleSheet(
        f"QLabel {{ color:{C['text']}; font-size:13px; font-weight:600; "
        f"background:transparent; border:none; padding:0; margin:0; }}")
    pal = lbl.palette()
    pal.setColor(QPalette.WindowText, QColor(C['text']))
    pal.setColor(QPalette.Text, QColor(C['text']))
    lbl.setPalette(pal)
    lbl.setAutoFillBackground(False)


def refresh_filter_labels(root: QWidget) -> None:
    for lbl in root.findChildren(QLabel):
        if lbl.property('mbtFilterLabel'):
            style_filter_label(lbl)


def refresh_date_edits(root: QWidget) -> None:
    for d in root.findChildren(QDateEdit):
        if d.property('mbtDateEdit'):
            style_date_edit(d)


def add_labeled(
    row: QHBoxLayout,
    label: str,
    widget: QWidget,
    *,
    spacing: int = 8,
) -> None:
    """Add plain label + control to a single-row filter bar."""
    row.addWidget(filter_label(label))
    row.addWidget(widget)
    if spacing:
        row.addSpacing(spacing)
