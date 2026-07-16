"""
MBT POS — POS Light Mode Theme
MugoByte Technologies

Applied ONLY to the SalesTab widget.
All other tabs remain dark. Toggle button sits inside the POS panel header.
High contrast white, larger fonts, clean layout — optimised for shop floor use.
"""
from desktop.utils.theme import qss_alpha, LIGHT, DARK, ThemeManager

def _active_palette():
    """POS panel palette — always from live ThemeManager tokens."""
    return dict(LIGHT if ThemeManager.is_light() else DARK)


def _light_tokens():
    """Light-mode POS extras (translucent accents)."""
    L = _active_palette()
    if not ThemeManager.is_light():
        return L
    L = dict(L)
    L['bg'] = L['surface']
    L['err_border'] = qss_alpha(L['err'], 0.40)
    L['gold_tint'] = qss_alpha(L['gold'], 0.13)
    return L

# Larger / bolder fonts for shop-floor readability (light mode priority)
FS = {
    'label':      '16px',
    'heading':    '20px',
    'caption':    '14px',
    'cart':       '16px',
    'cart_head':  '13px',
    'total':      '34px',
    'total_lbl':  '16px',
    'change':     '18px',
    'charge':     '19px',
    'product':    '17px',
    'mpesa':      '15px',
    'empty':      '18px',
    'toggle':     '14px',
    'btn':        '15px',
}

PROD_BTN_SIZE = (220, 150)
# Keep qty segmented control fully visible in both themes.
CART_ROW_H = 64


class _LivePalette:
    """Dict-like proxy so sales_tab can `from ... import L` and always get current tokens."""
    def __getitem__(self, key):
        return _light_tokens()[key]

    def get(self, key, default=None):
        return _light_tokens().get(key, default)

    def __contains__(self, key):
        return key in _light_tokens()

    def keys(self):
        return _light_tokens().keys()


# Back-compat for sales_tab imports (was a static LIGHT dict in older builds)
L = _LivePalette()

PROD_CARD_ACTIVE = (
    "QFrame#posProdCard{{"
    "  background:{card2}; border:1px solid {border2};"
    "  border-radius:14px;"
    "}}"
    "QFrame#posProdCard:hover{{"
    "  background:{hover}; border-color:{gold};"
    "}}"
)

PROD_CARD_EMPTY = (
    "QFrame#posProdCard{{"
    "  background:{panel}; border:1px solid {border};"
    "  border-radius:14px; opacity:0.75;"
    "}}"
)

# Legacy aliases (light theme helpers)
PROD_BTN_ACTIVE = PROD_CARD_ACTIVE
PROD_BTN_EMPTY = PROD_CARD_EMPTY

CART_TABLE = (
    "QTableWidget{{"
    "  background:#FFFFFF; border:2px solid {border2};"
    "  border-radius:10px; color:{text}; font-size:{font_cart};"
    "  font-weight:600;"
    "}}"
    "QTableWidget::item {{ padding:10px 10px; }}"
    "QHeaderView::section{{"
    "  background:{card2}; color:{text}; font-size:{font_cart_head};"
    "  font-weight:800; letter-spacing:0.6px; padding:10px 8px;"
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
    "QFrame#posTotFrame{{ background:#FFFFFF; border:2px solid {border2}; border-radius:12px; }}"
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
    "  color: {gold_fg}; border: none; border-radius: 10px;"
    "  font-size: {font_charge}; font-weight: 900; padding: 12px 24px; min-height:52px;"
    "}}"
    "QPushButton:hover{{ background:{gold_lt}; color:{gold_fg}; }}"
    "QPushButton:pressed{{ background:{gold_dk}; color:{gold_fg}; }}"
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
    L = _light_tokens()
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
    L = _light_tokens()
    w = f" font-weight:{weight};" if weight else ''
    return (
        f"color:{L[color_key]}; font-size:{FS[size_key]}; background:transparent;{w}")


def apply_light(sales_tab) -> None:
    """Apply light mode to every widget inside SalesTab."""
    L = _light_tokens()
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
        t._cnt.setStyleSheet(_label_style('muted', 'caption') + ' font-weight:600;')

    t._ctbl.setStyleSheet(fmt(CART_TABLE))
    t._ctbl.setAlternatingRowColors(True)
    t._ctbl.verticalHeader().setDefaultSectionSize(CART_ROW_H)

    t._tot_frame.setStyleSheet(fmt(TOTALS_FRAME))
    for lbl in (getattr(t, '_sub_lbl', None), getattr(t, '_tax_lbl', None)):
        if lbl:
            lbl.setStyleSheet(_label_style('text2', 'label', '600'))
    if getattr(t, '_disc_lbl', None):
        t._disc_lbl.setStyleSheet(_label_style('text2', 'label', '700'))
    if getattr(t, '_total_hdr', None):
        t._total_hdr.setStyleSheet(_label_style('text', 'total_lbl', '800'))
    t._tot_lbl.setStyleSheet(
        f"color:{L['gold']}; font-size:{FS['total']}; font-weight:900; background:transparent;")

    t._disc.setStyleSheet(_label_style('text', 'label', '700'))
    t._pay.setStyleSheet(fmt(COMBO))
    if getattr(t, '_pay_lbl', None):
        t._pay_lbl.setStyleSheet(_label_style('text2', 'label', '700'))
    t._paid.setStyleSheet(fmt(SPINBOX))
    if getattr(t, '_chg_lbl', None):
        t._chg_lbl.setStyleSheet(_label_style('text2', 'label', '700'))
    t._chg.setStyleSheet(
        f"color:{L['ok']}; font-size:{FS['change']}; font-weight:800; background:transparent;")

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
            f"QPushButton{{background:{L['card2']};color:{L['text']};"
            f"border:1px solid {L['border2']};border-radius:8px;"
            f"font-size:14px;font-weight:700;min-height:42px;padding:6px 10px;}}"
            f"QPushButton:checked{{background:{L['gold_tint']};color:{L['gold']};"
            f"border-color:{L['gold']};font-weight:800;}}")

    t._theme_btn.setText('\u263e  Dark')
    t._theme_btn.setStyleSheet(fmt(TOGGLE_BTN_LIGHT))

    t._empty.setStyleSheet(
        f"color:{L['muted']}; font-size:{FS['empty']}; background:transparent;")

    t._is_light = True
    if getattr(t, 'cart', None):
        t._refresh_cart()
    t._filter()


