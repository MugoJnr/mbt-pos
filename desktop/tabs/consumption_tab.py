"""
MBT POS — Internal Stock Consumption
MugoByte Technologies | mugobyte.com

Record stock used internally (production, staff, cleaning, etc.)
without a customer sale. Soft-void restores stock.
"""
import logging
import os
from datetime import date, timedelta

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, qss_alpha, RADIUS, TOUCH_MIN
from desktop.utils.widgets import (
    Card, H2, H3, Caption, PrimaryBtn, SecondaryBtn, DangerBtn, GhostBtn,
    Badge, SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout,
    lovable_tab_qss, wrap_table_card, retint_table_items, apply_table_row_backgrounds,
)

# Touch-friendly line-item / search-result density (presentation only)
LINE_ROW_H = max(48, TOUCH_MIN)
PROD_LIST_ITEM_H = max(44, TOUCH_MIN)
from desktop.utils.security import has_permission, require_permission
from desktop.utils.option_lists import CONSUMPTION_REASONS
from desktop.utils.select_controls import (
    Select, SearchableSelect, ReasonSelect, DatePresetSelect, prompt_reason,
    CONTROL_HEIGHT,
)
from desktop.utils.date_controls import (
    make_date_edit, filter_label, refresh_filter_labels,
    DATE_DISPLAY_FMT as _DATE_FMT, DATE_API_FMT, add_labeled,
)


_log = logging.getLogger('consumption')

REASONS = CONSUMPTION_REASONS


def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _fmt_qty(v):
    f = round(_safe_float(v, 0), 4)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    text = f"{f:.3f}".rstrip('0').rstrip('.')
    if '.' in text and len(text.split('.')[1]) < 2:
        text = f"{f:.2f}"
    return text


def _unit_bucket(unit):
    raw = (unit or 'pcs').strip()
    key = raw.lower()
    aliases = {
        'kg': 'kg', 'kilogram': 'kg', 'kilograms': 'kg',
        'g': 'g', 'gram': 'g', 'grams': 'g',
        'l': 'L', 'ltr': 'L', 'litre': 'L', 'liter': 'L', 'litres': 'L', 'liters': 'L',
        'ml': 'ml', 'millilitre': 'ml', 'milliliter': 'ml',
        'm': 'm', 'metre': 'm', 'meter': 'm',
        'pcs': 'pcs', 'pc': 'pcs', 'piece': 'pcs', 'pieces': 'pcs',
    }
    return aliases.get(key, raw or 'pcs')


def _qty_by_unit(lines):
    totals = {}
    for line in lines:
        unit = _unit_bucket(line.get('unit'))
        totals[unit] = totals.get(unit, 0.0) + _safe_float(line.get('quantity'))
    return totals


def _currency(cfg):
    try:
        return (cfg or {}).get('currency_symbol', 'KES') or 'KES'
    except Exception:
        return 'KES'


