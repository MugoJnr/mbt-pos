"""
MBT POS — Premium UI Component Library v3 (Lovable-aligned)
MugoByte Technologies | mugobyte.com

All components theme-aware: pick up C[] at paint time.
ThemeManager.apply() triggers a global stylesheet refresh —
no per-widget repaint needed.
"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme import C, COLORS, MBT_STYLESHEET, RADIUS, qss_alpha


# ── TYPOGRAPHY ────────────────────────────────────────────────────────────────

def H1(text, color=None):
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{color or C['text']}; font-size:24px; font-weight:800; "
        f"background:transparent; border:none;")
    return l

def H2(text, color=None):
    l = QLabel(text)
    l.setObjectName('sectionTitle')
    l.setProperty('mbtTitleSize', 16)
    l.setStyleSheet(
        f"color:{color or C['text']}; font-size:16px; font-weight:700; "
        f"background:transparent; border:none;")
    return l

def H3(text):
    l = QLabel(text.upper())
    l.setStyleSheet(
        f"color:{C['muted']}; font-size:10px; font-weight:800; "
        f"letter-spacing:1.8px; background:transparent; border:none;")
    return l

def SectionTitle(text):
    """Lovable SectionTitle — 15px semibold page-section header."""
    return H2(text)

def Body(text, muted=False):
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{C['text2'] if muted else C['text']}; font-size:14px; "
        f"background:transparent; border:none;")
    l.setWordWrap(True)
    return l

def Caption(text):
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{C['muted']}; font-size:13px; font-weight:600; background:transparent; border:none;")
    return l


# ── CARDS ─────────────────────────────────────────────────────────────────────

class Card(QFrame):
    """Standard section card with optional accent top-bar (Lovable rounded-xl)."""
    def __init__(self, parent=None, accent=None, flat=False):
        super().__init__(parent)
        self._accent = accent
        self._flat = flat
        self.refresh_theme()

    def refresh_theme(self):
        r = RADIUS['xl']
        if self._flat:
            self.setStyleSheet(
                f"QFrame {{ background:{C['card2']}; border:none; border-radius:{r}px; }}")
        elif self._accent:
            self.setStyleSheet(
                f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
                f"border-top:3px solid {self._accent}; border-radius:{r}px; }}")
        else:
            self.setStyleSheet(
                f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
                f"border-radius:{r}px; }}")

    def layout_v(self, margins=(20, 16, 20, 16), spacing=14):
        l = QVBoxLayout(self)
        l.setContentsMargins(*margins)
        l.setSpacing(spacing)
        return l

    def layout_h(self, margins=(20, 14, 20, 14), spacing=12):
        l = QHBoxLayout(self)
        l.setContentsMargins(*margins)
        l.setSpacing(spacing)
        return l


class KPICard(QFrame):
    """
    Premium KPI tile — icon circle + left accent border.
    Large value, readable label, optional sub-label.
    """
    def __init__(self, label, value='0', sub='', accent=None, icon=''):
        super().__init__()
        self._accent = accent or C['gold']
        self._icon   = icon
        self.setMinimumHeight(100)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # Icon circle
        self._ic = None
        if icon:
            self._ic = QLabel(icon)
            self._ic.setFixedSize(42, 42)
            self._ic.setAlignment(Qt.AlignCenter)
            root.addWidget(self._ic)

        # Text block
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)

        self._lbl = QLabel(label.upper())
        self._val = QLabel(str(value))
        self._sub = QLabel(sub)

        col.addWidget(self._lbl)
        col.addWidget(self._val)
        col.addWidget(self._sub)
        root.addLayout(col, 1)
        self.refresh_theme()

    def refresh_theme(self):
        r = RADIUS['xl']
        self.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
            f"border-left:3px solid {self._accent}; border-radius:{r}px; }}")
        if self._ic is not None:
            self._ic.setStyleSheet(
                f"background:{qss_alpha(self._accent, 0.12)}; border-radius:10px; "
                f"color:{self._accent}; font-size:18px; border:none;")
        self._lbl.setStyleSheet(
            f"color:{C['muted']}; font-size:10px; font-weight:700; "
            f"letter-spacing:1.2px; background:transparent; border:none;")
        self._val.setStyleSheet(
            f"color:{self._accent}; font-size:28px; font-weight:800; "
            f"background:transparent; border:none; line-height:1;")
        self._sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; border:none;")

    def set_value(self, v, color=None):
        self._val.setText(str(v))
        c = color or self._accent
        self._val.setStyleSheet(
            f"color:{c}; font-size:28px; font-weight:800; "
            f"background:transparent; border:none; line-height:1;")

    def set_sub(self, s):
        self._sub.setText(str(s))


def _refresh_section_icon(lbl):
    gold = C['gold']
    lbl.setStyleSheet(
        f"QLabel {{ background-color: {qss_alpha(gold, 0.15)}; color: {gold}; "
        f"border-radius:8px; font-size:14px; font-weight:800; border:none; }}")


def _refresh_badge(lbl):
    tone = lbl.property('mbtBadgeTone') or 'ok'
    tone_map = {
        'ok': C['ok'], 'warn': C['warn'], 'err': C['err'],
        'info': C['info'], 'muted': C['text2'], 'gold': C['gold'],
    }
    color = tone_map.get(str(tone), C['ok'])
    r = RADIUS['md']
    lbl.setStyleSheet(
        f"QLabel {{ color:{color}; font-size:11px; font-weight:600; "
        f"background:{qss_alpha(color, 0.10)}; border:1px solid {qss_alpha(color, 0.28)}; "
        f"border-radius:{r}px; padding:2px 10px; }}")


def refresh_themed_widgets(root):
    """Re-apply theme-bound inline styles after ThemeManager.apply (light/dark)."""
    if root is None:
        return
    for w in root.findChildren(Card):
        try:
            w.refresh_theme()
        except Exception:
            pass
    for w in root.findChildren(KPICard):
        try:
            w.refresh_theme()
        except Exception:
            pass
    for w in root.findChildren(QLabel):
        try:
            if w.objectName() == 'sectionTitle':
                # Inline H2/page_intro colors bake at build time — retint on theme change
                # so light mode never keeps dark-mode near-white text (invisible titles).
                fs = int(w.property('mbtTitleSize') or 15)
                weight = 700 if fs >= 20 else 600
                w.setStyleSheet(
                    f"color:{C['text']}; font-size:{fs}px; font-weight:{weight}; "
                    f"background:transparent; border:none;")
            elif w.objectName() == 'sectionSubtitle':
                w.setStyleSheet(
                    f"color:{C['text2']}; font-size:13px; background:transparent; border:none;")
            elif w.property('mbtSectionIcon'):
                _refresh_section_icon(w)
            elif w.property('mbtBadgeTone'):
                _refresh_badge(w)
        except Exception:
            pass
    for w in root.findChildren(QLineEdit):
        try:
            if w.objectName() == 'mbtSearchBar':
                r = RADIUS['md']
                w.setStyleSheet(
                    f"QLineEdit {{ background:{C['input']}; color:{C['text']}; "
                    f"border:1px solid {C['border']}; border-radius:{r}px; "
                    f"padding:0 12px 0 14px; font-size:13px; }}"
                    f"QLineEdit:focus {{ border-color:{C['gold']}; }}")
        except Exception:
            pass
    for w in root.findChildren(QTabWidget):
        try:
            if w.property('mbtLovableTabs'):
                w.setStyleSheet(lovable_tab_qss())
        except Exception:
            pass
    for w in root.findChildren(QWidget):
        try:
            if w.objectName() == 'mbtPageInner':
                w.setStyleSheet(f"background:{C['surface']};")
        except Exception:
            pass


# ── BUTTONS ───────────────────────────────────────────────────────────────────

def PrimaryBtn(text, height=40):
    """Gold primary action — inline QSS so Fusion/transparent parents can't hide it."""
    b = QPushButton(text)
    b.setObjectName('primaryBtn')
    b.setMinimumHeight(height)
    b.setCursor(Qt.PointingHandCursor)
    gold_fg = C.get('gold_fg', '#0A0F1A')
    b.setStyleSheet(
        f"QPushButton#primaryBtn {{ background:{C['gold']}; color:{gold_fg};"
        f" border:none; border-radius:{RADIUS['md']}px; font-weight:700;"
        f" font-size:14px; padding:8px 16px; }}"
        f"QPushButton#primaryBtn:hover {{ background:{C['gold_lt']}; color:{gold_fg}; }}"
        f"QPushButton#primaryBtn:pressed {{ background:{C['gold_dk']}; color:{gold_fg}; }}"
        f"QPushButton#primaryBtn:disabled {{ background:{C['border2']}; color:{C['muted']}; }}")
    return b