def apply_dark(sales_tab) -> None:
    """Restore dark mode on SalesTab — explicit DARK tokens (no leftover #FFFFFF)."""
    from desktop.utils.theme import C, DARK

    # Prefer immutable DARK tokens so a desynced live C cannot leave white panels
    D = dict(DARK)
    # If ThemeManager already restored dark into C, prefer those live values
    if (C.get('text') or '').upper() in ('#EEF2FC', '#F5F7FA', '#FFFFFF'):
        D.update({k: C[k] for k in DARK.keys() if k in C})

    t = sales_tab
    t.setStyleSheet(f"background:{D['surface']};")
    t._left_panel.setStyleSheet(
        f"QFrame#posProductPanel {{ background:{D['card']}; "
        f"border:1px solid {D['border']}; border-radius:12px; }}")
    t._right_panel.setStyleSheet(
        f"QFrame#posCartPanel {{ background:{D['card']}; "
        f"border:1px solid {D['border']}; border-radius:12px; }}")
    if getattr(t, '_checkout_scroll', None):
        t._checkout_scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{D['card']};}}"
            f"QScrollArea > QWidget > QWidget{{background:{D['card']};}}")
        w = t._checkout_scroll.widget()
        if w:
            w.setStyleSheet(f"background:{D['card']};")

    # Explicit dark inputs — never leave light-mode #FFFFFF stylesheets
    _dark_input = (
        f"background:{D['input']}; color:{D['text']}; "
        f"border:1px solid {D['border2']}; border-radius:8px; "
        f"padding:8px 12px; font-size:14px; min-height:40px;"
    )
    t._search.setStyleSheet(f"QLineEdit{{{_dark_input} border-radius:22px;}}")
    t._cat.setStyleSheet(
        f"QComboBox{{{_dark_input}}}"
        f"QComboBox::drop-down{{border:none;width:28px;}}"
        f"QComboBox QAbstractItemView{{background:{D['card']};color:{D['text']};"
        f"selection-background-color:{D['selected']};selection-color:{D['text']};}}")
    t._gw.setStyleSheet(f"background:{D['card']};")

    if getattr(t, '_sale_hdr', None):
        t._sale_hdr.setStyleSheet(
            f"color:{D['text']}; font-size:17px; font-weight:700; background:transparent;")
    if getattr(t, '_cnt', None):
        t._cnt.setStyleSheet(
            f"color:{D['muted']}; font-size:13px; font-weight:600; background:transparent;")

    t._ctbl.setStyleSheet(
        f"QTableWidget{{background:{D['card']};border:1px solid {D['border2']};"
        f"border-radius:10px;color:#F5F7FA;font-size:15px;font-weight:700;"
        f"alternate-background-color:{D['card2']};gridline-color:transparent;}}"
        f"QTableWidget::item{{color:#F5F7FA;padding:10px 10px;}}"
        f"QHeaderView::section{{background:{D['panel']};color:#C5D0E0;"
        f"font-size:12px;font-weight:800;letter-spacing:0.6px;padding:10px 8px;"
        f"border:none;border-bottom:1px solid {D['border2']};}}"
    )
    t._ctbl.verticalHeader().setDefaultSectionSize(CART_ROW_H)

    t._tot_frame.setStyleSheet(
        f"QFrame#posTotFrame{{background:{D['panel']};border:1px solid {D['border2']};"
        f"border-radius:8px;}}")
    for lbl in (getattr(t, '_sub_lbl', None), getattr(t, '_tax_lbl', None)):
        if lbl:
            lbl.setStyleSheet(
                f"color:{D['text2']}; font-size:14px; font-weight:600; background:transparent;")
    if getattr(t, '_disc_lbl', None):
        t._disc_lbl.setStyleSheet(
            f"color:{D['text2']}; font-size:14px; font-weight:700; background:transparent;")
    if getattr(t, '_total_hdr', None):
        t._total_hdr.setStyleSheet(
            f"color:{D['text']}; font-size:14px; font-weight:700; background:transparent;")
    t._tot_lbl.setStyleSheet(
        f"color:{D['gold']}; font-size:28px; font-weight:900; background:transparent;")

    t._disc.setStyleSheet(
        f"color:{D['text']}; font-size:15px; font-weight:700; background:transparent;")
    t._pay.setStyleSheet(
        f"QComboBox{{{_dark_input}}}"
        f"QComboBox QAbstractItemView{{background:{D['card']};color:{D['text']};}}")
    if getattr(t, '_pay_lbl', None):
        t._pay_lbl.setStyleSheet(
            f"color:{D['text2']}; font-size:14px; font-weight:600; background:transparent;")
    t._paid.setStyleSheet(f"QDoubleSpinBox{{{_dark_input}}}")
    if getattr(t, '_chg_lbl', None):
        t._chg_lbl.setStyleSheet(
            f"color:{D['text2']}; font-size:14px; font-weight:600; background:transparent;")
    t._chg.setStyleSheet(
        f"color:{D['ok']}; font-size:16px; font-weight:800; background:transparent;")

    t._mpesa_frame.setStyleSheet(
        f"QFrame{{background:{D['card2']};border:1px solid {D['border2']};border-radius:8px;}}")
    t._mpesa_info.setStyleSheet(
        f"color:{D['gold']}; font-size:13px; font-weight:700; background:transparent;")
    t._mpesa_ref.setStyleSheet(f"QLineEdit{{{_dark_input}}}")

    t._note.setStyleSheet(f"QLineEdit{{{_dark_input}}}")
    t._charge_btn.setObjectName('primaryBtn')
    gold_fg = D.get('gold_fg', '#0A0F1A')
    t._charge_btn.setStyleSheet(
        f"QPushButton#primaryBtn {{ background:{D['gold']}; color:{gold_fg};"
        f" border:none; border-radius:8px; font-weight:800; font-size:16px;"
        f" padding:12px 16px; min-height:52px; }}"
        f"QPushButton#primaryBtn:hover {{ background:{D['gold_lt']}; color:{gold_fg}; }}"
        f"QPushButton#primaryBtn:pressed {{ background:{D['gold_dk']}; color:{gold_fg}; }}")
    _sec = (
        f"QPushButton{{background:{D['card2']};color:{D['text']};"
        f"border:1px solid {D['border2']};border-radius:8px;"
        f"font-size:13px;font-weight:600;padding:9px 14px;min-height:42px;}}"
        f"QPushButton:hover{{background:{D['hover']};border-color:{D['gold']};}}"
    )
    t._prv_btn.setStyleSheet(_sec)
    t._clr_btn.setStyleSheet(
        f"QPushButton{{background:{D['err_dim']};color:{D['err']};"
        f"border:1px solid {D['border2']};border-radius:8px;"
        f"font-size:13px;font-weight:700;padding:9px 14px;min-height:42px;}}"
        f"QPushButton:hover{{background:{D['err']};color:#fff;}}")
    if getattr(t, '_reprint_btn', None):
        t._reprint_btn.setStyleSheet(_sec)

    for b in getattr(t, '_pay_btns', {}).values():
        b.setStyleSheet(
            f"QPushButton{{background:{D['card2']};color:{D['text2']};"
            f"border:1px solid {D['border']};border-radius:8px;"
            f"font-size:13px;font-weight:700;min-height:40px;padding:6px 8px;}}"
            f"QPushButton:checked{{background:{D['selected']};color:{D['gold']};"
            f"border-color:{D['gold']};font-weight:800;}}")

    t._theme_btn.setText('\u2600  Light')
    t._theme_btn.setStyleSheet(
        f"QPushButton{{background:{D['card2']}; color:{D['text']};"
        f"border:1px solid {D['border']}; border-radius:8px;"
        f"font-size:13px; font-weight:600; padding:6px 12px; min-height:36px;}}"
        f"QPushButton:hover{{background:{D['hover']}; color:{D['text']};}}")

    t._empty.setStyleSheet(
        f"color:{D['muted']}; font-size:15px; font-weight:600; background:transparent;")

    t._is_light = False
    if getattr(t, 'cart', None):
        t._refresh_cart()
    t._filter()
