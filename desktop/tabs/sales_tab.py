"""MBT POS — Point of Sale  |  MugoByte Technologies"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from datetime        import datetime
from desktop.utils.theme   import C, ThemeManager, qss_alpha, RADIUS, PADDING, GAP
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, IconBtn,
                                    make_table, tbl_item, tbl_right)
from desktop.utils.pos_components import (
    ProductCard, ProductGrid, QuantityControl, PaymentSegment, SummaryCard,
    CustomerSelector, PosSearchBar, safe_price as _safe_price,
    fmt_stock_short as _fmt_stock_short, round_qty, refresh_pos_components,
)
from desktop.utils.option_lists import POS_PAYMENT_METHODS
from desktop.utils.select_controls import Select


def _sfx(event: str, **kw):
    try:
        from desktop.utils.audio_manager import play
        play(event, **kw)
    except Exception:
        pass


class _KesEdit(QLineEdit):
    """KES amount field — select-all on focus so typing 60 replaces 0.00 without sip crashes."""

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)


class SalesTab(QWidget):
    sale_completed = pyqtSignal()
    theme_changed = pyqtSignal(bool)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self.cart = []; self.products = []
        self._subtotal = self._discount = self._tax = self._total = 0.0
        self._original_total = 0.0
        self._rounding_adj = 0.0
        self._rounding_info = {}
        self._currency = 'KES'
        self._is_light  = bool(ThemeManager.is_light())
        self._last_sale_id = None
        self._last_receipt = ''
        self._printer_mgr = None
        self._credit_to_apply = 0.0
        self._wallet_by_customer = {}
        # Cash Paid smart auto-fill: once cashier edits, do not overwrite
        # until payment method change or sale reset.
        self._cash_paid_dirty = False
        self._paid_programmatic = False
        self._build()
        # Defer product grid load so MainWindow can paint first (avoids hang)
        QTimer.singleShot(400, self.refresh)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(PADDING, 18, PADDING, 18)
        root.setSpacing(GAP)

        # ── LEFT: product browser (modular ProductGrid) ───────────────────────
        self._left_panel = QFrame()
        self._left_panel.setObjectName('posProductPanel')
        self._left_panel.setStyleSheet(
            f"QFrame#posProductPanel {{ background:{C['card']}; "
            f"border:1px solid {C['border']}; border-radius:{RADIUS['xl']}px; }}")
        ll = QVBoxLayout(self._left_panel)
        ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(0)

        search_bar = QWidget()
        search_bar.setStyleSheet(
            f"background:transparent; border-bottom:1px solid {C['border']};")
        sf = QHBoxLayout(search_bar); sf.setContentsMargins(16, 14, 16, 14); sf.setSpacing(10)
        self._search = PosSearchBar()
        self._search.textChanged.connect(self._filter)
        self._search.submitted.connect(self._on_barcode_enter)
        sf.addWidget(self._search, 1)
        self._cat = QComboBox()
        self._cat.setObjectName('posCatCombo')
        self._cat.setMinimumHeight(44)
        self._cat.setFixedWidth(220)
        from desktop.utils.pos_light_theme import style_cat_combo
        style_cat_combo(self._cat, is_light=bool(getattr(self, '_is_light', False)))
        self._cat.addItem('All Categories')
        self._cat.currentTextChanged.connect(self._filter)
        sf.addWidget(self._cat)
        ref = IconBtn('↺', 40, 40); ref.clicked.connect(self.refresh); sf.addWidget(ref)
        self._refresh_btn = ref
        # Theme switch lives in the main topbar only (avoids dual-bar fight)
        self._theme_btn = None
        self._search_bar = search_bar
        ll.addWidget(search_bar)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._prod_grid = ProductGrid()
        self._prod_grid.productClicked.connect(self._add)
        self._gw = self._prod_grid  # back-compat for theme helpers
        self._grid = self._prod_grid._grid
        scroll.setWidget(self._prod_grid)
        ll.addWidget(scroll)

        self._empty = QLabel('No products.\nAdd products in Inventory.')
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(f"color:{C['muted']};font-size:14px;background:transparent;")
        self._empty.hide(); ll.addWidget(self._empty)
        root.addWidget(self._left_panel, 6)

        # ── RIGHT: checkout cart — wide enough for names + prices without clipping
        self._right_panel = QFrame()
        self._right_panel.setObjectName('posCartPanel')
        self._right_panel.setMinimumWidth(740)
        self._right_panel.setMaximumWidth(920)
        # Wide enough for Item + Qty ± + Price(1,070) + Disc("- 50.00") + Total + X
        self._right_panel.setFixedWidth(880)
        self._right_panel.setStyleSheet(
            f"QFrame#posCartPanel {{ background:{C['card']}; "
            f"border:1px solid {C['border']}; border-radius:{RADIUS['xl']}px; }}")
        rp_outer = QVBoxLayout(self._right_panel)
        rp_outer.setContentsMargins(0, 0, 0, 0)
        rp_outer.setSpacing(0)

        self._checkout_scroll = QScrollArea()
        self._checkout_scroll.setWidgetResizable(True)
        self._checkout_scroll.setFrameShape(QFrame.NoFrame)
        self._checkout_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._checkout_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        checkout = QWidget()
        checkout.setStyleSheet("background:transparent;")
        rl = QVBoxLayout(checkout)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(f"border-bottom:1px solid {C['border']};")
        self._cart_hdr = hdr
        ch = QHBoxLayout(hdr); ch.setContentsMargins(16, 14, 16, 14)
        self._sale_hdr = H2('Current Sale')
        ch.addWidget(self._sale_hdr); ch.addStretch()
        self._cnt = Caption('0 items'); ch.addWidget(self._cnt)
        rl.addWidget(hdr)

        cart_body = QWidget()
        cbl = QVBoxLayout(cart_body); cbl.setContentsMargins(16, 12, 16, 16); cbl.setSpacing(12)

        self._ctbl = make_table(['Item', 'Qty', 'Price', 'Disc', 'Total', ''],
                                stretch_col=0, row_height=56)
        # Disc = KES per line. Wide enough for stepper + value.
        hdr = self._ctbl.horizontalHeader()
        hdr.setMinimumSectionSize(40)
        self._ctbl.verticalHeader().setMinimumSectionSize(56)
        self._ctbl.setColumnWidth(0, 200)
        for ci, w in [(1, 128), (2, 90), (3, 128), (4, 92), (5, 42)]:
            hdr.setSectionResizeMode(ci, QHeaderView.Fixed)
            self._ctbl.setColumnWidth(ci, w)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        self._ctbl.setWordWrap(False)
        self._ctbl.setTextElideMode(Qt.ElideRight)
        self._ctbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Widgets own interaction — row selection paints ugly nested boxes
        self._ctbl.setAlternatingRowColors(False)
        self._ctbl.setSelectionMode(QAbstractItemView.NoSelection)
        self._ctbl.setFocusPolicy(Qt.NoFocus)
        self._ctbl.setMinimumHeight(220)
        self._ctbl.setMaximumHeight(320)
        cbl.addWidget(self._ctbl)

        # Totals (SummaryCard + KES disc edit)
        self._summary = SummaryCard()
        self._tot_frame = self._summary
        self._sub_lbl = self._summary._sub_lbl
        self._tax_lbl = self._summary._tax_lbl
        self._tot_lbl = self._summary._tot_lbl
        self._total_hdr = self._summary._total_hdr
        self._disc_lbl = self._summary.disc_label

        disc_row = QHBoxLayout(); disc_row.setContentsMargins(0, 0, 0, 0)
        self._disc_lbl.setToolTip(
            'Cart discount in KES. You can also set Disc per item in the cart table.')
        self._disc = _KesEdit()
        self._disc.setObjectName('cartDisc')
        self._disc.setText('0.00')
        self._disc.setFixedWidth(150)
        self._disc.setMinimumHeight(38)
        self._disc.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._disc.setPlaceholderText('0')
        self._disc.setToolTip('Click, type e.g. 60, press Enter')
        self._disc.setStyleSheet(
            f"QLineEdit#cartDisc{{"
            f"background:{C['input']};color:{C['text']};"
            f"border:1.5px solid {C['border2']};border-radius:8px;"
            f"padding:4px 8px;font-size:14px;font-weight:700;}}"
            f"QLineEdit#cartDisc:focus{{border-color:{C['gold']};}}"
        )
        self._disc.editingFinished.connect(self._commit_cart_disc)
        self._disc.returnPressed.connect(self._commit_cart_disc)
        self._summary.disc_edit = self._disc
        # Insert disc row before tax (index 1 is after subtotal)
        disc_row.addWidget(self._disc_lbl); disc_row.addStretch(); disc_row.addWidget(self._disc)
        self._summary._body.insertLayout(1, disc_row)
        cbl.addWidget(self._summary)

        # Payment method toggles (Cash / M-Pesa / Card) + full combo for other methods
        self._pay_seg = PaymentSegment()
        self._pay_seg.methodChanged.connect(self._select_pay_method)
        self._pay_btns = self._pay_seg._btns
        cbl.addWidget(self._pay_seg)

        # Customer for credit / debt notes
        cust_row = QHBoxLayout(); cust_row.setSpacing(8)
        self._cust_lbl = QLabel('Customer')
        self._cust_lbl.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        self._customer = CustomerSelector()
        self._customer.currentIndexChanged.connect(self._on_customer_changed)
        cust_row.addWidget(self._cust_lbl)
        cust_row.addWidget(self._customer, 1)
        cbl.addLayout(cust_row)

        # Store credit apply row (shown when customer has wallet balance)
        self._credit_frame = QFrame()
        self._credit_frame.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
        cfl = QHBoxLayout(self._credit_frame)
        cfl.setContentsMargins(10, 8, 10, 8); cfl.setSpacing(8)
        self._credit_info = QLabel('Store credit: —')
        self._credit_info.setStyleSheet(
            f"color:{C['ok']};font-size:12px;font-weight:600;background:transparent;")
        self._credit_spin = QDoubleSpinBox()
        self._credit_spin.setRange(0, 99999999)
        self._credit_spin.setDecimals(2)
        self._credit_spin.setMinimumHeight(36)
        self._credit_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._credit_spin.setPrefix('Apply ')
        self._credit_spin.valueChanged.connect(self._on_credit_apply_changed)
        self._apply_all_credit_btn = SecondaryBtn('Use All', 36)
        self._apply_all_credit_btn.setFixedWidth(80)
        self._apply_all_credit_btn.clicked.connect(self._apply_all_credit)
        cfl.addWidget(self._credit_info, 1)
        cfl.addWidget(self._credit_spin)
        cfl.addWidget(self._apply_all_credit_btn)
        self._credit_frame.hide()
        cbl.addWidget(self._credit_frame)

        pay = QHBoxLayout(); pay.setSpacing(8)
        self._pay_lbl = QLabel('Method')
        self._pay_lbl.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        self._pay = Select()
        self._pay.set_items(list(POS_PAYMENT_METHODS))
        self._pay.setMinimumHeight(44); self._pay.setMinimumWidth(140)
        self._pay.currentTextChanged.connect(self._on_payment_changed)
        self._paid = QDoubleSpinBox(); self._paid.setRange(0, 99999999)
        self._paid.setDecimals(2); self._paid.setMinimumHeight(44)
        self._paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._paid.setToolTip('Cash Paid')
        self._paid.valueChanged.connect(self._on_paid_changed)
        self._cash_paid_lbl = QLabel('Cash Paid')
        self._cash_paid_lbl.setStyleSheet(
            f"color:{C['text2']};font-size:12px;background:transparent;")
        pay.addWidget(self._pay_lbl); pay.addWidget(self._pay)
        pay.addWidget(self._cash_paid_lbl)
        pay.addWidget(self._paid, 1)
        cbl.addLayout(pay)

        # Expected / Received / Difference (M-Pesa Till variance)
        self._var_frame = QFrame()
        self._var_frame.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
        vfl = QVBoxLayout(self._var_frame)
        vfl.setContentsMargins(12, 8, 12, 8); vfl.setSpacing(4)
        self._expected_lbl = QLabel('Expected: —')
        self._received_lbl = QLabel('Received: —')
        self._diff_lbl = QLabel('Difference: —')
        for w in (self._expected_lbl, self._received_lbl, self._diff_lbl):
            w.setStyleSheet(
                f"color:{C['text2']};font-size:12px;font-weight:600;background:transparent;")
            vfl.addWidget(w)
        self._var_frame.hide()
        cbl.addWidget(self._var_frame)

        # Cash rounding breakdown — shown only when Cash/Mixed + delta ≠ 0
        self._round_frame = QFrame()
        self._round_frame.setObjectName('posRoundFrame')
        self._round_frame.setStyleSheet(
            f"QFrame#posRoundFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
        rfl = QVBoxLayout(self._round_frame)
        rfl.setContentsMargins(12, 8, 12, 8); rfl.setSpacing(4)
        self._round_badge = QLabel('Cash Rounding Applied')
        self._round_badge.setStyleSheet(
            f"color:{C['gold']};font-size:11px;font-weight:800;background:transparent;")
        self._orig_due_lbl = QLabel('Original: —')
        self._round_adj_lbl = QLabel('Cash Rounding: —')
        self._amount_due_lbl = QLabel('Amount Due: —')
        for w in (self._orig_due_lbl, self._round_adj_lbl, self._amount_due_lbl):
            w.setStyleSheet(
                f"color:{C['text2']};font-size:12px;font-weight:600;background:transparent;")
        self._amount_due_lbl.setStyleSheet(
            f"color:{C['text']};font-size:13px;font-weight:800;background:transparent;")
        rfl.addWidget(self._round_badge)
        rfl.addWidget(self._orig_due_lbl)
        rfl.addWidget(self._round_adj_lbl)
        rfl.addWidget(self._amount_due_lbl)
        self._round_frame.hide()
        cbl.addWidget(self._round_frame)

        # Split / 2-way tender (outside rounding — visible whenever Cash or Mixed)
        self._split_frame = QFrame()
        self._split_frame.setObjectName('posSplitFrame')
        self._split_frame.setStyleSheet(
            f"QFrame#posSplitFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
        sfl = QVBoxLayout(self._split_frame)
        sfl.setContentsMargins(12, 8, 12, 8); sfl.setSpacing(6)
        self._split_hdr = QLabel('Split payment (optional)')
        self._split_hdr.setStyleSheet(
            f"color:{C['text2']};font-size:11px;font-weight:700;background:transparent;")
        sfl.addWidget(self._split_hdr)
        erow = QHBoxLayout(); erow.setSpacing(8)
        self._elec_method = Select()
        self._elec_method.set_items(['M-Pesa', 'Card', 'Bank Transfer', 'Airtel Money'])
        self._elec_method.setMinimumHeight(34)
        self._elec_method.setMinimumWidth(120)
        self._elec_lbl = QLabel('Electronic')
        self._elec_lbl.setStyleSheet(
            f"color:{C['text2']};font-size:12px;background:transparent;")
        self._elec_paid = QDoubleSpinBox()
        self._elec_paid.setRange(0, 99999999)
        self._elec_paid.setDecimals(2)
        self._elec_paid.setMinimumHeight(34)
        self._elec_paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._elec_paid.setToolTip(
            'Amount paid electronically (M-Pesa / Card / Bank). '
            'Cash portion below is rounded separately.')
        self._elec_paid.valueChanged.connect(self._on_elec_paid_changed)
        try:
            self._elec_method.currentTextChanged.connect(
                lambda *_: self._update_rounding_ui())
        except Exception:
            pass
        erow.addWidget(self._elec_lbl)
        erow.addWidget(self._elec_method, 1)
        erow.addWidget(self._elec_paid, 1)
        sfl.addLayout(erow)
        self._split_summary = QLabel('')
        self._split_summary.setWordWrap(True)
        self._split_summary.setStyleSheet(
            f"color:{C['text']};font-size:12px;font-weight:700;background:transparent;")
        sfl.addWidget(self._split_summary)
        self._split_frame.hide()
        cbl.addWidget(self._split_frame)

        chg = QHBoxLayout()
        self._chg_lbl = QLabel('Change')
        self._chg_lbl.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        self._chg = QLabel('KES 0.00')
        self._chg.setStyleSheet(
            f"color:{C['ok']};font-size:15px;font-weight:700;background:transparent;")
        chg.addWidget(self._chg_lbl); chg.addWidget(self._chg); chg.addStretch()
        cbl.addLayout(chg)

        self._mpesa_frame = QFrame()
        self._mpesa_frame.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
        mfl = QVBoxLayout(self._mpesa_frame)
        mfl.setContentsMargins(12, 10, 12, 10); mfl.setSpacing(6)
        self._mpesa_info = QLabel('Pay to Till: —')
        self._mpesa_info.setWordWrap(True)
        self._mpesa_info.setStyleSheet(
            f"color:{C['gold']};font-size:12px;font-weight:600;background:transparent;")
        self._mpesa_ref = QLineEdit()
        self._mpesa_ref.setPlaceholderText('M-Pesa confirmation code (optional)')
        self._mpesa_ref.setMinimumHeight(40)
        mfl.addWidget(self._mpesa_info); mfl.addWidget(self._mpesa_ref)
        self._mpesa_frame.hide()
        cbl.addWidget(self._mpesa_frame)

        self._note = QLineEdit(); self._note.setPlaceholderText('Note (optional)…')
        self._note.setMinimumHeight(40); cbl.addWidget(self._note)

        # Preview/Reprint live in sticky footer (not under Complete Sale).
        # Note: Checkout is pinned below the scroll area so it is always visible.
        rl.addWidget(cart_body, 1)
        self._checkout_scroll.setWidget(checkout)
        rp_outer.addWidget(self._checkout_scroll, 1)

        foot = QWidget()
        foot.setObjectName('posCheckoutFoot')
        foot.setAttribute(Qt.WA_StyledBackground, True)
        foot.setStyleSheet(
            f"QWidget#posCheckoutFoot {{ background:{C['card']}; "
            f"border-top:1px solid {C['border']}; }}")
        self._checkout_foot = foot
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 12)
        fl.setSpacing(8)

        br = QHBoxLayout(); br.setSpacing(10)
        self._clr_btn = DangerBtn('🗑', 40); self._clr_btn.setFixedWidth(44)
        self._clr_btn.setToolTip('Clear cart'); self._clr_btn.clicked.connect(self._clear)
        self._prv_btn = SecondaryBtn('🖨  Preview', 40)
        self._prv_btn.clicked.connect(self._preview)
        self._reprint_btn = SecondaryBtn('🖨  Reprint', 40)
        self._reprint_btn.setToolTip('Reprint a completed receipt')
        self._reprint_btn.clicked.connect(self._reprint_receipt)
        br.addWidget(self._clr_btn); br.addWidget(self._prv_btn, 1)
        br.addWidget(self._reprint_btn)
        from desktop.utils.security import can_void_sales
        if can_void_sales(self.user):
            self._void_btn = DangerBtn('Void Sale', 40)
            self._void_btn.setToolTip(
                'Void a completed sale (reason dropdown + Super-Admin PIN)')
            self._void_btn.clicked.connect(self._void_sale)
            br.addWidget(self._void_btn)
        else:
            self._void_btn = None
        fl.addLayout(br)

        self._charge_btn = PrimaryBtn('🛒  Complete Sale', 56)
        self._charge_btn.setMinimumHeight(56)
        self._charge_btn.clicked.connect(self._process)
        fl.addWidget(self._charge_btn)
        rp_outer.addWidget(foot)
        root.addWidget(self._right_panel, 5)

    def _select_pay_method(self, method: str):
        if hasattr(self, '_pay_seg'):
            self._pay_seg.select(method, emit=False)
        for k, b in getattr(self, '_pay_btns', {}).items():
            b.setChecked(k == method)
        idx = self._pay.findText(method)
        if idx >= 0:
            self._pay.setCurrentIndex(idx)

    # ── Theme toggle ──────────────────────────────────────────────────────────

    def _on_theme_bar(self, want_light: bool):
        self.theme_changed.emit(want_light)

    def _toggle_theme(self):
        self.theme_changed.emit(not ThemeManager.is_light())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tot_row(self, parent_lay, label):
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        l = QLabel(label)
        l.setStyleSheet(f"color:{C['text2']};font-size:14px;background:transparent;")
        v = QLabel('KES 0.00')
        v.setStyleSheet(f"color:{C['text']};font-size:14px;background:transparent;")
        row.addWidget(l); row.addStretch(); row.addWidget(v)
        parent_lay.addLayout(row); return v

    def on_show(self):
        self.refresh()
        self._on_payment_changed(self._pay.currentText())
        try:
            self._search.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            cols = self._product_columns()
            if getattr(self, '_last_cols', None) != cols:
                self._last_cols = cols
                self._filter()
        except Exception:
            pass

    def _amount_due(self):
        """Payable after store credit and cash rounding (when active)."""
        info = self._compute_rounding()
        return round(float(info.get('amount_due', max(0.0, self._total - float(self._credit_to_apply or 0)))), 2)

    def _elec_portion(self) -> float:
        if not hasattr(self, '_elec_paid'):
            return 0.0
        return round(float(self._elec_paid.value() or 0), 2)

    def _elec_method_name(self) -> str:
        if hasattr(self, '_elec_method'):
            try:
                return (self._elec_method.currentText() or 'M-Pesa').strip()
            except Exception:
                pass
        return 'M-Pesa'

    def _is_split_method(self, method=None) -> bool:
        method = method or (self._pay.currentText() if hasattr(self, '_pay') else 'Cash')
        return method in ('Cash', 'Mixed')

    def _cash_due_amount(self) -> float:
        """Cash portion due (post rounding) — used for Cash Paid autofill on split."""
        info = self._rounding_info or self._compute_rounding()
        elec = float(info.get('electronic') or 0)
        if elec > 0.009:
            return round(float(info.get('cash_rounded', 0)), 2)
        return round(float(info.get('amount_due', self._amount_due())), 2)

    def _on_elec_paid_changed(self, *_args):
        # Split tender: remaining cash due re-fills Cash Paid when not dirty
        self._recalc()

    def _cfg(self) -> dict:
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _set_paid_value(self, value: float, *, mark_clean: bool = False):
        """Programmatic Cash Paid / Received update (does not set dirty)."""
        self._paid_programmatic = True
        try:
            self._paid.blockSignals(True)
            self._paid.setValue(round(float(value or 0), 2))
        except Exception:
            pass
        finally:
            try:
                self._paid.blockSignals(False)
            except Exception:
                pass
            self._paid_programmatic = False
        if mark_clean:
            self._cash_paid_dirty = False

    def _on_paid_changed(self, *_args):
        if not self._paid_programmatic:
            method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
            # Only Cash / Mixed use the dirty flag for auto-fill
            try:
                from desktop.utils.auto_fill import AutoFillService
                if AutoFillService.is_cash_like(method):
                    self._cash_paid_dirty = True
            except Exception:
                if method in ('Cash', 'Mixed'):
                    self._cash_paid_dirty = True
        self._calc_change()

    def _focus_cash_paid(self):
        """Auto-focus Cash Paid and select-all for quick overwrite."""
        def _do():
            try:
                self._paid.setFocus(Qt.OtherFocusReason)
                le = self._paid.lineEdit() if hasattr(self._paid, 'lineEdit') else None
                if le is not None:
                    le.selectAll()
                elif hasattr(self._paid, 'selectAll'):
                    self._paid.selectAll()
            except Exception:
                pass
        QTimer.singleShot(0, _do)

    def _set_cash_paid_ui_visible(self, visible: bool):
        if hasattr(self, '_paid'):
            self._paid.setVisible(visible)
        if hasattr(self, '_cash_paid_lbl'):
            self._cash_paid_lbl.setVisible(visible)
        if hasattr(self, '_chg_lbl'):
            self._chg_lbl.setVisible(visible)
        if hasattr(self, '_chg'):
            self._chg.setVisible(visible)

    def _maybe_autofill_cash_paid(self, *, focus: bool = False):
        """Fill Cash Paid = cash due (post rounding) when allowed."""
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        cfg = self._cfg()
        try:
            from desktop.utils.auto_fill import AutoFillService
            ok = AutoFillService.should_autofill_cash_paid(
                method, dirty=bool(self._cash_paid_dirty), cfg=cfg)
        except Exception:
            ok = (
                method in ('Cash', 'Mixed')
                and not self._cash_paid_dirty
                and cfg.get('autofill_cash_paid', '1') != '0'
            )
        if not ok:
            return False
        # Split: only autofill the cash portion, not electronic + cash
        due = self._cash_due_amount()
        self._set_paid_value(due, mark_clean=True)
        if focus and due > 0.009:
            self._focus_cash_paid()
        return True

    def _compute_rounding(self) -> dict:
        """Recompute cash rounding for current cart / payment method."""
        from desktop.utils.cash_rounding_service import CashRoundingService
        cfg = {}
        try:
            cfg = self.config_getter() or {}
        except Exception:
            cfg = {}
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        credit = float(self._credit_to_apply or 0)
        # Electronic portion only on Cash / Mixed (split tender)
        elec = self._elec_portion() if self._is_split_method(method) else 0.0
        # Mixed always applies cash-portion rounding rules
        round_method = 'Cash' if method == 'Mixed' else method
        info = CashRoundingService.apply_to_total(
            self._subtotal, self._discount, self._tax, round_method, cfg,
            credit_applied=credit, electronic_portion=elec)
        self._rounding_info = info
        self._original_total = float(info.get('cart_total', self._total))
        self._rounding_adj = float(info.get('adjustment') or 0)
        return info

    def _update_rounding_ui(self):
        info = self._rounding_info or self._compute_rounding()
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        from desktop.utils.cash_rounding_service import CashRoundingService
        cfg = {}
        try:
            cfg = self.config_getter() or {}
        except Exception:
            pass
        st = CashRoundingService.settings_from_config(cfg)
        adj = float(info.get('adjustment') or 0)
        # Rounding badge/lines ONLY when Cash/Mixed + enabled + non-zero delta
        show_round = (
            self._is_split_method(method)
            and bool(st.get('enabled'))
            and CashRoundingService.should_apply('cash', st)
            and abs(adj) > 0.009
        )
        if hasattr(self, '_round_frame'):
            self._round_frame.setVisible(show_round)
            if show_round:
                cur = self._currency
                orig = float(info.get('original_due', info.get('original', 0)))
                due = float(info.get('amount_due', orig))
                cash_orig = float(info.get('cash_original') or orig)
                cash_rnd = float(info.get('cash_rounded') or due)
                elec = float(info.get('electronic') or 0)
                if elec > 0.009:
                    self._orig_due_lbl.setText(
                        f'Cash original: {cur} {cash_orig:,.2f}')
                    self._amount_due_lbl.setText(
                        f'Cash due: {cur} {cash_rnd:,.2f}')
                else:
                    self._orig_due_lbl.setText(f'Original: {cur} {orig:,.2f}')
                    self._amount_due_lbl.setText(f'Amount Due: {cur} {due:,.2f}')
                sign = '+' if adj >= 0 else ''
                self._round_adj_lbl.setText(
                    f'Cash Rounding: {sign}{cur} {adj:,.2f}')
                self._round_badge.setVisible(True)
                gold, mute, text = C['gold'], C['text2'], C['text']
                self._round_badge.setStyleSheet(
                    f"color:{gold};font-size:11px;font-weight:800;background:transparent;")
                self._orig_due_lbl.setStyleSheet(
                    f"color:{mute};font-size:12px;font-weight:600;background:transparent;")
                self._round_adj_lbl.setStyleSheet(
                    f"color:{mute};font-size:12px;font-weight:600;background:transparent;")
                self._amount_due_lbl.setStyleSheet(
                    f"color:{text};font-size:13px;font-weight:800;background:transparent;")
                self._round_frame.setStyleSheet(
                    f"QFrame#posRoundFrame{{background:{C['card2']};"
                    f"border:1px solid {C['border2']};border-radius:8px;}}")

        # Split tender panel — Cash / Mixed only (never on pure M-Pesa/Card/Bank)
        show_split = self._is_split_method(method)
        if hasattr(self, '_split_frame'):
            self._split_frame.setVisible(show_split)
            if show_split:
                mute = C['text2']
                self._split_frame.setStyleSheet(
                    f"QFrame#posSplitFrame{{background:{C['card2']};"
                    f"border:1px solid {C['border2']};border-radius:8px;}}")
                self._elec_lbl.setStyleSheet(
                    f"color:{mute};font-size:12px;background:transparent;")
                self._split_hdr.setStyleSheet(
                    f"color:{mute};font-size:11px;font-weight:700;background:transparent;")
                # Force Mixed label when electronic amount entered on Cash
                elec = float(info.get('electronic') or 0)
                cash_due = float(info.get('cash_rounded') or 0)
                cash_paid = float(self._paid.value() or 0) if hasattr(self, '_paid') else cash_due
                cur = self._currency
                em = self._elec_method_name()
                if elec > 0.009:
                    self._split_summary.setText(
                        f'{em} {cur} {elec:,.2f}  +  Cash {cur} {cash_paid:,.2f}'
                        f'  =  {cur} {elec + cash_paid:,.2f}'
                        f'   (cash due {cur} {cash_due:,.2f})')
                    self._split_hdr.setText('Split payment')
                else:
                    self._split_summary.setText(
                        'Enter electronic amount for 2-way pay '
                        '(e.g. M-Pesa + Cash). Leave 0 for cash only.')
                    self._split_hdr.setText(
                        'Split payment (optional)' if method == 'Cash'
                        else 'Split payment — enter both tenders')


    def _is_till_method(self, method=None):
        method = method or self._pay.currentText()
        return method in ('M-Pesa',)

    def _on_customer_changed(self, *_args):
        cust_id = self._customer.selected_id() if hasattr(self, '_customer') else None
        bal = float(self._wallet_by_customer.get(cust_id) or 0) if cust_id else 0.0
        # Credit customer summary tooltip (balance / limit / outstanding)
        try:
            from desktop.utils.auto_fill import AutoFillService
            cfg = self._cfg() if hasattr(self, '_cfg') else (self.config_getter() or {})
            if cust_id and AutoFillService.enabled(cfg, 'autofill_credit_customer_info'):
                cust = None
                try:
                    for c in (self.api.get_customers() or []):
                        if c.get('id') == cust_id:
                            cust = c
                            break
                except Exception:
                    cust = None
                summary = AutoFillService.credit_customer_summary(cust, cfg)
                hint = AutoFillService.format_credit_customer_hint(
                    summary, self._currency)
                if hasattr(self, '_customer'):
                    self._customer.setToolTip(hint or '')
            elif hasattr(self, '_customer'):
                self._customer.setToolTip('')
        except Exception:
            pass
        if cust_id and bal > 0.009:
            self._credit_frame.show()
            self._credit_info.setText(
                f'Store credit available: {self._currency} {bal:,.2f}')
            self._credit_spin.blockSignals(True)
            self._credit_spin.setMaximum(min(bal, self._total if self._total > 0 else bal))
            # Keep existing apply if still valid
            apply = min(float(self._credit_to_apply or 0), bal, self._total)
            self._credit_spin.setValue(apply)
            self._credit_spin.blockSignals(False)
            self._credit_to_apply = apply
        else:
            self._credit_frame.hide()
            self._credit_to_apply = 0.0
            self._credit_spin.blockSignals(True)
            self._credit_spin.setValue(0)
            self._credit_spin.blockSignals(False)
        self._calc_change()

    def _on_credit_apply_changed(self, val):
        self._credit_to_apply = round(float(val or 0), 2)
        method = self._pay.currentText()
        if self._is_till_method():
            self._set_paid_value(self._amount_due())
        elif method in ('Cash', 'Mixed'):
            self._maybe_autofill_cash_paid(focus=False)
        self._calc_change()

    def _apply_all_credit(self):
        cust_id = self._customer.selected_id()
        bal = float(self._wallet_by_customer.get(cust_id) or 0) if cust_id else 0.0
        self._credit_spin.setValue(min(bal, self._total))

    def _on_payment_changed(self, method: str):
        if hasattr(self, '_pay_seg') and method in ('Cash', 'M-Pesa', 'Card'):
            self._pay_seg.select(method, emit=False)
        if hasattr(self, '_pay_btns'):
            for k, b in self._pay_btns.items():
                b.blockSignals(True)
                b.setChecked(k == method)
                b.blockSignals(False)

        from desktop.utils.auto_fill import AutoFillService

        is_mpesa = method == 'M-Pesa'
        self._mpesa_frame.setVisible(is_mpesa)
        if hasattr(self, '_var_frame'):
            self._var_frame.setVisible(is_mpesa)

        # Switching payment method resets Cash Paid dirty flag for Cash/Mixed
        if AutoFillService.is_cash_like(method):
            self._cash_paid_dirty = False
        else:
            # Leaving split methods — clear electronic portion
            if hasattr(self, '_elec_paid'):
                self._elec_paid.blockSignals(True)
                self._elec_paid.setValue(0)
                self._elec_paid.blockSignals(False)

        if is_mpesa:
            cfg = self._cfg()
            till = cfg.get('mpesa_till', '').strip()
            pb   = cfg.get('mpesa_paybill', '').strip()
            biz  = cfg.get('mpesa_business_name', '') or cfg.get('shop_name', 'Shop')
            parts = [biz]
            if till:
                parts.append(f'Till: {till}')
            if pb:
                parts.append(f'Paybill: {pb}')
            if not till and not pb:
                parts.append('Set Till/Paybill in Settings → M-Pesa')
            self._mpesa_info.setText(' · '.join(parts))
            # Received Amount for Till variance (not Cash Paid auto-fill)
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_cash_paid_lbl'):
                self._cash_paid_lbl.setText('Received')
            self._paid.setEnabled(True)
            self._set_paid_value(self._amount_due())
            self._paid.setToolTip('Received Amount — enter what customer paid via Till')
            self._pay_lbl.setText('Method')
            self._chg_lbl.setText('Difference')
        elif method in ('Credit Sale', 'Credit Account'):
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_cash_paid_lbl'):
                self._cash_paid_lbl.setText('Paid Now')
            self._set_paid_value(0.0)
            self._paid.setEnabled(False)
            self._mpesa_ref.clear()
            self._paid.setToolTip('')
            self._chg_lbl.setText('Change')
        elif AutoFillService.hides_cash_paid_ui(method):
            # Card / Bank / Cheque / Airtel — hide Cash Paid & Change
            self._set_cash_paid_ui_visible(False)
            self._set_paid_value(self._amount_due())
            self._paid.setEnabled(False)
            self._mpesa_ref.clear()
            self._paid.setToolTip('')
            self._chg_lbl.setText('Change')
        elif method == 'Part Payment':
            # Partial pay — never auto-fill amount (intentional credit remainder)
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_cash_paid_lbl'):
                self._cash_paid_lbl.setText('Paid Now')
            self._paid.setEnabled(True)
            self._mpesa_ref.clear()
            self._paid.setToolTip('Amount paid now (remainder on credit)')
            self._chg_lbl.setText('Balance Due')
            # Leave current paid unless zeroed for a fresh part-payment flow
            if self._paid.value() <= 0.009:
                self._set_paid_value(0.0)
        else:
            # Cash / Mixed — smart Cash Paid = Amount Due (post rounding)
            self._set_cash_paid_ui_visible(True)
            if hasattr(self, '_cash_paid_lbl'):
                self._cash_paid_lbl.setText('Cash Paid')
            self._paid.setEnabled(True)
            self._mpesa_ref.clear()
            self._paid.setToolTip('Cash Paid — defaults to Amount Due; edit for change')
            self._chg_lbl.setText('Change')
            self._maybe_autofill_cash_paid(focus=True)
        self._update_rounding_ui()
        self._calc_change()

    def refresh(self):
        try: self.products = self.api.get_products() or []
        except Exception: self.products = []
        try:
            self._currency = (self.config_getter() or {}).get('currency_symbol', 'KES') or 'KES'
        except Exception: pass
        try:
            self._categories_by_name = self.api.categories_by_name_map()
        except Exception:
            self._categories_by_name = {}
        try:
            customers = self.api.get_customers() or []
            self._wallet_by_customer = {
                c.get('id'): float(c.get('wallet_balance') or 0)
                for c in customers if c.get('id')
            }
            if hasattr(self, '_customer'):
                self._customer.load_customers(customers)
                self._on_customer_changed()
        except Exception:
            pass
        cats = sorted({p.get('category') or 'General' for p in self.products})
        # Prefer managed category list when available
        try:
            managed = [c.get('name') for c in (self.api.get_categories() or []) if c.get('name')]
            if managed:
                cats = sorted(set(cats) | set(managed))
        except Exception:
            pass
        self._cat.blockSignals(True)
        cur = self._cat.currentText()
        self._cat.clear(); self._cat.addItem('All Categories')
        for c in cats:
            meta = (self._categories_by_name or {}).get(c) or {}
            # Show icon hint in combo via item data; text stays readable
            self._cat.addItem(c)
            idx_i = self._cat.count() - 1
            if meta.get('icon_name'):
                try:
                    from desktop.utils.category_visuals import icon_to_pixmap
                    self._cat.setItemIcon(
                        idx_i, QIcon(icon_to_pixmap(icon_id=meta['icon_name'], size=20)))
                except Exception:
                    pass
        idx = self._cat.findText(cur)
        if idx >= 0: self._cat.setCurrentIndex(idx)
        self._cat.blockSignals(False)
        self._filter()

    def _on_barcode_enter(self, text: str):
        """Barcode / SKU Enter — add exact match and clear search for next scan."""
        q = (text or '').strip()
        if not q:
            return
        ql = q.lower()
        hit = None
        for p in self.products:
            sku = (p.get('sku') or '').strip().lower()
            bar = (p.get('barcode') or '').strip().lower()
            if ql == sku or ql == bar or ql == str(p.get('id', '')):
                hit = p
                break
        if hit is None:
            # Unique partial SKU/barcode match
            matches = [p for p in self.products
                       if ql in (p.get('sku') or '').lower()
                       or ql in (p.get('barcode') or '').lower()
                       or ql in (p.get('name') or '').lower()]
            if len(matches) == 1:
                hit = matches[0]
        if hit is not None:
            try:
                stock_n = float(hit.get('stock', 0) or 0)
            except (TypeError, ValueError):
                stock_n = 0
            if stock_n <= 0:
                _sfx('warning')
                QMessageBox.information(self, 'Out of stock',
                                        f'{(hit.get("name") or "Item")} is out of stock.')
            else:
                self._add(hit, from_scan=True)
            self._search.clear()
            self._search.setFocus(Qt.OtherFocusReason)
        else:
            self._filter()

    def _filter(self):
        q   = self._search.text().strip().lower()
        cat = self._cat.currentText()
        filtered = [p for p in self.products
                    if (not q or q in p.get('name', '').lower()
                        or q in (p.get('sku') or '').lower()
                        or q in (p.get('barcode') or '').lower())
                    and (cat == 'All Categories'
                         or (p.get('category') or 'General') == cat)]
        if not filtered:
            self._prod_grid.clear()
            self._empty.show()
        else:
            self._empty.hide()
            self._prod_grid.set_currency(self._currency)
            self._prod_grid.set_light(bool(getattr(self, '_is_light', False)))
            self._prod_grid.set_categories_map(
                getattr(self, '_categories_by_name', None) or {})
            cols = self._product_columns()
            self._prod_grid.populate(filtered, columns=cols)

    def _retint_prod_grid(self):
        """Update product card colors in place — no destroy/rebuild (theme switch fast path)."""
        if hasattr(self, '_prod_grid'):
            self._prod_grid.set_light(bool(getattr(self, '_is_light', False)))
            self._prod_grid.retint()
        refresh_pos_components(self)

    def _product_columns(self) -> int:
        try:
            available = max(640, self._left_panel.width() - 48)
        except Exception:
            available = 760
        if hasattr(self, '_prod_grid'):
            return self._prod_grid.columns_for_width(available)
        card_w = 214 if self._is_light else 206
        gap = 14
        cols = max(2, int((available + gap) // (card_w + gap)))
        return min(4, cols)

    def _prod_btn(self, p):
        """Legacy helper — ProductGrid builds ProductCard now."""
        card = ProductCard(
            p, currency=self._currency,
            card_size=(220, 150) if self._is_light else (214, 148))
        card.clicked.connect(self._add)
        return card

    def _set_card_text(self, label: QLabel, text: str, width: int, max_lines: int):
        """Clamp label text with ellipsis to keep POS cards readable."""
        safe = (text or '').strip()
        if not safe:
            label.setText('')
            return
        fm = label.fontMetrics()
        lines, current = [], ''
        for word in safe.split():
            probe = (current + ' ' + word).strip()
            if fm.horizontalAdvance(probe) <= width:
                current = probe
            else:
                if current:
                    lines.append(current)
                if len(lines) >= max_lines:
                    break
                if fm.horizontalAdvance(word) <= width:
                    current = word
                else:
                    chunk = ''
                    for ch in word:
                        test = chunk + ch
                        if fm.horizontalAdvance(test) <= width:
                            chunk = test
                        else:
                            if chunk:
                                lines.append(chunk)
                            if len(lines) >= max_lines:
                                chunk = ''
                                break
                            chunk = ch
                    current = chunk
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        rendered = '\n'.join(lines[:max_lines])
        if rendered.replace('\n', ' ') != safe and lines:
            lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
            rendered = '\n'.join(lines[:max_lines])
        label.setText(rendered)

    def _display_name(self, name: str, limit: int = 22) -> str:
        """
        Keep product names readable on buttons, even for long single words.
        Split into up to three lines and ellipsize tail.
        """
        if not name:
            return ''
        words = name.split()
        lines = []
        line = ''
        for w in words:
            if len(w) > 12:
                # Break very long words so they still wrap in button text.
                chunks = [w[i:i + 12] for i in range(0, len(w), 12)]
            else:
                chunks = [w]
            for c in chunks:
                candidate = (line + ' ' + c).strip()
                if len(candidate) <= 12:
                    line = candidate
                else:
                    if line:
                        lines.append(line)
                    line = c
                    if len(lines) >= 3:
                        break
            if len(lines) >= 3:
                break
        if line and len(lines) < 3:
            lines.append(line)
        text = '\n'.join(lines[:3])
        if len(words) > 0 and len(' '.join(words)) > len(text.replace('\n', ' ')):
            if '\n' in text:
                head, tail = text.rsplit('\n', 1)
                text = head + '\n' + (tail[:10] + '…')
            else:
                text = text[:11] + '…'
        return text

    def _line_gross(self, item):
        return round(float(item.get('quantity') or 0) * float(item.get('unit_price') or 0), 2)

    def _apply_line_total(self, item):
        """Clamp Disc (KES) to line gross and set line total after discount."""
        gross = self._line_gross(item)
        disc = max(0.0, min(float(item.get('discount') or 0), gross))
        item['discount'] = round(disc, 2)
        item['total'] = round(gross - disc, 2)
        return item['total']

    def _add(self, p, from_scan: bool = False):
        if from_scan:
            _sfx('barcode_scan')
        else:
            _sfx('product_add')
        # Low-stock cue (grouped) — never audio-only; UI already shows stock on cards
        try:
            stock_n = float(p.get('stock', 0) or 0)
            reorder = float(p.get('reorder_level') or p.get('min_stock') or 5)
            if 0 < stock_n <= reorder:
                _sfx('low_stock')
        except (TypeError, ValueError):
            pass
        for item in self.cart:
            if item['product_id'] == p['id']:
                item['quantity'] = round(item['quantity'] + 1.0, 2)
                self._apply_line_total(item)
                self._refresh_cart(); return
        self.cart.append({
            'product_id':   p['id'],
            'product_name': p.get('name', ''),
            'sku':          p.get('sku', '') or '',
            'quantity':     1.0,
            'unit_price':   p.get('price', 0),
            'discount':     0.0,
            'total':        p.get('price', 0),
        })
        self._refresh_cart()

    def _cart_fg(self):
        """High-contrast cart text — never inherit a stale light-mode dark fg on dark bg."""
        from desktop.utils.theme import DARK, LIGHT, ThemeManager
        light = bool(getattr(self, '_is_light', False) or ThemeManager.is_light())
        # Dark navy text on light cards; near-white on dark cards
        return '#0C1828' if light else '#F5F7FA'

    def _refresh_cart(self):
        from desktop.utils.pos_light_theme import fmt, SPINBOX, REMOVE_BTN, L, CART_ROW_H
        from desktop.utils.theme import DARK, LIGHT, ThemeManager
        from desktop.utils.widgets import apply_table_row_backgrounds, tbl_item
        self._ctbl.setRowCount(0)
        light = bool(getattr(self, '_is_light', False) or ThemeManager.is_light())
        item_color = self._cart_fg()
        # Keep table QSS in sync — no ::item selection chrome (NoSelection)
        if light:
            self._ctbl.setStyleSheet(fmt(
                "QTableWidget{{background:#FFFFFF;border:2px solid {border2};"
                "border-radius:10px;color:{text};font-size:{font_cart};font-weight:700;"
                "gridline-color:transparent;outline:0;}}"
                "QTableWidget::item{{color:{text};padding:8px 10px;background:transparent;}}"
                "QTableWidget::item:selected{{background:transparent;color:{text};}}"
                "QHeaderView::section{{background:{card2};color:{text};font-size:{font_cart_head};"
                "font-weight:800;letter-spacing:0.6px;padding:10px 8px;border:none;"
                "border-bottom:2px solid {border2};}}"
            ))
        else:
            self._ctbl.setStyleSheet(
                f"QTableWidget{{background:{DARK['card']};border:1px solid {DARK['border2']};"
                f"border-radius:10px;color:#F5F7FA;font-size:15px;font-weight:700;"
                f"gridline-color:transparent;outline:0;}}"
                f"QTableWidget::item{{color:#F5F7FA;padding:8px 10px;background:transparent;}}"
                f"QTableWidget::item:selected{{background:transparent;color:#F5F7FA;}}"
                f"QHeaderView::section{{background:{DARK['panel']};color:#C5D0E0;"
                f"font-size:12px;font-weight:800;letter-spacing:0.6px;padding:10px 8px;"
                f"border:none;border-bottom:1px solid {DARK['border2']};}}"
            )
        for i, item in enumerate(self.cart):
            self._ctbl.insertRow(i)
            full_name = item['product_name']
            # Plain item (no nested QLabel box) — ThemeTableDelegate elides
            name_it = tbl_item(full_name, color=item_color)
            name_it.setToolTip(full_name)
            name_it.setFlags(name_it.flags() & ~Qt.ItemIsEditable)
            self._ctbl.setItem(i, 0, name_it)

            # Qty — flat QuantityControl (shared light/dark)
            qty = QuantityControl(
                value=float(item['quantity']), step=0.25, minimum=0.25, width=124)
            qty.valueChanged.connect(lambda v, idx=i: self._qty(idx, v))
            cell_wrap = QWidget()
            cell_wrap.setStyleSheet('background:transparent;border:none;')
            cw_lay = QHBoxLayout(cell_wrap)
            cw_lay.setContentsMargins(2, 6, 2, 6)
            cw_lay.setSpacing(0)
            cw_lay.addWidget(qty, 0, Qt.AlignCenter)
            self._ctbl.setCellWidget(i, 1, cell_wrap)
            self._ctbl.setItem(i, 2, tbl_right(f'{item["unit_price"]:,.2f}', color=item_color))

            # Disc — same stepper chrome as Qty (no nested boxes)
            self._apply_line_total(item)
            disc = QuantityControl(
                value=float(item.get('discount') or 0),
                step=10.0,
                minimum=0.0,
                maximum=999999.0,
                snap=False,
                width=124,
            )
            disc.valueChanged.connect(lambda v, idx=i: self._set_line_disc(idx, v))
            disc_wrap = QWidget()
            disc_wrap.setStyleSheet('background:transparent;border:none;')
            dw_lay = QHBoxLayout(disc_wrap)
            dw_lay.setContentsMargins(2, 6, 2, 6)
            dw_lay.setSpacing(0)
            dw_lay.addWidget(disc, 0, Qt.AlignCenter)
            self._ctbl.setCellWidget(i, 3, disc_wrap)

            self._ctbl.setItem(i, 4, tbl_right(f'{item["total"]:,.2f}', color=item_color))
            rm = QPushButton('✕')
            if self._is_light:
                rm.setStyleSheet(fmt(REMOVE_BTN))
            else:
                rm.setStyleSheet(
                    f"QPushButton{{background:{C['err_dim']};color:{C['err']};"
                    f"border:1px solid {qss_alpha(C['err'], 0.40)};border-radius:6px;"
                    f"font-weight:800;font-size:14px;min-width:32px;min-height:30px;padding:2px 6px;}}"
                    f"QPushButton:hover{{background:{C['err']};color:#fff;}}")
            rm.setCursor(Qt.PointingHandCursor)
            rm.clicked.connect(lambda _, idx=i: self._rm(idx))
            self._ctbl.setCellWidget(i, 5, rm)
            # Match CART_ROW_H from theme (64) — was forcing 48 and clamping against default 56
            self._ctbl.setRowHeight(i, CART_ROW_H)

        apply_table_row_backgrounds(self._ctbl)

        n = len(self.cart)
        self._cnt.setText(f"{n} item{'s' if n != 1 else ''}")
        self._recalc()

    def _parse_kes(self, text):
        """Parse typed KES amount; commas and spaces allowed."""
        s = (text or '').strip().replace(',', '').replace(' ', '')
        if not s or s in ('-', '.', '-.'):
            return 0.0
        try:
            return max(0.0, float(s))
        except ValueError:
            return None

    def _commit_line_disc_text(self, idx, ed):
        if not (0 <= idx < len(self.cart)):
            return
        parsed = self._parse_kes(ed.text())
        if parsed is None:
            ed.setText(f"{float(self.cart[idx].get('discount') or 0):.2f}")
            return
        self._set_line_disc(idx, parsed)
        # Reflect clamped value
        ed.blockSignals(True)
        ed.setText(f"{float(self.cart[idx].get('discount') or 0):.2f}")
        ed.blockSignals(False)

    def _set_line_disc(self, idx, v):
        if not (0 <= idx < len(self.cart)):
            return
        item = self.cart[idx]
        gross = self._line_gross(item)
        if gross <= 0:
            # Can't discount a zero-price line — keep at 0 and tip the cashier
            item['discount'] = 0.0
            item['total'] = 0.0
            color = self._cart_fg()
            self._ctbl.setItem(idx, 4, tbl_right('0.00', color=color))
            self._recalc()
            return
        item['discount'] = float(v)
        self._apply_line_total(item)
        color = self._cart_fg()
        self._ctbl.setItem(idx, 4, tbl_right(f'{item["total"]:,.2f}', color=color))
        self._recalc()

    def _bump_line_disc(self, idx, delta):
        if not (0 <= idx < len(self.cart)):
            return
        item = self.cart[idx]
        gross = self._line_gross(item)
        if gross <= 0:
            return
        new_d = max(0.0, min(gross, float(item.get('discount') or 0) + float(delta)))
        item['discount'] = round(new_d, 2)
        self._apply_line_total(item)
        disc_w = self._ctbl.cellWidget(idx, 3)
        if disc_w:
            qc = disc_w.findChild(QuantityControl)
            if qc is not None:
                qc.setValue(item['discount'])
            else:
                ed = disc_w.findChild(QLineEdit)
                if ed:
                    ed.blockSignals(True)
                    ed.setText(f"{item['discount']:.2f}")
                    ed.blockSignals(False)
        color = self._cart_fg()
        self._ctbl.setItem(idx, 4, tbl_right(f'{item["total"]:,.2f}', color=color))
        self._recalc()

    def _qty(self, idx, v):
        if 0 <= idx < len(self.cart):
            q = round_qty(v, 0.25)
            self.cart[idx]['quantity'] = round(q, 2)
            self._apply_line_total(self.cart[idx])
            # Keep Disc field in sync without full refresh
            disc_w = self._ctbl.cellWidget(idx, 3)
            if disc_w:
                ed = disc_w.findChild(QLineEdit, 'lineDisc')
                if ed is None:
                    ed = disc_w.findChild(QLineEdit)
                if ed:
                    ed.blockSignals(True)
                    ed.setText(f"{float(self.cart[idx].get('discount') or 0):.2f}")
                    ed.blockSignals(False)
            color = self._cart_fg()
            self._ctbl.setItem(idx, 4, tbl_right(f'{self.cart[idx]["total"]:,.2f}', color=color))
            self._recalc()

    def _change_qty(self, idx, delta):
        if not (0 <= idx < len(self.cart)):
            return
        new_q = round_qty(self.cart[idx]['quantity'] + delta, 0.25)
        self.cart[idx]['quantity'] = round(new_q, 2)
        self._apply_line_total(self.cart[idx])
        self._refresh_cart()

    def _rm(self, idx):
        if 0 <= idx < len(self.cart):
            del self.cart[idx]
            _sfx('product_remove')
            self._refresh_cart()

    def _cart_disc_value(self):
        parsed = self._parse_kes(self._disc.text())
        return 0.0 if parsed is None else parsed

    def _commit_cart_disc(self):
        parsed = self._parse_kes(self._disc.text())
        if parsed is None:
            parsed = 0.0
        self._disc.blockSignals(True)
        self._disc.setText(f'{parsed:.2f}')
        self._disc.blockSignals(False)
        self._recalc()

    def _recalc(self):
        try:
            rate = float((self.config_getter() or {}).get('tax_rate', 0) or 0) / 100
            cur  = (self.config_getter() or {}).get('currency_symbol', 'KES') or 'KES'
        except Exception:
            rate = 0.0; cur = 'KES'
        self._currency = cur
        for item in self.cart:
            self._apply_line_total(item)
        # Subtotal before discount; total disc = cart KES + per-line KES
        sub = sum(self._line_gross(i) for i in self.cart)
        line_dis = round(sum(float(i.get('discount') or 0) for i in self.cart), 2)
        cart_dis = round(self._cart_disc_value(), 2)
        # Cap cart discount so total discount never exceeds subtotal
        cart_dis = min(cart_dis, max(0.0, sub - line_dis))
        if abs(cart_dis - self._cart_disc_value()) > 0.001:
            self._disc.blockSignals(True)
            self._disc.setText(f'{cart_dis:.2f}')
            self._disc.blockSignals(False)
        dis = round(line_dis + cart_dis, 2)
        tax = round(max(0, sub - dis) * rate, 2)
        tot = round(max(0, sub - dis) + tax, 2)
        self._subtotal = sub; self._discount = dis; self._tax = tax; self._total = tot
        self._sub_lbl.setText(f'{cur} {sub:,.2f}')
        self._tax_lbl.setText(f'{cur} {tax:,.2f}')
        self._tot_lbl.setText(f'{cur} {tot:,.2f}')
        # Cap credit apply to new total
        if self._credit_to_apply > tot:
            self._credit_to_apply = tot
            if hasattr(self, '_credit_spin'):
                self._credit_spin.blockSignals(True)
                self._credit_spin.setMaximum(tot)
                self._credit_spin.setValue(tot)
                self._credit_spin.blockSignals(False)
        elif hasattr(self, '_credit_spin') and self._credit_frame.isVisible():
            cust_id = self._customer.selected_id()
            bal = float(self._wallet_by_customer.get(cust_id) or 0) if cust_id else 0.0
            self._credit_spin.setMaximum(min(bal, tot) if tot > 0 else bal)
        # Cap electronic split to amount due before rounding
        if hasattr(self, '_elec_paid'):
            raw_due = round(max(0.0, tot - float(self._credit_to_apply or 0)), 2)
            self._elec_paid.setMaximum(raw_due if raw_due > 0 else 0)
            if self._elec_paid.value() > raw_due:
                self._elec_paid.blockSignals(True)
                self._elec_paid.setValue(raw_due)
                self._elec_paid.blockSignals(False)
        self._compute_rounding()
        self._update_rounding_ui()
        method = self._pay.currentText()
        # Recalc Amount Due → update Cash Paid ONLY if not manually dirty
        if method in ('Cash', 'Mixed'):
            self._maybe_autofill_cash_paid(focus=False)
        elif method == 'M-Pesa':
            self._set_paid_value(self._amount_due())
        elif method in ('Card', 'Bank Transfer', 'Cheque', 'Airtel Money'):
            self._set_paid_value(self._amount_due())
        self._calc_change()

    def _calc_change(self):
        due = self._amount_due()
        paid = self._paid.value()
        method = self._pay.currentText() if hasattr(self, '_pay') else 'Cash'
        from desktop.utils.pos_light_theme import L, FS
        from desktop.utils.auto_fill import AutoFillService
        ok_color = L['ok'] if self._is_light else C['ok']
        err_color = L['err'] if self._is_light else C['err']
        warn_color = (
            L.get('warn', C.get('warn', '#E8A838')) if self._is_light
            else C.get('warn', '#E8A838')
        )
        chg_sz = FS['change'] if self._is_light else '16px'

        if method == 'Part Payment':
            rem = max(0.0, round(due - paid, 2))
            self._chg_lbl.setText('Balance Due')
            self._chg.setText(f'{self._currency} {rem:,.2f}')
            tone = ok_color if rem < 0.01 else warn_color
            self._chg.setStyleSheet(
                f"color:{tone};font-size:{chg_sz};font-weight:700;background:transparent;")
        elif AutoFillService.is_cash_like(method) or method in ('Credit Sale', 'Credit Account'):
            elec = self._elec_portion() if self._is_split_method(method) else 0.0
            # Split: Change/Remaining is vs cash portion only
            compare_due = self._cash_due_amount() if elec > 0.009 else due
            st = AutoFillService.cash_change_state(paid, compare_due)
            if elec > 0.009 and st.get('tone') == 'err':
                # Remaining on total bill when cash short
                rem_total = max(0.0, round(due - elec - paid, 2))
                if rem_total > 0.009:
                    self._chg_lbl.setText('Remaining')
                    self._chg.setText(f'{self._currency} {rem_total:,.2f}')
                    self._chg.setStyleSheet(
                        f"color:{err_color};font-size:{chg_sz};font-weight:700;background:transparent;")
                else:
                    self._chg_lbl.setText(st['label'])
                    self._chg.setText(f"{self._currency} {st['amount']:,.2f}")
                    self._chg.setStyleSheet(
                        f"color:{err_color};font-size:{chg_sz};font-weight:700;background:transparent;")
            else:
                self._chg_lbl.setText(st['label'])
                self._chg.setText(f"{self._currency} {st['amount']:,.2f}")
                color = {'ok': ok_color, 'warn': warn_color, 'err': err_color}.get(
                    st['tone'], ok_color)
                self._chg.setStyleSheet(
                    f"color:{color};font-size:{chg_sz};font-weight:700;background:transparent;")
            # Keep split summary in sync when Cash Paid edits
            if hasattr(self, '_split_frame') and self._split_frame.isVisible():
                self._update_rounding_ui()
        else:
            # M-Pesa Difference label handled below; keep Change neutral when hidden
            chg = max(0.0, paid - due)
            self._chg.setText(f'{self._currency} {chg:,.2f}')
            self._chg.setStyleSheet(
                f"color:{ok_color if paid >= due or due == 0 else err_color};"
                f"font-size:{chg_sz};font-weight:700;background:transparent;")

        if hasattr(self, '_var_frame') and self._is_till_method():
            self._expected_lbl.setText(f'Expected Amount: {self._currency} {due:,.2f}')
            self._received_lbl.setText(f'Received Amount: {self._currency} {paid:,.2f}')
            diff = round(paid - due, 2)
            if diff > 0.009:
                self._diff_lbl.setText(
                    f'Difference: {self._currency} {diff:,.2f} excess — choose handling at checkout')
                self._diff_lbl.setStyleSheet(
                    f"color:{warn_color};font-size:12px;font-weight:700;background:transparent;")
            elif diff < -0.009:
                self._diff_lbl.setText(
                    f'Difference: {self._currency} {diff:,.2f} short')
                self._diff_lbl.setStyleSheet(
                    f"color:{err_color};font-size:12px;font-weight:700;background:transparent;")
            else:
                self._diff_lbl.setText(f'Difference: {self._currency} 0.00')
                self._diff_lbl.setStyleSheet(
                    f"color:{ok_color};font-size:12px;font-weight:600;background:transparent;")

    def _clear(self):
        """Manual Clear cart — full After Sale defaults (Walk-in, Cash, focus)."""
        from desktop.utils.state_reset import StateResetManager
        cfg = {}
        try:
            cfg = self.config_getter() or {}
        except Exception:
            pass
        StateResetManager.reset_pos(self, cfg, force_walk_in=True)

    def _process(self):
        if not self.cart:
            _sfx('warning')
            QMessageBox.warning(self, 'Empty Cart', 'Add items before charging.'); return
        pay_method = self._pay.currentText()
        is_debt = pay_method in ('Part Payment', 'Credit Sale', 'Credit Account')
        due = self._amount_due()
        credit_applied = round(float(self._credit_to_apply or 0), 2)
        cfg = self.config_getter() or {}
        variance_enabled = cfg.get('variance_enabled', '1') == '1'

        if pay_method in ('Cash', 'Mixed'):
            elec = self._elec_portion()
            cash_due = self._cash_due_amount()
            cash_paid = float(self._paid.value() or 0)
            if elec > 0.009:
                if cash_paid + 0.009 < cash_due:
                    em = self._elec_method_name()
                    QMessageBox.warning(
                        self, 'Insufficient',
                        f'Cash Paid is less than the cash portion due '
                        f'({self._currency} {cash_due:,.2f}).\n\n'
                        f'{em}: {self._currency} {elec:,.2f}\n'
                        f'Cash due: {self._currency} {cash_due:,.2f}')
                    return
            elif cash_paid + 0.009 < due:
                QMessageBox.warning(
                    self, 'Insufficient',
                    'Cash Paid is less than Amount Due.\n\n'
                    'Pay the remainder in cash, use Split payment '
                    '(Electronic + Cash), or use Part Payment / Credit Sale.')
                return
        if pay_method == 'Part Payment' and self._paid.value() >= self._total:
            QMessageBox.information(
                self, 'No Balance',
                'Amount paid covers the full total — use "Cash" instead of "Part Payment".')
            return
        if pay_method == 'M-Pesa':
            if not cfg.get('mpesa_till', '').strip() and not cfg.get('mpesa_paybill', '').strip():
                r = QMessageBox.question(
                    self, 'M-Pesa Not Configured',
                    'Till/Paybill is not set in Settings.\n\nRecord sale anyway?',
                    QMessageBox.Yes | QMessageBox.No)
                if r != QMessageBox.Yes:
                    return
            if self._paid.value() + 0.009 < due:
                QMessageBox.warning(
                    self, 'Insufficient',
                    f'Received Amount is less than Expected ({self._currency} {due:,.2f}).')
                return

        # Amount actually collected via payment method (Till / cash / card)
        if pay_method in ('Credit Sale', 'Credit Account'):
            paid_now = 0.0
            cash_paid_now = 0.0
            elec_now = 0.0
        else:
            cash_paid_now = float(self._paid.value() or 0)
            elec_now = self._elec_portion() if self._is_split_method(pay_method) else 0.0
            # amount_paid = total tendered (both methods when split)
            paid_now = round(cash_paid_now + elec_now, 2) if elec_now > 0.009 else cash_paid_now
        elec_method_name = self._elec_method_name() if elec_now > 0.009 else ''

        cust_id = None
        if hasattr(self, '_customer'):
            cust_id = self._customer.selected_id()
        if is_debt and not cust_id:
            from desktop.dialogs.credit_customer_dialogs import ensure_credit_customer
            cust_id = ensure_credit_customer(self, self.api)
            if not cust_id:
                return
            # Reload customers and assign without leaving POS / clearing cart
            try:
                customers = self.api.get_customers() or []
                self._wallet_by_customer = {
                    c['id']: float(c.get('wallet_balance') or 0)
                    for c in customers if c.get('id')
                }
                self._customer.load_customers(customers)
                if hasattr(self._customer, 'select_customer'):
                    self._customer.select_customer(cust_id)
                else:
                    idx = self._customer.findData(cust_id)
                    if idx >= 0:
                        self._customer.setCurrentIndex(idx)
                self._on_customer_changed()
            except Exception:
                pass
        if credit_applied > 0.009 and not cust_id:
            QMessageBox.warning(
                self, 'Customer Required',
                'Select a customer to apply store credit.')
            return

        variance_payload = None
        change_amount = 0.0
        # Till variance uses full paid vs due; cash split uses cash overpayment only
        if self._is_till_method(pay_method):
            excess = round(paid_now - due, 2) if not is_debt else 0.0
        elif self._is_split_method(pay_method) and elec_now > 0.009:
            excess = round(cash_paid_now - self._cash_due_amount(), 2) if not is_debt else 0.0
        else:
            excess = round(paid_now - due, 2) if not is_debt else 0.0

        _cash_like_excess = (
            pay_method == 'Cash'
            or (hasattr(self, '_is_split_method') and self._is_split_method(pay_method))
        )
        if variance_enabled and excess > 0.009 and (
                self._is_till_method(pay_method) or _cash_like_excess):
            from desktop.dialogs.payment_variance_dialog import PaymentVarianceDialog
            cust_name = ''
            if cust_id and hasattr(self, '_customer'):
                cust_name = self._customer.currentText().split('  ·  ')[0]
            dlg = PaymentVarianceDialog(
                self, self._currency, due, paid_now, excess,
                settings=cfg, has_customer=bool(cust_id),
                customer_name=cust_name)
            if dlg.exec_() != QDialog.Accepted or not dlg.result_data:
                return
            variance_payload = dlg.result_data
            # Manager approval when excess above threshold
            try:
                max_cash = float(cfg.get('variance_max_cashier', 1000) or 1000)
            except (TypeError, ValueError):
                max_cash = 1000.0
            if excess > max_cash + 0.009:
                from desktop.utils.security import ask_superadmin_pin, has_permission
                role_ok = has_permission(self.user, 'sales.variance_approve')
                if not role_ok:
                    if not ask_superadmin_pin(
                        self.api, self,
                        reason=f'Approve variance {self._currency} {excess:,.2f}'):
                        return
                    variance_payload['manager_approved'] = True
                    variance_payload['manager_name'] = 'superadmin-pin'
                else:
                    u = self.user.get('user', {}) if isinstance(self.user, dict) else {}
                    variance_payload['manager_approved'] = True
                    variance_payload['manager_name'] = (
                        u.get('full_name') or u.get('username') or 'manager')
            if variance_payload.get('handling') == 'return_change':
                change_amount = excess
            # Confirm till payment with split description
            handle_label = {
                'return_change': 'Return Change',
                'deposit': 'Customer Deposit',
                'transport': 'Transport/Delivery Fee',
                'tip': 'Tip',
                'advance': 'Advance Payment',
                'miscellaneous': 'Miscellaneous',
            }.get(variance_payload['handling'], variance_payload['handling'])
            if self._is_till_method(pay_method) and QMessageBox.question(
                self, 'Confirm M-Pesa',
                f'Confirm customer paid {self._currency} {paid_now:,.2f} via M-Pesa?\n\n'
                f'Sale: {self._currency} {self._total:,.2f}\n'
                f'Credit applied: {self._currency} {credit_applied:,.2f}\n'
                f'Excess {self._currency} {excess:,.2f} → {handle_label}',
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        elif pay_method == 'M-Pesa':
            if QMessageBox.question(
                self, 'Confirm M-Pesa',
                f'Confirm customer paid {self._currency} {paid_now:,.2f} via M-Pesa?',
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            # Variance disabled: treat excess as change returned (do not inflate sales)
            change_amount = max(0.0, excess)
        elif not is_debt and not variance_payload:
            if self._is_split_method(pay_method) and elec_now > 0.009:
                change_amount = max(0.0, round(cash_paid_now - self._cash_due_amount(), 2))
            else:
                change_amount = max(0.0, paid_now - due)

        try:
            info = self._compute_rounding()
            round_adj = float(info.get('adjustment') or 0)
            original_due = float(info.get('original_due', due))
            payable = float(info.get('amount_due', due))
            # Use rounded due for cash validation already done via _amount_due()
            final_total = round(float(info.get('cart_total', self._total)) + round_adj, 2)
            # When credit applied, final_total for storage = cart + adj (credit separate)
            cart_total = float(info.get('cart_total', self._total))
            sale_total = round(cart_total + round_adj, 2) if abs(round_adj) > 0.009 else cart_total
            elec = float(info.get('electronic') or elec_now or 0)
            is_split = elec > 0.009 and self._is_split_method(pay_method)
            pay_label = (
                'mixed' if is_split
                else (pay_method.lower() if pay_method else 'cash')
            )
            note_bits = [self._note.text().strip()]
            if is_split:
                note_bits.append(
                    f'Split: {elec_method_name} {elec:,.2f} + Cash {cash_paid_now:,.2f}')
            notes_joined = ' | '.join(b for b in note_bits if b)
            sale_payload = {
                'items':          self.cart,
                'subtotal':       self._subtotal,
                'discount':       self._discount,
                'tax':            self._tax,
                'total':          sale_total,
                'original_total': cart_total,
                'cash_rounding_adj': round_adj,
                'electronic_paid': elec,
                'electronic_method': elec_method_name if is_split else '',
                'cash_paid':      cash_paid_now if is_split else paid_now,
                'cash_original':  float(info.get('cash_original') or 0),
                'cash_rounded':   float(info.get('cash_rounded') or 0),
                'payment_method': pay_label,
                'amount_paid':    paid_now,
                'change_amount':  change_amount,
                'credit_applied': credit_applied,
                'notes':          notes_joined,
                'mpesa_ref':      self._mpesa_ref.text().strip() if pay_method == 'M-Pesa' else '',
            }
            if cust_id:
                sale_payload['customer_id'] = cust_id
            if variance_payload:
                sale_payload['variance'] = variance_payload
            res = self.api.create_sale(sale_payload)
            if res and res.get('success'):
                rn  = res.get('receipt_number', 'N/A')
                sid = res.get('sale_id')
                self._last_sale_id = sid
                self._last_receipt = rn
                try:
                    from desktop.utils.audio_manager import get_audio
                    get_audio().play_payment(pay_method)
                    _sfx('sale_complete')
                except Exception:
                    _sfx('sale_complete')
                # Part Payment / Credit Sale → create a debt invoice for the balance
                if is_debt:
                    self._create_debt_invoice(
                        sale_id=sid,
                        receipt_number=rn,
                        total=cart_total,
                        paid=paid_now + credit_applied,
                        method=pay_method,
                    )
                else:
                    msg = (
                        f'✓  Sale recorded\n\nInvoice:  {rn}\n'
                        f'Total:    {self._currency} {sale_total:,.2f}\n'
                    )
                    if is_split:
                        msg += (
                            f'{elec_method_name}: {self._currency} {elec:,.2f}\n'
                            f'Cash:     {self._currency} {cash_paid_now:,.2f}\n'
                        )
                    else:
                        msg += f'Received: {self._currency} {paid_now:,.2f}\n'
                    if abs(round_adj) > 0.009:
                        msg += (
                            f'Original: {self._currency} {cart_total:,.2f}\n'
                            f'Rounding: {self._currency} {round_adj:+,.2f}\n'
                        )
                    if credit_applied > 0:
                        msg += f'Credit used: {self._currency} {credit_applied:,.2f}\n'
                    if variance_payload:
                        h = variance_payload.get('handling')
                        msg += f'Excess:   {self._currency} {excess:,.2f} → {h}\n'
                        wb = res.get('wallet_balance')
                        if wb is not None:
                            msg += f'Wallet:   {self._currency} {float(wb):,.2f}\n'
                    elif change_amount > 0:
                        msg += f'Change:   {self._currency} {change_amount:,.2f}\n'
                    QMessageBox.information(self, 'Sale Complete', msg)
                self._try_print_receipt(sid, rn)
                # Refresh stock/products first, then force After Sale defaults
                # (Walk-in must win after credit sale — do not leave John selected).
                self.refresh()
                from desktop.utils.state_reset import StateResetManager
                cfg = {}
                try:
                    cfg = self.config_getter() or {}
                except Exception:
                    pass
                StateResetManager.reset_pos(self, cfg, force_walk_in=True)
                self.sale_completed.emit()
            else:
                err = (res or {}).get('error') if isinstance(res, dict) else None
                _sfx('error')
                QMessageBox.critical(self, 'Error', err or 'Failed to record sale.')
        except Exception as e:
            _sfx('error')
            QMessageBox.critical(self, 'Error', str(e))

    def _get_printer(self):
        if self._printer_mgr is None:
            from printing.printer_engine import PrinterManager
            self._printer_mgr = PrinterManager(self.config_getter)
        return self._printer_mgr

    def _build_print_data(self, sale_id, receipt_number=None):
        sale = self.api.get_sale(sale_id) if sale_id else {}
        if not sale:
            return None
        elec = float(sale.get('electronic_paid') or 0)
        notes = sale.get('notes', '') or ''
        elec_method = (sale.get('electronic_method') or '').strip()
        if not elec_method and elec > 0.009 and 'Split:' in notes:
            # "Split: M-Pesa 600.00 + Cash 400.00"
            try:
                part = notes.split('Split:', 1)[1].strip()
                elec_method = part.split()[0]
            except Exception:
                elec_method = 'Electronic'
        cash_paid = float(sale.get('cash_paid') or 0)
        if cash_paid < 0.009 and elec > 0.009:
            cash_paid = max(0.0, round(float(sale.get('amount_paid') or 0) - elec, 2))
        return {
            'receipt_number': receipt_number or sale.get('receipt_number', ''),
            'created_at':     sale.get('created_at', datetime.now().isoformat()),
            'cashier_name':   sale.get('cashier_name', ''),
            'items':          sale.get('items', []),
            'subtotal':       float(sale.get('subtotal') or 0),
            'discount':       float(sale.get('discount') or 0),
            'tax':            float(sale.get('tax') or 0),
            'total':          float(sale.get('total') or 0),
            'original_total': float(sale.get('original_total') or 0) or None,
            'cash_rounding_adj': float(sale.get('cash_rounding_adj') or 0),
            'payment_method': sale.get('payment_method', 'cash'),
            'amount_paid':    float(sale.get('amount_paid') or 0),
            'change_amount':  float(sale.get('change_amount') or 0),
            'credit_applied': float(sale.get('credit_applied') or 0),
            'customer_name':  sale.get('customer_name', '') or '',
            'wallet_balance': sale.get('wallet_balance'),
            'variance':       sale.get('variance') or {},
            'notes':          notes,
            'electronic_paid': elec,
            'electronic_method': elec_method,
            'cash_paid': cash_paid,
            'mpesa_till':     (self.config_getter() or {}).get('mpesa_till', ''),
            'mpesa_paybill':  (self.config_getter() or {}).get('mpesa_paybill', ''),
            'mpesa_ref':      sale.get('mpesa_ref', '') or '',
            'receipt_footer': (self.config_getter() or {}).get('receipt_footer', 'Thank you!'),
        }

    def _try_print_receipt(self, sale_id, receipt_number):
        """Print receipt after sale — failures never affect the recorded sale."""
        cfg = self.config_getter() or {}
        if cfg.get('auto_print', '1') != '1':
            return
        try:
            data = self._build_print_data(sale_id, receipt_number)
            if data:
                self._get_printer().print_receipt(data)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                'Receipt print failed (sale %s kept): %s', receipt_number, e)

    def _reprint_receipt(self):
        default = self._last_receipt or ''
        receipt, ok = QInputDialog.getText(
            self, 'Reprint Receipt',
            'Receipt number to reprint:',
            text=default)
        if not ok or not receipt.strip():
            return
        receipt = receipt.strip()
        try:
            from desktop.utils.api_client import _db
            db = _db()
            row = db.execute(
                "SELECT id, status FROM sales WHERE receipt_number=?", (receipt,)
            ).fetchone()
            db.close()
            if not row:
                QMessageBox.warning(self, 'Not Found',
                                    f'No sale found: {receipt}')
                return
            if row['status'] == 'voided':
                QMessageBox.warning(self, 'Voided',
                                    'This sale was voided — receipt not reprinted.')
                return
            data = self._build_print_data(row['id'], receipt)
            if not data:
                QMessageBox.warning(self, 'Error', 'Could not load sale data.')
                return
            self._get_printer().print_receipt(data)
            QMessageBox.information(self, 'Sent',
                                    f'Receipt {receipt} sent to printer queue.')
        except Exception as e:
            QMessageBox.warning(self, 'Print Error', str(e))

    def _void_sale(self):
        """Void a completed sale from POS (reason dropdown + Super-Admin PIN)."""
        from desktop.utils.security import prompt_void_sale
        prefill = getattr(self, '_last_receipt', '') or ''
        if prompt_void_sale(self.api, self, receipt_prefill=prefill):
            _sfx('void')
            self.sale_completed.emit()

    def _create_debt_invoice(self, sale_id, receipt_number, total, paid, method):
        """Auto-create debt linked to this completed sale (no orphan path)."""
        cust_id = None
        if hasattr(self, '_customer'):
            cust_id = self._customer.selected_id()
        if not cust_id or not sale_id or not receipt_number:
            QMessageBox.critical(
                self, 'Debt Invoice Error',
                'The sale was recorded but debt could not be created '
                '(missing customer, sale, or receipt).\n\n'
                'Contact an admin — do not create orphan debts from Debt Management.')
            return
        try:
            from datetime import date as _date, timedelta as _td
            res = self.api.create_debt_invoice({
                'customer_id': cust_id,
                'sale_id': sale_id,
                'receipt_number': receipt_number,
                'total_amount': total,
                'amount_paid': paid,
                'payment_method': (method or 'credit sale').lower(),
                'due_date': (_date.today() + _td(days=30)).isoformat(),
                'notes': f'Auto from POS {method}',
            })
            if res and res.get('success'):
                bal = float(res.get('balance') or 0)
                inv = res.get('invoice_number', '')
                msg = (
                    f'✓  Credit sale recorded\n\n'
                    f'Receipt:  {receipt_number}\n'
                    f'Debt Inv: {inv}\n'
                    f'Total:    {self._currency} {total:,.2f}\n'
                    f'Paid now: {self._currency} {paid:,.2f}\n'
                    f'Balance:  {self._currency} {bal:,.2f}\n'
                )
                if bal <= 0.009:
                    msg += '\n✓ Fully paid'
                else:
                    msg += '\n⚠ Outstanding balance due'
                QMessageBox.information(self, 'Sale Complete', msg)
            else:
                err = (res or {}).get('error', 'Failed to create debt invoice.')
                QMessageBox.critical(
                    self, 'Debt Invoice Error',
                    f'The sale was recorded ({receipt_number}).\n'
                    f'Debt create failed: {err}')
        except Exception as e:
            QMessageBox.critical(
                self, 'Debt Invoice Error',
                f'The sale was recorded ({receipt_number}).\n'
                f'Failed to create debt: {e}')

    def _get_debt_parent(self):
        """Minimal proxy so debt dialogs get api + currency."""
        class _Proxy:
            pass
        p = _Proxy()
        p.api = self.api
        p._currency = self._currency
        return p

    def _preview(self):
        if not self.cart:
            QMessageBox.information(self, 'Empty', 'Add items to preview.'); return
        try:
            from printing.printer_engine import generate_receipt_text
            cfg  = self.config_getter() or {}
            u    = self.user.get('user', {})
            info = self._compute_rounding()
            data = {
                'receipt_number': 'PREVIEW',
                'created_at':     datetime.now().isoformat(),
                'cashier_name':   u.get('full_name') or u.get('username', 'Staff'),
                'items':          self.cart,
                'subtotal':       self._subtotal,
                'discount':       self._discount,
                'tax':            self._tax,
                'total':          float(info.get('amount_due', self._total)) + float(self._credit_to_apply or 0)
                                  if abs(float(info.get('adjustment') or 0)) > 0.009
                                  else self._total,
                'original_total': float(info.get('cart_total', self._total)),
                'cash_rounding_adj': float(info.get('adjustment') or 0),
                'payment_method': self._pay.currentText(),
                'amount_paid':    self._paid.value(),
                'change_amount':  max(0.0, self._paid.value() - self._amount_due()),
                'credit_applied': float(self._credit_to_apply or 0),
                'receipt_footer': cfg.get('receipt_footer', 'Thank you!'),
                'mpesa_till':     cfg.get('mpesa_till', ''),
                'mpesa_paybill':  cfg.get('mpesa_paybill', ''),
                'mpesa_ref':      self._mpesa_ref.text().strip(),
            }
            if hasattr(self, '_customer') and self._customer.selected_id():
                data['customer_name'] = self._customer.currentText().split('  ·  ')[0]
            txt = generate_receipt_text(data, cfg.get('shop_name', 'My Shop'), self._currency)
            dlg = QDialog(self); dlg.setWindowTitle('Invoice Preview')
            dlg.resize(480, 580); lv = QVBoxLayout(dlg)
            te = QTextEdit(); te.setReadOnly(True); te.setFont(QFont('Consolas', 11))
            te.setStyleSheet(f"background:{C['app']};color:{C['text']};border:none;")
            te.setPlainText(txt); lv.addWidget(te)
            cb = SecondaryBtn('Close'); cb.clicked.connect(dlg.close); lv.addWidget(cb)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, 'Preview Error', str(e))
