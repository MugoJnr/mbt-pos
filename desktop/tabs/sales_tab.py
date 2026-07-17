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
        self._currency = 'KES'
        self._is_light  = bool(ThemeManager.is_light())
        self._last_sale_id = None
        self._last_receipt = ''
        self._printer_mgr = None
        self._build()
        # Defer product grid load so MainWindow can paint first (avoids hang)
        QTimer.singleShot(400, self.refresh)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        root.setSpacing(GAP - 2)

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
        self._cat.setMinimumHeight(42)
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
            f"border:1px solid {C['border']}; border-radius:12px; }}")
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
        # Disc = KES per line. Wide enough for prefix "- " + "0.00" / "9999.99".
        hdr = self._ctbl.horizontalHeader()
        hdr.setMinimumSectionSize(40)
        self._ctbl.setColumnWidth(0, 200)
        for ci, w in [(1, 118), (2, 90), (3, 140), (4, 92), (5, 42)]:
            hdr.setSectionResizeMode(ci, QHeaderView.Fixed)
            self._ctbl.setColumnWidth(ci, w)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        self._ctbl.setWordWrap(False)
        self._ctbl.setTextElideMode(Qt.ElideNone)
        self._ctbl.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._ctbl.setAlternatingRowColors(True)
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
        cust_row.addWidget(self._cust_lbl)
        cust_row.addWidget(self._customer, 1)
        cbl.addLayout(cust_row)

        pay = QHBoxLayout(); pay.setSpacing(8)
        self._pay_lbl = QLabel('Method')
        self._pay_lbl.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        self._pay = QComboBox()
        self._pay.addItems(['Cash', 'M-Pesa', 'Card', 'Cheque',
                            'Part Payment', 'Credit Sale'])
        self._pay.setMinimumHeight(40); self._pay.setMinimumWidth(120)
        self._pay.currentTextChanged.connect(self._on_payment_changed)
        self._paid = QDoubleSpinBox(); self._paid.setRange(0, 99999999)
        self._paid.setDecimals(2); self._paid.setMinimumHeight(40)
        self._paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._paid.valueChanged.connect(self._calc_change)
        pay.addWidget(self._pay_lbl); pay.addWidget(self._pay); pay.addWidget(self._paid, 1)
        cbl.addLayout(pay)

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

        br = QHBoxLayout(); br.setSpacing(8)
        self._clr_btn = DangerBtn('🗑', 40); self._clr_btn.setFixedWidth(44)
        self._clr_btn.setToolTip('Clear cart'); self._clr_btn.clicked.connect(self._clear)
        self._prv_btn = SecondaryBtn('🖨  Preview', 40)
        self._prv_btn.clicked.connect(self._preview)
        self._reprint_btn = SecondaryBtn('🖨  Reprint', 40)
        self._reprint_btn.setToolTip('Reprint a completed receipt')
        self._reprint_btn.clicked.connect(self._reprint_receipt)
        br.addWidget(self._clr_btn); br.addWidget(self._prv_btn, 1)
        br.addWidget(self._reprint_btn)
        cbl.addLayout(br)

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
        fl.setContentsMargins(16, 12, 16, 14)
        fl.setSpacing(0)
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

    def _on_payment_changed(self, method: str):
        if hasattr(self, '_pay_seg') and method in ('Cash', 'M-Pesa', 'Card'):
            self._pay_seg.select(method, emit=False)
        if hasattr(self, '_pay_btns'):
            for k, b in self._pay_btns.items():
                b.blockSignals(True)
                b.setChecked(k == method)
                b.blockSignals(False)
        is_mpesa = method == 'M-Pesa'
        self._mpesa_frame.setVisible(is_mpesa)
        if is_mpesa:
            cfg = self.config_getter() or {}
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
            self._paid.setValue(self._total)
            self._paid.setEnabled(False)
        elif method == 'Credit Sale':
            # Full amount on credit — nothing paid now
            self._paid.setValue(0.0)
            self._paid.setEnabled(False)
            self._mpesa_ref.clear()
        else:
            # Cash / Card / Cheque / Part Payment — cashier enters amount paid
            self._paid.setEnabled(True)
            self._mpesa_ref.clear()

    def refresh(self):
        try: self.products = self.api.get_products() or []
        except Exception: self.products = []
        try:
            self._currency = (self.config_getter() or {}).get('currency_symbol', 'KES') or 'KES'
        except Exception: pass
        try:
            customers = self.api.get_customers() or []
            if hasattr(self, '_customer'):
                self._customer.load_customers(customers)
        except Exception:
            pass
        cats = sorted({p.get('category') or 'General' for p in self.products})
        self._cat.blockSignals(True)
        cur = self._cat.currentText()
        self._cat.clear(); self._cat.addItem('All Categories')
        for c in cats: self._cat.addItem(c)
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
                QMessageBox.information(self, 'Out of stock',
                                        f'{(hit.get("name") or "Item")} is out of stock.')
            else:
                self._add(hit)
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

    def _add(self, p):
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
        from desktop.utils.pos_light_theme import fmt, SPINBOX, REMOVE_BTN, L
        from desktop.utils.theme import DARK, LIGHT, ThemeManager
        self._ctbl.setRowCount(0)
        light = bool(getattr(self, '_is_light', False) or ThemeManager.is_light())
        item_color = self._cart_fg()
        # Keep table QSS in sync so QTableWidgetItem + labels stay readable
        if light:
            self._ctbl.setStyleSheet(fmt(
                "QTableWidget{{background:#FFFFFF;border:2px solid {border2};"
                "border-radius:10px;color:{text};font-size:{font_cart};font-weight:700;"
                "alternate-background-color:{card2};gridline-color:transparent;}}"
                "QTableWidget::item{{color:{text};padding:10px 10px;background:transparent;}}"
                "QHeaderView::section{{background:{card2};color:{text};font-size:{font_cart_head};"
                "font-weight:800;letter-spacing:0.6px;padding:10px 8px;border:none;"
                "border-bottom:2px solid {border2};}}"
            ))
        else:
            self._ctbl.setStyleSheet(
                f"QTableWidget{{background:{DARK['card']};border:1px solid {DARK['border2']};"
                f"border-radius:10px;color:#F5F7FA;font-size:15px;font-weight:700;"
                f"alternate-background-color:{DARK['card2']};"
                f"gridline-color:transparent;}}"
                f"QTableWidget::item{{color:#F5F7FA;padding:10px 10px;background:transparent;}}"
                f"QHeaderView::section{{background:{DARK['panel']};color:#C5D0E0;"
                f"font-size:12px;font-weight:800;letter-spacing:0.6px;padding:10px 8px;"
                f"border:none;border-bottom:1px solid {DARK['border2']};}}"
            )
        for i, item in enumerate(self.cart):
            self._ctbl.insertRow(i)
            full_name = item['product_name']
            name_lbl = QLabel(full_name)
            name_lbl.setWordWrap(False)
            name_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            name_lbl.setToolTip(full_name)
            name_lbl.setMinimumWidth(80)
            name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            name_lbl.setStyleSheet(
                f"QLabel{{color:{item_color}; background:transparent; "
                f"font-size:15px; font-weight:800; padding-left:4px;}}"
            )
            name_wrap = QWidget()
            name_wrap.setMinimumWidth(80)
            nw_lay = QVBoxLayout(name_wrap)
            nw_lay.setContentsMargins(2, 0, 2, 0)
            nw_lay.setSpacing(0)
            nw_lay.addWidget(name_lbl, 0, Qt.AlignVCenter)
            self._ctbl.setCellWidget(i, 0, name_wrap)
            # Elide after column has a real width
            col_w = max(80, self._ctbl.columnWidth(0) - 12)
            name_lbl.setText(name_lbl.fontMetrics().elidedText(full_name, Qt.ElideRight, col_w))
            # Qty editor: modular QuantityControl (0.25 step, 2 decimals)
            qty = QuantityControl(value=float(item['quantity']), step=0.25)
            qty.valueChanged.connect(lambda v, idx=i: self._qty(idx, v))
            cell_wrap = QWidget()
            cw_lay = QHBoxLayout(cell_wrap)
            cw_lay.setContentsMargins(0, 0, 0, 0)
            cw_lay.setSpacing(0)
            cw_lay.addWidget(qty, 0, Qt.AlignCenter)
            self._ctbl.setCellWidget(i, 1, cell_wrap)
            self._ctbl.setItem(i, 2, tbl_right(f'{item["unit_price"]:,.2f}', color=item_color))

            # Disc (KES) — QLineEdit (spinbox was rejecting typed values / stuck on 0.00)
            self._apply_line_total(item)
            disc_bg = LIGHT['input'] if light else DARK['input']
            disc_fg = item_color
            disc_bd = LIGHT['border2'] if light else DARK['border2']
            disc_gold = LIGHT['gold'] if light else DARK['gold']

            disc_ed = _KesEdit()
            disc_ed.setObjectName('lineDisc')
            disc_ed.setText(f"{float(item.get('discount') or 0):.2f}")
            disc_ed.setFixedSize(78, 32)
            disc_ed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            disc_ed.setPlaceholderText('0')
            disc_ed.setToolTip('Click, type amount e.g. 60, press Enter')
            disc_ed.setStyleSheet(
                f"QLineEdit#lineDisc{{"
                f"background:{disc_bg};color:{disc_fg};"
                f"border:1px solid {disc_bd};border-radius:6px;"
                f"padding:0px 6px;font-size:13px;font-weight:700;}}"
                f"QLineEdit#lineDisc:focus{{border-color:{disc_gold};}}"
            )
            disc_ed.editingFinished.connect(
                lambda idx=i, ed=disc_ed: self._commit_line_disc_text(idx, ed))
            disc_ed.returnPressed.connect(
                lambda idx=i, ed=disc_ed: self._commit_line_disc_text(idx, ed))

            d_minus = QPushButton('-')
            d_plus = QPushButton('+')
            for b in (d_minus, d_plus):
                b.setFixedSize(28, 32)
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet(
                    f"QPushButton{{background:{disc_bg};color:{disc_fg};"
                    f"border:1px solid {disc_bd};border-radius:6px;"
                    f"font-size:14px;font-weight:800;padding:0;}}"
                    f"QPushButton:hover{{border-color:{disc_gold};color:{disc_gold};}}"
                )
            d_minus.clicked.connect(lambda _, idx=i: self._bump_line_disc(idx, -10))
            d_plus.clicked.connect(lambda _, idx=i: self._bump_line_disc(idx, 10))

            disc_wrap = QWidget()
            disc_wrap.setMinimumWidth(136)
            dw_lay = QHBoxLayout(disc_wrap)
            dw_lay.setContentsMargins(2, 0, 2, 0)
            dw_lay.setSpacing(3)
            dw_lay.addWidget(d_minus, 0, Qt.AlignVCenter)
            dw_lay.addWidget(disc_ed, 1, Qt.AlignVCenter)
            dw_lay.addWidget(d_plus, 0, Qt.AlignVCenter)
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
            self._ctbl.setRowHeight(i, 52)

        # Re-elide names with real column width (avoids mid-word cuts looking broken)
        name_w = max(100, int(self._ctbl.columnWidth(0)) - 16)
        for i, item in enumerate(self.cart):
            wrap = self._ctbl.cellWidget(i, 0)
            if wrap is None:
                continue
            lbl = wrap.findChild(QLabel)
            if lbl is None:
                continue
            full = item.get('product_name') or ''
            lbl.setToolTip(full)
            lbl.setText(lbl.fontMetrics().elidedText(full, Qt.ElideRight, name_w))

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
            del self.cart[idx]; self._refresh_cart()

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
        self._calc_change()
        if self._pay.currentText() == 'M-Pesa':
            self._paid.setValue(tot)

    def _calc_change(self):
        paid = self._paid.value(); chg = max(0.0, paid - self._total)
        ok   = paid >= self._total or self._total == 0
        from desktop.utils.pos_light_theme import L, FS
        ok_color = L['ok'] if self._is_light else C['ok']
        err_color = L['err'] if self._is_light else C['err']
        chg_sz = FS['change'] if self._is_light else '16px'
        self._chg.setText(f'{self._currency} {chg:,.2f}')
        self._chg.setStyleSheet(
            f"color:{ok_color if ok else err_color};"
            f"font-size:{chg_sz};font-weight:700;background:transparent;")

    def _clear(self):
        self.cart.clear()
        self._disc.blockSignals(True)
        self._disc.setText('0.00')
        self._disc.blockSignals(False)
        self._paid.setValue(0)
        self._note.clear(); self._refresh_cart()

    def _process(self):
        if not self.cart:
            QMessageBox.warning(self, 'Empty Cart', 'Add items before charging.'); return
        pay_method = self._pay.currentText()
        is_debt = pay_method in ('Part Payment', 'Credit Sale')
        if pay_method == 'Cash' and self._paid.value() < self._total:
            QMessageBox.warning(self, 'Insufficient', 'Amount paid is less than total.'); return
        if pay_method == 'Part Payment' and self._paid.value() >= self._total:
            QMessageBox.information(
                self, 'No Balance',
                'Amount paid covers the full total — use "Cash" instead of "Part Payment".')
            return
        if pay_method == 'M-Pesa':
            cfg = self.config_getter() or {}
            if not cfg.get('mpesa_till', '').strip() and not cfg.get('mpesa_paybill', '').strip():
                r = QMessageBox.question(
                    self, 'M-Pesa Not Configured',
                    'Till/Paybill is not set in Settings.\n\nRecord sale anyway?',
                    QMessageBox.Yes | QMessageBox.No)
                if r != QMessageBox.Yes:
                    return
            if QMessageBox.question(
                self, 'Confirm M-Pesa',
                f'Confirm customer paid {self._currency} {self._total:,.2f} via M-Pesa?',
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        # Amount actually collected now
        if pay_method == 'M-Pesa':
            paid_now = self._total
        elif pay_method == 'Credit Sale':
            paid_now = 0.0
        else:
            paid_now = self._paid.value()
        cust_id = None
        if hasattr(self, '_customer'):
            cust_id = self._customer.selected_id()
        if is_debt and not cust_id:
            QMessageBox.warning(
                self, 'Customer Required',
                'Select a customer for Part Payment / Credit Sale.')
            return
        try:
            sale_payload = {
                'items':          self.cart,
                'subtotal':       self._subtotal,
                'discount':       self._discount,
                'tax':            self._tax,
                'total':          self._total,
                'payment_method': pay_method.lower(),
                'amount_paid':    paid_now,
                'change_amount':  0.0 if is_debt or pay_method == 'M-Pesa'
                                  else max(0.0, self._paid.value() - self._total),
                'notes':          self._note.text().strip(),
                'mpesa_ref':      self._mpesa_ref.text().strip() if pay_method == 'M-Pesa' else '',
            }
            if cust_id:
                sale_payload['customer_id'] = cust_id
            res = self.api.create_sale(sale_payload)
            if res and res.get('success'):
                rn  = res.get('receipt_number', 'N/A')
                sid = res.get('sale_id')
                self._last_sale_id = sid
                self._last_receipt = rn
                chg = max(0.0, self._paid.value() - self._total)
                # Part Payment / Credit Sale → create a debt invoice for the balance
                if is_debt:
                    self._create_debt_invoice(
                        sale_id=sid,
                        receipt_number=rn,
                        total=self._total,
                        paid=paid_now,
                        method=pay_method,
                    )
                else:
                    QMessageBox.information(self, 'Sale Complete',
                        f'✓  Sale recorded\n\nInvoice:  {rn}\n'
                        f'Total:    {self._currency} {self._total:,.2f}\n'
                        f'Change:   {self._currency} {chg:,.2f}')
                self._try_print_receipt(sid, rn)
                self._clear(); self.refresh()
                self.sale_completed.emit()
            else:
                QMessageBox.critical(self, 'Error', 'Failed to record sale.')
        except Exception as e:
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
        return {
            'receipt_number': receipt_number or sale.get('receipt_number', ''),
            'created_at':     sale.get('created_at', datetime.now().isoformat()),
            'cashier_name':   sale.get('cashier_name', ''),
            'items':          sale.get('items', []),
            'subtotal':       float(sale.get('subtotal') or 0),
            'discount':       float(sale.get('discount') or 0),
            'tax':            float(sale.get('tax') or 0),
            'total':          float(sale.get('total') or 0),
            'payment_method': sale.get('payment_method', 'cash'),
            'amount_paid':    float(sale.get('amount_paid') or 0),
            'change_amount':  float(sale.get('change_amount') or 0),
            'notes':          sale.get('notes', '') or '',
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

    def _create_debt_invoice(self, sale_id, receipt_number, total, paid, method):
        """Open the debt invoice dialog pre-filled from this sale."""
        try:
            from desktop.tabs.debt_tab import _NewInvoiceDialog
            dlg = _NewInvoiceDialog(
                self._get_debt_parent(),
                self,
                prefill_total=total,
                prefill_paid=paid,
                prefill_sale_id=sale_id,
                prefill_receipt=receipt_number,
            )
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, 'Debt Invoice Error',
                f'The sale was recorded.\nFailed to open the debt dialog: {e}\n\n'
                f'Go to Debt Management to create the invoice manually.')

    def _get_debt_parent(self):
        """Minimal proxy so _NewInvoiceDialog gets api + currency."""
        class _Proxy:
            pass
        p = _Proxy()
        p.api       = self.api
        p._currency = self._currency
        return p

    def _preview(self):
        if not self.cart:
            QMessageBox.information(self, 'Empty', 'Add items to preview.'); return
        try:
            from printing.printer_engine import generate_receipt_text
            cfg  = self.config_getter() or {}
            u    = self.user.get('user', {})
            data = {
                'receipt_number': 'PREVIEW',
                'created_at':     datetime.now().isoformat(),
                'cashier_name':   u.get('full_name') or u.get('username', 'Staff'),
                'items':          self.cart,
                'subtotal':       self._subtotal,
                'discount':       self._discount,
                'tax':            self._tax,
                'total':          self._total,
                'payment_method': self._pay.currentText(),
                'amount_paid':    self._paid.value(),
                'change_amount':  max(0.0, self._paid.value() - self._total),
                'receipt_footer': cfg.get('receipt_footer', 'Thank you!'),
                'mpesa_till':     cfg.get('mpesa_till', ''),
                'mpesa_paybill':  cfg.get('mpesa_paybill', ''),
                'mpesa_ref':      self._mpesa_ref.text().strip(),
            }
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