class DateField(QWidget):
    """
    QDateEdit + explicit Cal button.
    Fusion often paints an empty drop-down square — this avoids that.
    """
    dateChanged = pyqtSignal(QDate)

    def __init__(self, initial=None, height=40, parent=None):
        super().__init__(parent)
        self.setStyleSheet('background:transparent; border:none;')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._edit = QDateEdit()
        self._edit.setCalendarPopup(True)
        self._edit.setDisplayFormat(_DATE_FMT)
        self._edit.setDate(initial if initial is not None else QDate.currentDate())
        self._edit.setMinimumHeight(height)
        self._edit.setMinimumWidth(148)
        self._edit.setMaximumDate(QDate.currentDate().addYears(5))
        self._edit.setMinimumDate(QDate(2000, 1, 1))
        self._edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        # Hide native empty drop-down square — Cal button opens the popup
        self._edit.setStyleSheet(
            "QDateEdit::drop-down{width:0px;border:none;}"
            "QDateEdit::down-arrow{image:none;width:0;height:0;}")
        self._edit.dateChanged.connect(self.dateChanged.emit)
        lay.addWidget(self._edit, 1)

        self._btn = QToolButton()
        self._btn.setObjectName('mbtCalBtn')
        self._btn.setText('\u25BE')  # small down triangle; label is "Cal" for clarity
        self._btn.setText('Cal')
        self._btn.setToolTip('Open calendar')
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setFixedSize(max(44, height), height)
        self._btn.clicked.connect(self._open_calendar)
        lay.addWidget(self._btn)
        self.refresh_theme()

    def _open_calendar(self):
        """Month grid of buttons. Native calendar day cells do not paint on the till."""
        from PyQt5.QtCore import QDate
        from PyQt5.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget
        parent = self.window() if self.window() is not None else self
        box = QDialog(parent)
        box.setWindowTitle("Choose date")
        box.setModal(True)
        box.resize(460, 420)
        box.setStyleSheet("QDialog{background-color:#F7F9FC;}")
        style = (
            "QPushButton{background-color:#F7F9FC;color:#121820;border:1px solid #C5D0DE;"
            "min-height:34px;min-width:40px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background-color:#E7EEF6;color:#121820;}"
            "QPushButton:disabled{color:#9CA3AF;background-color:#F7F9FC;}"
        )
        picked_style = style.replace("#F7F9FC", "#D6E4F5", 1)
        lay = QVBoxLayout(box)
        head = QHBoxLayout()
        prev = QPushButton("<", box)
        title = QPushButton(box)
        nxt = QPushButton(">", box)
        for btn in (prev, title, nxt):
            btn.setStyleSheet(style)
        title.setMinimumWidth(180)
        head.addWidget(prev)
        head.addWidget(title, 1)
        head.addWidget(nxt)
        lay.addLayout(head)
        host = QWidget(box)
        grid = QGridLayout(host)
        grid.setSpacing(4)
        lay.addWidget(host)
        try:
            current = self._edit.date()
        except Exception:
            current = QDate.currentDate()
        state = {"y": current.year(), "m": current.month()}
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        def _apply(chosen):
            if chosen > QDate.currentDate():
                chosen = QDate.currentDate()
            try:
                self._edit.setMaximumDate(QDate.currentDate())
                self._edit.setDate(chosen)
            except Exception:
                pass
            try:
                self.setDate(chosen)
            except Exception:
                pass
            box.accept()

        def _rebuild():
            while grid.count():
                item = grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            first = QDate(state["y"], state["m"], 1)
            title.setText(first.toString("MMMM yyyy"))
            for col, name in enumerate(names):
                label = QPushButton(name, host)
                label.setStyleSheet(style)
                grid.addWidget(label, 0, col)
            offset = first.dayOfWeek() - 1
            today = QDate.currentDate()
            for day_num in range(1, first.daysInMonth() + 1):
                chosen = QDate(state["y"], state["m"], day_num)
                day_btn = QPushButton(str(day_num), host)
                day_btn.setStyleSheet(picked_style if chosen == current else style)
                if chosen > today:
                    day_btn.setEnabled(False)
                day_btn.pressed.connect(lambda _=False, picked=chosen: _apply(picked))
                slot = offset + day_num - 1
                grid.addWidget(day_btn, 1 + (slot // 7), slot % 7)

        def _shift(delta):
            month = state["m"] + delta
            year = state["y"]
            if month < 1:
                month, year = 12, year - 1
            elif month > 12:
                month, year = 1, year + 1
            state["m"], state["y"] = month, year
            _rebuild()

        prev.pressed.connect(lambda: _shift(-1))
        nxt.pressed.connect(lambda: _shift(1))
        _rebuild()
        box.exec_()

    def date(self):
        return self._edit.date()

    def setDate(self, d):
        if not isinstance(d, QDate):
            d = QDate(d.year, d.month, d.day)
        self._edit.setDate(d)

    def displayFormat(self):
        return self._edit.displayFormat()

    def setDisplayFormat(self, fmt):
        self._edit.setDisplayFormat(fmt)

    def calendarPopup(self):
        return self._edit.calendarPopup()

    def calendarWidget(self):
        return self._edit.calendarWidget()

    def refresh_theme(self):
        r = RADIUS.get('md', 8)
        self._btn.setStyleSheet(
            f"QToolButton#mbtCalBtn {{"
            f"background:{C['input']}; color:{C['gold']};"
            f"border:1px solid {C['border2']}; border-radius:{r}px;"
            f"font-size:12px; font-weight:800; letter-spacing:0.5px; }}"
            f"QToolButton#mbtCalBtn:hover {{"
            f"border-color:{C['gold']}; background:{C['hover']}; }}")


def _make_date_edit(initial=None, height=40):
    return DateField(initial=initial, height=height)


def _table_entry(text):
    """Plain field. Spin boxes clip the last digit inside a styled table cell."""
    edit = QLineEdit(text)
    edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    edit.setMinimumHeight(36)
    edit.setTextMargins(8, 0, 14, 0)
    edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    r = RADIUS.get('md', 8)
    edit.setStyleSheet(
        f"QLineEdit {{"
        f"background:{C['input']}; color:{C['text']};"
        f"border:1px solid {C['border']}; border-radius:{r}px;"
        f"padding:2px 12px; font-size:13px; }}"
        f"QLineEdit:focus {{ border-color:{C['gold']}; }}")
    return edit


def _parse_decimal(text):
    raw = ''.join(ch for ch in str(text) if ch.isdigit() or ch in '.-')
    if raw in ('', '-', '.', '-.'):
        raise ValueError(text)
    return float(raw)


def _style_table_spin(spin):
    """Theme-safe spin for table cells — no up/down chrome (avoids light-mode gray blocks)."""
    r = RADIUS.get('md', 8)
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    spin.setMinimumHeight(36)
    spin.setStyleSheet(
        f"QDoubleSpinBox {{"
        f"background:{C['input']}; color:{C['text']};"
        f"border:1px solid {C['border']}; border-radius:{r}px;"
        f"padding:2px 10px; font-size:13px; min-height:36px; }}"
        f"QDoubleSpinBox:focus {{ border-color:{C['gold']}; }}"
        f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
        f"width:0px; height:0px; border:none; padding:0; margin:0; }}"
        f"QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{"
        f"width:0px; height:0px; image:none; }}")


def _cell_wrap(widget, *, h_margin=4, v_margin=4):
    """Center a cell widget inside the row so text/controls share vertical rhythm."""
    wrap = QWidget()
    wrap.setStyleSheet('background:transparent; border:none;')
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(h_margin, v_margin, h_margin, v_margin)
    lay.setSpacing(0)
    lay.addWidget(widget, 0, Qt.AlignCenter)
    return wrap


def _field_label(text):
    lbl = QLabel(text)
    lbl.setProperty('mbtFieldLabel', True)
    lbl.setStyleSheet(
        f"color:{C['muted']}; font-size:11px; font-weight:700; "
        f"letter-spacing:0.6px; background:transparent; border:none;")
    return lbl


def _field(label, widget):
    w = QWidget()
    w.setStyleSheet('background:transparent; border:none;')
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    v.addWidget(_field_label(label))
    v.addWidget(widget)
    return w


class ConsumptionTab(QWidget):
    """Sidebar: Internal Consumption — Create / History / Report."""

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api
        self.user = user
        self.db_path = db_path
        self.config_getter = config_getter
        self._build()

    def _cfg(self):
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _build(self):
        lay, _ = page_layout(self, margins=(0, 0, 0, 0), spacing=0)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setProperty('mbtLovableTabs', True)
        self._tabs.setStyleSheet(lovable_tab_qss())

        self._create = _CreatePane(self)
        self._history = _HistoryPane(self)
        self._report = _ReportPane(self)

        self._tabs.addTab(self._create, 'New Consumption')
        self._tabs.addTab(self._history, 'History')
        self._tabs.addTab(self._report, 'Report')
        self._tabs.currentChanged.connect(self._on_tab)
        lay.addWidget(self._tabs)

    def _on_tab(self, idx):
        w = self._tabs.widget(idx)
        if hasattr(w, 'refresh'):
            try:
                w.refresh()
            except Exception as e:
                _log.warning('consumption sub-refresh: %s', e)

    def on_show(self):
        self._create.refresh()
        if self._tabs.currentIndex() == 1:
            self._history.refresh()
        elif self._tabs.currentIndex() == 2:
            self._report.refresh()

    def refresh(self):
        self.on_show()

    def open_report(self):
        self._tabs.setCurrentWidget(self._report)
        self._report.refresh()

    def apply_theme(self, is_light=None):
        try:
            from desktop.utils.widgets import refresh_themed_widgets
            refresh_themed_widgets(self)
            self._tabs.setStyleSheet(lovable_tab_qss())
            for pane in (self._create, self._history, self._report):
                if hasattr(pane, 'apply_theme'):
                    pane.apply_theme()
        except Exception as e:
            _log.warning('consumption apply_theme: %s', e)


# ── New Consumption ───────────────────────────────────────────────────────────

class _CreatePane(QWidget):
    def __init__(self, parent_tab: ConsumptionTab):
        super().__init__()
        self.p = parent_tab
        self._lines = []  # list of dicts
        self._products = []
        self._staff_mode = False  # True when Taken By is SearchableSelect
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(20, 12, 20, 0)
        head.addWidget(H2('New internal consumption'))
        root.addLayout(head)

        work = QVBoxLayout()
        work.setContentsMargins(20, 8, 20, 8)
        work.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(12)

        # ── Details section (clean spacing, no cell grid) ──
        details = Card()
        fl = details.layout_v((16, 10, 16, 10), 8)
        fl.addWidget(H3('Details'))

        row1 = QHBoxLayout()
        row1.setSpacing(16)
        self._date = _make_date_edit(QDate.currentDate(), height=CONTROL_HEIGHT)
        self._ref_badge = Badge('AUTO-######', tone='gold')
        self._ref_badge.setMinimumHeight(CONTROL_HEIGHT)
        self._ref_badge.setAlignment(Qt.AlignCenter)
        self._ref_badge.setMinimumWidth(140)
        # Keep a hidden line for StateReset / peek compatibility
        self._ref = QLineEdit()
        self._ref.setVisible(False)
        self._ref.setReadOnly(True)
        row1.addWidget(_field('Date', self._date), 1)
        row1.addWidget(_field('Reference', self._ref_badge), 1)
        fl.addLayout(row1)

        self._dept = Select(placeholder='Select department', height=CONTROL_HEIGHT)
        self._dept.setMinimumWidth(220)
        self._add_dept = SecondaryBtn('Add department', CONTROL_HEIGHT)
        self._add_dept.setToolTip('Save a department, then choose it here')
        self._add_dept.clicked.connect(self._add_department)
        dept_box = QWidget()
        dept_box.setStyleSheet('background:transparent; border:none;')
        dept_col = QVBoxLayout(dept_box)
        dept_col.setContentsMargins(0, 0, 0, 0)
        dept_col.setSpacing(6)
        dept_col.addWidget(_field_label('Department'))
        dept_line = QHBoxLayout()
        dept_line.setSpacing(8)
        dept_line.addWidget(self._dept, 1)
        dept_line.addWidget(self._add_dept)
        dept_col.addLayout(dept_line)
        fl.addWidget(dept_box)

        row2 = QHBoxLayout()
        row2.setSpacing(16)
        self._reason = ReasonSelect(reasons=REASONS, height=CONTROL_HEIGHT)
        self._taken = QLineEdit()
        self._taken.setPlaceholderText('Staff name')
        self._taken.setMinimumHeight(CONTROL_HEIGHT)
        self._taken.setMinimumWidth(160)
        self._staff_mode = True
        row2.addWidget(_field('Reason', self._reason), 1)
        row2.addWidget(_field('Taken by', self._taken), 1)
        fl.addLayout(row2)

        self._notes = QLineEdit()
        self._notes.setObjectName('mbtNotes')
        self._notes.setPlaceholderText('Optional notes')
        self._notes.setMinimumHeight(CONTROL_HEIGHT)
        self._notes.setMaximumHeight(CONTROL_HEIGHT)
        fl.addWidget(self._notes)
        details.setMinimumWidth(520)
        details.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        picker = Card()
        pl = picker.layout_v((14, 12, 14, 12), 8)
        pl.addWidget(H3('Products'))
        add_row = QHBoxLayout()
        add_row.setSpacing(10)
        self._search = SearchBar('Search product by name or SKU…')
        self._search.setMinimumHeight(CONTROL_HEIGHT)
        self._search.textChanged.connect(self._filter_products)
        self._search.returnPressed.connect(self._add_top_result)
        self._qty_add = QDoubleSpinBox()
        self._qty_add.setRange(0.001, 1_000_000)
        self._qty_add.setDecimals(3)
        self._qty_add.setValue(1.0)
        self._qty_add.setMinimumHeight(CONTROL_HEIGHT)
        self._qty_add.setFixedWidth(120)
        self._qty_add.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._qty_add.setToolTip('Quantity to add')
        _style_table_spin(self._qty_add)
        self._qty_add.setValue(1.0)
        add_btn = SecondaryBtn('+ Add', CONTROL_HEIGHT)
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(self._add_selected)
        add_row.addWidget(self._search, 1)
        add_row.addWidget(self._qty_add)
        add_row.addWidget(add_btn)
        add_row.addSpacing(8)
        pl.addLayout(add_row)

        self._prod_list = QListWidget()
        self._prod_list.setObjectName('mbtConsProdList')
        self._prod_list.setMinimumHeight(PROD_LIST_ITEM_H * 3)
        self._prod_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._prod_list.setTextElideMode(Qt.ElideRight)
        self._prod_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._prod_list.setUniformItemSizes(True)
        self._prod_list.itemDoubleClicked.connect(self._add_from_list)
        self._prod_list.itemActivated.connect(self._add_from_list)
        pl.addWidget(self._prod_list, 1)
        self._style_prod_list()
        pl.addWidget(Caption('Search by name, SKU, or barcode. Double-click or Add keeps earlier lines.'))
        picker.setMinimumWidth(360)
        picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        top.addWidget(picker, 3)
        top.addWidget(details, 2)

        lines_card = Card()
        ll = lines_card.layout_v((14, 12, 14, 12), 8)
        ll.addWidget(H3('Selected lines'))
        self._tbl = make_table(
            ['Product', 'Stock', 'Unit', 'Qty', 'Unit cost', 'Line cost', ''],
            stretch_col=0, row_height=LINE_ROW_H)
        self._tbl.verticalHeader().setMinimumSectionSize(LINE_ROW_H)
        line_header = self._tbl.horizontalHeader()
        line_header.setStretchLastSection(False)
        line_header.setMinimumSectionSize(44)
        line_header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 72), (2, 64), (3, 132), (4, 180), (5, 132), (6, 108)):
            line_header.setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, width)
        self._tbl.setMinimumHeight(196)
        self._tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        ll.addWidget(self._tbl, 1)
        top_host = QWidget()
        top_host.setLayout(top)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(top_host)
        split.addWidget(lines_card)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([240, 300])
        self._split = split
        QTimer.singleShot(0, self._balance_split)
        work.addWidget(split, 1)
        root.addLayout(work, 1)

        # ── Sticky footer ──
        foot_wrap = QFrame()
        foot_wrap.setObjectName('mbtConsFooter')
        foot_lay = QHBoxLayout(foot_wrap)
        foot_lay.setContentsMargins(20, 12, 20, 16)
        foot_lay.setSpacing(12)
        self._total_lbl = QLabel('Total Cost Used: —')
        self._total_lbl.setObjectName('mbtConsTotal')
        foot_lay.addWidget(self._total_lbl)
        foot_lay.addStretch()
        self._clear_btn = GhostBtn('Clear', 40)
        self._clear_btn.setToolTip('Reset the form without saving')
        self._clear_btn.clicked.connect(self._clear_form)
        foot_lay.addWidget(self._clear_btn)
        self._save_btn = PrimaryBtn('Save Consumption', 40)
        self._save_btn.clicked.connect(self._save)
        if not has_permission(self.p.user, 'consumption.create'):
            self._save_btn.setEnabled(False)
            self._save_btn.setToolTip('Your role cannot create consumptions.')
        foot_lay.addWidget(self._save_btn)
        root.addWidget(foot_wrap)
        self._style_footer()
        self._style_notes()
        self._style_taken()

    def _style_footer(self):
        r = RADIUS.get('xl', 12)
        self.findChild(QFrame, 'mbtConsFooter').setStyleSheet(
            f"QFrame#mbtConsFooter {{"
            f"background:{C['card']}; border:none;"
            f"border-top:1px solid {C['border']}; }}")
        self._total_lbl.setStyleSheet(
            f"color:{C['gold']}; font-size:16px; font-weight:800; "
            f"background:transparent; border:none;")

    def _style_taken(self):
        r = RADIUS.get('md', 8)
        self._taken.setStyleSheet(
            f"QLineEdit {{"
            f"background:{C['input']}; color:{C['text']};"
            f"border:1px solid {C['border']}; border-radius:{r}px;"
            f"padding:0 12px; font-size:13px; }}")

    def _style_notes(self):
        r = RADIUS.get('md', 8)
        self._notes.setStyleSheet(
            f"QLineEdit#mbtNotes {{"
            f"background:{C['input']}; color:{C['text']};"
            f"border:1px solid {C['border2']}; border-radius:{r}px;"
            f"padding:0 10px; font-size:13px; }}"
            f"QLineEdit#mbtNotes:focus {{ border-color:{C['gold']}; }}")

    def _style_ref_badge(self):
        text = self._ref.text() or 'AUTO-######'
        self._ref_badge.setText(text)
        self._ref_badge.setProperty('mbtBadgeTone', 'gold')
        from desktop.utils.widgets import _refresh_badge
        _refresh_badge(self._ref_badge)
        self._ref_badge.setMinimumHeight(CONTROL_HEIGHT)
        self._ref_badge.setAlignment(Qt.AlignCenter)

    def refresh(self):
        # Always snap date to today when opening (fixes stale / wrong-year defaults)
        try:
            self._date.setDate(QDate.currentDate())
            self._date.setDisplayFormat(_DATE_FMT)
        except Exception:
            pass
        try:
            ref = self.p.api.peek_next_consumption_ref() or 'AUTO-######'
        except Exception:
            ref = 'AUTO-######'
        self._ref.setText(ref)
        self._style_ref_badge()

        try:
            depts = self.p.api.get_departments() or []
        except Exception:
            depts = []
        cur = self._dept.current_value()
        items = [(d.get('name') or '', d.get('id')) for d in depts]
        self._dept.set_items(items)
        if cur is not None:
            self._dept.set_value(cur)

        self._load_staff()
        try:
            self._products = self.p.api.get_products() or []
        except Exception:
            self._products = []
        self._filter_products()
        self._rebuild_table()
        self._balance_split()

    def _balance_split(self):
        split = getattr(self, '_split', None)
        if split is None:
            return
        total = split.height()
        if total < 200:
            return
        top = max(200, int(total * 0.42))
        split.setSizes([top, max(180, total - top)])

    def _load_staff(self):
        """Offer staff names while typing. A typed name is always accepted."""
        cur_text = (self._taken.text() or '').strip()
        names = []
        try:
            users = self.p.api.get_users() or []
            for u in users:
                if int(u.get('is_active', 1) or 1) != 1:
                    continue
                label = (u.get('full_name') or u.get('username') or '').strip()
                if label and label not in names:
                    names.append(label)
        except Exception:
            names = []
        try:
            me = self.p.user.get('user') or self.p.user
            me_name = (me.get('full_name') or me.get('username') or '').strip()
            if me_name and me_name not in names:
                names.insert(0, me_name)
        except Exception:
            me_name = ''
        completer = QCompleter(names, self._taken)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self._taken.setCompleter(completer)
        if cur_text:
            self._taken.setText(cur_text)
        elif me_name and not self._taken.text():
            self._taken.setText(me_name)

    def _style_prod_list(self):
        r = RADIUS.get('md', 8)
        ih = PROD_LIST_ITEM_H
        self._prod_list.setStyleSheet(
            f"QListWidget#mbtConsProdList {{"
            f"background:{C['input']}; color:{C['text']};"
            f"border:1px solid {C['border']}; border-radius:{r}px;"
            f"outline:0; padding:4px; font-size:13px; }}"
            f"QListWidget#mbtConsProdList::item {{"
            f"min-height:{ih - 4}px; padding:10px 12px;"
            f"border-radius:6px; margin:2px; }}"
            f"QListWidget#mbtConsProdList::item:selected {{"
            f"background:{qss_alpha(C['gold'], 0.18)}; color:{C['gold']}; }}"
            f"QListWidget#mbtConsProdList::item:hover:!selected {{"
            f"background:{C['hover']}; }}")

    def _filter_products(self):
        q = (self._search.text() or '').strip().lower()
        self._prod_list.clear()
        shown = 0
        for p in self._products:
            name = p.get('name') or ''
            sku = p.get('sku') or ''
            barcode = str(p.get('barcode') or '')
            if q and q not in name.lower() and q not in sku.lower() and q not in barcode.lower():
                continue
            stock = _fmt_qty(p.get('stock'))
            item = QListWidgetItem(f"{name}  ·  stock {stock}" + (f"  ·  {sku}" if sku else ''))
            item.setData(Qt.UserRole, p)
            # Fusion often ignores QSS padding alone — SizeHint enforces touch row height
            item.setSizeHint(QSize(0, PROD_LIST_ITEM_H))
            self._prod_list.addItem(item)
            shown += 1
            if shown >= 40:
                break
        if shown and self._prod_list.currentRow() < 0:
            self._prod_list.setCurrentRow(0)

    def apply_theme(self):
        self._style_footer()
        self._style_notes()
        self._style_taken()
        self._style_ref_badge()
        self._style_prod_list()
        _style_table_spin(self._qty_add)
        if hasattr(self._date, 'refresh_theme'):
            self._date.refresh_theme()
        for w in (self._dept, self._reason, self._taken):
            if hasattr(w, 'refresh_theme'):
                w.refresh_theme()
        for lbl in self.findChildren(QLabel):
            if lbl.property('mbtFieldLabel'):
                lbl.setStyleSheet(
                    f"color:{C['muted']}; font-size:11px; font-weight:700; "
                    f"letter-spacing:0.6px; background:transparent; border:none;")
        # Restyle table spins after theme flip
        for r in range(self._tbl.rowCount()):
            for c in (2, 3):
                w = self._tbl.cellWidget(r, c)
                if w is None:
                    continue
                spins = [w] if isinstance(w, QDoubleSpinBox) else w.findChildren(QDoubleSpinBox)
                for spin in spins:
                    _style_table_spin(spin)
        retint_table_items(self._tbl)
        apply_table_row_backgrounds(self._tbl)

    def _add_department(self):
        from desktop.utils.theme import apply_themed_dialog
        dlg = QDialog(self)
        dlg.setWindowTitle('Add department')
        dlg.setMinimumWidth(420)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        title = QLabel('Add a department')
        title.setStyleSheet('font-size:16px; font-weight:700;')
        lay.addWidget(title)
        hint = QLabel('Kitchen, shop floor, office, or any place that uses stock.')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        name = QLineEdit()
        name.setPlaceholderText('Department name')
        name.setMinimumHeight(CONTROL_HEIGHT)
        lay.addWidget(name)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = GhostBtn('Cancel', 36)
        save = PrimaryBtn('Add department', 36)
        cancel.clicked.connect(dlg.reject)
        save.clicked.connect(dlg.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        lay.addLayout(buttons)
        if dlg.exec_() != QDialog.Accepted:
            return
        label = name.text().strip()
        if not label:
            QMessageBox.warning(self, 'Department', 'Enter a department name.')
            return
        res = self.p.api.save_department(label) or {}
        if res.get('error'):
            QMessageBox.warning(self, 'Department', res['error'])
            return
        self.refresh()
        if res.get('id') is not None:
            self._dept.set_value(res.get('id'))

    def _taken_text(self):
        try:
            return (self._taken.text() or '').strip()
        except Exception:
            return ''

    def _add_selected(self):
        item = self._prod_list.currentItem()
        if item:
            self._add_product(item.data(Qt.UserRole), qty=float(self._qty_add.value()))
            self._qty_add.setValue(1.0)
        else:
            QMessageBox.information(
                self, 'Select Product',
                'Choose a product from the search results first.')

    def _add_from_list(self, item):
        if item:
            self._add_product(item.data(Qt.UserRole), qty=float(self._qty_add.value()))
            self._qty_add.setValue(1.0)

    def _add_top_result(self):
        if self._prod_list.count() == 0:
            return
        item = self._prod_list.currentItem() or self._prod_list.item(0)
        self._add_from_list(item)

    def _add_product(self, prod, qty=1.0):
        if not prod:
            return
        pid = prod.get('id')
        stock = _safe_float(prod.get('stock'), 0)
        if stock <= 0:
            QMessageBox.warning(
                self, 'Out of Stock',
                f"{prod.get('name')} has no stock available.")
            return
        for line in self._lines:
            if line['product_id'] == pid:
                QMessageBox.information(
                    self, 'Already Added',
                    f"{prod.get('name')} is already on this consumption.\n"
                    f"Edit the quantity in the table instead.")
                return
        qty = max(0.001, float(qty or 1.0))
        if qty > stock + 1e-9:
            QMessageBox.warning(
                self, 'Insufficient Stock',
                f"{prod.get('name')}: only {_fmt_qty(stock)} available.\n"
                f"Cannot add {_fmt_qty(qty)}.")
            return
        cost = _safe_float(prod.get('cost_price'), 0)
        self._lines.append({
            'product_id': pid,
            'product_name': prod.get('name') or '',
            'quantity': qty,
            'unit': prod.get('unit') or 'pcs',
            'unit_cost': cost,
            'stock': stock,
        })
        self._rebuild_table()

    def _rebuild_table(self):
        cur = _currency(self.p._cfg())
        self._tbl.setRowCount(0)
        total = 0.0
        for i, line in enumerate(self._lines):
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, tbl_item(line['product_name']))
            self._tbl.setItem(i, 1, tbl_center(_fmt_qty(line.get('stock')), C['muted']))
            self._tbl.setItem(i, 2, tbl_center(line.get('unit') or 'pcs'))

            max_stock = max(0.001, float(line.get('stock') or 0))
            qty_edit = _table_entry(f"{float(line['quantity']):.3f}")
            qty_edit.setToolTip(f"Max {_fmt_qty(max_stock)} {line.get('unit') or 'pcs'} on hand")
            qty_edit.editingFinished.connect(lambda idx=i, box=qty_edit: self._commit_qty(idx, box))
            self._tbl.setCellWidget(i, 3, qty_edit)

            cost_edit = _table_entry(f"{cur} {float(line['unit_cost']):,.2f}")
            cost_edit.editingFinished.connect(lambda idx=i, box=cost_edit: self._commit_cost(idx, box))
            self._tbl.setCellWidget(i, 4, cost_edit)

            line_tot = float(line['quantity']) * float(line['unit_cost'])
            total += line_tot
            self._tbl.setItem(i, 5, tbl_right(f"{cur} {line_tot:,.2f}", C['gold']))

            rm = QPushButton('Remove')
            rm.setCursor(Qt.PointingHandCursor)
            rm.setMinimumSize(84, 32)
            rm.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            rm.setToolTip('Remove line')
            rm.setStyleSheet(
                f"QPushButton {{ background:{C['card2']}; color:{C['text']}; "
                f"border:1px solid {C['border2']}; border-radius:8px; "
                f"font-size:12px; font-weight:700; padding:0 8px; }}"
                f"QPushButton:hover {{ border-color:{C['gold']}; color:{C['gold']}; }}"
            )
            rm.clicked.connect(lambda _, idx=i: self._remove_line(idx))
            self._tbl.setCellWidget(i, 6, rm)
            # Cell widgets can shrink Fusion rows below defaultSectionSize — lock height
            self._tbl.setRowHeight(i, LINE_ROW_H)

        groups = _qty_by_unit(self._lines)
        grouped = '  ·  '.join(f"{_fmt_qty(amount)} {unit}" for unit, amount in groups.items())
        self._total_lbl.setText(
            f"{len(self._lines)} products"
            + (f"  ·  {grouped}" if grouped else "")
            + f"  ·  Stock cost {cur} {total:,.2f}"
        )
        apply_table_row_backgrounds(self._tbl)

    def _commit_qty(self, idx, edit):
        if not (0 <= idx < len(self._lines)):
            return
        line = self._lines[idx]
        previous = float(line['quantity'])
        try:
            val = _parse_decimal(edit.text())
        except ValueError:
            edit.setText(f"{previous:.3f}")
            return
        stock = float(line.get('stock') or 0)
        if val <= 0:
            edit.setText(f"{previous:.3f}")
            return
        if val > stock + 1e-9:
            QMessageBox.warning(
                self, 'Insufficient Stock',
                f"{line['product_name']}: only {_fmt_qty(stock)} available.")
            val = stock
        line['quantity'] = float(val)
        shown = f"{val:.3f}"
        if edit.text() != shown:
            edit.setText(shown)
        self._refresh_totals_only()

    def _commit_cost(self, idx, edit):
        if not (0 <= idx < len(self._lines)):
            return
        line = self._lines[idx]
        cur = _currency(self.p._cfg())
        previous = float(line['unit_cost'])
        try:
            val = _parse_decimal(edit.text())
        except ValueError:
            edit.setText(f"{cur} {previous:,.2f}")
            return
        if val < 0:
            edit.setText(f"{cur} {previous:,.2f}")
            return
        line['unit_cost'] = float(val)
        shown = f"{cur} {val:,.2f}"
        if edit.text() != shown:
            edit.setText(shown)
        self._refresh_totals_only()

    def _on_qty(self, idx, val):
        if 0 <= idx < len(self._lines):
            stock = float(self._lines[idx].get('stock') or 0)
            if val > stock + 1e-9:
                QMessageBox.warning(
                    self, 'Insufficient Stock',
                    f"{self._lines[idx]['product_name']}: only {_fmt_qty(stock)} available.")
                # Clamp via spin already, but sync line
                val = stock
            self._lines[idx]['quantity'] = float(val)
            self._refresh_totals_only()

    def _on_cost(self, idx, val):
        if 0 <= idx < len(self._lines):
            self._lines[idx]['unit_cost'] = float(val)
            self._refresh_totals_only()

    def _refresh_totals_only(self):
        cur = _currency(self.p._cfg())
        total = 0.0
        for i, line in enumerate(self._lines):
            line_tot = float(line['quantity']) * float(line['unit_cost'])
            total += line_tot
            self._tbl.setItem(i, 5, tbl_right(f"{cur} {line_tot:,.2f}", C['gold']))
        groups = _qty_by_unit(self._lines)
        grouped = '  ·  '.join(f"{_fmt_qty(amount)} {unit}" for unit, amount in groups.items())
        self._total_lbl.setText(
            f"{len(self._lines)} products"
            + (f"  ·  {grouped}" if grouped else "")
            + f"  ·  Stock cost {cur} {total:,.2f}"
        )

    def _remove_line(self, idx):
        if 0 <= idx < len(self._lines):
            self._lines.pop(idx)
            self._rebuild_table()

    def _clear_form(self):
        from desktop.utils.state_reset import StateResetManager
        StateResetManager.reset_consumption(self)

    def _save(self):
        if not require_permission(self.p.user, 'consumption.create', self):
            return
        if not self._lines:
            QMessageBox.warning(self, 'Required', 'Add at least one product line.')
            return
        dept_id = self._dept.current_value()
        if not dept_id:
            QMessageBox.warning(self, 'Required', 'Select a department.')
            return
        if not self._reason.is_valid():
            QMessageBox.warning(self, 'Required', self._reason.validation_error())
            return
        for line in self._lines:
            if float(line['quantity']) <= 0:
                QMessageBox.warning(
                    self, 'Invalid Qty',
                    f"Quantity for {line['product_name']} must be greater than zero.")
                return
            if float(line['quantity']) > float(line.get('stock') or 0) + 1e-9:
                QMessageBox.warning(
                    self, 'Insufficient Stock',
                    f"{line['product_name']}: only {_fmt_qty(line.get('stock'))} available.\n"
                    f"Reduce the quantity before saving.")
                return

        import uuid
        if not getattr(self, '_client_token', ''):
            self._client_token = uuid.uuid4().hex
        payload = {
            'date': self._date.date().toString('yyyy-MM-dd'),
            'department_id': dept_id,
            'reason': self._reason.value(),
            'notes': self._notes.text().strip(),
            'taken_by': self._taken_text(),
            'client_token': self._client_token,
            'items': [
                {
                    'product_id': ln['product_id'],
                    'quantity': ln['quantity'],
                    'unit_cost': ln['unit_cost'],
                }
                for ln in self._lines
            ],
        }
        try:
            res = self.p.api.create_consumption(payload) or {}
        except Exception as e:
            QMessageBox.critical(self, 'Save Failed', str(e))
            return
        if res.get('error'):
            QMessageBox.critical(self, 'Save Failed', res['error'])
            return
        self._client_token = ''

        ref = res.get('reference_no', '')
        cur = _currency(self.p._cfg())
        try:
            from desktop.utils.audio_manager import play as _audio_play
            _audio_play('save')
        except Exception:
            pass
        QMessageBox.information(
            self, 'Consumption Saved',
            f"Reference {ref}\nTotal cost: {cur} {float(res.get('total_cost') or 0):,.2f}\n"
            f"Stock has been reduced.")
        from desktop.utils.state_reset import StateResetManager
        StateResetManager.reset_consumption(self)


