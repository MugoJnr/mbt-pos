"""Build shared POS panels once — SalesTab owns business logic; panels are pure UI."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from desktop.utils.theme import C, RADIUS, PADDING, GAP, qss_alpha
from desktop.utils.widgets import H2, Caption, PrimaryBtn, SecondaryBtn, DangerBtn, IconBtn
from desktop.utils.pos_components import (
    ProductGrid, PaymentSegment, SummaryCard, CustomerCard, CartList, PosSearchBar,
)
from desktop.utils.option_lists import POS_PAYMENT_METHODS
from desktop.utils.select_controls import Select


class _KesEdit(QLineEdit):
    """KES amount field — select-all on focus so typing replaces without sip crashes."""

    def focusInEvent(self, e):
        super().focusInEvent(e)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self.selectAll)


def build_shared_panels(tab) -> None:
    """Create product / sale / actions panels and attach widgets onto ``tab``."""
    # ── Product browser ───────────────────────────────────────────────────────
    product = QFrame()
    product.setObjectName('posProductPanel')
    product.setAttribute(Qt.WA_StyledBackground, True)
    ll = QVBoxLayout(product)
    ll.setContentsMargins(0, 0, 0, 0)
    ll.setSpacing(0)

    # ── Business day bar (sale date) — visible on all checkout layouts ────────
    biz = QFrame()
    biz.setObjectName('posBusinessDayBar')
    biz.setAttribute(Qt.WA_StyledBackground, True)
    bf = QHBoxLayout(biz)
    bf.setContentsMargins(16, 8, 16, 8)
    bf.setSpacing(8)
    biz_lbl = QLabel('Business day')
    biz_lbl.setStyleSheet(
        f"color:{C['text2']};font-size:12px;font-weight:700;background:transparent;")
    bf.addWidget(biz_lbl)
    from desktop.utils.security import can_set_business_day
    from desktop.utils.shop_time import shop_today
    today = shop_today()
    tab._business_day = today
    tab._biz_date = QDateEdit()
    tab._biz_date.setCalendarPopup(True)
    tab._biz_date.setDisplayFormat('yyyy-MM-dd')
    tab._biz_date.setDate(QDate(today.year, today.month, today.day))
    tab._biz_date.setMaximumDate(QDate(today.year, today.month, today.day))
    tab._biz_date.setMinimumHeight(34)
    tab._biz_date.setMinimumWidth(130)
    can_biz = can_set_business_day(tab.user)
    tab._biz_date.setEnabled(can_biz)
    tab._biz_date.setToolTip(
        'Sale / reporting date (Nairobi shop calendar). Manager+ can backdate.'
        if can_biz else
        'Cashiers record sales for today only. Ask a manager to backdate.'
    )
    tab._biz_date.dateChanged.connect(tab._on_business_day_changed)
    bf.addWidget(tab._biz_date)
    tab._biz_today_btn = SecondaryBtn('Today', 32)
    tab._biz_today_btn.setEnabled(can_biz)
    tab._biz_today_btn.clicked.connect(tab._reset_business_day_today)
    bf.addWidget(tab._biz_today_btn)
    tab._biz_view_btn = SecondaryBtn('View day', 32)
    tab._biz_view_btn.setToolTip('View / adjust / copy sales for the selected business day')
    tab._biz_view_btn.clicked.connect(tab._open_business_day_sales)
    bf.addWidget(tab._biz_view_btn)
    tab._biz_copy_btn = SecondaryBtn('Copy sale…', 32)
    tab._biz_copy_btn.setToolTip('Copy a past sale’s lines into the cart for this business day')
    tab._biz_copy_btn.clicked.connect(tab._open_business_day_sales)
    bf.addWidget(tab._biz_copy_btn)
    tab._biz_warn = QLabel('')
    tab._biz_warn.setStyleSheet(
        f"color:{C.get('warn', '#D97706')};font-size:12px;font-weight:700;"
        f"background:transparent;")
    bf.addWidget(tab._biz_warn, 1)
    tab._business_day_bar = biz
    ll.addWidget(biz)

    search_bar = QWidget()
    search_bar.setStyleSheet(
        f"background:transparent; border-bottom:1px solid {C['border']};")
    sf = QHBoxLayout(search_bar)
    sf.setContentsMargins(16, 14, 16, 14)
    sf.setSpacing(10)
    tab._search = PosSearchBar()
    tab._search.textChanged.connect(tab._filter)
    tab._search.submitted.connect(tab._on_barcode_enter)
    sf.addWidget(tab._search, 1)
    tab._cat = QComboBox()
    tab._cat.setObjectName('posCatCombo')
    tab._cat.setMinimumHeight(44)
    tab._cat.setFixedWidth(220)
    from desktop.utils.pos_light_theme import style_cat_combo
    style_cat_combo(tab._cat, is_light=bool(getattr(tab, '_is_light', False)))
    tab._cat.addItem('All Categories')
    tab._cat.currentTextChanged.connect(tab._filter)
    sf.addWidget(tab._cat)
    ref = IconBtn('', 40, 40)
    try:
        from desktop.utils.nav_icons import apply_button_icon
        apply_button_icon(ref, 'refresh', 18)
    except Exception:
        pass
    ref.clicked.connect(lambda: tab.refresh(force=True))
    sf.addWidget(ref)
    tab._refresh_btn = ref
    tab._focus_btn = SecondaryBtn('Focus', 40)
    tab._focus_btn.setMinimumWidth(96)
    tab._focus_btn.setToolTip(
        'Maximize Point of Sale — hide sidebar and top bar. Esc or Restore to exit.')
    tab._focus_btn.clicked.connect(tab._toggle_focus_mode)
    sf.addWidget(tab._focus_btn)
    tab._theme_btn = None
    tab._search_bar = search_bar
    ll.addWidget(search_bar)

    scroll = QScrollArea()
    scroll.setObjectName('posProductScroll')
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
    from desktop.utils.no_wheel_small_scroll import mark_wheel_scroll
    mark_wheel_scroll(scroll, True)
    tab._prod_grid = ProductGrid()
    tab._prod_grid.productClicked.connect(tab._add)
    tab._gw = tab._prod_grid
    tab._grid = tab._prod_grid._grid
    scroll.setWidget(tab._prod_grid)
    tab._prod_scroll = scroll
    ll.addWidget(scroll, 1)

    tab._empty = QLabel(product)
    tab._empty.setText('No products.\nAdd products in Inventory.')
    tab._empty.setAlignment(Qt.AlignCenter)
    tab._empty.setStyleSheet(
        f"color:{C['muted']};font-size:14px;background:transparent;")
    tab._empty.hide()
    tab._empty.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    tab._product_panel = product
    tab._left_panel = product

    # ── Current Sale panel (cart + summary) ───────────────────────────────────
    sale = QFrame()
    sale.setObjectName('posSalePanel')
    sale.setAttribute(Qt.WA_StyledBackground, True)
    sl = QVBoxLayout(sale)
    sl.setContentsMargins(0, 0, 0, 0)
    sl.setSpacing(0)

    hdr = QWidget()
    hdr.setStyleSheet(f"border-bottom:1px solid {C['border']};")
    tab._cart_hdr = hdr
    ch = QHBoxLayout(hdr)
    ch.setContentsMargins(16, 14, 16, 14)
    tab._sale_hdr = H2('Current Sale')
    ch.addWidget(tab._sale_hdr)
    ch.addStretch()
    tab._cnt = Caption('0 items')
    ch.addWidget(tab._cnt)
    tab._cart_max_btn = SecondaryBtn('Review', 36)
    tab._cart_max_btn.setMinimumWidth(110)
    tab._cart_max_btn.setMinimumHeight(40)
    tab._cart_max_btn.setToolTip(
        'Enlarge the cart to review and edit many items. Esc or Restore to add products again.')
    tab._cart_max_btn.clicked.connect(tab._toggle_cart_maximized)
    ch.addWidget(tab._cart_max_btn)
    sl.addWidget(hdr)

    cart_scroll = QScrollArea()
    cart_scroll.setObjectName('posSaleCartScroll')
    cart_scroll.setWidgetResizable(True)
    cart_scroll.setFrameShape(QFrame.NoFrame)
    cart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    cart_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
    mark_wheel_scroll(cart_scroll, True)
    cart_host = QWidget()
    cart_host.setStyleSheet('background:transparent;')
    cbl = QVBoxLayout(cart_host)
    cbl.setContentsMargins(16, 12, 16, 12)
    cbl.setSpacing(8)

    tab._ctbl = None
    tab._cart_list = CartList()
    tab._cart_list.qtyChanged.connect(tab._qty)
    tab._cart_list.discChanged.connect(tab._set_line_disc)
    tab._cart_list.priceChanged.connect(tab._set_line_price)
    tab._cart_list.removeClicked.connect(tab._rm)
    tab._cart_select_idx = None
    cbl.addWidget(tab._cart_list, 1)
    cart_scroll.setWidget(cart_host)
    tab._sale_cart_scroll = cart_scroll
    sl.addWidget(cart_scroll, 1)

    # Pinned totals at bottom of sale panel
    sum_wrap = QWidget()
    sum_wrap.setStyleSheet(
        f"background:transparent;border-top:1px solid {C['border']};")
    swl = QVBoxLayout(sum_wrap)
    swl.setContentsMargins(16, 10, 16, 12)
    swl.setSpacing(8)
    tab._summary = SummaryCard()
    tab._tot_frame = tab._summary
    tab._sub_lbl = tab._summary._sub_lbl
    tab._tax_lbl = tab._summary._tax_lbl
    tab._tot_lbl = tab._summary._tot_lbl
    tab._total_hdr = tab._summary._total_hdr
    tab._disc_lbl = tab._summary.disc_label

    disc_row = QHBoxLayout()
    disc_row.setContentsMargins(0, 0, 0, 0)
    tab._disc_lbl.setToolTip(
        'Cart discount in KES. You can also set Disc per line in the cart.')
    tab._disc = _KesEdit()
    tab._disc.setObjectName('cartDisc')
    tab._disc.setText('0.00')
    tab._disc.setFixedWidth(150)
    tab._disc.setMinimumHeight(38)
    tab._disc.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    tab._disc.setPlaceholderText('0')
    tab._disc.setToolTip('Click, type e.g. 60, press Enter')
    tab._disc.setStyleSheet(
        f"QLineEdit#cartDisc{{"
        f"background:{C['input']};color:{C['text']};"
        f"border:1.5px solid {C['border2']};border-radius:8px;"
        f"padding:4px 8px;font-size:14px;font-weight:700;}}"
        f"QLineEdit#cartDisc:focus{{border-color:{C['gold']};}}"
    )
    tab._disc.editingFinished.connect(tab._commit_cart_disc)
    tab._disc.returnPressed.connect(tab._commit_cart_disc)
    tab._summary.disc_edit = tab._disc
    disc_row.addWidget(tab._disc_lbl)
    disc_row.addStretch()
    disc_row.addWidget(tab._disc)
    tab._summary._body.insertLayout(2, disc_row)
    swl.addWidget(tab._summary)
    sl.addWidget(sum_wrap, 0)
    tab._sale_summary_wrap = sum_wrap
    tab._sale_panel = sale

    # ── Actions panel body (customer + payment) + sticky foot ─────────────────
    actions = QFrame()
    actions.setObjectName('posActionsPanel')
    actions.setAttribute(Qt.WA_StyledBackground, True)
    al = QVBoxLayout(actions)
    al.setContentsMargins(0, 0, 0, 0)
    al.setSpacing(0)

    body = QWidget()
    body.setStyleSheet('background:transparent;')
    bl = QVBoxLayout(body)
    bl.setContentsMargins(16, 12, 16, 12)
    bl.setSpacing(10)

    tab._cust_card = CustomerCard()
    tab._cust_card.set_api(tab.api)
    tab._customer = tab._cust_card.selector
    tab._customer.currentIndexChanged.connect(tab._on_customer_changed)
    tab._cust_lbl = None
    bl.addWidget(tab._cust_card)

    tab._credit_frame = QFrame()
    tab._credit_frame.setStyleSheet(
        f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
    cfl = QHBoxLayout(tab._credit_frame)
    cfl.setContentsMargins(10, 8, 10, 8)
    cfl.setSpacing(8)
    tab._credit_info = QLabel('Store credit: —')
    tab._credit_info.setStyleSheet(
        f"color:{C['ok']};font-size:12px;font-weight:600;background:transparent;")
    tab._credit_spin = QDoubleSpinBox()
    tab._credit_spin.setRange(0, 99999999)
    tab._credit_spin.setDecimals(2)
    tab._credit_spin.setMinimumHeight(36)
    tab._credit_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    tab._credit_spin.setPrefix('Apply ')
    tab._credit_spin.valueChanged.connect(tab._on_credit_apply_changed)
    tab._apply_all_credit_btn = SecondaryBtn('Use All', 36)
    tab._apply_all_credit_btn.setFixedWidth(80)
    tab._apply_all_credit_btn.clicked.connect(tab._apply_all_credit)
    cfl.addWidget(tab._credit_info, 1)
    cfl.addWidget(tab._credit_spin)
    cfl.addWidget(tab._apply_all_credit_btn)
    tab._credit_frame.hide()
    bl.addWidget(tab._credit_frame)

    pay_hdr = QLabel('Payment Method')
    pay_hdr.setObjectName('posPayHdr')
    pay_hdr.setMinimumHeight(18)
    pay_hdr.setStyleSheet(
        f"color:{C['text2']};font-size:12px;font-weight:800;letter-spacing:0.3px;"
        f"background:transparent;")
    tab._pay_hdr = pay_hdr
    bl.addWidget(pay_hdr)
    tab._pay_seg = PaymentSegment()
    tab._pay_seg.methodChanged.connect(tab._select_pay_method)
    tab._pay_btns = tab._pay_seg._btns
    bl.addWidget(tab._pay_seg)

    pay = QHBoxLayout()
    pay.setSpacing(8)
    tab._pay_lbl = QLabel('Method')
    tab._pay_lbl.setStyleSheet(
        f"color:{C['text2']};font-size:13px;background:transparent;")
    tab._pay = Select()
    tab._pay.set_items(list(POS_PAYMENT_METHODS))
    tab._pay.setMinimumHeight(44)
    tab._pay.setMinimumWidth(140)
    tab._pay.currentTextChanged.connect(tab._on_payment_changed)
    # Legacy label kept for payment-method handlers; chrome hides it in favor of Amount Paid
    tab._cash_paid_lbl = QLabel('Cash Paid')
    tab._cash_paid_lbl.setStyleSheet(
        f"color:{C['text2']};font-size:12px;background:transparent;")
    tab._cash_paid_lbl.hide()
    pay.addWidget(tab._pay_lbl)
    pay.addWidget(tab._pay, 1)
    pay.addWidget(tab._cash_paid_lbl)
    bl.addLayout(pay)

    # Amount Paid — labeled high-contrast input (shared by all checkout layouts)
    amt_block = QWidget()
    amt_block.setObjectName('posAmountPaidBlock')
    abl = QVBoxLayout(amt_block)
    abl.setContentsMargins(0, 0, 0, 0)
    abl.setSpacing(4)
    tab._amount_paid_cap = QLabel('Amount Paid')
    tab._amount_paid_cap.setObjectName('posAmountCap')
    tab._amount_paid_cap.setStyleSheet(
        f"color:{C['text2']};font-size:12px;font-weight:800;letter-spacing:0.3px;"
        f"background:transparent;")
    tab._paid = QDoubleSpinBox()
    tab._paid.setObjectName('posAmountPaid')
    tab._paid.setRange(0, 99999999)
    tab._paid.setDecimals(2)
    tab._paid.setMinimumHeight(48)
    tab._paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
    tab._paid.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    tab._paid.setToolTip('Amount Paid')
    tab._paid.valueChanged.connect(tab._on_paid_changed)
    tab._paid.setStyleSheet(
        f"QDoubleSpinBox#posAmountPaid{{"
        f"background:{C['card']};color:{C['text']};"
        f"border:2.5px solid {C['text2']};border-radius:10px;"
        f"padding:8px 12px;font-size:18px;font-weight:800;"
        f"selection-background-color:{qss_alpha(C['gold'], 0.22)};"
        f"selection-color:{C['text']};}}"
        f"QDoubleSpinBox#posAmountPaid:focus{{border-color:{C['gold']};"
        f"background:{C['input']};}}"
        f"QDoubleSpinBox#posAmountPaid:hover{{border-color:{C['gold']};}}"
        f"QDoubleSpinBox#posAmountPaid:disabled{{color:{C['muted']};"
        f"border-color:{C['border']};}}"
        f"QDoubleSpinBox#posAmountPaid::up-button,QDoubleSpinBox#posAmountPaid::down-button{{"
        f"width:0;border:none;}}")
    abl.addWidget(tab._amount_paid_cap)
    abl.addWidget(tab._paid)
    bl.addWidget(amt_block)
    tab._amount_paid_block = amt_block
    tab._amount_block = amt_block
    tab._amount_block_lay = abl

    tab._var_frame = QFrame()
    tab._var_frame.setStyleSheet(
        f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
    vfl = QVBoxLayout(tab._var_frame)
    vfl.setContentsMargins(12, 8, 12, 8)
    vfl.setSpacing(4)
    tab._expected_lbl = QLabel('Expected: —')
    tab._received_lbl = QLabel('Received: —')
    tab._diff_lbl = QLabel('Difference: —')
    for w in (tab._expected_lbl, tab._received_lbl, tab._diff_lbl):
        w.setStyleSheet(
            f"color:{C['text2']};font-size:12px;font-weight:600;background:transparent;")
        vfl.addWidget(w)
    tab._var_frame.hide()
    bl.addWidget(tab._var_frame)

    tab._round_frame = QFrame()
    tab._round_frame.setObjectName('posRoundFrame')
    tab._round_frame.setStyleSheet(
        f"QFrame#posRoundFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
    rfl = QVBoxLayout(tab._round_frame)
    rfl.setContentsMargins(12, 8, 12, 8)
    rfl.setSpacing(4)
    tab._round_badge = QLabel('Cash Rounding Applied')
    tab._round_badge.setStyleSheet(
        f"color:{C['gold']};font-size:11px;font-weight:800;background:transparent;")
    tab._orig_due_lbl = QLabel('Original: —')
    tab._round_adj_lbl = QLabel('Cash Rounding: —')
    tab._amount_due_lbl = QLabel('Amount Due: —')
    for w in (tab._orig_due_lbl, tab._round_adj_lbl, tab._amount_due_lbl):
        w.setStyleSheet(
            f"color:{C['text2']};font-size:12px;font-weight:600;background:transparent;")
    tab._amount_due_lbl.setStyleSheet(
        f"color:{C['text']};font-size:13px;font-weight:800;background:transparent;")
    rfl.addWidget(tab._round_badge)
    rfl.addWidget(tab._orig_due_lbl)
    rfl.addWidget(tab._round_adj_lbl)
    rfl.addWidget(tab._amount_due_lbl)
    tab._round_frame.hide()
    bl.addWidget(tab._round_frame)

    tab._split_frame = QFrame()
    tab._split_frame.setObjectName('posSplitFrame')
    tab._split_frame.setStyleSheet(
        f"QFrame#posSplitFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
    sfl = QVBoxLayout(tab._split_frame)
    sfl.setContentsMargins(12, 8, 12, 8)
    sfl.setSpacing(6)
    tab._split_hdr = QLabel('Split payment (optional)')
    tab._split_hdr.setStyleSheet(
        f"color:{C['text2']};font-size:11px;font-weight:700;background:transparent;")
    sfl.addWidget(tab._split_hdr)
    erow = QHBoxLayout()
    erow.setSpacing(8)
    tab._elec_method = Select()
    tab._elec_method.set_items(['M-Pesa', 'Card', 'Bank Transfer', 'Airtel Money'])
    tab._elec_method.setMinimumHeight(34)
    tab._elec_method.setMinimumWidth(120)
    tab._elec_lbl = QLabel('Electronic')
    tab._elec_lbl.setStyleSheet(
        f"color:{C['text2']};font-size:12px;background:transparent;")
    tab._elec_paid = QDoubleSpinBox()
    tab._elec_paid.setRange(0, 99999999)
    tab._elec_paid.setDecimals(2)
    tab._elec_paid.setMinimumHeight(34)
    tab._elec_paid.setButtonSymbols(QAbstractSpinBox.NoButtons)
    tab._elec_paid.setToolTip(
        'Amount paid electronically (M-Pesa / Card / Bank). '
        'Cash portion below is rounded separately.')
    tab._elec_paid.valueChanged.connect(tab._on_elec_paid_changed)
    try:
        tab._elec_method.currentTextChanged.connect(
            lambda *_: tab._update_rounding_ui())
    except Exception:
        pass
    erow.addWidget(tab._elec_lbl)
    erow.addWidget(tab._elec_method, 1)
    erow.addWidget(tab._elec_paid, 1)
    sfl.addLayout(erow)
    tab._split_summary = QLabel('')
    tab._split_summary.setWordWrap(True)
    tab._split_summary.setStyleSheet(
        f"color:{C['text']};font-size:12px;font-weight:700;background:transparent;")
    sfl.addWidget(tab._split_summary)
    tab._split_frame.hide()
    bl.addWidget(tab._split_frame)

    tab._chg_frame = QFrame()
    tab._chg_frame.setObjectName('posChangeDue')
    tab._chg_frame.setStyleSheet(
        f"QFrame#posChangeDue{{background:{qss_alpha(C['ok'], 0.10)};"
        f"border:1px solid {qss_alpha(C['ok'], 0.28)};border-radius:12px;}}")
    chg = QHBoxLayout(tab._chg_frame)
    chg.setContentsMargins(14, 12, 14, 12)
    tab._chg_lbl = QLabel('Change Due')
    tab._chg_lbl.setStyleSheet(
        f"color:{C['text2']};font-size:13px;font-weight:700;background:transparent;")
    tab._chg = QLabel('KES 0.00')
    tab._chg.setStyleSheet(
        f"color:{C['ok']};font-size:22px;font-weight:900;background:transparent;")
    chg.addWidget(tab._chg_lbl)
    chg.addStretch()
    chg.addWidget(tab._chg)
    bl.addWidget(tab._chg_frame)

    tab._mpesa_frame = QFrame()
    tab._mpesa_frame.setStyleSheet(
        f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
    mfl = QVBoxLayout(tab._mpesa_frame)
    mfl.setContentsMargins(12, 10, 12, 10)
    mfl.setSpacing(6)
    tab._mpesa_info = QLabel('Pay to Till: —')
    tab._mpesa_info.setWordWrap(True)
    tab._mpesa_info.setStyleSheet(
        f"color:{C['gold']};font-size:12px;font-weight:600;background:transparent;")
    tab._mpesa_ref = QLineEdit()
    tab._mpesa_ref.setPlaceholderText('M-Pesa confirmation code (optional)')
    tab._mpesa_ref.setMinimumHeight(40)
    mfl.addWidget(tab._mpesa_info)
    mfl.addWidget(tab._mpesa_ref)
    tab._mpesa_frame.hide()
    bl.addWidget(tab._mpesa_frame)

    tab._note = QLineEdit()
    tab._note.setPlaceholderText('Note (optional)…')
    tab._note.setMinimumHeight(40)
    bl.addWidget(tab._note)
    bl.addStretch(0)

    tab._actions_body = body

    foot = QWidget()
    foot.setObjectName('posCheckoutFoot')
    foot.setAttribute(Qt.WA_StyledBackground, True)
    foot.setStyleSheet(
        f"QWidget#posCheckoutFoot {{ background:{C['card']}; "
        f"border-top:1px solid {C['border']}; }}")
    tab._checkout_foot = foot
    fl = QVBoxLayout(foot)
    fl.setContentsMargins(12, 8, 12, 12)
    fl.setSpacing(8)

    # Secondary actions row — quieter than Complete Sale (styled by layout chrome)
    br = QHBoxLayout()
    br.setSpacing(6)
    br.setContentsMargins(0, 0, 0, 0)
    # Touch targets ≥40 (U04). Label Clear (was "X") — still DangerBtn height 40.
    tab._clr_btn = DangerBtn('Clear', 40)
    tab._clr_btn.setMinimumWidth(52)
    tab._clr_btn.setMaximumWidth(88)
    tab._clr_btn.setToolTip('Clear cart')
    tab._clr_btn.clicked.connect(tab._clear)
    tab._hold_btn = SecondaryBtn('Hold', 40)
    tab._hold_btn.setToolTip('Park current cart (in-memory; cleared on exit)')
    tab._hold_btn.clicked.connect(tab._hold_sale)
    tab._resume_btn = SecondaryBtn('Resume', 40)
    tab._resume_btn.setToolTip('Restore held cart')
    tab._resume_btn.clicked.connect(tab._resume_held)
    tab._resume_btn.setEnabled(False)
    tab._prv_btn = SecondaryBtn('Preview', 40)
    tab._prv_btn.clicked.connect(tab._preview)
    tab._reprint_btn = SecondaryBtn('Reprint', 40)
    tab._reprint_btn.setToolTip('Reprint a completed receipt')
    tab._reprint_btn.clicked.connect(tab._reprint_receipt)
    br.addWidget(tab._clr_btn)
    br.addWidget(tab._hold_btn)
    br.addWidget(tab._resume_btn)
    br.addWidget(tab._prv_btn, 1)
    br.addWidget(tab._reprint_btn)
    from desktop.utils.security import can_void_sales
    if can_void_sales(tab.user):
        tab._void_btn = DangerBtn('Void Sale', 40)
        tab._void_btn.setToolTip(
            'Void a completed sale (reason dropdown + Super-Admin PIN). '
            'Returns not available — void or edit instead.')
        tab._void_btn.clicked.connect(tab._void_sale)
        br.addWidget(tab._void_btn)
    else:
        tab._void_btn = None
    tab._returns_help_btn = SecondaryBtn('Return / Exchange', 40)
    tab._returns_help_btn.setToolTip(
        'Return items from a completed receipt (restock + refund record)')
    tab._returns_help_btn.clicked.connect(tab._open_return_sale)
    br.addWidget(tab._returns_help_btn)
    tab._checkout_sec_row = br
    fl.addLayout(br)

    # Breathing room between secondary row and primary Complete Sale
    fl.addSpacing(10)

    tab._charge_btn = PrimaryBtn('$  Complete Sale', 56)
    tab._charge_btn.setMinimumHeight(56)
    tab._charge_btn.clicked.connect(tab._process)
    fl.addWidget(tab._charge_btn)

    al.addWidget(body, 1)
    al.addWidget(foot, 0)
    tab._actions_panel = actions

    # Classic bottom payment bar host (filled by shell assembler)
    tab._payment_footer_bar = QFrame()
    tab._payment_footer_bar.setObjectName('posPaymentFooter')
    tab._payment_footer_bar.hide()
