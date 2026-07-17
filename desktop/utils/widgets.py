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
        f"color:{C['text2']}; font-size:13px; font-weight:600; background:transparent; border:none;")
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


def _refresh_primary_btn(btn):
    """PrimaryBtn bakes gold QSS at create — retint so light/dark gold_fg stays correct."""
    gold_fg = C.get('gold_fg', '#0A0F1A')
    btn.setStyleSheet(
        f"QPushButton#primaryBtn {{ background:{C['gold']}; color:{gold_fg};"
        f" border:none; border-radius:{RADIUS['md']}px; font-weight:700;"
        f" font-size:14px; padding:8px 16px; }}"
        f"QPushButton#primaryBtn:hover {{ background:{C['gold_lt']}; color:{gold_fg}; }}"
        f"QPushButton#primaryBtn:pressed {{ background:{C['gold_dk']}; color:{gold_fg}; }}"
        f"QPushButton#primaryBtn:disabled {{ background:{C['border2']}; color:{C['muted']}; }}")


def refresh_themed_widgets(root):
    """Re-apply theme-bound inline styles after ThemeManager.apply (light/dark)."""
    if root is None:
        return
    # Guard: callers sometimes pass a dict (e.g. MainWindow._nav) by mistake
    if not hasattr(root, 'findChildren'):
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
            elif w.objectName() == 'formLabel':
                w.setStyleSheet(
                    f"color:{C['text2']}; font-size:13px; font-weight:600; "
                    f"background:transparent; border:none;")
            elif w.objectName() == 'invStatsCaption':
                # Inventory footer — must follow theme (no dark strip under light table)
                w.setStyleSheet(
                    f"color:{C['text2']}; font-size:13px; font-weight:600; "
                    f"background:transparent; padding:4px 2px;")
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
    for w in root.findChildren(QPushButton):
        try:
            if w.objectName() == 'primaryBtn':
                _refresh_primary_btn(w)
        except Exception:
            pass
    for w in root.findChildren(QTabWidget):
        try:
            if w.property('mbtLovableTabs'):
                w.setStyleSheet(lovable_tab_qss())
        except Exception:
            pass
    # Prefer named lookups — avoid walking every QWidget in large trees
    for w in root.findChildren(QWidget, 'mbtPageInner'):
        try:
            w.setStyleSheet(f"background:{C['surface']};")
        except Exception:
            pass
    for w in root.findChildren(QWidget, 'themeSwitchBar'):
        try:
            if hasattr(w, '_refresh_theme'):
                w._refresh_theme()
        except Exception:
            pass
    # QTableWidgetItem foregrounds are frozen RGB — retint tones / clear baked text
    for w in root.findChildren(QTableWidget):
        try:
            retint_table_items(w)
        except Exception:
            pass
    try:
        from desktop.utils.pos_components import refresh_pos_components
        refresh_pos_components(root)
    except Exception:
        pass
    try:
        from desktop.utils.select_controls import refresh_select_controls
        refresh_select_controls(root)
    except Exception:
        pass


# ── BUTTONS ───────────────────────────────────────────────────────────────────

def PrimaryBtn(text, height=40):
    """Gold primary action — inline QSS so Fusion/transparent parents can't hide it."""
    b = QPushButton(text)
    b.setObjectName('primaryBtn')
    b.setMinimumHeight(height)
    b.setCursor(Qt.PointingHandCursor)
    _refresh_primary_btn(b)
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
        lbl.setObjectName('formLabel')
        lbl.setMinimumWidth(140)
        lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; font-weight:600; "
            f"background:transparent; border:none;")
        form_layout.addRow(lbl, widget)
    else:
        form_layout.addRow(widget)


# ── TABLES ────────────────────────────────────────────────────────────────────

# Palette key stored on items so theme toggles can retint without DB reload
TBL_TONE_ROLE = Qt.UserRole + 41
_TBL_TONE_KEYS = (
    'text', 'text2', 'muted', 'gold', 'warn', 'err', 'ok', 'info', 'success',
)