def SecondaryBtn(text, height=36):
    """Outline — secondary action. Styled via global QSS (#outlineBtn)."""
    b = QPushButton(text)
    b.setObjectName('outlineBtn')
    b.setMinimumHeight(height)
    b.setCursor(Qt.PointingHandCursor)
    return b


def GhostBtn(text, height=36):
    """Transparent ghost — tertiary action (Lovable ghost)."""
    b = QPushButton(text)
    b.setObjectName('ghostBtn')
    b.setMinimumHeight(height)
    b.setCursor(Qt.PointingHandCursor)
    return b


def DangerBtn(text, height=36):
    """Red — destructive actions."""
    b = QPushButton(text)
    b.setObjectName('dangerBtn')
    b.setMinimumHeight(height)
    b.setCursor(Qt.PointingHandCursor)
    return b


def SuccessBtn(text, height=36):
    """Green — confirm / connect."""
    b = QPushButton(text)
    b.setObjectName('successBtn')
    b.setMinimumHeight(height)
    b.setCursor(Qt.PointingHandCursor)
    return b


def IconBtn(text, height=32, width=32):
    b = QPushButton(text)
    b.setFixedSize(width, height)
    b.setCursor(Qt.PointingHandCursor)
    r = RADIUS['md']
    b.setStyleSheet(
        f"QPushButton {{ background:{C['card']}; color:{C['text']}; "
        f"border:1px solid {C['border2']}; border-radius:{r}px; font-size:14px; font-weight:600; }}"
        f"QPushButton:hover {{ color:{C['gold']}; border-color:{C['gold']}; "
        f"background:{C['hover']}; }}")
    return b


