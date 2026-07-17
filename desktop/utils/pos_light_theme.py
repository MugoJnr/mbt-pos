"""
MBT POS — POS Light Mode Theme
MugoByte Technologies

Applied ONLY to the SalesTab widget.
All other tabs remain dark. Toggle button sits inside the POS panel header.
High contrast white, larger fonts, clean layout — optimised for shop floor use.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette
from desktop.utils.theme import qss_alpha, LIGHT, DARK, ThemeManager

# Category popup: compact scroll list (not full-screen), always re-applied on theme switch
_CAT_POPUP_MAX_H = 280
_CAT_MAX_VISIBLE = 10
_CAT_ITEM_FG_DARK = '#F5F7FA'
_CAT_POPUP_BG_DARK = '#121C30'  # dark card — readable vs transparent/global wipe

def _active_palette():
    """POS panel palette — always from live ThemeManager tokens."""
    return dict(LIGHT if ThemeManager.is_light() else DARK)


def _light_tokens():
    """Light-mode POS extras (translucent accents)."""
    L = dict(_active_palette())
    L.setdefault('on_danger', '#FFFFFF')
    L.setdefault('on_success', '#FFFFFF')
    if not ThemeManager.is_light():
        return L
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
    "  background:{card}; border:2px solid {border2};"
    "  border-radius:10px; color:{text}; font-size:{font_cart};"
    "  font-weight:600;"
    "}}"
    "QTableWidget::item {{ padding:10px 10px; }}"
    "QHeaderView::section{{"
    "  background:{card2}; color:{text2}; font-size:{font_cart_head};"
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
    "QPushButton:hover{{ background:{err}; color:{on_danger}; }}"
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
    "QFrame#posTotFrame{{ background:{card}; border:2px solid {border2}; border-radius:12px; }}"
)

MPESA_FRAME = (
    "QFrame{{ background:{card2}; border:2px solid {border2}; border-radius:10px; }}"
)

NOTE_INPUT = (
    "QLineEdit{{"
    "  background:{input}; color:{text}; border:2px solid {border2};"
    "  border-radius:8px; padding:10px 14px; font-size:{font_label}; min-height:40px;"
    "}}"
    "QLineEdit:focus{{ border-color:{gold}; }}"
)

COMBO = (
    "QComboBox{{"
    "  background:{input}; color:{text}; border:2px solid {border2};"
    "  border-radius:8px; padding:10px 14px; font-size:{font_label}; min-height:40px;"
    "}}"
    "QComboBox:focus {{ border-color:{gold}; }}"
    "QComboBox::drop-down {{ border:none; width:32px; }}"
    "QComboBox QAbstractItemView{{"
    "  background:{card}; color:{text}; border:2px solid {border2};"
    "  font-size:{font_label}; max-height:280px;"
    "  selection-background-color:{selected}; selection-color:{text};"
    "}}"
)


def style_cat_combo(combo, is_light: bool = False) -> None:
    """Sales category QComboBox — scrollable popup + high-contrast items.

    Must be called from apply_light / apply_dark so theme switches do not leave
    invisible dark-on-dark (or wiped) popup styles.
    """
    if combo is None:
        return
    combo.setObjectName('posCatCombo')
    combo.setMaxVisibleItems(_CAT_MAX_VISIBLE)
    view = combo.view()
    view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    if is_light:
        L = _light_tokens()
        bg = L.get('input') or L.get('card') or L['surface']
        fg = L['text']
        sel = L['selected']
        sel_fg = L['text']
        hover = L['hover']
        border = L['border2']
        combo.setStyleSheet(
            f"QComboBox#posCatCombo{{"
            f"background:{bg};color:{fg};border:2px solid {border};"
            f"border-radius:8px;padding:10px 14px;font-size:{FS['label']};min-height:40px;}}"
            f"QComboBox#posCatCombo:focus{{border-color:{L['gold']};}}"
            f"QComboBox#posCatCombo::drop-down{{border:none;width:32px;}}"
            f"QComboBox#posCatCombo QAbstractItemView{{"
            f"background:{bg};color:{fg};border:2px solid {border};"
            f"outline:0;font-size:{FS['label']};max-height:{_CAT_POPUP_MAX_H}px;"
            f"selection-background-color:{sel};selection-color:{sel_fg};}}"
            f"QComboBox#posCatCombo QAbstractItemView::item{{"
            f"color:{fg};min-height:30px;padding:4px 10px;}}"
            f"QComboBox#posCatCombo QAbstractItemView::item:selected{{"
            f"background:{sel};color:{sel_fg};}}"
            f"QComboBox#posCatCombo QAbstractItemView::item:hover{{"
            f"background:{hover};color:{fg};}}"
        )
    else:
        D = dict(DARK)
        bg = _CAT_POPUP_BG_DARK  # #121C30 — distinct dark card
        fg = _CAT_ITEM_FG_DARK   # #F5F7FA
        sel = D.get('selected', '#1A3560')
        sel_fg = fg
        hover = D.get('hover', '#162A44')
        border = D.get('border2', '#18283E')
        inp = D.get('input', '#0C1626')
        combo.setStyleSheet(
            f"QComboBox#posCatCombo{{"
            f"background:{inp};color:{fg};"
            f"border:1px solid {border};border-radius:8px;padding:6px 10px;"
            f"font-size:14px;min-height:40px;}}"
            f"QComboBox#posCatCombo:focus{{border-color:{D.get('gold', '#F2A800')};}}"
            f"QComboBox#posCatCombo::drop-down{{border:none;width:28px;}}"
            f"QComboBox#posCatCombo QAbstractItemView{{"
            f"background:{bg};color:{fg};border:1px solid {border};"
            f"outline:0;font-size:14px;max-height:{_CAT_POPUP_MAX_H}px;"
            f"selection-background-color:{sel};selection-color:{sel_fg};}}"
            f"QComboBox#posCatCombo QAbstractItemView::item{{"
            f"color:{fg};background:{bg};min-height:30px;padding:4px 10px;}}"
            f"QComboBox#posCatCombo QAbstractItemView::item:selected{{"
            f"background:{sel};color:{sel_fg};}}"
            f"QComboBox#posCatCombo QAbstractItemView::item:hover{{"
            f"background:{hover};color:{fg};}}"
        )

    # Palette on the list view — Qt popup often ignores QSS color alone
    pal = view.palette()
    pal.setColor(QPalette.Base, QColor(bg))
    pal.setColor(QPalette.Text, QColor(fg))
    pal.setColor(QPalette.WindowText, QColor(fg))
    pal.setColor(QPalette.ButtonText, QColor(fg))
    pal.setColor(QPalette.Highlight, QColor(sel))
    pal.setColor(QPalette.HighlightedText, QColor(sel_fg))
    pal.setColor(QPalette.Window, QColor(bg))
    view.setPalette(pal)
    view.setStyleSheet(
        f"QAbstractItemView{{background:{bg};color:{fg};"
        f"outline:0;max-height:{_CAT_POPUP_MAX_H}px;}}"
        f"QAbstractItemView::item{{color:{fg};min-height:30px;}}"
        f"QAbstractItemView::item:selected{{background:{sel};color:{sel_fg};}}"
    )
    combo.setMaxVisibleItems(_CAT_MAX_VISIBLE)

SEARCH_INPUT = (
    "QLineEdit{{"
    "  background:{input}; color:{text}; border:2px solid {border2};"
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
    "  background:{card}; color:{text};"
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
    "QPushButton:hover{{ background:{err}; color:{on_danger}; }}"
)

TOGGLE_BTN_LIGHT = (
    "QPushButton{{"
    "  background:{card}; color:{text2};"
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



def _tint_checkout_foot(sales_tab, bg: str, border: str) -> None:
    foot = getattr(sales_tab, '_checkout_foot', None)
    if foot is None:
        return
    foot.setAttribute(Qt.WA_StyledBackground, True)
    foot.setStyleSheet(
        f"QWidget#posCheckoutFoot {{ background:{bg}; border-top:1px solid {border}; }}")


def _tint_refresh_btn(sales_tab, bg: str, fg: str, border: str, hover: str, gold: str) -> None:
    btn = getattr(sales_tab, '_refresh_btn', None)
    if btn is None:
        return
    btn.setStyleSheet(
        f"QPushButton {{ background:{bg}; color:{fg}; "
        f"border:1px solid {border}; border-radius:8px; font-size:14px; font-weight:600; }}"
        f"QPushButton:hover {{ color:{gold}; border-color:{gold}; background:{hover}; }}")

def apply_light(sales_tab) -> None:
    """Apply light mode to every widget inside SalesTab."""
    # Ensure ThemeManager is light so token helpers expose light extras (bg, etc.)
    if not ThemeManager.is_light():
        ThemeManager.apply(True)
    L = _light_tokens()
    if 'bg' not in L:
        L = dict(L)
        L['bg'] = L.get('surface', '#FFFFFF')
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

    if hasattr(t._search, 'refresh_theme'):
        t._search.refresh_theme()
    else:
        t._search.setStyleSheet(fmt(SEARCH_INPUT))
    style_cat_combo(getattr(t, '_cat', None), is_light=True)
    _tint_checkout_foot(t, L['card'], L['border'])
    _tint_refresh_btn(t, L['card'], L['text'], L['border2'], L['hover'], L['gold'])
    sb = getattr(t, '_search_bar', None)
    if sb is not None:
        sb.setStyleSheet(
            f"background:transparent; border-bottom:1px solid {L['border']};")
    chdr = getattr(t, '_cart_hdr', None)
    if chdr is not None:
        chdr.setStyleSheet(f"border-bottom:1px solid {L['border']};")
    if getattr(t, '_cust_lbl', None):
        t._cust_lbl.setStyleSheet(_label_style('text2', 'label'))
    if getattr(t, '_gw', None) is not None:
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

    t._disc.setStyleSheet(fmt(NOTE_INPUT))
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
        if hasattr(b, 'refresh_theme'):
            b.refresh_theme()
        else:
            b.setStyleSheet(
                f"QPushButton{{background:{L['card2']};color:{L['text']};"
                f"border:1px solid {L['border2']};border-radius:8px;"
                f"font-size:14px;font-weight:700;min-height:42px;padding:6px 10px;}}"
                f"QPushButton:checked{{background:{L['gold_tint']};color:{L['gold']};"
                f"border-color:{L['gold']};font-weight:800;}}")
    if hasattr(t, '_pay_seg') and hasattr(t._pay_seg, 'refresh_theme'):
        t._pay_seg.refresh_theme()
    if hasattr(t, '_customer') and hasattr(t._customer, 'refresh_theme'):
        t._customer.refresh_theme()
    if hasattr(t, '_summary') and hasattr(t._summary, 'refresh_theme'):
        t._summary.refresh_theme()

    tb = getattr(t, '_theme_btn', None)
    if tb is not None and hasattr(tb, '_refresh_theme'):
        tb._refresh_theme()
    elif tb is not None:
        tb.setText('\u263e  Dark')
        tb.setStyleSheet(fmt(TOGGLE_BTN_LIGHT))

    t._empty.setStyleSheet(
        f"color:{L['muted']}; font-size:{FS['empty']}; background:transparent;")

    t._is_light = True
    # Fast in-place card colors only — cart rebuild + product grid deferred by MainWindow
    if hasattr(t, '_retint_prod_grid'):
        try:
            t._retint_prod_grid()
        except Exception:
            pass
    # Cart row labels bake colors at build time — rebuild so light mode never keeps white text
    if getattr(t, 'cart', None) is not None and hasattr(t, '_refresh_cart'):
        try:
            t._refresh_cart()
        except Exception:
            pass


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
    if hasattr(t._search, 'refresh_theme'):
        t._search.refresh_theme()
    else:
        t._search.setStyleSheet(f"QLineEdit{{{_dark_input} border-radius:22px;}}")
    style_cat_combo(getattr(t, '_cat', None), is_light=False)
    _tint_checkout_foot(t, D['card'], D['border'])
    _tint_refresh_btn(t, D['card'], D['text'], D['border2'], D['hover'], D.get('gold', '#F2A800'))
    sb = getattr(t, '_search_bar', None)
    if sb is not None:
        sb.setStyleSheet(
            f"background:transparent; border-bottom:1px solid {D['border']};")
    chdr = getattr(t, '_cart_hdr', None)
    if chdr is not None:
        chdr.setStyleSheet(f"border-bottom:1px solid {D['border']};")
    if getattr(t, '_cust_lbl', None):
        t._cust_lbl.setStyleSheet(
            f"color:{D['text2']};font-size:13px;background:transparent;")
    if getattr(t, '_gw', None) is not None:
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

    t._disc.setStyleSheet(f"QLineEdit{{{_dark_input}}}")
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
        if hasattr(b, 'refresh_theme'):
            b.refresh_theme()
        else:
            b.setStyleSheet(
                f"QPushButton{{background:{D['card2']};color:{D['text2']};"
                f"border:1px solid {D['border']};border-radius:8px;"
                f"font-size:13px;font-weight:700;min-height:40px;padding:6px 8px;}}"
                f"QPushButton:checked{{background:{D['selected']};color:{D['gold']};"
                f"border-color:{D['gold']};font-weight:800;}}")
    if hasattr(t, '_pay_seg') and hasattr(t._pay_seg, 'refresh_theme'):
        t._pay_seg.refresh_theme()
    if hasattr(t, '_customer') and hasattr(t._customer, 'refresh_theme'):
        t._customer.refresh_theme()
    if hasattr(t, '_summary') and hasattr(t._summary, 'refresh_theme'):
        t._summary.refresh_theme()

    tb = getattr(t, '_theme_btn', None)
    if tb is not None and hasattr(tb, '_refresh_theme'):
        tb._refresh_theme()
    elif tb is not None:
        tb.setText('\u2600  Light')
        tb.setStyleSheet(
            f"QPushButton{{background:{D['card2']}; color:{D['text']};"
            f"border:1px solid {D['border']}; border-radius:8px;"
            f"font-size:13px; font-weight:600; padding:6px 12px; min-height:36px;}}"
            f"QPushButton:hover{{background:{D['hover']}; color:{D['text']};}}")

    t._empty.setStyleSheet(
        f"color:{D['muted']}; font-size:15px; font-weight:600; background:transparent;")

    t._is_light = False
    # Fast in-place card colors only — cart rebuild + product grid deferred by MainWindow
    if hasattr(t, '_retint_prod_grid'):
        try:
            t._retint_prod_grid()
        except Exception:
            pass
    if getattr(t, 'cart', None) is not None and hasattr(t, '_refresh_cart'):
        try:
            t._refresh_cart()
        except Exception:
            pass
