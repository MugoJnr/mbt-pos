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

from desktop.utils.theme import C, qss_alpha
from desktop.utils.widgets import (
    Card, H2, H3, Caption, PrimaryBtn, SecondaryBtn, DangerBtn, GhostBtn,
    SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout,
    lovable_tab_qss, wrap_table_card, retint_table_items, apply_table_row_backgrounds,
)
from desktop.utils.security import has_permission, require_permission
from desktop.utils.option_lists import CONSUMPTION_REASONS
from desktop.utils.select_controls import (
    Select, SearchableSelect, ReasonSelect, DatePresetSelect, prompt_reason,
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
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        body = QWidget()
        body.setStyleSheet('background:transparent;')
        lay, _ = page_layout(body, margins=(28, 24, 28, 24), spacing=16)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        lay.addWidget(H2('Internal Consumption'))
        lay.addWidget(Caption(
            'Remove stock for production, staff use, cleaning, and other internal needs. '
            'No sale receipt is created.'))

        # Header fields
        form = Card()
        fl = form.layout_v((20, 16, 20, 16), 12)

        row1 = QHBoxLayout(); row1.setSpacing(12)
        self._date = QDateEdit(QDate.currentDate())
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat('yyyy-MM-dd')
        self._date.setMinimumHeight(36)
        self._ref = QLineEdit()
        self._ref.setReadOnly(True)
        self._ref.setMinimumHeight(36)
        self._ref.setPlaceholderText('AUTO-######')
        row1.addWidget(self._field('Date', self._date), 1)
        row1.addWidget(self._field('Reference', self._ref), 1)
        fl.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(12)
        self._dept = SearchableSelect(placeholder='Select department…')
        self._dept.setMinimumHeight(36)
        self._taken = QLineEdit(); self._taken.setMinimumHeight(36)
        self._taken.setPlaceholderText('Staff name who took the items')
        self._reason = ReasonSelect(reasons=REASONS, height=36)
        row2.addWidget(self._field('Department', self._dept), 1)
        row2.addWidget(self._field('Taken By', self._taken), 1)
        row2.addWidget(self._field('Reason', self._reason), 1)
        fl.addLayout(row2)

        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText('Optional notes…')
        self._notes.setMaximumHeight(72)
        fl.addWidget(self._field('Notes', self._notes))
        lay.addWidget(form)

        # Product search + lines
        lines_card = Card()
        ll = lines_card.layout_v((20, 16, 20, 16), 10)
        ll.addWidget(H3('Line Items'))

        search_row = QHBoxLayout(); search_row.setSpacing(8)
        self._search = SearchBar('Search product by name or SKU…')
        self._search.textChanged.connect(self._filter_products)
        self._prod_list = QListWidget()
        self._prod_list.setMaximumHeight(120)
        self._prod_list.itemDoubleClicked.connect(self._add_from_list)
        add_btn = SecondaryBtn('+ Add Selected', 36)
        add_btn.clicked.connect(self._add_selected)
        search_row.addWidget(self._search, 1)
        search_row.addWidget(add_btn)
        ll.addLayout(search_row)
        ll.addWidget(self._prod_list)

        self._tbl = make_table(
            ['Product', 'Qty', 'Unit Cost', 'Total Cost', ''],
            stretch_col=0, row_height=44)
        for col, w in ((1, 90), (2, 110), (3, 120), (4, 70)):
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
        ll.addWidget(self._tbl)

        foot = QHBoxLayout()
        self._total_lbl = QLabel('Total Cost Used: —')
        self._total_lbl.setStyleSheet(
            f"color:{C['gold']}; font-size:16px; font-weight:800; background:transparent;")
        foot.addWidget(self._total_lbl)
        foot.addStretch()
        self._save_btn = PrimaryBtn('Save Consumption', 40)
        self._save_btn.clicked.connect(self._save)
        if not has_permission(self.p.user, 'consumption.create'):
            self._save_btn.setEnabled(False)
            self._save_btn.setToolTip('Your role cannot create consumptions.')
        foot.addWidget(self._save_btn)
        ll.addLayout(foot)
        lay.addWidget(lines_card)
        lay.addStretch()

    def _field(self, label, widget):
        w = QWidget()
        w.setStyleSheet('background:transparent;')
        v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(4)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color:{C['muted']}; font-size:11px; font-weight:700; "
            f"letter-spacing:0.6px; background:transparent;")
        v.addWidget(lbl)
        v.addWidget(widget)
        return w

    def refresh(self):
        try:
            self._ref.setText(self.p.api.peek_next_consumption_ref() or 'AUTO-######')
        except Exception:
            self._ref.setText('AUTO-######')
        try:
            depts = self.p.api.get_departments() or []
        except Exception:
            depts = []
        cur = self._dept.current_value()
        items = [(d.get('name') or '', d.get('id')) for d in depts]
        self._dept.set_items(items)
        if cur is not None:
            self._dept.set_value(cur)
        try:
            self._products = self.p.api.get_products() or []
        except Exception:
            self._products = []
        self._filter_products()
        self._rebuild_table()

    def apply_theme(self):
        self._total_lbl.setStyleSheet(
            f"color:{C['gold']}; font-size:16px; font-weight:800; background:transparent;")
        retint_table_items(self._tbl)
        apply_table_row_backgrounds(self._tbl)

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
            item = QListWidgetItem(f"{name}  ·  stock {stock}  ·  {sku}")
            item.setData(Qt.UserRole, p)
            self._prod_list.addItem(item)
            shown += 1
            if shown >= 40:
                break

    def _add_selected(self):
        item = self._prod_list.currentItem()
        if item:
            self._add_product(item.data(Qt.UserRole))

    def _add_from_list(self, item):
        self._add_product(item.data(Qt.UserRole))

    def _add_product(self, prod):
        if not prod:
            return
        pid = prod.get('id')
        for line in self._lines:
            if line['product_id'] == pid:
                QMessageBox.information(self, 'Already Added',
                    f"{prod.get('name')} is already on this consumption.")
                return
        cost = _safe_float(prod.get('cost_price'), 0)
        self._lines.append({
            'product_id': pid,
            'product_name': prod.get('name') or '',
            'quantity': 1.0,
            'unit_cost': cost,
            'stock': _safe_float(prod.get('stock'), 0),
        })
        self._rebuild_table()

    def _rebuild_table(self):
        cur = _currency(self.p._cfg())
        self._tbl.setRowCount(0)
        total = 0.0
        for i, line in enumerate(self._lines):
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, tbl_item(line['product_name']))

            qty_spin = QDoubleSpinBox()
            qty_spin.setRange(0.001, 1_000_000)
            qty_spin.setDecimals(3)
            qty_spin.setValue(float(line['quantity']))
            qty_spin.setMinimumHeight(32)
            qty_spin.valueChanged.connect(lambda v, idx=i: self._on_qty(idx, v))
            self._tbl.setCellWidget(i, 1, qty_spin)

            cost_spin = QDoubleSpinBox()
            cost_spin.setRange(0, 1_000_000_000)
            cost_spin.setDecimals(2)
            cost_spin.setPrefix(f'{cur} ')
            cost_spin.setValue(float(line['unit_cost']))
            cost_spin.setMinimumHeight(32)
            cost_spin.valueChanged.connect(lambda v, idx=i: self._on_cost(idx, v))
            self._tbl.setCellWidget(i, 2, cost_spin)

            line_tot = float(line['quantity']) * float(line['unit_cost'])
            total += line_tot
            self._tbl.setItem(i, 3, tbl_right(f"{cur} {line_tot:,.2f}", C['gold']))

            rm = GhostBtn('✕', 32)
            rm.setFixedWidth(40)
            rm.clicked.connect(lambda _, idx=i: self._remove_line(idx))
            self._tbl.setCellWidget(i, 4, rm)

        self._total_lbl.setText(f'Total Cost Used: {cur} {total:,.2f}')
        apply_table_row_backgrounds(self._tbl)

    def _on_qty(self, idx, val):
        if 0 <= idx < len(self._lines):
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
            self._tbl.setItem(i, 3, tbl_right(f"{cur} {line_tot:,.2f}", C['gold']))
        self._total_lbl.setText(f'Total Cost Used: {cur} {total:,.2f}')

    def _remove_line(self, idx):
        if 0 <= idx < len(self._lines):
            self._lines.pop(idx)
            self._rebuild_table()

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
                QMessageBox.warning(self, 'Invalid Qty',
                    f"Quantity for {line['product_name']} must be greater than zero.")
                return
            if float(line['quantity']) > float(line.get('stock') or 0) + 1e-9:
                QMessageBox.warning(self, 'Insufficient Stock',
                    f"{line['product_name']}: only {_fmt_qty(line.get('stock'))} available.")
                return

        payload = {
            'date': self._date.date().toString('yyyy-MM-dd'),
            'department_id': dept_id,
            'reason': self._reason.value(),
            'notes': self._notes.toPlainText().strip(),
            'taken_by': self._taken.text().strip(),
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

        bar = QHBoxLayout(); bar.setSpacing(8)
        self._s = QDateEdit(QDate.currentDate().addDays(-30))
        self._s.setCalendarPopup(True); self._s.setDisplayFormat('yyyy-MM-dd')
        self._s.setMinimumHeight(36)
        self._e = QDateEdit(QDate.currentDate())
        self._e.setCalendarPopup(True); self._e.setDisplayFormat('yyyy-MM-dd')
        self._e.setMinimumHeight(36)
        bar.addWidget(QLabel('From')); bar.addWidget(self._s)
        bar.addWidget(QLabel('To')); bar.addWidget(self._e)
        run = SecondaryBtn('Refresh', 36); run.clicked.connect(self.refresh)
        bar.addWidget(run); bar.addStretch()
        lay.addLayout(bar)

        self._tbl = make_table(
            ['Date', 'Reference', 'Department', 'Reason', 'Taken By',
             'Lines', 'Total Cost', 'By', 'Status', ''],
            stretch_col=2, row_height=44)
        for col, w in ((0, 100), (1, 110), (3, 140), (4, 110), (5, 60),
                       (6, 110), (7, 100), (8, 80), (9, 90)):
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
        lay.addWidget(wrap_table_card(self._tbl), 1)
        self._stats = Caption('')
        lay.addWidget(self._stats)

    def apply_theme(self):
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
            self._tbl.setItem(i, 0, tbl_item(str(r.get('date') or '')[:10]))
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

        filters = Card()
        fl = filters.layout_v((16, 12, 16, 12), 10)

        preset_row = QHBoxLayout(); preset_row.setSpacing(8)
        preset_row.addWidget(self._lbl('Period'))
        self._preset = DatePresetSelect()
        self._preset.setMinimumWidth(160)
        self._preset.presetChanged.connect(self._on_preset)
        preset_row.addWidget(self._preset)
        preset_row.addStretch()
        fl.addLayout(preset_row)

        row = QHBoxLayout(); row.setSpacing(8)
        self._s = QDateEdit(QDate.currentDate())
        self._s.setCalendarPopup(True); self._s.setDisplayFormat('yyyy-MM-dd')
        self._s.setMinimumHeight(36)
        self._e = QDateEdit(QDate.currentDate())
        self._e.setCalendarPopup(True); self._e.setDisplayFormat('yyyy-MM-dd')
        self._e.setMinimumHeight(36)
        self._dept = SearchableSelect(placeholder='Search department…')
        self._dept.setMinimumHeight(36)
        self._reason = Select()
        self._reason.setMinimumHeight(36)
        self._reason.set_items(
            [('All reasons', '')] + [(r, r) for r in REASONS])
        self._user = SearchableSelect(placeholder='Search user…')
        self._user.setMinimumHeight(36)
        self._prod = SearchableSelect(placeholder='Search product…')
        self._prod.setMinimumHeight(36)
        self._prod.setMinimumWidth(180)
        row.addWidget(self._lbl('From')); row.addWidget(self._s)
        row.addWidget(self._lbl('To')); row.addWidget(self._e)
        row.addWidget(self._lbl('Dept')); row.addWidget(self._dept, 1)
        fl.addLayout(row)

        row2 = QHBoxLayout(); row2.setSpacing(8)
        row2.addWidget(self._lbl('Reason')); row2.addWidget(self._reason, 1)
        row2.addWidget(self._lbl('User')); row2.addWidget(self._user, 1)
        row2.addWidget(self._lbl('Product')); row2.addWidget(self._prod, 1)
        run = PrimaryBtn('Run', 36); run.clicked.connect(self.refresh)
        row2.addWidget(run)
        self._exp = SecondaryBtn('Export Excel', 36)
        self._exp.clicked.connect(self._export)
        if not has_permission(self.p.user, 'consumption.export'):
            self._exp.setEnabled(False)
        row2.addWidget(self._exp)
        fl.addLayout(row2)
        lay.addWidget(filters)

        self._tbl = make_table(
            ['Date', 'Reference', 'Department', 'Taken By', 'Reason',
             'Product', 'Qty', 'Unit Cost', 'Total Cost', 'User', 'Status'],
            stretch_col=5, row_height=40)
        for col, w in ((0, 95), (1, 100), (2, 110), (3, 100), (4, 120),
                       (6, 70), (7, 100), (8, 110), (9, 100), (10, 70)):
            self._tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._tbl.setColumnWidth(col, w)
        lay.addWidget(wrap_table_card(self._tbl), 1)

        self._footer = Caption('')
        self._footer.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
        lay.addWidget(self._footer)

    def _lbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        return l

    def _on_preset(self, key):
        from desktop.utils.option_lists import date_range_for_preset
        if key == 'custom':
            return
        start, end = date_range_for_preset(key)
        self._s.setDate(start)
        self._e.setDate(end)
        self.refresh()

    def _quick(self, key):
        self._on_preset(key)

    def apply_theme(self):
        retint_table_items(self._tbl)
        apply_table_row_backgrounds(self._tbl)
        self._footer.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
        for w in (self._preset, self._dept, self._reason, self._user, self._prod):
            if hasattr(w, 'refresh_theme'):
                w.refresh_theme()

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
            self._tbl.setItem(i, 0, tbl_item(str(r.get('date') or '')[:10]))
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
        dept = ''
        try:
            if hasattr(self, '_dept') and self._dept.currentData():
                dept = f"Department filter applied"
        except Exception:
            pass

        try:
            from backend.report_export_service import export_consumption_report
            path = export_consumption_report(
                self._last_rows,
                shop_name=shop,
                start_date=start,
                end_date=end,
                currency=cur,
                generated_by=who,
                filters=dept or f'Date range {start} to {end}',
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
