"""
MBT POS — POS Light Mode Theme
MugoByte Technologies

Applied ONLY to the SalesTab widget.
All other tabs remain dark. Toggle button sits inside the POS panel header.
High contrast white, larger fonts, clean layout — optimised for shop floor use.
"""
from desktop.utils.theme import qss_alpha

# Light palette — aligned with ThemeManager LIGHT / Lovable .light
L = {
    'bg':        '#F0F4FA',
    'surface':   '#FFFFFF',
    'panel':     '#E8EDF6',
    'card':      '#FFFFFF',
    'card2':     '#F4F7FC',
    'input':     '#FFFFFF',
    'border':    '#CDD8E8',
    'border2':   '#B8C8DC',
    'hover':     '#DDE6F2',
    'selected':  '#CDDAEE',
    'text':      '#0C1828',
    'text2':     '#3C5270',
    'muted':     '#7890AA',
    'disabled':  '#C0CCD8',
    'gold':      '#B87000',
    'gold_lt':   '#D48800',
    'gold_dk':   '#8C5400',
    'ok':        '#006B48',
    'ok_dim':    '#E6F5EF',
    'err':       '#B81C2C',
    'err_dim':   '#FDECEA',
    'warn':      '#A05800',
    'info':      '#1850A8',
    'sep':       '#E0E8F0',
    'app':       '#F0F4FA',
}
# Qt-safe translucent accents (never append hex alpha to #RRGGBB)
L['err_border'] = qss_alpha(L['err'], 0.40)
L['gold_tint'] = qss_alpha(L['gold'], 0.13)

# Larger fonts for shop-floor / touch use (light mode)
FS = {
    'label':      '15px',
    'heading':    '18px',
    'caption':    '13px',
    'cart':       '15px',
    'cart_head':  '12px',
    'total':      '32px',
    'total_lbl':  '15px',
    'change':     '17px',
    'charge':     '18px',
    'product':    '15px',
    'mpesa':      '14px',
    'empty':      '17px',
    'toggle':     '13px',
    'btn':        '14px',
}

PROD_BTN_SIZE = (172, 118)
# Keep qty segmented control fully visible in both themes.
CART_ROW_H = 64

PROD_BTN_ACTIVE = (
    "QPushButton{{"
    "  background:#FFFFFF; border:2px solid {border2};"
    "  border-radius:12px; color:{text};"
    "  font-size:{font_product}; font-weight:700; padding:12px;"
    "}}"
    "QPushButton:hover{{"
    "  background:{hover}; border-color:{gold}; color:{gold};"
    "}}"
    "QPushButton:pressed{{ background:{selected}; }}"
)

PROD_BTN_EMPTY = (
    "QPushButton{{"
    "  background:#F4F6FB; border:2px solid {border};"
    "  border-radius:12px; color:{text2};"
    "  font-size:{font_product}; font-weight:600; padding:12px;"
    "}}"
)

CART_TABLE = (
    "QTableWidget{{"
    "  background:#FFFFFF; border:2px solid {border2};"
    "  border-radius:10px; color:{text}; font-size:{font_cart};"
    "}}"
    "QTableWidget::item {{ padding:10px 12px; }}"
    "QHeaderView::section{{"
    "  background:{card2}; color:{text2}; font-size:{font_cart_head};"
    "  font-weight:700; letter-spacing:0.8px; padding:10px 12px;"
    "  border:none; border-bottom:2px solid {border2};"
    "}}"
)

REMOVE_BTN = (
    "QPushButton{{"
    "  background:{err_dim}; color:{err}; border:2px solid {err_border};"
    "  border-radius:8px; font-weight:800; font-size:{font_btn};"
    "  min-width:34px; min-height:34px; padding:2px 8px;"
    "}}"
    "QPushButton:hover{{ background:{err}; color:#fff; }}"
)

