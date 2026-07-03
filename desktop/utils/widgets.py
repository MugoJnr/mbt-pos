"""
MBT POS - Premium UI Components
MugoByte Technologies | mugobyte.com
"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme import C, COLORS, MBT_STYLESHEET


# Typography
def H1(text, color=None):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color or C['text']}; font-size:22px; font-weight:800; background:transparent;")
    return l

def H2(text, color=None):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color or C['text']}; font-size:16px; font-weight:700; background:transparent;")
    return l

def H3(text):
    l = QLabel(text.upper())
    l.setStyleSheet(f"color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:1.5px; background:transparent;")
    return l

def Body(text, muted=False):
    l = QLabel(text)
    l.setStyleSheet(f"color:{C['text2'] if muted else C['text']}; font-size:14px; background:transparent;")
    l.setWordWrap(True)
    return l

def Caption(text):
    l = QLabel(text)
    l.setStyleSheet(f"color:{C['muted']}; font-size:12px; background:transparent;")
    return l


# Cards
class Card(QFrame):
    def __init__(self, parent=None, accent=None, flat=False):
        super().__init__(parent)
        if flat:
            self.setStyleSheet(f"QFrame {{ background:{C['card2']}; border:none; border-radius:12px; }}")
        elif accent:
            self.setStyleSheet(
                f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
                f"border-top:3px solid {accent}; border-radius:12px; }}")
        else:
            self.setStyleSheet(f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:12px; }}")

    def layout_v(self, margins=(22,18,22,18), spacing=14):
        l = QVBoxLayout(self); l.setContentsMargins(*margins); l.setSpacing(spacing)
        return l

    def layout_h(self, margins=(22,16,22,16), spacing=14):
        l = QHBoxLayout(self); l.setContentsMargins(*margins); l.setSpacing(spacing)
        return l


class KPICard(QFrame):
    """Premium metric tile - top accent bar, large value, label."""
    def __init__(self, label, value='0', sub='', accent=None):
        super().__init__()
        self._accent = accent or C['gold']
        self.setMinimumHeight(110)
        self.setStyleSheet(f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:12px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top accent bar
        bar = QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet(f"background:{self._accent}; border:none; border-top-left-radius:12px; border-top-right-radius:12px;")
        root.addWidget(bar)

        body = QWidget()
        body.setStyleSheet("background:transparent; border:none;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(5)

        self._lbl = QLabel(label.upper())
        self._lbl.setStyleSheet(f"color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:1.5px; background:transparent;")

        self._val = QLabel(str(value))
        self._val.setStyleSheet(f"color:{self._accent}; font-size:28px; font-weight:900; background:transparent;")

        self._sub = QLabel(sub)
        self._sub.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")

        bl.addWidget(self._lbl)
        bl.addWidget(self._val)
        bl.addWidget(self._sub)
        root.addWidget(body)

    def set_value(self, v, color=None):
        self._val.setText(str(v))
        c = color or self._accent
        self._val.setStyleSheet(f"color:{c}; font-size:28px; font-weight:900; background:transparent;")

    def set_sub(self, s): self._sub.setText(s)


# ── Buttons ────────────────────────────────────────────────────────────────────
# Each button carries its own stylesheet so it never depends on objectName
# cascade working correctly in PyQt5 on Windows.

def PrimaryBtn(text, height=42):
    """Gold gradient — main action (Save, Add, Charge, Run…)"""
    b = QPushButton(text)
    b.setMinimumHeight(height); b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"    stop:0 {C['gold_lt']}, stop:1 {C['gold']});"
        f"  color: #0A0F18;"
        f"  border: none; border-radius: 8px;"
        f"  font-size: 13.5px; font-weight: 800;"
        f"  padding: 8px 22px;"
        f"}}"
        f"QPushButton:hover   {{ background: {C['gold_lt']}; color: #000; }}"
        f"QPushButton:pressed {{ background: {C['gold_dk']}; color: #000; }}"
        f"QPushButton:disabled {{ background: {C['panel']}; color: {C['muted']}; border: 1px solid {C['border2']}; }}"
    )
    return b


def SecondaryBtn(text, height=38):
    """Dark card — secondary action (Cancel, Refresh, Back…)"""
    b = QPushButton(text)
    b.setMinimumHeight(height); b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{"
        f"  background: {C['card2']};"
        f"  color: {C['text']};"
        f"  border: 1px solid {C['border2']}; border-radius: 8px;"
        f"  font-size: 13px; font-weight: 500;"
        f"  padding: 7px 18px;"
        f"}}"
        f"QPushButton:hover   {{ background: {C['hover']}; color: {C['text']}; border-color: {C['gold']}40; }}"
        f"QPushButton:pressed {{ background: {C['app']}; color: {C['text']}; }}"
        f"QPushButton:disabled {{ background: {C['panel']}; color: {C['muted']}; }}"
    )
    return b


def DangerBtn(text, height=38):
    """Red — destructive actions (Delete…)"""
    b = QPushButton(text)
    b.setMinimumHeight(height); b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{"
        f"  background: {C['err']};"
        f"  color: #ffffff;"
        f"  border: none; border-radius: 8px;"
        f"  font-size: 13px; font-weight: 700;"
        f"  padding: 7px 18px;"
        f"}}"
        f"QPushButton:hover   {{ background: #FF6B78; color: #fff; }}"
        f"QPushButton:pressed {{ background: #CC2233; }}"
        f"QPushButton:disabled {{ background: {C['panel']}; color: {C['muted']}; }}"
    )
    return b


def SuccessBtn(text, height=38):
    """Green — confirm / send / connect actions"""
    b = QPushButton(text)
    b.setMinimumHeight(height); b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{"
        f"  background: {C['ok']};"
        f"  color: #0A0F18;"
        f"  border: none; border-radius: 8px;"
        f"  font-size: 13px; font-weight: 700;"
        f"  padding: 7px 18px;"
        f"}}"
        f"QPushButton:hover   {{ background: #1DFAA0; color: #000; }}"
        f"QPushButton:pressed {{ background: #00A870; }}"
        f"QPushButton:disabled {{ background: {C['panel']}; color: {C['muted']}; }}"
    )
    return b

def IconBtn(text, height=36, width=36):
    b = QPushButton(text); b.setFixedSize(width, height); b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton {{ background:{C['card2']}; color:{C['text']}; border:1px solid {C['border2']}; border-radius:8px; font-size:14px; }}"
        f"QPushButton:hover {{ color:{C['gold']}; border-color:{C['gold']}40; background:{C['hover']}; }}")
    return b


# Inputs
def Field(placeholder='', password=False, mono=False, height=42):
    f = QLineEdit(); f.setPlaceholderText(placeholder); f.setMinimumHeight(height)
    if password: f.setEchoMode(QLineEdit.Password)
    if mono: f.setFont(QFont('Consolas', 12))
    return f

def SearchBar(placeholder='Search...'):
    f = QLineEdit()
    f.setPlaceholderText(f'  \U0001f50d  {placeholder}')
    f.setMinimumHeight(42)
    f.setStyleSheet(
        f"QLineEdit {{ background:{C['input']}; color:{C['text']}; border:1px solid {C['border2']}; border-radius:21px; padding:0 18px; font-size:13.5px; }}"
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
        lbl.setMinimumWidth(130)
        lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:13.5px; background:transparent;")
        form_layout.addRow(lbl, widget)
    else:
        form_layout.addRow(widget)


# Tables
def make_table(headers, stretch_col=0, row_height=40, alt=True):
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
    t.setFocusPolicy(Qt.NoFocus)
    return t

def tbl_item(text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None):
    item = QTableWidgetItem(str(text)); item.setTextAlignment(align)
    if color: item.setForeground(QColor(color))
    return item

def tbl_right(text, color=None): return tbl_item(text, Qt.AlignRight | Qt.AlignVCenter, color)
def tbl_center(text, color=None): return tbl_item(text, Qt.AlignCenter, color)


# Page layout
def page_layout(parent=None, margins=(28, 24, 28, 28), spacing=22):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
    inner = QWidget(); inner.setStyleSheet(f"background:{C['surface']};")
    lay = QVBoxLayout(inner); lay.setContentsMargins(*margins); lay.setSpacing(spacing)
    scroll.setWidget(inner)
    if parent is not None:
        outer = QVBoxLayout(parent); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
    return lay, scroll


def Badge(text, color=None):
    color = color or C['ok']
    l = QLabel(text)
    l.setStyleSheet(
        f"QLabel {{ color:{color}; font-size:11px; font-weight:700; "
        f"background-color:{color}18; border:1px solid {color}44; "
        f"border-radius:10px; padding:2px 10px; }}")
    return l
