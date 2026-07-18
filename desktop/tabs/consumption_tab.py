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

from desktop.utils.theme import C, qss_alpha, RADIUS
from desktop.utils.widgets import (
    Card, H2, H3, Caption, PrimaryBtn, SecondaryBtn, DangerBtn, GhostBtn,
    Badge, SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout,
    lovable_tab_qss, wrap_table_card, retint_table_items, apply_table_row_backgrounds,
)
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
    f = _safe_float(v, 0)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:g}"


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
        self._edit.setFocus(Qt.MouseFocusReason)
        QApplication.sendEvent(
            self._edit,
            QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.AltModifier))
        QApplication.sendEvent(
            self._edit,
            QKeyEvent(QEvent.KeyRelease, Qt.Key_Down, Qt.AltModifier))

    def date(self):
        return self._edit.date()

    def setDate(self, d):
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


def _style_table_spin(spin):
    """Theme-safe spin for table cells — no up/down chrome (avoids light-mode gray blocks)."""
    r = RADIUS.get('md', 8)
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setStyleSheet(
        f"QDoubleSpinBox {{"
        f"background:{C['input']}; color:{C['text']};"
        f"border:1px solid {C['border']}; border-radius:{r}px;"
        f"padding:4px 8px; }}"
        f"QDoubleSpinBox:focus {{ border-color:{C['gold']}; }}")


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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        body = QWidget()
        body.setStyleSheet('background:transparent; border:none;')
        lay, _ = page_layout(body, margins=(28, 24, 28, 12), spacing=18)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # Header
        lay.addWidget(H2('Internal Consumption'))
        lay.addWidget(Caption(
            'Remove stock for production, staff use, cleaning, and other internal needs. '
            'No sale receipt is created.'))

        # ── Details section (clean spacing, no cell grid) ──
        details = Card()
        fl = details.layout_v((22, 18, 22, 18), 16)
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

        row2 = QHBoxLayout()
        row2.setSpacing(16)
        self._dept = SearchableSelect(placeholder='Select department…')
        self._dept.setMinimumHeight(CONTROL_HEIGHT)
        self._reason = ReasonSelect(reasons=REASONS, height=CONTROL_HEIGHT)
        self._taken = SearchableSelect(placeholder='Search staff or type name…')
        self._taken.setMinimumHeight(CONTROL_HEIGHT)
        self._staff_mode = True
        row2.addWidget(_field('Department', self._dept), 1)
        row2.addWidget(_field('Reason', self._reason), 1)
        row2.addWidget(_field('Taken By', self._taken), 1)
        fl.addLayout(row2)

        self._notes = QPlainTextEdit()
        self._notes.setObjectName('mbtNotes')
        self._notes.setPlaceholderText('Optional notes…')
        self._notes.setMinimumHeight(72)
        self._notes.setMaximumHeight(96)
        fl.addWidget(_field('Notes', self._notes))
        lay.addWidget(details)

        # ── Line items ──
        lines_card = Card()
        ll = lines_card.layout_v((22, 18, 22, 18), 12)
        ll.addWidget(H3('Line Items'))

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
        self._qty_add.setFixedWidth(100)
        self._qty_add.setToolTip('Quantity to add')
        _style_table_spin(self._qty_add)
        add_btn = SecondaryBtn('+ Add', CONTROL_HEIGHT)
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(self._add_selected)
        add_row.addWidget(self._search, 1)
        add_row.addWidget(self._qty_add)
        add_row.addWidget(add_btn)
        ll.addLayout(add_row)

        self._prod_list = QListWidget()
        self._prod_list.setObjectName('mbtConsProdList')
        self._prod_list.setMaximumHeight(132)
        self._prod_list.setMinimumHeight(88)
        self._prod_list.itemDoubleClicked.connect(self._add_from_list)
        self._prod_list.itemActivated.connect(self._add_from_list)
        ll.addWidget(self._prod_list)
        self._style_prod_list()

        hint = Caption(
            'Search, select a product, set qty, then Add — Enter adds the top/selected result.')
        ll.addWidget(hint)

        self._tbl = make_table(
            ['Product', 'Stock', 'Qty', 'Unit Cost', 'Total Cost', ''],
            stretch_col=0, row_height=44)
        for col, w in ((1, 70), (2, 100), (3, 120), (4, 120), (5, 56)):
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
        ll.addWidget(self._tbl)
        lay.addWidget(lines_card)
        lay.addStretch()

        # ── Sticky footer ──
        foot_wrap = QFrame()
        foot_wrap.setObjectName('mbtConsFooter')
        foot_lay = QHBoxLayout(foot_wrap)
        foot_lay.setContentsMargins(28, 12, 28, 16)
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

    def _style_footer(self):
        r = RADIUS.get('xl', 12)
        self.findChild(QFrame, 'mbtConsFooter').setStyleSheet(
            f"QFrame#mbtConsFooter {{"
            f"background:{C['card']}; border:none;"
            f"border-top:1px solid {C['border']}; }}")
        self._total_lbl.setStyleSheet(
            f"color:{C['gold']}; font-size:16px; font-weight:800; "
            f"background:transparent; border:none;")

    def _style_notes(self):
        r = RADIUS.get('md', 8)
        self._notes.setStyleSheet(
            f"QPlainTextEdit#mbtNotes {{"
            f"background:{C['input']}; color:{C['text']};"
            f"border:1px solid {C['border2']}; border-radius:{r}px;"
            f"padding:8px 10px; font-size:13px; }}"
            f"QPlainTextEdit#mbtNotes:focus {{ border-color:{C['gold']}; }}")

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

    def _load_staff(self):
        """Populate Taken By from users when available; keep free-type via editable select."""
        cur_text = ''
        try:
            if self._taken.lineEdit():
                cur_text = self._taken.lineEdit().text().strip()
            elif hasattr(self._taken, 'current_label'):
                cur_text = self._taken.current_label() or ''
        except Exception:
            pass
        items = []
        try:
            users = self.p.api.get_users() or []
            for u in users:
                if int(u.get('is_active', 1) or 1) != 1:
                    continue
                label = (u.get('full_name') or u.get('username') or '').strip()
                if label:
                    items.append((label, label))
        except Exception:
            items = []
        # Always include current user
        try:
            me = self.p.user.get('user') or self.p.user
            me_name = (me.get('full_name') or me.get('username') or '').strip()
            if me_name and me_name not in [x[0] for x in items]:
                items.insert(0, (me_name, me_name))
        except Exception:
            pass
        self._taken.set_items(items)
        if cur_text:
            if not self._taken.set_value(cur_text) and self._taken.lineEdit():
                self._taken.lineEdit().setText(cur_text)

    def _style_prod_list(self):
        r = RADIUS.get('md', 8)
        self._prod_list.setStyleSheet(
            f"QListWidget#mbtConsProdList {{"
            f"background:{C['input']}; color:{C['text']};"
            f"border:1px solid {C['border']}; border-radius:{r}px;"
            f"outline:0; padding:4px; }}"
            f"QListWidget#mbtConsProdList::item {{"
            f"padding:8px 10px; border-radius:6px; margin:1px 2px; }}"
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
            if q and q not in name.lower() and q not in sku.lower():
                continue
            stock = _fmt_qty(p.get('stock'))
            item = QListWidgetItem(f"{name}  ·  stock {stock}" + (f"  ·  {sku}" if sku else ''))
            item.setData(Qt.UserRole, p)
            self._prod_list.addItem(item)
            shown += 1
            if shown >= 40:
                break
        if shown and self._prod_list.currentRow() < 0:
            self._prod_list.setCurrentRow(0)

    def apply_theme(self):
        self._style_footer()
        self._style_notes()
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
                if isinstance(w, QDoubleSpinBox):
                    _style_table_spin(w)
        retint_table_items(self._tbl)
        apply_table_row_backgrounds(self._tbl)

    def _taken_text(self):
        try:
            if self._taken.lineEdit():
                t = self._taken.lineEdit().text().strip()
                if t:
                    return t
            v = self._taken.current_value()
            if v:
                return str(v)
            return (self._taken.current_label() or '').strip()
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

            qty_spin = QDoubleSpinBox()
            max_stock = max(0.001, float(line.get('stock') or 0))
            qty_spin.setRange(0.001, max_stock)
            qty_spin.setDecimals(3)
            qty_spin.setValue(min(float(line['quantity']), max_stock))
            qty_spin.setMinimumHeight(32)
            qty_spin.setToolTip(f"Max {_fmt_qty(max_stock)} (on hand)")
            _style_table_spin(qty_spin)
            qty_spin.valueChanged.connect(lambda v, idx=i: self._on_qty(idx, v))
            self._tbl.setCellWidget(i, 2, qty_spin)

            cost_spin = QDoubleSpinBox()
            cost_spin.setRange(0, 1_000_000_000)
            cost_spin.setDecimals(2)
            cost_spin.setPrefix(f'{cur} ')
            cost_spin.setValue(float(line['unit_cost']))
            cost_spin.setMinimumHeight(32)
            _style_table_spin(cost_spin)
            cost_spin.valueChanged.connect(lambda v, idx=i: self._on_cost(idx, v))
            self._tbl.setCellWidget(i, 3, cost_spin)

            line_tot = float(line['quantity']) * float(line['unit_cost'])
            total += line_tot
            self._tbl.setItem(i, 4, tbl_right(f"{cur} {line_tot:,.2f}", C['gold']))

            rm = GhostBtn('✕', 32)
            rm.setFixedWidth(44)
            rm.setToolTip('Remove line')
            rm.clicked.connect(lambda _, idx=i: self._remove_line(idx))
            self._tbl.setCellWidget(i, 5, rm)

        self._total_lbl.setText(f'Total Cost Used: {cur} {total:,.2f}')
        apply_table_row_backgrounds(self._tbl)

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
            self._tbl.setItem(i, 4, tbl_right(f"{cur} {line_tot:,.2f}", C['gold']))
        self._total_lbl.setText(f'Total Cost Used: {cur} {total:,.2f}')

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

        payload = {
            'date': self._date.date().toString('yyyy-MM-dd'),
            'department_id': dept_id,
            'reason': self._reason.value(),
            'notes': self._notes.toPlainText().strip(),
            'taken_by': self._taken_text(),
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
        lay, _ = page_layout(self, margins=(28, 24, 28, 24), spacing=14)
        lay.addWidget(H2('Consumption History'))
        lay.addWidget(Caption('Posted consumptions — void to restore stock.'))

        filters = Card()
        fl = filters.layout_h((16, 12, 16, 12), 10)
        self._preset = DatePresetSelect()
        self._preset.setMinimumWidth(160)
        self._preset.presetChanged.connect(self._on_preset)
        self._s = _make_date_edit(QDate.currentDate().addDays(-30))
        self._e = _make_date_edit(QDate.currentDate())
        add_labeled(fl, 'Period', self._preset, spacing=14)
        add_labeled(fl, 'From', self._s, spacing=14)
        add_labeled(fl, 'To', self._e, spacing=10)
        fl.addStretch()
        run = SecondaryBtn('Refresh', CONTROL_HEIGHT)
        run.clicked.connect(self.refresh)
        fl.addWidget(run)
        lay.addWidget(filters)

        self._tbl = make_table(
            ['Date', 'Reference', 'Department', 'Reason', 'Taken By',
             'Lines', 'Total Cost', 'By', 'Status', ''],
            stretch_col=2, row_height=44)
        for col, w in ((0, 110), (1, 110), (3, 140), (4, 110), (5, 60),
                       (6, 110), (7, 100), (8, 80), (9, 90)):
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
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
            rows = self.p.api.get_consumptions(start, end, include_voided=True) or []
        except Exception as e:
            self._stats.setText(f'  Could not load: {e}')
            return
        self._tbl.setRowCount(0)
        can_void = has_permission(self.p.user, 'consumption.void')
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
            self._tbl.setItem(i, 2, tbl_item(str(r.get('department_name') or '')))
            self._tbl.setItem(i, 3, tbl_item(str(r.get('reason') or '')))
            self._tbl.setItem(i, 4, tbl_item(str(r.get('taken_by') or '—')))
            self._tbl.setItem(i, 5, tbl_center(str(r.get('item_count') or 0)))
            self._tbl.setItem(i, 6, tbl_right(
                f"{cur} {_safe_float(r.get('total_cost')):,.2f}",
                C['muted'] if voided else C['gold']))
            self._tbl.setItem(i, 7, tbl_item(str(r.get('created_by_name') or '')))
            self._tbl.setItem(i, 8, tbl_center(
                'Voided' if voided else 'Posted',
                C['err'] if voided else C['ok']))
            if can_void and not voided:
                vb = DangerBtn('Void', 32)
                vb.clicked.connect(lambda _, cid=r.get('id'): self._void(cid))
                self._tbl.setCellWidget(i, 9, vb)
            else:
                self._tbl.setItem(i, 9, tbl_center('—', C['muted']))
        apply_table_row_backgrounds(self._tbl)
        self._stats.setText(f'  {len(rows)} consumption record(s)')

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


# ── Report ────────────────────────────────────────────────────────────────────

class _ReportPane(QWidget):
    def __init__(self, parent_tab: ConsumptionTab):
        super().__init__()
        self.p = parent_tab
        self._last_rows = []
        self._last_totals = {}
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(28, 24, 28, 24), spacing=14)
        lay.addWidget(H2('Internal Consumption Report'))
        lay.addWidget(Caption('Filter, review, and export consumption cost by period.'))

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
        self._dept = SearchableSelect(placeholder='Search department…')
        self._dept.setMinimumHeight(CONTROL_HEIGHT)
        row.addWidget(_field('Department', self._dept), 1)
        fl.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self._reason = Select()
        self._reason.setMinimumHeight(CONTROL_HEIGHT)
        self._reason.set_items(
            [('All reasons', '')] + [(r, r) for r in REASONS])
        self._user = SearchableSelect(placeholder='Search user…')
        self._user.setMinimumHeight(CONTROL_HEIGHT)
        self._prod = SearchableSelect(placeholder='Search product…')
        self._prod.setMinimumHeight(CONTROL_HEIGHT)
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
        fl.addLayout(actions)
        lay.addWidget(filters)

        self._tbl = make_table(
            ['Date', 'Reference', 'Department', 'Taken By', 'Reason',
             'Product', 'Qty', 'Unit Cost', 'Total Cost', 'User', 'Status'],
            stretch_col=5, row_height=40)
        for col, w in ((0, 110), (1, 100), (2, 110), (3, 100), (4, 120),
                       (6, 70), (7, 100), (8, 110), (9, 100), (10, 70)):
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
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
        items = [('All departments', None)]
        try:
            for d in (self.p.api.get_departments() or []):
                items.append((d.get('name') or '', d.get('id')))
        except Exception:
            pass
        self._dept.set_items(items)
        if cur_dept is not None:
            self._dept.set_value(cur_dept)

        cur_user = self._user.current_value()
        uitems = [('All users', None)]
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
        pitems = [('All products', None)]
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
            self._tbl.setItem(i, 2, tbl_item(str(r.get('department_name') or '')))
            self._tbl.setItem(i, 3, tbl_item(str(r.get('taken_by') or '—')))
            self._tbl.setItem(i, 4, tbl_item(str(r.get('reason') or '')))
            self._tbl.setItem(i, 5, tbl_item(str(r.get('product_name') or '')))
            self._tbl.setItem(i, 6, tbl_center(_fmt_qty(r.get('quantity'))))
            self._tbl.setItem(i, 7, tbl_right(f"{_safe_float(r.get('unit_cost')):,.2f}"))
            self._tbl.setItem(i, 8, tbl_right(
                f"{cur} {_safe_float(r.get('total_cost')):,.2f}",
                C['muted'] if voided else C['gold']))
            self._tbl.setItem(i, 9, tbl_item(str(r.get('created_by_name') or '')))
            self._tbl.setItem(i, 10, tbl_center(
                'Voided' if voided else 'OK',
                C['err'] if voided else C['ok']))
        apply_table_row_backgrounds(self._tbl)
        self._footer.setText(
            f"  {int(totals.get('line_count') or 0)} lines  ·  "
            f"{int(totals.get('consumption_count') or 0)} consumptions  ·  "
            f"Qty {_fmt_qty(totals.get('total_qty'))}  ·  "
            f"Total Cost {cur} {_safe_float(totals.get('total_cost')):,.2f}"
        )

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