SPINBOX = (
    "QDoubleSpinBox, QSpinBox {{"
    "  background:{input}; color:{text}; border:2px solid {border2};"
    "  border-radius:8px; padding:8px 12px; font-size:{font_label}; min-height:40px;"
    "}}"
    "QDoubleSpinBox:focus, QSpinBox:focus {{ border-color:{gold}; }}"
    "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,"
    "QSpinBox::up-button, QSpinBox::down-button {{"
    "  background:{border2}; width:24px; border-radius:4px;"
    "}}"
    "QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover {{ background:{gold}; }}"
)

TOTALS_FRAME = (
    "QFrame{{ background:#FFFFFF; border:2px solid {border2}; border-radius:12px; }}"
)

MPESA_FRAME = (
    "QFrame{{ background:{card2}; border:2px solid {border2}; border-radius:10px; }}"
)

NOTE_INPUT = (
    "QLineEdit{{"
    "  background:#FFFFFF; color:{text}; border:2px solid {border2};"
    "  border-radius:8px; padding:10px 14px; font-size:{font_label}; min-height:40px;"
    "}}"
    "QLineEdit:focus{{ border-color:{gold}; }}"
)

COMBO = (
    "QComboBox{{"
    "  background:#FFFFFF; color:{text}; border:2px solid {border2};"
    "  border-radius:8px; padding:10px 14px; font-size:{font_label}; min-height:40px;"
    "}}"
    "QComboBox:focus {{ border-color:{gold}; }}"
    "QComboBox::drop-down {{ border:none; width:32px; }}"
    "QComboBox QAbstractItemView{{"
    "  background:#FFFFFF; color:{text}; border:2px solid {border2};"
    "  font-size:{font_label};"
    "  selection-background-color:{selected}; selection-color:{text};"
    "}}"
)

SEARCH_INPUT = (
    "QLineEdit{{"
    "  background:#FFFFFF; color:{text}; border:2px solid {border2};"
    "  border-radius:22px; padding:10px 18px; font-size:{font_label}; min-height:42px;"
    "}}"
    "QLineEdit:focus{{ border-color:{gold}; }}"
)

CHARGE_BTN = (
    "QPushButton{{"
    "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    "    stop:0 {gold_lt}, stop:1 {gold});"
    "  color: #0A0F18; border: none; border-radius: 10px;"
    "  font-size: {font_charge}; font-weight: 900; padding: 12px 24px; min-height:52px;"
    "}}"
    "QPushButton:hover{{ background:{gold_lt}; color:#000; }}"
    "QPushButton:pressed{{ background:{gold_dk}; }}"
)

SECONDARY_BTN = (
    "QPushButton{{"
    "  background:#FFFFFF; color:{text};"
    "  border:2px solid {border2}; border-radius:8px;"
    "  font-size:{font_btn}; font-weight:600; padding:9px 18px; min-height:42px;"
    "}}"
    "QPushButton:hover{{ background:{hover}; border-color:{gold}; }}"
)

DANGER_BTN = (
    "QPushButton{{"
    "  background:{err_dim}; color:{err};"
    "  border:2px solid {err_border}; border-radius:8px;"
    "  font-size:{font_btn}; font-weight:700; padding:9px 14px; min-height:42px;"
    "}}"
    "QPushButton:hover{{ background:{err}; color:#fff; }}"
)

TOGGLE_BTN_LIGHT = (
    "QPushButton{{"
    "  background:#FFFFFF; color:{text2};"
    "  border:2px solid {border2}; border-radius:18px;"
    "  font-size:{font_toggle}; font-weight:600; padding:6px 14px; min-height:40px;"
    "}}"
    "QPushButton:hover{{ background:{hover}; border-color:{gold}; color:{text}; }}"
)


def fmt(template: str) -> str:
    """Fill a style template with light palette + font sizes."""
    return template.format(**L, **{f'font_{k}': v for k, v in (
        ('label', FS['label']),
        ('heading', FS['heading']),
        ('caption', FS['caption']),
        ('cart', FS['cart']),
        ('cart_head', FS['cart_head']),
        ('total', FS['total']),
        ('total_lbl', FS['total_lbl']),
        ('change', FS['change']),
        ('charge', FS['charge']),
        ('product', FS['product']),
        ('mpesa', FS['mpesa']),
        ('empty', FS['empty']),
        ('toggle', FS['toggle']),
        ('btn', FS['btn']),
    )})