class ThemeTableDelegate(QStyledItemDelegate):
    """
    Paint BackgroundRole + ForegroundRole explicitly.

    Global QSS on QTableWidget/::item routinely ignores item roles (and can
    leave QPalette::Base white on half the zebra). This delegate is the
    reliable path for theme-correct contrast on every row.
    """

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        bg = index.data(Qt.BackgroundRole)
        fg = index.data(Qt.ForegroundRole)

        selected = bool(opt.state & QStyle.State_Selected)
        hovered = bool(opt.state & QStyle.State_MouseOver) and not selected

        painter.save()
        painter.setPen(Qt.NoPen)

        if selected:
            fill = QColor(C['selected'])
        elif hovered:
            fill = QColor(C['hover'])
        elif isinstance(bg, QBrush) and bg.style() != Qt.NoBrush:
            fill = bg.color()
        elif bg is not None:
            fill = QColor(bg)
        else:
            fill = QColor(
                table_row_bg_hex(index.row())
                if (opt.widget and opt.widget.property('mbtZebraViaRoles'))
                else C['card']
            )
        painter.setBrush(fill)
        painter.drawRect(opt.rect)

        # Bottom hairline
        painter.setPen(QPen(QColor(C['border']), 1))
        painter.drawLine(opt.rect.bottomLeft(), opt.rect.bottomRight())

        if isinstance(fg, QBrush):
            color = fg.color()
        elif fg is not None:
            color = QColor(fg)
        else:
            color = QColor(C['text'])

        text = opt.text or ''
        if text:
            painter.setPen(color)
            painter.setFont(opt.font)
            # Match former QSS padding ~10px 14px
            text_rect = opt.rect.adjusted(14, 0, -14, 0)
            align = opt.displayAlignment or (Qt.AlignLeft | Qt.AlignVCenter)
            painter.drawText(
                text_rect, int(align) | Qt.TextSingleLine,
                painter.fontMetrics().elidedText(
                    text, Qt.ElideRight, text_rect.width()))
        painter.restore()


def make_table(headers, stretch_col=0, row_height=44, alt=True):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    # Zebra is painted via BackgroundRole + ThemeTableDelegate.
    # Qt QSS alternate-background-color overrides item roles and historically
    # leaked light-theme white rows under dark text.
    t.setAlternatingRowColors(False)
    t.setProperty('mbtZebraViaRoles', bool(alt))
    t.setItemDelegate(ThemeTableDelegate(t))
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


def table_row_bg_hex(row: int) -> str:
    """Theme-consistent zebra: even=card, odd=card2 (both dark-in-dark / light-in-light)."""
    return C['card2'] if (int(row) % 2) else C['card']


def apply_table_row_backgrounds(table, row=None):
    """
    Paint BackgroundRole on every data cell so zebra matches the live palette.

    Critical: setForeground() makes Qt use QPalette::Base (often white) for
    non-alternate rows, so QSS alternate-background-color alone leaves
    white-on-white / white-on-light zebra failures. Explicit BackgroundRole
    keeps every row on-theme with contrasting ForegroundRole tones.
    """
    if table is None or not hasattr(table, 'rowCount'):
        return
    rows = [int(row)] if row is not None else range(table.rowCount())
    for r in rows:
        if r < 0 or r >= table.rowCount():
            continue
        bg = QColor(table_row_bg_hex(r))
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item is not None:
                item.setBackground(bg)
            w = table.cellWidget(r, c) if hasattr(table, 'cellWidget') else None
            if w is not None:
                w.setAutoFillBackground(True)
                pal = w.palette()
                pal.setColor(QPalette.Window, bg)
                pal.setColor(QPalette.Base, bg)
                w.setPalette(pal)
                prev = (w.styleSheet() or '')
                if 'QPushButton' not in prev:
                    w.setStyleSheet(f"background:{bg.name()}; border:none;")


def _tone_from_color(color):
    """Map a live palette hex back to its key (for retint after theme toggle)."""
    if not color:
        return None
    if isinstance(color, str) and color in _TBL_TONE_KEYS:
        return color
    hex_c = str(color).upper()
    for k in _TBL_TONE_KEYS:
        v = C.get(k)
        if v and str(v).upper() == hex_c:
            return k
    return None


def tbl_item(text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None, tone=None):
    """
    Table cell. Prefer no color for primary text (inherits live QSS).
    Pass tone='gold'|'warn'|… or color=C['gold'] — both retint on theme change.
    """
    item = QTableWidgetItem(str(text))
    item.setTextAlignment(align)
    key = tone or _tone_from_color(color)
    if key:
        item.setData(TBL_TONE_ROLE, key)
        hex_c = C.get(key) or color
        if hex_c:
            item.setForeground(QColor(hex_c))
    elif color:
        item.setForeground(QColor(color))
    return item

def tbl_right(text, color=None, tone=None):
    return tbl_item(text, Qt.AlignRight | Qt.AlignVCenter, color, tone)

def tbl_center(text, color=None, tone=None):
    return tbl_item(text, Qt.AlignCenter, color, tone)