# ── INPUTS ────────────────────────────────────────────────────────────────────

def Field(placeholder='', password=False, mono=False, height=40):
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setMinimumHeight(height)
    if password:
        f.setEchoMode(QLineEdit.Password)
    if mono:
        f.setFont(QFont('Consolas', 12))
    return f


def SearchBar(placeholder='Search...'):
    """Lovable-style search input (rounded-md, not pill)."""
    f = QLineEdit()
    f.setObjectName('mbtSearchBar')
    f.setPlaceholderText(placeholder)
    f.setMinimumHeight(40)
    r = RADIUS['md']
    f.setStyleSheet(
        f"QLineEdit {{ background:{C['input']}; color:{C['text']}; "
        f"border:1px solid {C['border']}; border-radius:{r}px; "
        f"padding:0 12px 0 14px; font-size:13px; }}"
        f"QLineEdit:focus {{ border-color:{C['gold']}; }}")
    return f


def make_form(spacing=16):
    f = QFormLayout()
    f.setSpacing(spacing)
    f.setHorizontalSpacing(18)
    f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return f


def FormRow(label_text, widget, form_layout):
    if label_text:
        lbl = QLabel(label_text)
        lbl.setMinimumWidth(140)
        lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; "
            f"background:transparent; border:none;")
        form_layout.addRow(lbl, widget)
    else:
        form_layout.addRow(widget)