def _label_style(color_key='text2', size_key='label', weight=''):
    w = f" font-weight:{weight};" if weight else ''
    return (
        f"color:{L[color_key]}; font-size:{FS[size_key]}; background:transparent;{w}")


def apply_light(sales_tab) -> None:
    """Apply light mode to every widget inside SalesTab."""
    t = sales_tab

    t.setStyleSheet(f"background:{L['bg']};")
    t._left_panel.setStyleSheet(
        f"QFrame#posProductPanel {{ background:{L['card']}; "
        f"border:1px solid {L['border']}; border-radius:12px; }}")
    t._right_panel.setStyleSheet(
        f"QFrame#posCartPanel {{ background:{L['card']}; "
        f"border:1px solid {L['border']}; border-radius:12px; }}")
    if getattr(t, '_checkout_scroll', None):
        t._checkout_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}")
        w = t._checkout_scroll.widget()
        if w:
            w.setStyleSheet("background:transparent;")

    t._search.setStyleSheet(fmt(SEARCH_INPUT))
    t._cat.setStyleSheet(fmt(COMBO))
    t._gw.setStyleSheet("background:transparent;")

    if getattr(t, '_sale_hdr', None):
        t._sale_hdr.setStyleSheet(_label_style('text', 'heading', '700'))
    if getattr(t, '_cnt', None):
        t._cnt.setStyleSheet(_label_style('muted', 'caption'))

    t._ctbl.setStyleSheet(fmt(CART_TABLE))
    t._ctbl.setAlternatingRowColors(True)
    t._ctbl.verticalHeader().setDefaultSectionSize(CART_ROW_H)

    t._tot_frame.setStyleSheet(fmt(TOTALS_FRAME))
    for lbl in (getattr(t, '_sub_lbl', None), getattr(t, '_tax_lbl', None)):
        if lbl:
            lbl.setStyleSheet(_label_style('text2', 'label'))
    if getattr(t, '_disc_lbl', None):
        t._disc_lbl.setStyleSheet(_label_style('text2', 'label'))
    if getattr(t, '_total_hdr', None):
        t._total_hdr.setStyleSheet(_label_style('text', 'total_lbl', '700'))
    t._tot_lbl.setStyleSheet(
        f"color:{L['gold']}; font-size:{FS['total']}; font-weight:900; background:transparent;")

    t._disc.setStyleSheet(fmt(SPINBOX))
    t._pay.setStyleSheet(fmt(COMBO))
    if getattr(t, '_pay_lbl', None):
        t._pay_lbl.setStyleSheet(_label_style('text2', 'label'))
    t._paid.setStyleSheet(fmt(SPINBOX))
    if getattr(t, '_chg_lbl', None):
        t._chg_lbl.setStyleSheet(_label_style('text2', 'label'))
    t._chg.setStyleSheet(
        f"color:{L['ok']}; font-size:{FS['change']}; font-weight:700; background:transparent;")

    t._mpesa_frame.setStyleSheet(fmt(MPESA_FRAME))
    t._mpesa_info.setStyleSheet(
        f"color:{L['gold']}; font-size:{FS['mpesa']}; font-weight:700; background:transparent;")
    t._mpesa_ref.setStyleSheet(fmt(NOTE_INPUT))

    t._note.setStyleSheet(fmt(NOTE_INPUT))
    t._charge_btn.setStyleSheet(fmt(CHARGE_BTN))
    t._prv_btn.setStyleSheet(fmt(SECONDARY_BTN))
    t._clr_btn.setStyleSheet(fmt(DANGER_BTN))
    if getattr(t, '_reprint_btn', None):
        t._reprint_btn.setStyleSheet(fmt(SECONDARY_BTN))

    for b in getattr(t, '_pay_btns', {}).values():
        b.setStyleSheet(
            f"QPushButton{{background:{L['card2']};color:{L['text2']};"
            f"border:1px solid {L['border']};border-radius:8px;"
            f"font-size:12px;font-weight:600;min-height:40px;}}"
            f"QPushButton:checked{{background:{L['gold_tint']};color:{L['gold']};"
            f"border-color:{L['gold']};}}")

    t._theme_btn.setText('🌙  Dark')
    t._theme_btn.setStyleSheet(fmt(TOGGLE_BTN_LIGHT))

    t._empty.setStyleSheet(
        f"color:{L['muted']}; font-size:{FS['empty']}; background:transparent;")

    t._is_light = True
    t._filter()