def retint_table_items(table):
    """Re-apply palette tones + zebra backgrounds after ThemeManager.apply."""
    if table is None or not hasattr(table, 'rowCount'):
        return
    from desktop.utils.theme import DARK, LIGHT
    # Accents that may still be frozen from the opposite palette
    accent_hex = {}
    for pal in (DARK, LIGHT):
        for k in ('gold', 'warn', 'err', 'ok', 'info', 'success', 'text2', 'muted'):
            v = pal.get(k)
            if v:
                accent_hex[str(v).lower()] = k
    text_hex = {str(DARK.get('text', '')).lower(), str(LIGHT.get('text', '')).lower()}

    for r in range(table.rowCount()):
        bg = QColor(table_row_bg_hex(r))
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item is None:
                continue
            item.setBackground(bg)
            key = item.data(TBL_TONE_ROLE)
            if key:
                hex_c = C.get(key)
                if hex_c:
                    item.setForeground(QColor(hex_c))
                continue
            # Legacy: baked ForegroundRole without tone marker
            if item.data(Qt.ForegroundRole) is None:
                # Ensure primary text still contrasts with zebra bg
                item.setData(TBL_TONE_ROLE, 'text')
                item.setForeground(QColor(C['text']))
                continue
            fg = item.foreground().color().name().lower()
            mapped = accent_hex.get(fg)
            if mapped:
                item.setData(TBL_TONE_ROLE, mapped)
                item.setForeground(QColor(C[mapped]))
            elif fg in text_hex:
                # Primary text baked from wrong theme — bind to live 'text' tone
                item.setData(TBL_TONE_ROLE, 'text')
                item.setForeground(QColor(C['text']))
        # Retint cell-widget chrome to the same zebra (action columns, etc.)
        for c in range(table.columnCount()):
            w = table.cellWidget(r, c) if hasattr(table, 'cellWidget') else None
            if w is None:
                continue
            w.setAutoFillBackground(True)
            pal = w.palette()
            pal.setColor(QPalette.Window, bg)
            pal.setColor(QPalette.Base, bg)
            w.setPalette(pal)
            # Don't clobber shells that embed QPushButton rules; palette is enough.
            prev = (w.styleSheet() or '')
            if 'QPushButton' not in prev:
                w.setStyleSheet(f"background:{bg.name()}; border:none;")


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
    """Legacy single button — prefer ThemeSwitchBar for clearer Light/Dark UX."""
    return ThemeSwitchBar(on_toggle=on_toggle)


class ThemeSwitchBar(QWidget):
    """
    Always-visible Dark | Light segmented switch.
    Active side is gold-filled; click the other side to switch.
    Icons: Dark = moon (U+263E), Light = sun (U+2600) — ASCII-safe escapes.
    """

    _DARK_LABEL = '\u263E  Dark'   # ☾
    _LIGHT_LABEL = '\u2600  Light'  # ☀

    def __init__(self, on_toggle=None, parent=None):
        super().__init__(parent)
        self._on_toggle = on_toggle
        self.setObjectName('themeSwitchBar')
        self.setFixedHeight(36)
        self.setMinimumWidth(168)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._dark_btn = QPushButton(self._DARK_LABEL)
        self._light_btn = QPushButton(self._LIGHT_LABEL)
        for b in (self._dark_btn, self._light_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(34)
            b.setMinimumWidth(84)
            b.setCheckable(True)
            b.setAutoExclusive(True)
        self._dark_btn.clicked.connect(lambda: self._pick(False))
        self._light_btn.clicked.connect(lambda: self._pick(True))
        lay.addWidget(self._dark_btn)
        lay.addWidget(self._light_btn)
        self._refresh_theme()

    def _pick(self, want_light: bool):
        from desktop.utils.theme import ThemeManager
        if want_light == ThemeManager.is_light():
            self._refresh_theme()
            return
        if self._on_toggle:
            self._on_toggle(want_light)
        else:
            ThemeManager.apply(want_light)
        self._refresh_theme()

    def _refresh_theme(self):
        from desktop.utils.theme import ThemeManager, C as _C, RADIUS as _R, qss_alpha
        is_light = ThemeManager.is_light()
        # Keep labels/icons correct even if setText was called with wrong copy
        self._dark_btn.setText(self._DARK_LABEL)
        self._light_btn.setText(self._LIGHT_LABEL)
        self._dark_btn.setChecked(not is_light)
        self._light_btn.setChecked(is_light)
        r = _R['md']
        # Outer shell
        self.setStyleSheet(
            f"QWidget#themeSwitchBar {{ background:{_C['card2']}; border:1px solid {_C['border2']}; "
            f"border-radius:{r}px; }}"
        )
        active = (
            f"background:{_C['gold']}; color:{_C.get('gold_fg', '#0B1120')}; "
            f"border:none; font-size:12px; font-weight:700; padding:4px 10px;"
        )
        idle = (
            f"background:transparent; color:{_C['text2']}; border:none; "
            f"font-size:12px; font-weight:600; padding:4px 10px;"
        )
        hover = f"color:{_C['gold']};"
        # Left dark segment
        self._dark_btn.setStyleSheet(
            f"QPushButton {{ {active if not is_light else idle} "
            f"border-top-left-radius:{r}px; border-bottom-left-radius:{r}px; "
            f"border-top-right-radius:0; border-bottom-right-radius:0; }}"
            f"QPushButton:hover {{ {hover if is_light else ''} }}"
        )
        # Right light segment
        self._light_btn.setStyleSheet(
            f"QPushButton {{ {active if is_light else idle} "
            f"border-top-right-radius:{r}px; border-bottom-right-radius:{r}px; "
            f"border-top-left-radius:0; border-bottom-left-radius:0; }}"
            f"QPushButton:hover {{ {hover if not is_light else ''} }}"
        )

    # Compat with MainWindow refresh hooks
    def setText(self, _text):
        self._refresh_theme()



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
