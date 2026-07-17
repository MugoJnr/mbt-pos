"""
MBT POS — Security & Super-Admin Tab
MugoByte Technologies | mugobyte.com

Only visible to users with role='superadmin'.
Provides:
  • Super-admin PIN management
  • Stock movement audit log
  • Sale edits / void log
  • Direct stock adjustment
  • Audit log viewer
  • License remote control shortcuts
"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, qss_alpha
from desktop.utils.widgets import (PrimaryBtn, SecondaryBtn, DangerBtn, Card,
                                    make_table, tbl_item, tbl_right,
                                    tbl_center, page_layout, H2, Caption,
                                    lovable_tab_qss, Badge, section_card)
from desktop.utils.security import ask_superadmin_pin, set_superadmin_pin, verify_superadmin_pin
from desktop.utils.option_lists import STOCK_ADJUSTMENT_REASONS
from desktop.utils.select_controls import SearchableSelect, ReasonSelect


class SecurityTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────
    def _build(self):
        lay, _ = page_layout(self, margins=(24, 22, 24, 24), spacing=16)

        # Lovable status KPI strip
        kpi = QHBoxLayout(); kpi.setSpacing(12)
        for label, value, tone in (
            ('PIN Policy', 'Strong', C['ok']),
            ('Auto-Lock', 'Session', C['info']),
            ('Audit Log', 'Enabled', C['ok']),
        ):
            c = Card(); cl = c.layout_h((16, 14, 16, 14), 12)
            ic = QLabel('🔐')
            ic.setFixedSize(40, 40); ic.setAlignment(Qt.AlignCenter)
            ic.setStyleSheet(
                f"background:{qss_alpha(C['gold'], 0.13)}; color:{C['gold']}; border-radius:8px; "
                f"font-size:16px; border:none;")
            cl.addWidget(ic)
            col = QVBoxLayout(); col.setSpacing(2)
            l = QLabel(label.upper())
            l.setStyleSheet(
                f"color:{C['text2']}; font-size:10px; font-weight:700; "
                f"letter-spacing:1.5px; background:transparent;")
            v = QLabel(value)
            v.setStyleSheet(
                f"color:{C['text']}; font-size:18px; font-weight:700; background:transparent;")
            col.addWidget(l); col.addWidget(v)
            cl.addLayout(col, 1)
            cl.addWidget(Badge('OK', color=tone))
            kpi.addWidget(c)
        lay.addLayout(kpi)

        # Header warning
        warn = QFrame()
        warn.setStyleSheet(
            f"QFrame{{background:{qss_alpha(C['gold'], 0.07)};border:1px solid {qss_alpha(C['gold'], 0.25)};"
            f"border-radius:10px;}}")
        wl = QHBoxLayout(warn); wl.setContentsMargins(18, 12, 18, 12)
        wl.addWidget(QLabel('🔐'))
        info = QLabel(
            '<b>Super-Admin Security Panel</b> — '
            'Actions here are logged and irreversible. Use with care.')
        info.setStyleSheet(f"color:{C['gold']}; font-size:13px; background:transparent;")
        info.setTextFormat(Qt.RichText)
        wl.addWidget(info, 1)
        lay.addWidget(warn)

        # Tabs — Lovable gold pills
        tabs = QTabWidget()
        tabs.setProperty('mbtLovableTabs', True)
        tabs.setStyleSheet(lovable_tab_qss())
        tabs.addTab(self._build_pin_tab(),        'PIN Setup')
        tabs.addTab(self._build_stock_adj_tab(),  'Stock Adjust')
        tabs.addTab(self._build_stock_log_tab(),  'Stock Log')
        tabs.addTab(self._build_sales_edit_tab(), 'Sale Edits / Voids')
        tabs.addTab(self._build_audit_tab(),      'Full Audit Log')
        lay.addWidget(tabs, 1)

    # ── PIN Setup ─────────────────────────────────────────────────────────────
    def _build_pin_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24); lay.setSpacing(16)

        title = H2('Super-Admin PIN')
        title.setStyleSheet(f"color:{C['text']}; font-size:18px; font-weight:800;")
        lay.addWidget(title)

        desc = QLabel(
            'The Super-Admin PIN is required to:\n'
            '  •  Adjust stock quantities directly\n'
            '  •  Void or edit completed sales\n'
            '  •  Access this security panel\n'
            '  •  Override protected actions\n\n'
            'Do NOT share this PIN with cashiers or regular admins.')
        desc.setStyleSheet(f"color:{C['text2']}; font-size:13px; background:transparent;")
        lay.addWidget(desc)

        form = QFormLayout(); form.setSpacing(12)

        self._pin_current = QLineEdit(); self._pin_current.setEchoMode(QLineEdit.Password)
        self._pin_current.setMinimumHeight(42)
        self._pin_current.setPlaceholderText('Current PIN  (leave blank if not yet set)')

        self._pin_new = QLineEdit(); self._pin_new.setEchoMode(QLineEdit.Password)
        self._pin_new.setMinimumHeight(42); self._pin_new.setPlaceholderText('New PIN  (min 6 digits)')

        self._pin_confirm = QLineEdit(); self._pin_confirm.setEchoMode(QLineEdit.Password)
        self._pin_confirm.setMinimumHeight(42); self._pin_confirm.setPlaceholderText('Confirm new PIN')

        for lbl, w2 in [('Current PIN:', self._pin_current),
                         ('New PIN:', self._pin_new),
                         ('Confirm PIN:', self._pin_confirm)]:
            l = QLabel(lbl); l.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
            form.addRow(l, w2)

        lay.addLayout(form)

        btn_row = QHBoxLayout()
        save = PrimaryBtn('Set / Update PIN', 46); save.clicked.connect(self._save_pin)
        btn_row.addWidget(save); btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    def _save_pin(self):
        new  = self._pin_new.text().strip()
        conf = self._pin_confirm.text().strip()
        if len(new) < 6:
            QMessageBox.warning(self, 'Too Short', 'PIN must be at least 6 characters.'); return
        if new != conf:
            QMessageBox.warning(self, 'Mismatch', 'PIN and confirmation do not match.'); return
        cfg = self.api.get_settings() or {}
        if cfg.get('superadmin_pin_hash'):
            curr = self._pin_current.text().strip()
            if not curr:
                QMessageBox.warning(self, 'Required',
                    'Enter your current PIN to change it.'); return
            if not verify_superadmin_pin(curr, self.api, self, log_attempt=True):
                return
        if set_superadmin_pin(new, self.api):
            QMessageBox.information(self, '✓ Saved', 'Super-Admin PIN has been set.')
            self._pin_current.clear(); self._pin_new.clear(); self._pin_confirm.clear()
        else:
            QMessageBox.critical(self, 'Error', 'Failed to save PIN.')

    # ── Stock Adjustment ──────────────────────────────────────────────────────
    def _build_stock_adj_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24); lay.setSpacing(14)

        desc = QLabel(
            '⚖  Directly adjust stock levels for any product.\n'
            'Requires Super-Admin PIN. All adjustments are permanently logged.')
        desc.setStyleSheet(f"color:{C['text2']}; font-size:13px; background:transparent;")
        desc.setWordWrap(True); lay.addWidget(desc)

        form = QFormLayout(); form.setSpacing(12)
        self._adj_prod = SearchableSelect(placeholder='Search product…')
        self._adj_prod.setMinimumHeight(42)
        self._adj_qty  = QDoubleSpinBox(); self._adj_qty.setRange(0, 999999)
        self._adj_qty.setDecimals(4); self._adj_qty.setMinimumHeight(42)
        self._adj_reason = ReasonSelect(reasons=STOCK_ADJUSTMENT_REASONS, height=42)

        for lbl, w2 in [('Product:', self._adj_prod),
                         ('New Stock Qty:', self._adj_qty),
                         ('Reason:', self._adj_reason)]:
            l = QLabel(lbl); l.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
            form.addRow(l, w2)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        load = SecondaryBtn('↺  Load Products', 42)
        load.clicked.connect(self._load_products_for_adj)
        apply = PrimaryBtn('⚖  Apply Adjustment', 46)
        apply.clicked.connect(self._apply_adj)
        btn_row.addWidget(load); btn_row.addWidget(apply); btn_row.addStretch()
        lay.addLayout(btn_row)

        self._adj_result = QLabel('')
        self._adj_result.setStyleSheet(
            f"color:{C['ok']}; font-size:13px; background:transparent;")
        lay.addWidget(self._adj_result)
        lay.addStretch()
        return w

    def _load_products_for_adj(self):
        try:
            prods = self.api.get_products() or []
            self._adj_prods = {p['id']: p for p in prods}
            items = [
                (f"{p['name']}  (stock: {p['stock']})", p['id'])
                for p in prods
            ]
            self._adj_prod.set_loading(True, 'Loading products…')
            self._adj_prod.set_loading(False)
            self._adj_prod.set_items(items)
            if not items:
                self._adj_prod.set_empty_label('No products')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def _apply_adj(self):
        if not hasattr(self, '_adj_prods') or not self._adj_prods:
            QMessageBox.warning(self, 'No Products', 'Load products first.'); return
        if not self._adj_reason.is_valid():
            QMessageBox.warning(self, 'Required', self._adj_reason.validation_error()); return
        reason = self._adj_reason.value()
        pid = self._adj_prod.current_value()
        if pid is None:
            QMessageBox.warning(self, 'Required', 'Select a product.'); return
        prod = self._adj_prods.get(pid)
        if not prod:
            QMessageBox.warning(self, 'Required', 'Select a product.'); return
        new_qty = self._adj_qty.value()
        if QMessageBox.question(self, 'Confirm Adjustment',
                f"Adjust '{prod['name']}' stock:\n"
                f"  Current: {prod['stock']}\n"
                f"  New:     {new_qty}\n\n"
                f"Reason: {reason}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if not ask_superadmin_pin(self.api, self, reason='Stock Adjustment'):
            return
        res = self.api.adjust_stock(prod['id'], new_qty, reason)
        if res and res.get('success'):
            self._adj_result.setText(
                f"✓  {prod['name']}: {res['old_stock']} → {res['new_stock']}")
            self._adj_result.setStyleSheet(
                f"color:{C['ok']}; font-size:13px; background:transparent;")
            self._load_products_for_adj()
        else:
            self._adj_result.setText(f"✗  {res.get('error','Failed')}")
            self._adj_result.setStyleSheet(
                f"color:{C['err']}; font-size:13px; background:transparent;")

    # ── Stock Movement Log ────────────────────────────────────────────────────
    def _build_stock_log_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(H2('Stock Movement Log'))
        top.addStretch()
        ref = SecondaryBtn('↺ Refresh', 38); ref.clicked.connect(self._load_stock_log)
        top.addWidget(ref); lay.addLayout(top)
        self._stock_tbl = make_table(
            ['Time', 'Product', 'Type', 'Before', 'Change', 'After',
             'Reference', 'Reason', 'User'],
            stretch_col=7, row_height=36)
        for col, w2 in [(0,140),(1,160),(2,120),(3,70),(4,70),(5,70),(6,130),(8,100)]:
            self._stock_tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._stock_tbl.setColumnWidth(col, w2)
        lay.addWidget(self._stock_tbl)
        return w

    def _load_stock_log(self):
        try:
            moves = self.api.get_stock_movements(limit=300)
            self._stock_tbl.setRowCount(0)
            type_colors = {
                'SALE':             C['ok'],
                'VOID_RESTORE':     C['info'],
                'INITIAL':          C['text2'],
                'SUPERADMIN_ADJUST': C['gold'],
                'MANUAL_ADJUST':    C['warn'],
            }
            for i, m in enumerate(moves):
                self._stock_tbl.insertRow(i)
                chg = m.get('qty_change', 0)
                chg_color = C['err'] if chg < 0 else C['ok']
                typ = m.get('movement_type', '')
                self._stock_tbl.setItem(i, 0, tbl_item(
                    (m.get('created_at','') or '')[:16]))
                self._stock_tbl.setItem(i, 1, tbl_item(m.get('product_name','')))
                tc = tbl_center(typ, type_colors.get(typ, C['text2']))
                self._stock_tbl.setItem(i, 2, tc)
                self._stock_tbl.setItem(i, 3, tbl_right(str(m.get('qty_before',0))))
                self._stock_tbl.setItem(i, 4, tbl_right(
                    f"{'+' if chg>=0 else ''}{chg}", chg_color))
                self._stock_tbl.setItem(i, 5, tbl_right(str(m.get('qty_after',0))))
                self._stock_tbl.setItem(i, 6, tbl_item(m.get('reference','') or ''))
                self._stock_tbl.setItem(i, 7, tbl_item(m.get('reason','') or ''))
                self._stock_tbl.setItem(i, 8, tbl_item(m.get('username','') or ''))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    # ── Sale Edits / Voids ───────────────────────────────────────────────────
    def _build_sales_edit_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(H2('Sale Edits & Voids'))
        top.addStretch()
        ref = SecondaryBtn('↺ Refresh', 38); ref.clicked.connect(self._load_edits)
        top.addWidget(ref); lay.addLayout(top)

        # Void a sale section
        void_frame = QFrame()
        void_frame.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};"
            f"border-radius:10px;}}")
        vl = QHBoxLayout(void_frame); vl.setContentsMargins(16,10,16,10); vl.setSpacing(12)
        vl.addWidget(QLabel('Void Sale:').setStyleSheet if False else QLabel('Void Sale:'))
        self._void_receipt = QLineEdit(); self._void_receipt.setPlaceholderText(
            'Receipt number  e.g. RCP-20260520-0001')
        self._void_receipt.setMinimumHeight(38); vl.addWidget(self._void_receipt, 1)
        void_btn = DangerBtn('🗑  Void Sale', 42); void_btn.clicked.connect(self._void_sale)
        vl.addWidget(void_btn)
        lay.addWidget(void_frame)

        self._edits_tbl = make_table(
            ['Time','Sale ID','Edit Type','Field','Old Value','New Value','Reason','By'],
            stretch_col=6, row_height=36)
        lay.addWidget(self._edits_tbl)
        return w

    def _void_sale(self):
        from desktop.utils.security import prompt_void_sale
        receipt = self._void_receipt.text().strip()
        if not receipt:
            QMessageBox.warning(self, 'Required', 'Enter a receipt number.')
            return
        if prompt_void_sale(self.api, self, receipt_prefill=receipt):
            self._void_receipt.clear()
            self._load_edits()

    def _load_edits(self):
        try:
            edits = self.api.get_sale_edits()
            self._edits_tbl.setRowCount(0)
            for i, e in enumerate(edits):
                self._edits_tbl.insertRow(i)
                for j, v in enumerate([
                    (e.get('created_at','') or '')[:16],
                    str(e.get('sale_id','')),
                    e.get('edit_type',''),
                    e.get('field_name','') or '',
                    e.get('old_value','') or '',
                    e.get('new_value','') or '',
                    e.get('reason','') or '',
                    e.get('edited_by_name','') or '',
                ]):
                    self._edits_tbl.setItem(i, j, tbl_item(str(v)))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    # ── Full Audit Log ────────────────────────────────────────────────────────
    def _build_audit_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(H2('Full Audit Log'))
        top.addStretch()
        ref = SecondaryBtn('↺ Refresh', 38); ref.clicked.connect(self._load_audit)
        top.addWidget(ref); lay.addLayout(top)
        self._audit_tbl = make_table(
            ['Time', 'User', 'Action', 'Module', 'Details'],
            stretch_col=4, row_height=36)
        for col, w2 in [(0,140),(1,110),(2,160),(3,100)]:
            self._audit_tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._audit_tbl.setColumnWidth(col, w2)
        lay.addWidget(self._audit_tbl)
        return w

    def _load_audit(self):
        try:
            logs = self.api.get_audit_log()
            self._audit_tbl.setRowCount(0)
            action_colors = {
                'VOID_SALE': C['warn'], 'STOCK_ADJUSTED': C['gold'],
                'SUPERADMIN_PIN_FAIL': C['err'], 'STOCK_ADJUST_BLOCKED': C['err'],
                'INTERNAL_USE': C['info'], 'INTERNAL_USE_VOID': C['warn'],
                'CREATE_CONSUMPTION': C['info'], 'VOID_CONSUMPTION': C['warn'],
                'TAMPER_DETECT': C['err'], 'DEVICE_MISMATCH': C['err'],
                'REVOKED': C['err'], 'ACTIVATED': C['ok'],
            }
            for i, lg in enumerate(logs):
                self._audit_tbl.insertRow(i)
                action = lg.get('action', '')
                color  = action_colors.get(action, C['text'])
                self._audit_tbl.setItem(i, 0, tbl_item(
                    (lg.get('created_at','') or '')[:16]))
                self._audit_tbl.setItem(i, 1, tbl_item(lg.get('username','') or 'system'))
                self._audit_tbl.setItem(i, 2, tbl_center(action, color))
                self._audit_tbl.setItem(i, 3, tbl_item(lg.get('module','') or ''))
                self._audit_tbl.setItem(i, 4, tbl_item(lg.get('details','') or ''))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def on_show(self):
        self._load_audit()
        self._load_stock_log()
        self._load_edits()