def apply_dark(sales_tab) -> None:
    """Restore dark mode on SalesTab."""
    from desktop.utils.theme import C

    t = sales_tab
    t.setStyleSheet("")
    t._left_panel.setStyleSheet(
        f"QFrame#posProductPanel {{ background:{C['card']}; "
        f"border:1px solid {C['border']}; border-radius:12px; }}")
    t._right_panel.setStyleSheet(
        f"QFrame#posCartPanel {{ background:{C['card']}; "
        f"border:1px solid {C['border']}; border-radius:12px; }}")
    if getattr(t, '_checkout_scroll', None):
        t._checkout_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}")
        w = t._checkout_scroll.widget()
        if w:
            w.setStyleSheet("background:transparent;")

    t._search.setStyleSheet("")
    t._cat.setStyleSheet("")
    t._gw.setStyleSheet("background:transparent;")

    if getattr(t, '_sale_hdr', None):
        t._sale_hdr.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:600; background:transparent;")
    if getattr(t, '_cnt', None):
        t._cnt.setStyleSheet(
            f"color:{C['muted']}; font-size:12px; background:transparent;")

    t._ctbl.setStyleSheet("")
    t._ctbl.verticalHeader().setDefaultSectionSize(CART_ROW_H)

    t._tot_frame.setStyleSheet(
        f"QFrame{{background:{C['panel']};border:1px solid {C['border']};border-radius:8px;}}")
    for lbl in (getattr(t, '_sub_lbl', None), getattr(t, '_tax_lbl', None)):
        if lbl:
            lbl.setStyleSheet(
                f"color:{C['text2']}; font-size:13px; background:transparent;")
    if getattr(t, '_disc_lbl', None):
        t._disc_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent;")
    if getattr(t, '_total_hdr', None):
        t._total_hdr.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:600; background:transparent;")
    t._tot_lbl.setStyleSheet(
        f"color:{C['gold']}; font-size:24px; font-weight:800; background:transparent;")

    t._disc.setStyleSheet("")
    t._pay.setStyleSheet("")
    if getattr(t, '_pay_lbl', None):
        t._pay_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent;")
    t._paid.setStyleSheet("")
    if getattr(t, '_chg_lbl', None):
        t._chg_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent;")
    t._chg.setStyleSheet(
        f"color:{C['ok']}; font-size:15px; font-weight:700; background:transparent;")

    t._mpesa_frame.setStyleSheet(
        f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};border-radius:8px;}}")
    t._mpesa_info.setStyleSheet(
        f"color:{C['gold']}; font-size:12px; font-weight:600; background:transparent;")
    t._mpesa_ref.setStyleSheet("")

    t._note.setStyleSheet("")
    t._charge_btn.setObjectName('primaryBtn')
    t._charge_btn.setStyleSheet("")
    t._prv_btn.setStyleSheet("")
    t._clr_btn.setStyleSheet("")
    if getattr(t, '_reprint_btn', None):
        t._reprint_btn.setStyleSheet("")

    for b in getattr(t, '_pay_btns', {}).values():
        b.setStyleSheet("")

    t._theme_btn.setText('☀  Light')
    t._theme_btn.setStyleSheet(
        f"QPushButton{{background:{C['card2']}; color:{C['text2']};"
        f"border:1px solid {C['border']}; border-radius:8px;"
        f"font-size:12px; font-weight:500; padding:4px 10px;}}"
        f"QPushButton:hover{{background:{C['hover']}; color:{C['text']};}}")

    t._empty.setStyleSheet(
        f"color:{C['muted']}; font-size:14px; background:transparent;")

    t._is_light = False
    t._filter()
