"""
Shared date filter controls — ThemeManager tokens only.
MugoByte Technologies | mugobyte.com
"""
from __future__ import annotations

import ctypes
import os
import sys
from datetime import date as date_cls
from typing import Optional, Union

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QCalendarWidget,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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


def release_window_topmost(widget) -> None:
    """Drop always-on-top from a window. The date dialog must not pin the till."""
    if widget is None:
        return
    window = widget.window()
    flags = window.windowFlags()
    if flags & Qt.WindowStaysOnTopHint:
        window.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        window.show()
    if sys.platform != 'win32' or os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        return
    try:
        hwnd = int(window.winId())
        # HWND_NOTOPMOST. Does nothing when the window was not pinned.
        ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    except Exception:
        pass


def pick_shop_day_dialog(
    parent: QWidget,
    initial: Optional[Union[QDate, date_cls]] = None,
    *,
    title: str = 'Select business day',
    min_date: Optional[Union[QDate, date_cls]] = None,
    max_date: Optional[Union[QDate, date_cls]] = None,
) -> Optional[date_cls]:
    """Modal calendar — reliable on Windows packaged builds (no QDateEdit popup)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setWindowFlag(Qt.WindowStaysOnTopHint, False)
    dlg.setMinimumSize(380, 420)
    dlg.setStyleSheet(
        "QDialog{background:#101820;color:#f5f7fb;}"
        "QLabel{color:#f5f7fb;background:transparent;}"
        "QCalendarWidget{background:#101820;color:#f5f7fb;}"
        "QCalendarWidget QWidget{background:#101820;color:#f5f7fb;alternate-background-color:#16202b;}"
        "QCalendarWidget QAbstractItemView{background:#101820;color:#f5f7fb;"
        "selection-background-color:#e0b15a;selection-color:#101820;}"
        "QCalendarWidget QToolButton{color:#f5f7fb;background:#1c2836;font-size:14px;}"
        "QDialogButtonBox QPushButton{min-height:36px;background:#1c2836;color:#f5f7fb;"
        "border:1px solid #e0b15a;padding:6px 14px;font-weight:700;}"
    )
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(10)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet("font-size:16px;font-weight:700;color:#f5f7fb;")
    lay.addWidget(title_lbl)

    cal = QCalendarWidget(dlg)
    cal.setMinimumSize(340, 280)
    cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
    cal.setGridVisible(True)
    cal.setSelectedDate(_as_qdate(initial))
    if min_date is not None:
        cal.setMinimumDate(_as_qdate(min_date))
    if max_date is not None:
        cal.setMaximumDate(_as_qdate(max_date))

    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setDefault(True)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(cal)
    lay.addWidget(bb)

    try:
        accepted = dlg.exec_() == QDialog.Accepted
    finally:
        release_window_topmost(parent)
        release_window_topmost(dlg)
    if not accepted:
        return None
    sel = cal.selectedDate()
    if not sel.isValid():
        return None
    return date_cls(sel.year(), sel.month(), sel.day())


def pick_date_range(
    parent: QWidget,
    start: date_cls,
    end: date_cls,
    *,
    title: str = 'Choose dates',
) -> Optional[tuple]:
    """Month grid for a from/to range. Day buttons paint reliably on the till."""
    if end < start:
        start, end = end, start
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setWindowFlag(Qt.WindowStaysOnTopHint, False)
    dlg.setMinimumSize(460, 520)
    day_style = (
        "QPushButton{background:#16202b;color:#f5f7fb;border:1px solid #2a3848;"
        "min-height:36px;min-width:44px;font-size:13px;font-weight:600;border-radius:6px;}"
        "QPushButton:hover{background:#243244;}"
        "QPushButton:disabled{color:#5c6b7a;background:#101820;}"
    )
    picked_style = day_style.replace("#16202b", "#e0b15a", 1).replace("#f5f7fb", "#101820", 1)
    between_style = day_style.replace("#16202b", "#3d3424", 1)
    dlg.setStyleSheet(
        "QDialog{background:#101820;color:#f5f7fb;}"
        "QLabel{color:#f5f7fb;background:transparent;}"
    )
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(10)
    heading = QLabel(title)
    heading.setStyleSheet("font-size:16px;font-weight:700;")
    lay.addWidget(heading)
    hint = QLabel("Click the first day, then the last day.")
    hint.setStyleSheet("color:#9aa8b8;font-size:12px;")
    lay.addWidget(hint)

    state = {
        "y": start.year,
        "m": start.month,
        "start": start,
        "end": end,
    }
    summary = QLabel()
    summary.setStyleSheet("font-size:14px;font-weight:700;color:#e0b15a;")
    lay.addWidget(summary)

    presets = QHBoxLayout()
    today = date_cls.today()

    def _set_range(first, last, close=False):
        if last < first:
            first, last = last, first
        if first > today:
            first = today
        if last > today:
            last = today
        state["start"], state["end"] = first, last
        state["y"], state["m"] = last.year, last.month
        _paint()
        if close:
            dlg.accept()

    for label, first, last in (
        ("Today", today, today),
        ("Yesterday", today.fromordinal(today.toordinal() - 1), today.fromordinal(today.toordinal() - 1)),
        ("Last 7 days", today.fromordinal(today.toordinal() - 6), today),
        ("This month", today.replace(day=1), today),
    ):
        btn = QPushButton(label)
        btn.setStyleSheet(day_style)
        btn.clicked.connect(lambda _=False, a=first, b=last: _set_range(a, b, True))
        presets.addWidget(btn)
    lay.addLayout(presets)

    nav = QHBoxLayout()
    prev = QPushButton("<")
    month_lbl = QLabel()
    nxt = QPushButton(">")
    for btn in (prev, nxt):
        btn.setStyleSheet(day_style)
        btn.setFixedSize(44, 36)
    month_lbl.setAlignment(Qt.AlignCenter)
    month_lbl.setStyleSheet("font-size:14px;font-weight:700;")
    nav.addWidget(prev)
    nav.addWidget(month_lbl, 1)
    nav.addWidget(nxt)
    lay.addLayout(nav)

    host = QWidget(dlg)
    grid = QGridLayout(host)
    grid.setSpacing(4)
    lay.addWidget(host)

    def _paint():
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        first_of = date_cls(state["y"], state["m"], 1)
        month_lbl.setText(first_of.strftime("%B %Y"))
        summary.setText(
            f"{state['start'].strftime('%d %b %Y')}  –  {state['end'].strftime('%d %b %Y')}"
        )
        for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            label = QLabel(name)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color:#9aa8b8;font-size:11px;font-weight:700;")
            grid.addWidget(label, 0, col)
        offset = first_of.weekday()
        days = (date_cls(state["y"] + (state["m"] == 12), (state["m"] % 12) + 1, 1) - first_of).days
        for day_num in range(1, days + 1):
            chosen = date_cls(state["y"], state["m"], day_num)
            day_btn = QPushButton(str(day_num))
            if chosen == state["start"] or chosen == state["end"]:
                day_btn.setStyleSheet(picked_style)
            elif state["start"] < chosen < state["end"]:
                day_btn.setStyleSheet(between_style)
            else:
                day_btn.setStyleSheet(day_style)
            if chosen > today:
                day_btn.setEnabled(False)
            day_btn.clicked.connect(lambda _=False, picked=chosen: _click(picked))
            slot = offset + day_num - 1
            grid.addWidget(day_btn, 1 + (slot // 7), slot % 7)

    def _click(chosen):
        if state.get("awaiting_end"):
            _set_range(state["start"], chosen)
            state["awaiting_end"] = False
            hint.setText("Click the first day, then the last day.")
        else:
            state["start"] = chosen
            state["end"] = chosen
            state["awaiting_end"] = True
            hint.setText("Now click the last day.")
            _paint()

    def _shift(delta):
        month = state["m"] + delta
        year = state["y"]
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        state["m"], state["y"] = month, year
        _paint()

    prev.clicked.connect(lambda: _shift(-1))
    nxt.clicked.connect(lambda: _shift(1))
    actions = QHBoxLayout()
    cancel = QPushButton("Cancel")
    apply_btn = QPushButton("Use these dates")
    cancel.setStyleSheet(day_style)
    apply_btn.setStyleSheet(picked_style)
    cancel.clicked.connect(dlg.reject)
    apply_btn.clicked.connect(dlg.accept)
    actions.addWidget(cancel)
    actions.addWidget(apply_btn)
    lay.addLayout(actions)
    state["awaiting_end"] = False
    _paint()
    try:
        accepted = dlg.exec_() == QDialog.Accepted
    finally:
        release_window_topmost(parent)
        release_window_topmost(dlg)
    if not accepted:
        return None
    return state["start"], state["end"]


def apply_shop_day_edit(
    edit: QDateEdit,
    day: Optional[Union[QDate, date_cls]] = None,
    *,
    today: Optional[date_cls] = None,
    block_signals: bool = True,
) -> date_cls:
    """
    Set a QDateEdit to ``day``, always refreshing maximumDate to shop today first.

    Qt clamps setDate() to the current maximumDate. If maximumDate was frozen at
    construction (e.g. last year), Today / setDate(2026-…) silently stays on
    2025-… — raise max before setDate to avoid that.
    """
    try:
        from desktop.utils.shop_time import shop_today
        shop = today or shop_today()
    except Exception:
        shop = today or date_cls.today()
    target = _as_qdate(day if day is not None else shop)
    target_d = date_cls(target.year(), target.month(), target.day())
    if target_d > shop:
        target_d = shop
        target = QDate(shop.year, shop.month, shop.day)
    qd_max = QDate(shop.year, shop.month, shop.day)
    if block_signals:
        edit.blockSignals(True)
    try:
        edit.setMaximumDate(qd_max)
        edit.setDate(target)
    finally:
        if block_signals:
            edit.blockSignals(False)
    return target_d


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
    d.setMinimumHeight(height)
    d.setMinimumWidth(min_width)
    d.setMaximumWidth(max(min_width + 40, 200))
    d.setMinimumDate(QDate(2000, 1, 1))
    today = QDate.currentDate()
    # Max before setDate — Qt clamps setDate to maximumDate
    d.setMaximumDate(today.addYears(5) if allow_future else today)
    d.setDate(_as_qdate(initial))
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