# ── TABLES ────────────────────────────────────────────────────────────────────

def make_table(headers, stretch_col=0, row_height=44, alt=True):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(alt)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setShowGrid(False)
    t.setFrameShape(QFrame.NoFrame)
    t.verticalHeader().setDefaultSectionSize(row_height)
    t.horizontalHeader().setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    t.horizontalHeader().setHighlightSections(False)
    t.setFocusPolicy(Qt.StrongFocus)
    return t


def tbl_item(text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None):
    item = QTableWidgetItem(str(text))
    item.setTextAlignment(align)
    if color:
        item.setForeground(QColor(color))
    return item

def tbl_right(text, color=None):
    return tbl_item(text, Qt.AlignRight | Qt.AlignVCenter, color)

def tbl_center(text, color=None):
    return tbl_item(text, Qt.AlignCenter, color)


# ── PAGE LAYOUT ───────────────────────────────────────────────────────────────

def page_layout(parent=None, margins=(24, 24, 24, 24), spacing=18):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
    inner = QWidget()
    inner.setObjectName('mbtPageInner')
    inner.setStyleSheet(f"background:{C['surface']};")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    scroll.setWidget(inner)
    if parent is not None:
        outer = QVBoxLayout(parent)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
    return lay, scroll


# ── BADGES ────────────────────────────────────────────────────────────────────

def Badge(text, color=None, tone=None):
    """
    Status badge (Lovable Badge).
    tone: 'ok' | 'warn' | 'err' | 'info' | 'muted' | 'gold'
    """
    tone_map = {
        'ok': C['ok'], 'warn': C['warn'], 'err': C['err'],
        'info': C['info'], 'muted': C['text2'], 'gold': C['gold'],
    }
    color = color or tone_map.get(tone, C['ok'])
    l = QLabel(str(text))
    l.setProperty('mbtBadgeTone', tone or 'ok')
    l.setAlignment(Qt.AlignCenter)
    r = RADIUS['md']
    l.setStyleSheet(
        f"QLabel {{ color:{color}; font-size:11px; font-weight:600; "
        f"background:{qss_alpha(color, 0.10)}; border:1px solid {qss_alpha(color, 0.28)}; "
        f"border-radius:{r}px; padding:2px 10px; }}")
    return l


# ── SEPARATOR ─────────────────────────────────────────────────────────────────

def HSep():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(
        f"border:none; border-top:1px solid {C['border']}; background:transparent;")
    return f


# ── THEME TOGGLE BUTTON ───────────────────────────────────────────────────────

def ThemeToggleBtn(on_toggle=None):
    """A Light/Dark button that calls ThemeManager.toggle() on click."""
    from desktop.utils.theme import ThemeManager, C as _C, RADIUS as _R
    btn = QPushButton('☀  Light')
    btn.setObjectName('themeBtn')
    btn.setMinimumHeight(34)
    btn.setFixedWidth(100)
    btn.setCursor(Qt.PointingHandCursor)

    def _style():
        r = _R['md']
        btn.setStyleSheet(
            f"QPushButton#themeBtn {{ background:{_C['card']}; color:{_C['text']}; "
            f"border:1px solid {_C['border']}; border-radius:{r}px; "
            f"font-size:12px; font-weight:500; padding:5px 10px; }}"
            f"QPushButton#themeBtn:hover {{ border-color:{_C['gold']}; color:{_C['gold']}; }}")

    def _update_label():
        btn.setText('🌙  Dark' if ThemeManager.is_light() else '☀  Light')
        _style()

    def _click():
        ThemeManager.toggle()
        _update_label()
        if on_toggle:
            on_toggle(ThemeManager.is_light())

    btn._refresh_theme = _update_label
    btn.clicked.connect(_click)
    _update_label()
    return btn


# ── LOVABLE CHROME HELPERS ────────────────────────────────────────────────────