# ── History ───────────────────────────────────────────────────────────────────

class _HistoryPane(QWidget):
    def __init__(self, parent_tab: ConsumptionTab):
        super().__init__()
        self.p = parent_tab
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(20, 18, 20, 18), spacing=16)
        lay.addWidget(H2('Consumption History'))
        lay.addWidget(Caption(
            'Click a row to open the receipt. Void, request void, and edit are on that receipt.'
        ))

        filters = Card()
        fl = filters.layout_h((16, 12, 16, 12), 10)
        self._preset = DatePresetSelect()
        self._preset.setMinimumWidth(160)
        self._preset.presetChanged.connect(self._on_preset)
        self._s = _make_date_edit(QDate.currentDate())
        self._e = _make_date_edit(QDate.currentDate())
        self._dept = Select(placeholder='All departments', height=CONTROL_HEIGHT)
        self._dept.setMinimumWidth(180)
        self._reason = Select(placeholder='All reasons', height=CONTROL_HEIGHT)
        self._reason.setMinimumWidth(160)
        self._reason.set_items([(r, r) for r in REASONS])
        add_labeled(fl, 'Period', self._preset, spacing=14)
        add_labeled(fl, 'From', self._s, spacing=14)
        add_labeled(fl, 'To', self._e, spacing=10)
        add_labeled(fl, 'Department', self._dept, spacing=10)
        add_labeled(fl, 'Reason', self._reason, spacing=10)
        fl.addStretch()
        run = SecondaryBtn('Refresh', CONTROL_HEIGHT)
        run.clicked.connect(self.refresh)
        fl.addWidget(run)
        lay.addWidget(filters)

        self._tbl = make_table(
            ['Date', 'Reference', 'Department', 'Reason', 'Cost', 'Status'],
            stretch_col=3, row_height=44)
        header = self._tbl.horizontalHeader()
        header.setMinimumSectionSize(56)
        for col in range(6):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        self._tbl.setTextElideMode(Qt.ElideRight)
        self._tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl.setMinimumWidth(0)
        self._tbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self._preset.setMinimumWidth(0)
        self._s.setMinimumWidth(0)
        self._e.setMinimumWidth(0)
        self._s._edit.setMinimumWidth(120)
        self._e._edit.setMinimumWidth(120)
        self._tbl.setCursor(Qt.PointingHandCursor)
        self._tbl.setToolTip('Click a row to open the consumption receipt')
        self._tbl.cellClicked.connect(self._open_from_row)
        lay.addWidget(wrap_table_card(self._tbl), 1)
        self._stats = Caption('')
        lay.addWidget(self._stats)

    def _on_preset(self, key):
        from desktop.utils.option_lists import date_range_for_preset
        if key == 'custom':
            return
        start, end = date_range_for_preset(key)
        self._s.setDate(start)
        self._e.setDate(end)
        self.refresh()

    def apply_theme(self):
        if hasattr(self._preset, 'refresh_theme'):
            self._preset.refresh_theme()
        for df in (self._s, self._e):
            if hasattr(df, 'refresh_theme'):
                df.refresh_theme()
        refresh_filter_labels(self)
        for lbl in self.findChildren(QLabel):
            if lbl.property('mbtFieldLabel'):
                lbl.setStyleSheet(
                    f"color:{C['muted']}; font-size:11px; font-weight:700; "
                    f"letter-spacing:0.6px; background:transparent; border:none;")
        retint_table_items(self._tbl)
        apply_table_row_backgrounds(self._tbl)

    def refresh(self):
        cur = _currency(self.p._cfg())
        start = self._s.date().toString('yyyy-MM-dd')
        end = self._e.date().toString('yyyy-MM-dd')
        try:
            depts = self.p.api.get_departments() or []
            self._dept.set_items(
                [(d.get('name') or '', d.get('id')) for d in depts],
                keep_selection=True,
            )
        except Exception:
            depts = []
        try:
            rows = self.p.api.get_consumptions(
                start, end,
                department_id=self._dept.current_value(),
                reason=self._reason.current_value(),
                include_voided=True,
            ) or []
        except Exception as e:
            self._stats.setText(f'  Could not load: {e}')
            return
        self._tbl.setRowCount(0)
        self._history_rows = list(rows)
        for i, r in enumerate(rows):
            self._tbl.insertRow(i)
            voided = int(r.get('voided') or 0) == 1
            dstr = str(r.get('date') or '')[:10]
            try:
                qd = QDate.fromString(dstr, 'yyyy-MM-dd')
                dstr = qd.toString(_DATE_FMT) if qd.isValid() else dstr
            except Exception:
                pass
            self._tbl.setItem(i, 0, tbl_item(dstr))
            ref = tbl_item(str(r.get('reference_no') or ''))
            ref.setToolTip(f"{r.get('item_count') or 0} lines · taken by {r.get('taken_by') or '—'}")
            self._tbl.setItem(i, 1, ref)
            self._tbl.setItem(i, 2, tbl_item(str(r.get('department_name') or '—')))
            self._tbl.setItem(i, 3, tbl_item(str(r.get('reason') or '—')))
            self._tbl.setItem(i, 4, tbl_right(
                f"{cur} {_safe_float(r.get('total_cost')):,.2f}",
                C['muted'] if voided else C['gold']))
            if voided:
                status, tone = 'Voided', C['err']
            elif r.get('void_requested'):
                status, tone = 'Requested', C['warn']
            else:
                status, tone = 'Posted', C['ok']
            self._tbl.setItem(i, 5, tbl_center(status, tone))
        apply_table_row_backgrounds(self._tbl)
        self._stats.setText(f'  {len(rows)} consumption record(s)')

    def _open_from_row(self, row, _column):
        rows = getattr(self, '_history_rows', [])
        if 0 <= row < len(rows):
            self._view(rows[row].get('id'))

    def _view(self, cid):
        detail = self.p.api.get_consumption(int(cid)) or {}
        if not detail:
            QMessageBox.warning(self, 'Receipt', 'That consumption receipt was not found.')
            return
        from desktop.utils.theme import apply_themed_dialog
        voided = int(detail.get('voided') or 0) == 1
        requested = bool(detail.get('void_requested'))
        cur = _currency(self.p._cfg())
        dlg = QDialog(self)
        dlg.setWindowTitle(str(detail.get('reference_no') or 'Internal consumption'))
        dlg.resize(980, 720)
        dlg.setMinimumSize(860, 560)
        apply_themed_dialog(dlg)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        shop = str((self.p._cfg() or {}).get('shop_name') or '').strip()
        if shop:
            shop_lbl = QLabel(shop)
            shop_lbl.setStyleSheet('font-size:16px; font-weight:800;')
            layout.addWidget(shop_lbl)
        kicker = QLabel('INTERNAL CONSUMPTION')
        kicker.setStyleSheet(f"color:{C['gold']}; font-size:11px; font-weight:700; letter-spacing:0.6px;")
        layout.addWidget(kicker)
        title = QLabel(str(detail.get('reference_no') or 'Receipt'))
        title.setStyleSheet('font-size:20px; font-weight:800;')
        layout.addWidget(title)
        if voided:
            status = 'Voided'
        elif requested:
            status = 'Void requested'
        else:
            status = 'Posted'
        meta = QLabel(
            f"{status}   ·   {str(detail.get('created_at') or detail.get('date') or '—').replace('T', ' ')[:19]}\n"
            f"{detail.get('created_by_name') or '—'}   ·   {detail.get('department_name') or '—'}\n"
            f"Taken by {detail.get('taken_by') or '—'}   ·   {detail.get('reason') or '—'}"
        )
        meta.setWordWrap(True)
        layout.addWidget(meta)
        note = QLabel('This is stock used by the business. It is not a customer sale and has no payment.')
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['text2']};")
        layout.addWidget(note)
        items = list(detail.get('items') or [])
        table = QTableWidget(len(items), 8)
        table.setHorizontalHeaderLabels([
            'Product', 'SKU', 'Qty', 'Unit', 'Unit cost', 'Line cost', 'Before', 'After',
        ])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setShowGrid(False)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setMinimumSectionSize(72)
        for column, width in ((1, 110), (2, 80), (3, 70), (4, 120), (5, 120), (6, 90), (7, 90)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            table.setColumnWidth(column, width)
        cost_total = 0.0
        for index, item in enumerate(items):
            try:
                cost_total += float(item.get('total_cost') or 0)
            except (TypeError, ValueError):
                pass
            before = item.get('stock_before')
            after = item.get('stock_after')
            values = [
                item.get('product_name') or 'Product',
                item.get('sku') or '—',
                _fmt_qty(item.get('quantity')),
                item.get('unit') or 'pcs',
                f"{cur} {_safe_float(item.get('unit_cost')):,.2f}",
                f"{cur} {_safe_float(item.get('total_cost')):,.2f}",
                _fmt_qty(before) if before is not None else '—',
                _fmt_qty(after) if after is not None else '—',
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column >= 2 and column != 3:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(index, column, cell)
            table.setRowHeight(index, 40)
        visible_rows = min(max(len(items), 2), 8)
        table.setMinimumHeight(48 + 40 * visible_rows)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(table, 1)
        groups = _qty_by_unit(items)
        grouped = '  ·  '.join(f"{_fmt_qty(amount)} {unit}" for unit, amount in groups.items()) or '—'
        measures = QLabel(f"{len(items)} products    ·    {grouped}")
        measures.setWordWrap(True)
        layout.addWidget(measures)
        total = QLabel(f"Stock cost    {cur} {_safe_float(detail.get('total_cost') or cost_total):,.2f}")
        total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total.setStyleSheet(
            f"color:{C['gold']}; font-size:18px; font-weight:800; "
            f"background:{C['card2']}; border:1px solid {C['border']}; "
            f"border-radius:10px; padding:10px 14px;"
        )
        layout.addWidget(total)
        if detail.get('notes'):
            notes = QLabel(f"Notes: {detail.get('notes')}")
            notes.setWordWrap(True)
            layout.addWidget(notes)
        if detail.get('void_reason'):
            why = QLabel(f"Void reason: {detail.get('void_reason')}")
            why.setWordWrap(True)
            layout.addWidget(why)
        for revision in detail.get('revisions') or []:
            changed = QLabel(
                f"Correction: {revision.get('reason') or '—'} · {revision.get('edited_by_name') or '—'}"
            )
            changed.setWordWrap(True)
            layout.addWidget(changed)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        can_edit = has_permission(self.p.user, 'consumption.edit')
        can_void = has_permission(self.p.user, 'consumption.void')
        can_request = has_permission(self.p.user, 'consumption.request_void')
        if can_edit and not voided:
            edit = SecondaryBtn('Edit', 40)
            edit.clicked.connect(lambda _checked=False, i=cid: (dlg.accept(), self._edit(i)))
            actions.addWidget(edit)
        if can_void and not voided:
            void = DangerBtn('Void', 40)
            void.clicked.connect(lambda _checked=False, i=cid: (dlg.accept(), self._void(i)))
            actions.addWidget(void)
        elif can_request and not voided:
            ask = SecondaryBtn('Void requested' if requested else 'Request void', 40)
            ask.setEnabled(not requested)
            if not requested:
                ask.clicked.connect(lambda _checked=False, i=cid: (dlg.accept(), self._request_void(i)))
            actions.addWidget(ask)
        actions.addStretch(1)
        print_btn = SecondaryBtn('Print', 40)
        print_btn.clicked.connect(lambda _checked=False, payload=detail: self._print_receipt(payload))
        actions.addWidget(print_btn)
        close = SecondaryBtn('Close', 40)
        close.clicked.connect(dlg.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        dlg.exec_()

    def _print_receipt(self, detail):
        """Open the print dialog. Printing does not change stock."""
        try:
            from PyQt5.QtPrintSupport import QPrinter, QPrintDialog
        except Exception:
            QMessageBox.information(self, 'Print', 'Printing is not available on this till.')
            return
        cur = _currency(self.p._cfg())
        shop = str((self.p._cfg() or {}).get('shop_name') or 'Shop')
        lines = [
            shop,
            'INTERNAL CONSUMPTION',
            str(detail.get('reference_no') or ''),
            str(detail.get('created_at') or detail.get('date') or ''),
            f"Recorded by {detail.get('created_by_name') or '—'}",
            f"Department {detail.get('department_name') or '—'}",
            f"Taken by {detail.get('taken_by') or '—'}",
            f"Purpose {detail.get('reason') or '—'}",
            'Voided' if int(detail.get('voided') or 0) == 1 else 'Posted',
            '',
        ]
        if detail.get('notes'):
            lines.append(f"Notes {detail.get('notes')}")
            lines.append('')
        for item in detail.get('items') or []:
            lines.append(
                f"{item.get('product_name')}  {item.get('sku') or ''}  "
                f"{_fmt_qty(item.get('quantity'))} {item.get('unit') or 'pcs'}  "
                f"@ {cur} {_safe_float(item.get('unit_cost')):,.2f}  "
                f"= {cur} {_safe_float(item.get('total_cost')):,.2f}  "
                f"stock {_fmt_qty(item.get('stock_before')) if item.get('stock_before') is not None else '—'} "
                f"-> {_fmt_qty(item.get('stock_after')) if item.get('stock_after') is not None else '—'}"
            )
        groups = _qty_by_unit(detail.get('items') or [])
        lines.append('')
        lines.append('  ·  '.join(f"{_fmt_qty(amount)} {unit}" for unit, amount in groups.items()))
        lines.append(f"Stock cost {cur} {_safe_float(detail.get('total_cost')):,.2f}")
        lines.append('This is not a customer sale.')
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        document = QTextDocument()
        document.setPlainText('\n'.join(lines))
        document.print_(printer)

    def _edit(self, cid):
        if not require_permission(self.p.user, 'consumption.edit', self):
            return
        detail = self.p.api.get_consumption(int(cid)) or {}
        if not detail or int(detail.get('voided') or 0) == 1:
            QMessageBox.warning(self, 'Edit', 'A voided consumption cannot be corrected.')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Correct {detail.get('reference_no')}")
        dlg.resize(560, 420)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            'Only the quantity difference changes stock. Enter why this correction is needed.'
        ))
        spins = []
        for item in detail.get('items') or []:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{item.get('product_name')} ({item.get('unit') or 'pcs'})"))
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setSingleStep(0.25)
            spin.setRange(0.001, 1000000)
            spin.setValue(float(item.get('quantity') or 0))
            spin.setProperty('product_id', int(item.get('product_id') or 0))
            row.addWidget(spin)
            remove = SecondaryBtn('Remove', 32)
            remove.clicked.connect(lambda _, box=spin: box.setProperty('removed', True) or box.hide())
            row.addWidget(remove)
            layout.addLayout(row)
            spins.append(spin)
        reason = QLineEdit()
        reason.setPlaceholderText('Why this correction is needed')
        layout.addWidget(reason)
        buttons = QHBoxLayout()
        save = PrimaryBtn('Save correction', 36)
        cancel = SecondaryBtn('Cancel', 36)
        cancel.clicked.connect(dlg.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        def _save():
            why = reason.text().strip()
            if len(why) < 3:
                QMessageBox.warning(dlg, 'Correction', 'Enter why this consumption is being corrected.')
                return
            items = []
            for spin in spins:
                if spin.property('removed'):
                    continue
                items.append({
                    'product_id': int(spin.property('product_id') or 0),
                    'quantity': float(spin.value()),
                })
            if not items:
                QMessageBox.warning(dlg, 'Correction', 'Keep at least one product, or void the consumption.')
                return
            result = self.p.api.edit_consumption(int(cid), {
                'edit_reason': why,
                'reason': detail.get('reason') or 'Other',
                'items': items,
            }) or {}
            if result.get('error'):
                QMessageBox.critical(dlg, 'Correction', result['error'])
                return
            dlg.accept()
            QMessageBox.information(self, 'Corrected', 'Only the quantity difference was applied to stock.')
            self.refresh()

        save.clicked.connect(_save)
        dlg.exec_()

    def _void(self, cid):
        if not require_permission(self.p.user, 'consumption.void', self):
            return
        from desktop.utils.option_lists import VOID_REASONS
        reason = prompt_reason(
            self,
            title='Void Consumption',
            prompt='Reason for voiding (stock will be restored):',
            reasons=VOID_REASONS,
        )
        if not reason or not reason.strip():
            return
        try:
            res = self.p.api.void_consumption(int(cid), reason.strip()) or {}
        except Exception as e:
            QMessageBox.critical(self, 'Void Failed', str(e))
            return
        if res.get('error'):
            QMessageBox.critical(self, 'Void Failed', res['error'])
            return
        QMessageBox.information(self, 'Voided', 'Consumption voided and stock restored.')
        self.refresh()

    def _request_void(self, cid):
        if not require_permission(self.p.user, 'consumption.request_void', self):
            return
        from desktop.utils.option_lists import VOID_REASONS
        reason = prompt_reason(
            self,
            title='Request consumption void',
            prompt='Why should this internal consumption be voided? Stock stays reduced until an admin approves.',
            reasons=VOID_REASONS,
        )
        if not reason or not reason.strip():
            return
        try:
            res = self.p.api.request_consumption_void(int(cid), reason.strip()) or {}
        except Exception as e:
            QMessageBox.critical(self, 'Request failed', str(e))
            return
        if res.get('error'):
            QMessageBox.critical(self, 'Request failed', res['error'])
            return
        if res.get('duplicate'):
            QMessageBox.information(self, 'Already requested', 'This void is already waiting for an admin.')
        else:
            QMessageBox.information(
                self, 'Request sent',
                'The void request is waiting for an admin. Stock has not been restored.',
            )
        self.refresh()


# ── Report ────────────────────────────────────────────────────────────────────

class _ReportPane(QWidget):
    def __init__(self, parent_tab: ConsumptionTab):
        super().__init__()
        self.p = parent_tab
        self._last_rows = []
        self._last_totals = {}
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(20, 18, 20, 18), spacing=16)
        lay.addWidget(H2('Internal Consumption Report'))
        lay.addWidget(Caption(
            'Click a line to open that consumption receipt. Voided lines stay visible and are marked.'
        ))

        filters = Card()
        fl = filters.layout_v((16, 14, 16, 14), 12)

        date_row = QHBoxLayout()
        date_row.setSpacing(10)
        self._preset = DatePresetSelect()
        self._preset.setMinimumWidth(160)
        self._preset.presetChanged.connect(self._on_preset)
        self._s = _make_date_edit(QDate.currentDate())
        self._e = _make_date_edit(QDate.currentDate())
        add_labeled(date_row, 'Period', self._preset, spacing=14)
        add_labeled(date_row, 'From', self._s, spacing=14)
        add_labeled(date_row, 'To', self._e, spacing=10)
        date_row.addStretch()
        fl.addLayout(date_row)

        row = QHBoxLayout()
        row.setSpacing(12)
        self._dept = Select(placeholder='All departments', height=CONTROL_HEIGHT)
        self._dept.setMinimumWidth(180)
        row.addWidget(_field('Department', self._dept), 1)
        fl.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self._reason = Select()
        self._reason.setMinimumHeight(CONTROL_HEIGHT)
        self._reason.set_items(
            [('All reasons', '')] + [(r, r) for r in REASONS])
        self._user = Select(placeholder='All users', height=CONTROL_HEIGHT)
        self._user.setMinimumWidth(160)
        self._prod = Select(placeholder='All products', height=CONTROL_HEIGHT)
        self._prod.setMinimumWidth(160)
        row2.addWidget(_field('Reason', self._reason), 1)
        row2.addWidget(_field('User', self._user), 1)
        row2.addWidget(_field('Product', self._prod), 1)
        fl.addLayout(row2)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch()
        run = PrimaryBtn('Run Report', CONTROL_HEIGHT)
        run.clicked.connect(self.refresh)
        self._exp = SecondaryBtn('Export Excel', CONTROL_HEIGHT)
        self._exp.clicked.connect(self._export)
        if not has_permission(self.p.user, 'consumption.export'):
            self._exp.setEnabled(False)
        actions.addWidget(run)
        actions.addWidget(self._exp)
        actions.addSpacing(72)
        fl.addLayout(actions)
        lay.addWidget(filters)

        self._tbl = make_table(
            ['Date', 'Reference', 'Product', 'Qty', 'Cost', 'Status'],
            stretch_col=2, row_height=40)
        header = self._tbl.horizontalHeader()
        header.setMinimumSectionSize(56)
        for col in range(6):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        self._tbl.setTextElideMode(Qt.ElideRight)
        self._tbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tbl.setMinimumWidth(0)
        self._tbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self._tbl.setCursor(Qt.PointingHandCursor)
        self._tbl.setToolTip('Click a line to open the consumption receipt')
        self._tbl.cellClicked.connect(self._open_line)
        lay.addWidget(wrap_table_card(self._tbl), 1)

        self._footer = Caption('')
        self._footer.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
        lay.addWidget(self._footer)

    def _on_preset(self, key):
        from desktop.utils.option_lists import date_range_for_preset
        if key == 'custom':
            return
        start, end = date_range_for_preset(key)
        self._s.setDate(start)
        self._e.setDate(end)
        self.refresh()

    def apply_theme(self):
        retint_table_items(self._tbl)
        apply_table_row_backgrounds(self._tbl)
        refresh_filter_labels(self)
        self._footer.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
        for w in (self._preset, self._dept, self._reason, self._user, self._prod):
            if hasattr(w, 'refresh_theme'):
                w.refresh_theme()
        for df in (self._s, self._e):
            if hasattr(df, 'refresh_theme'):
                df.refresh_theme()
        for lbl in self.findChildren(QLabel):
            if lbl.property('mbtFieldLabel'):
                lbl.setStyleSheet(
                    f"color:{C['muted']}; font-size:11px; font-weight:700; "
                    f"letter-spacing:0.6px; background:transparent; border:none;")

    def _load_filter_options(self):
        cur_dept = self._dept.current_value()
        items = []
        try:
            for d in (self.p.api.get_departments() or []):
                items.append((d.get('name') or '', d.get('id')))
        except Exception:
            pass
        self._dept.set_items(items)
        if cur_dept is not None:
            self._dept.set_value(cur_dept)

        cur_user = self._user.current_value()
        uitems = []
        try:
            users = self.p.api.get_users() or []
            for u in users:
                label = u.get('full_name') or u.get('username') or str(u.get('id'))
                uitems.append((label, u.get('id')))
        except Exception:
            pass
        self._user.set_items(uitems)
        if cur_user is not None:
            self._user.set_value(cur_user)

        cur_prod = self._prod.current_value()
        pitems = []
        try:
            for p in (self.p.api.get_products() or []):
                pitems.append((p.get('name') or '', p.get('id')))
        except Exception:
            pass
        self._prod.set_items(pitems)
        if cur_prod is not None:
            self._prod.set_value(cur_prod)

    def refresh(self):
        if not has_permission(self.p.user, 'consumption.view_report'):
            self._footer.setText('  You do not have permission to view this report.')
            self._tbl.setRowCount(0)
            return
        self._load_filter_options()
        cur = _currency(self.p._cfg())
        start = self._s.date().toString('yyyy-MM-dd')
        end = self._e.date().toString('yyyy-MM-dd')
        try:
            data = self.p.api.get_consumption_report(
                start, end,
                department_id=self._dept.current_value(),
                user_id=self._user.current_value(),
                product_id=self._prod.current_value(),
                reason=self._reason.current_value() or None,
                include_voided=True,
            ) or {}
        except Exception as e:
            self._footer.setText(f'  Error: {e}')
            return
        rows = data.get('rows') or []
        totals = data.get('totals') or {}
        self._last_rows = rows
        self._last_totals = totals

        self._tbl.setRowCount(0)
        for i, r in enumerate(rows):
            self._tbl.insertRow(i)
            voided = int(r.get('voided') or 0) == 1
            dstr = str(r.get('date') or '')[:10]
            try:
                qd = QDate.fromString(dstr, 'yyyy-MM-dd')
                dstr = qd.toString(_DATE_FMT) if qd.isValid() else dstr
            except Exception:
                pass
            self._tbl.setItem(i, 0, tbl_item(dstr))
            self._tbl.setItem(i, 1, tbl_item(str(r.get('reference_no') or '')))
            product = tbl_item(str(r.get('product_name') or ''))
            product.setToolTip(
                f"{r.get('department_name') or '—'}\n"
                f"{r.get('reason') or '—'}\n"
                f"Taken by {r.get('taken_by') or '—'}\n"
                f"{r.get('created_by_name') or '—'}"
            )
            self._tbl.setItem(i, 2, product)
            self._tbl.setItem(i, 3, tbl_center(_fmt_qty(r.get('quantity'))))
            self._tbl.setItem(i, 4, tbl_right(
                f"{cur} {_safe_float(r.get('total_cost')):,.2f}",
                C['muted'] if voided else C['gold']))
            self._tbl.setItem(i, 5, tbl_center(
                'Voided' if voided else 'Posted',
                C['err'] if voided else C['ok']))
        apply_table_row_backgrounds(self._tbl)
        posted_cost = sum(
            _safe_float(r.get('total_cost')) for r in rows
            if int(r.get('voided') or 0) != 1
        )
        self._footer.setText(
            f"  {int(totals.get('line_count') or 0)} lines  ·  "
            f"{int(totals.get('consumption_count') or 0)} consumptions  ·  "
            f"Qty {_fmt_qty(totals.get('total_qty'))}  ·  "
            f"Posted cost {cur} {posted_cost:,.2f}  ·  "
            f"Including voided {cur} {_safe_float(totals.get('total_cost')):,.2f}"
        )

    def _open_line(self, row, _column):
        rows = getattr(self, '_last_rows', [])
        if 0 <= row < len(rows):
            self.p._history._view(rows[row].get('consumption_id'))

    def _export(self):
        if not require_permission(self.p.user, 'consumption.export', self):
            return
        if not self._last_rows:
            QMessageBox.information(self, 'Export', 'Run the report first.')
            return

        cur = _currency(self.p._cfg())
        shop = (self.p._cfg() or {}).get('shop_name', 'My Shop')
        start = self._s.date().toString('yyyy-MM-dd')
        end = self._e.date().toString('yyyy-MM-dd')
        user = self.p.user.get('user') or self.p.user
        who = user.get('full_name') or user.get('username') or 'admin'

        try:
            from backend.report_export_service import export_consumption_report
            path = export_consumption_report(
                self._last_rows,
                shop_name=shop,
                start_date=start,
                end_date=end,
                currency=cur,
                generated_by=who,
                filters=f'Date range {start} to {end}',
                totals=self._last_totals or {},
            )
        except Exception as e:
            QMessageBox.critical(self, 'Export Failed', str(e))
            return
        QMessageBox.information(
            self, 'Exported',
            f'Report saved ({cur}):\n{path}')
        try:
            os.startfile(path)
        except Exception:
            pass