def page_intro(title, subtitle='', action_widget=None):
    """
    Top row used on Lovable screens: title/subtitle left, primary action right.
    Returns (layout, title_label).
    """
    row = QHBoxLayout(); row.setSpacing(12)
    col = QVBoxLayout(); col.setSpacing(2); col.setContentsMargins(0, 0, 0, 0)
    t = QLabel(title)
    t.setObjectName('sectionTitle')
    t.setProperty('mbtTitleSize', 20)
    t.setStyleSheet(
        f"color:{C['text']}; font-size:20px; font-weight:700; "
        f"background:transparent; border:none;")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName('sectionSubtitle')
        s.setWordWrap(True)
        s.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent; border:none;")
        col.addWidget(s)
    row.addLayout(col, 1)
    if action_widget is not None:
        row.addWidget(action_widget)
    return row, t


def lovable_tab_qss():
    """Gold underline / pill tab chrome matching Lovable segmented controls."""
    gold_fg = C.get('gold_fg', '#0A0F1A')
    r = RADIUS['md']
    return f"""
    QTabWidget::pane {{
        background: {C['card']};
        border: 1px solid {C['border']};
        border-radius: {RADIUS['lg']}px;
        top: -1px;
    }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: transparent;
        color: {C['text2']};
        border: none;
        padding: 8px 16px;
        margin: 4px 2px;
        font-size: 12px; font-weight: 600;
        border-radius: {r}px;
        min-height: 28px;
    }}
    QTabBar::tab:selected {{
        background: {C['gold']};
        color: {gold_fg};
    }}
    QTabBar::tab:hover:!selected {{
        color: {C['text']};
        background: {C['hover']};
    }}
    """


def section_card(icon_text, title, desc=''):
    """
    Lovable Settings-style section card with gold icon tile + title.
    Returns (Card, body_layout) — put fields into body_layout.
    Prefer monochrome glyphs (not color emoji) so gold CSS tint applies.
    """
    card = Card()
    root = card.layout_v(margins=(22, 18, 22, 18), spacing=16)
    hdr = QHBoxLayout(); hdr.setSpacing(12)
    glyph = '◆'
    ic = QLabel(glyph)
    ic.setFixedSize(40, 40)
    ic.setAlignment(Qt.AlignCenter)
    # Lovable: bg-gold/15 text-gold
    gold = C['gold']
    ic.setStyleSheet(
        f"QLabel {{ background-color: {qss_alpha(gold, 0.15)}; color: {gold}; "
        f"border-radius:8px; font-size:14px; font-weight:800; border:none; }}")
    ic.setProperty('mbtSectionIcon', True)
    hdr.addWidget(ic)
    tcol = QVBoxLayout(); tcol.setSpacing(1); tcol.setContentsMargins(0, 0, 0, 0)
    eye = QLabel('SECTION')
    eye.setStyleSheet(
        f"color:{C['gold']}; font-size:10px; font-weight:700; "
        f"letter-spacing:2px; background:transparent; border:none;")
    ttl = QLabel(title)
    ttl.setStyleSheet(
        f"color:{C['text']}; font-size:16px; font-weight:700; "
        f"background:transparent; border:none;")
    tcol.addWidget(eye); tcol.addWidget(ttl)
    if desc:
        d = QLabel(desc)
        d.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; border:none;")
        tcol.addWidget(d)
    hdr.addLayout(tcol, 1)
    root.addLayout(hdr)
    body = QVBoxLayout(); body.setSpacing(12); body.setContentsMargins(0, 0, 0, 0)
    root.addLayout(body)
    return card, body


def wrap_table_card(table, title=None):
    """Put a QTableWidget inside a Card with optional section title."""
    card = Card()
    lay = card.layout_v(margins=(0, 0, 0, 0), spacing=0)
    if title:
        hdr = QWidget()
        hdr.setStyleSheet(f"border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16, 14, 16, 14)
        hl.addWidget(H2(title)); hl.addStretch()
        lay.addWidget(hdr)
    lay.addWidget(table)
    return card
