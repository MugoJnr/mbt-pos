"""
MBT POS — Dashboard Tab v2  (Modern Redesign)
MugoByte Technologies | mugobyte.com

Full dark + light mode support.
Larger, readable KPI values. Debt summary. Top products mini-bar.
Recent sales with status badges. 2×2 quick action grid.
"""
import logging
from datetime import date, timedelta
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, ThemeManager, is_light_mode, qss_alpha
from desktop.utils.widgets import (PrimaryBtn, SecondaryBtn, make_table,
                                    tbl_item, tbl_right, tbl_center, page_layout)
from desktop.utils.charts import GoldBarChart, PaymentBars, ChartCard
from desktop.utils.security import can_void_sales, prompt_void_sale

log = logging.getLogger(__name__)

def _palette(is_light=None):
    """Active global palette (C is mutated by ThemeManager)."""
    return C


def _qs(css): return css  # passthrough — just for readability


# ══════════════════════════════════════════════════════════════════════════════
# KPI CARD  (redesigned — bigger value, icon accent, both modes)
# ══════════════════════════════════════════════════════════════════════════════

class _KPI(QFrame):
    def __init__(self, label, icon, value='—', sub='', accent=None, is_light=False):
        super().__init__()
        self._accent   = accent
        self._is_light = is_light
        self._label    = label
        self._icon_ch  = icon
        self._build(value, sub)

    def _build(self, value, sub):
        p = _palette(self._is_light)
        a = self._accent or p['gold']

        self.setStyleSheet(
            f"QFrame {{ background:{p['card']}; border:1px solid {p['border']}; "
            f"border-radius:14px; border-left:4px solid {a}; }}")
        self.setMinimumHeight(100)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # Icon circle
        icon_lbl = QLabel(self._icon_ch)
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background:{qss_alpha(a, 0.14)}; border-radius:22px; "
            f"color:{a}; font-size:20px; border:none;")
        root.addWidget(icon_lbl)

        # Text
        col = QVBoxLayout(); col.setSpacing(2); col.setContentsMargins(0,0,0,0)
        self._lbl_w = QLabel(self._label.upper())
        self._lbl_w.setStyleSheet(
            f"color:{p['muted']}; font-size:10px; font-weight:700; "
            f"letter-spacing:1.2px; background:transparent; border:none;")
        self._val_w = QLabel(str(value))
        self._val_w.setStyleSheet(
            f"color:{a}; font-size:30px; font-weight:900; "
            f"background:transparent; border:none;")
        self._sub_w = QLabel(str(sub))
        self._sub_w.setStyleSheet(
            f"color:{p['text2']}; font-size:12px; "
            f"background:transparent; border:none;")
        col.addWidget(self._lbl_w)
        col.addWidget(self._val_w)
        col.addWidget(self._sub_w)
        root.addLayout(col, 1)

    def set_value(self, v, color=None):
        p = _palette(self._is_light)
        a = color or self._accent or p['gold']
        self._val_w.setText(str(v))
        self._val_w.setStyleSheet(
            f"color:{a}; font-size:30px; font-weight:900; "
            f"background:transparent; border:none;")

    def set_sub(self, s):
        self._sub_w.setText(str(s))

    def apply_mode(self, is_light):
        self._is_light = is_light
        p = _palette(is_light)
        a = self._accent or p['gold']
        self.setStyleSheet(
            f"QFrame {{ background:{p['card']}; border:1px solid {p['border']}; "
            f"border-radius:14px; border-left:4px solid {a}; }}")
        self._lbl_w.setStyleSheet(
            f"color:{p['muted']}; font-size:10px; font-weight:700; "
            f"letter-spacing:1.2px; background:transparent; border:none;")
        self._sub_w.setStyleSheet(
            f"color:{p['text2']}; font-size:12px; "
            f"background:transparent; border:none;")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION CARD
# ══════════════════════════════════════════════════════════════════════════════

class _Card(QFrame):
    def __init__(self, is_light=False):
        super().__init__()
        self._is_light = is_light
        self._apply()

    def _apply(self):
        p = _palette(self._is_light)
        self.setStyleSheet(
            f"QFrame {{ background:{p['card']}; border:1px solid {p['border']}; "
            f"border-radius:14px; }}")

    def apply_mode(self, is_light):
        self._is_light = is_light
        self._apply()

    def body(self, margins=(20,18,20,18), spacing=14):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*margins)
        lay.setSpacing(spacing)
        return lay

    def header_row(self, title, is_light=False):
        p = _palette(is_light)
        row = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; "
            f"background:transparent; border:none;")
        row.addWidget(lbl)
        row.addStretch()
        return row, lbl


# ══════════════════════════════════════════════════════════════════════════════
# MINI BAR ROW  (top products)
# ══════════════════════════════════════════════════════════════════════════════

class _BarRow(QWidget):
    def __init__(self, name, value_str, pct, accent, is_light=False):
        super().__init__()
        p = _palette(is_light)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self); lay.setContentsMargins(0,2,0,2); lay.setSpacing(10)

        nm = QLabel(name)
        nm.setFixedWidth(130)
        nm.setStyleSheet(
            f"color:{p['text']}; font-size:13px; background:transparent; border:none;")
        nm.setToolTip(name)

        track = QProgressBar()
        track.setRange(0, 100)
        track.setValue(int(pct))
        track.setTextVisible(False)
        track.setFixedHeight(8)
        track.setStyleSheet(
            f"QProgressBar {{ background:{p['border']}; border-radius:4px; border:none; }}"
            f"QProgressBar::chunk {{ background:{accent}; border-radius:4px; }}")

        val = QLabel(value_str)
        val.setFixedWidth(90)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setStyleSheet(
            f"color:{accent}; font-size:13px; font-weight:700; "
            f"background:transparent; border:none;")

        lay.addWidget(nm); lay.addWidget(track, 1); lay.addWidget(val)


# ══════════════════════════════════════════════════════════════════════════════
# QUICK ACTION BUTTON
# ══════════════════════════════════════════════════════════════════════════════

def _qa_btn(icon, label, accent, bg_dim, is_light=False):
    """Flat quick-action button — fixed size so grid rows never overlap."""
    p = _palette(is_light)
    btn = QPushButton(label)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(44)
    btn.setMinimumWidth(110)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setStyleSheet(
        f"QPushButton {{ background:{bg_dim}; color:{p['text']}; "
        f"border:1px solid {qss_alpha(accent, 0.28)}; border-radius:10px; "
        f"font-size:13px; font-weight:700; padding:8px; }}"
        f"QPushButton:hover {{ background:{qss_alpha(accent, 0.20)}; border:1px solid {accent}; "
        f"color:{accent}; }}"
        f"QPushButton:pressed {{ background:{qss_alpha(accent, 0.14)}; }}")
    return btn


# ══════════════════════════════════════════════════════════════════════════════
# STATUS ROW
# ══════════════════════════════════════════════════════════════════════════════

def _status_row(label, value, color, is_light=False):
    p = _palette(is_light)
    w = QWidget(); w.setStyleSheet("background:transparent;")
    row = QHBoxLayout(w); row.setContentsMargins(0, 4, 0, 4); row.setSpacing(8)

    dot = QLabel("●")
    dot.setStyleSheet(
        f"color:{color}; font-size:13px; background:transparent; border:none;")
    lbl = QLabel(label)
    lbl.setStyleSheet(
        f"color:{p['text2']}; font-size:13px; background:transparent; border:none;")
    val = QLabel(value)
    val.setStyleSheet(
        f"color:{p['text']}; font-size:13px; font-weight:600; "
        f"background:transparent; border:none;")
    row.addWidget(dot); row.addWidget(lbl); row.addStretch(); row.addWidget(val)
    return w, val, dot


# ══════════════════════════════════════════════════════════════════════════════
# SEPARATOR
# ══════════════════════════════════════════════════════════════════════════════

def _sep(is_light=False):
    p = _palette(is_light)
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"border:none; border-top:1px solid {p['border']}; background:transparent;")
    return f


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD TAB
# ══════════════════════════════════════════════════════════════════════════════

class DashboardTab(QWidget):
    navigate = pyqtSignal(str)
    theme_changed = pyqtSignal(bool)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api           = api
        self.user          = user
        self.db_path       = db_path
        self.config_getter = config_getter
        self._is_light     = False
        self._currency     = 'KES'

        self._build()
        self._t = QTimer(self)
        self._t.timeout.connect(self._load)
        self._t.start(60_000)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Page scrolls as a whole — never clip Quick Actions under the window edge
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._page_scroll = QScrollArea()
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setFrameShape(QFrame.NoFrame)
        self._page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._page_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        self._page = QWidget()
        self._page.setStyleSheet('background:transparent;')
        self._root_lay = QVBoxLayout(self._page)
        self._root_lay.setContentsMargins(28, 24, 28, 24)
        self._root_lay.setSpacing(20)
        self._page_scroll.setWidget(self._page)
        outer.addWidget(self._page_scroll)
        self._build_content()

    def _build_content(self):
        p = _palette(self._is_light)

        # ── HEADER ──────────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(0)
        left = QVBoxLayout(); left.setSpacing(3)

        self._date_lbl = QLabel()
        today = date.today()
        weekday = today.strftime('%A')
        rest = today.strftime('%d %B %Y')
        self._date_lbl.setText(f"{weekday}  ·  {rest}")
        self._date_lbl.setStyleSheet(
            f"color:{p['text2']}; font-size:12px; font-weight:500; "
            f"letter-spacing:0.4px; background:transparent; border:none;")
        # Emphasize weekday via rich text
        self._date_lbl.setText(
            f'<span style="color:{p["gold"]};font-weight:600">{weekday}</span>'
            f'<span style="color:{p["muted"]}">  ·  </span>'
            f'<span style="color:{p["text2"]}">{rest}</span>')
        self._title_lbl = QLabel('Welcome back')
        self._title_lbl.setStyleSheet(
            f"color:{p['text']}; font-size:26px; font-weight:800; "
            f"background:transparent; border:none;")
        self._shop_lbl = QLabel('Loading...')
        self._shop_lbl.setStyleSheet(
            f"color:{p['text2']}; font-size:14px; "
            f"background:transparent; border:none;")
        left.addWidget(self._date_lbl)
        left.addWidget(self._title_lbl)
        left.addWidget(self._shop_lbl)
        hdr.addLayout(left, 1)

        # Header right buttons
        right_row = QHBoxLayout(); right_row.setSpacing(10)

        self._theme_btn = QPushButton('☀ Light' if not self._is_light else '🌙 Dark')
        self._theme_btn.setMinimumHeight(38)
        self._theme_btn.setFixedWidth(100)
        self._theme_btn.setCursor(Qt.PointingHandCursor)
        self._theme_btn.setStyleSheet(
            f"QPushButton {{ background:{p['card2']}; color:{p['text']}; "
            f"border:1px solid {p['border2']}; border-radius:8px; "
            f"font-size:13px; font-weight:600; }}"
            f"QPushButton:hover {{ border-color:{p['gold']}; color:{p['gold']}; }}")
        self._theme_btn.clicked.connect(self._toggle_theme)
        right_row.addWidget(self._theme_btn)

        ns_btn = QPushButton('＋  New Sale')
        ns_btn.setObjectName('primaryBtn')
        ns_btn.setMinimumHeight(38)
        ns_btn.setFixedWidth(130)
        ns_btn.setCursor(Qt.PointingHandCursor)
        self._ns_btn = ns_btn
        self._style_new_sale_btn()
        ns_btn.clicked.connect(lambda: self.navigate.emit('sales'))
        right_row.addWidget(ns_btn)

        hdr.addLayout(right_row)
        self._root_lay.addLayout(hdr)

        # ── KPI ROW 1 — Sales ────────────────────────────────────────────────
        kr1 = QHBoxLayout(); kr1.setSpacing(14)
        self._k_sales = _KPI("Today's Sales",   '🛒', '0',   'transactions', p['gold'],   self._is_light)
        self._k_rev   = _KPI("Today's Revenue", '💰', '—',   'gross income',  p['ok'],     self._is_light)
        self._k_avg   = _KPI("Avg Transaction", '📈', '—',   'per receipt',   p['info'],   self._is_light)
        self._k_low   = _KPI("Low Stock",        '⚠', '0',   'items',         p['err'],    self._is_light)
        for k in (self._k_sales, self._k_rev, self._k_avg, self._k_low):
            kr1.addWidget(k)
        self._root_lay.addLayout(kr1)

        # ── KPI ROW 2 — Debt ────────────────────────────────────────────────
        kr2 = QHBoxLayout(); kr2.setSpacing(14)
        self._k_debt_out  = _KPI("Outstanding Debt",    '📋', '—', 'unpaid',        p['err'],  self._is_light)
        self._k_debt_col  = _KPI("Collected Today",     '✅', '—', 'debt payments', p['ok'],   self._is_light)
        self._k_customers = _KPI("Customers w/ Debt",   '👤', '0', 'accounts',      p['warn'], self._is_light)
        self._k_overdue   = _KPI("Overdue",             '🔔', '0', 'past due date', p['err'],  self._is_light)
        for k in (self._k_debt_out, self._k_debt_col, self._k_customers, self._k_overdue):
            kr2.addWidget(k)
        self._root_lay.addLayout(kr2)

        # ── CHARTS ROW (Lovable-style) ───────────────────────────────────────
        charts = QHBoxLayout(); charts.setSpacing(14)
        self._trend_chart = GoldBarChart(height=148)
        self._trend_card = ChartCard('Sales · Last 7 Days', self._trend_chart)
        self._pay_chart = PaymentBars()
        self._pay_card = ChartCard('By Payment · 7 Days', self._pay_chart)
        charts.addWidget(self._trend_card, 3)
        charts.addWidget(self._pay_card, 2)
        self._root_lay.addLayout(charts)

        # ── Quick Actions (full width — never crushed in the side rail) ───────
        self._qa_card = _Card(self._is_light)
        self._qa_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        qcl = self._qa_card.body(margins=(16, 14, 16, 14), spacing=10)
        self._qa_title = QLabel('Quick Actions')
        self._qa_title.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; "
            f"background:transparent; border:none;")
        qcl.addWidget(self._qa_title)
        qa_row = QHBoxLayout(); qa_row.setSpacing(10)
        actions = [
            ('New Sale',   'gold',  'sales'),
            ('Inventory',  'ok',    'inventory'),
            ('Debt',       'info',  'debt'),
            ('Reports',    'warn',  'reports'),
        ]
        self._qa_btns = []
        for lbl, acc_key, tid in actions:
            acc = p[acc_key]
            dim = p.get(f'{acc_key}_dim', p['card2'])
            btn = _qa_btn('', lbl, acc, dim, self._is_light)
            btn.setProperty('mbtQaAccent', acc_key)
            btn.clicked.connect(lambda _, t=tid: self.navigate.emit(t))
            self._qa_btns.append(btn)
            qa_row.addWidget(btn)
        qcl.addLayout(qa_row)
        self._root_lay.addWidget(self._qa_card)

        # ── BODY ROW ─────────────────────────────────────────────────────────
        body = QHBoxLayout(); body.setSpacing(16)

        # Left: Recent Sales (60%)
        self._sales_card = _Card(self._is_light)
        scl = self._sales_card.body((0, 0, 0, 0), 0)

        # Card header
        sh = QHBoxLayout(); sh.setContentsMargins(20, 18, 16, 14); sh.setSpacing(8)
        self._sales_title = QLabel('Recent Sales')
        self._sales_title.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; "
            f"background:transparent; border:none;")
        sh.addWidget(self._sales_title)
        sh.addStretch()

        if can_void_sales(self.user):
            self._void_btn = QPushButton('Void Sale')
            self._void_btn.setMinimumHeight(32)
            self._void_btn.setFixedWidth(90)
            self._void_btn.setCursor(Qt.PointingHandCursor)
            self._void_btn.setStyleSheet(
                f"QPushButton {{ background:{qss_alpha(p['err'], 0.12)}; color:{p['err']}; "
                f"border:1px solid {qss_alpha(p['err'], 0.40)}; border-radius:7px; "
                f"font-size:12px; font-weight:700; }}"
                f"QPushButton:hover {{ background:{p['err']}; color:#fff; }}")
            self._void_btn.clicked.connect(self._void_selected_sale)
            sh.addWidget(self._void_btn)
        else:
            self._void_btn = None

        ref_btn = QPushButton('↺')
        ref_btn.setFixedSize(32, 32)
        ref_btn.setCursor(Qt.PointingHandCursor)
        ref_btn.setStyleSheet(
            f"QPushButton {{ background:{p['card2']}; color:{p['text2']}; "
            f"border:1px solid {p['border']}; border-radius:8px; font-size:16px; }}"
            f"QPushButton:hover {{ color:{p['gold']}; border-color:{p['gold']}; }}")
        ref_btn.clicked.connect(self._load)
        sh.addWidget(ref_btn)
        scl.addLayout(sh)
        scl.addWidget(_sep(self._is_light))

        # Sales table
        self._tbl = make_table(
            ['Receipt', 'Time', 'Cashier', 'Total', 'Status'],
            stretch_col=0, row_height=42)
        for ci, w in [(1, 130), (2, 110), (3, 110), (4, 90)]:
            self._tbl.setColumnWidth(ci, w)
        self._tbl.setMinimumHeight(220)
        self._tbl.setStyleSheet(
            f"QTableWidget {{ background:{p['card']}; border:none; "
            f"color:{p['text']}; font-size:13px; gridline-color:{p['border']}; }}"
            f"QHeaderView::section {{ background:{p['card2']}; color:{p['muted']}; "
            f"font-size:11px; font-weight:700; letter-spacing:0.8px; "
            f"padding:8px 14px; border:none; border-bottom:1px solid {p['border']}; }}"
            f"QTableWidget::item {{ padding:0 14px; }}"
            f"QTableWidget::item:selected {{ background:{p['selected']}; color:{p['text']}; }}")
        self._tbl.itemSelectionChanged.connect(self._on_sale_selected)
        scl.addWidget(self._tbl)

        # Table footer
        self._tbl_footer = QLabel('')
        self._tbl_footer.setContentsMargins(20, 8, 20, 14)
        self._tbl_footer.setStyleSheet(
            f"color:{p['muted']}; font-size:11px; background:transparent; border:none;")
        scl.addWidget(self._tbl_footer)

        body.addWidget(self._sales_card, 6)

        # Right column (40%)
        rcol = QVBoxLayout(); rcol.setSpacing(14)

        # ── Top Products ──────────────────────────────────────────────────────
        self._top_card = _Card(self._is_light)
        self._top_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        tcl = self._top_card.body()
        self._top_title = QLabel('Top Products Today')
        self._top_title.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; "
            f"background:transparent; border:none;")
        tcl.addWidget(self._top_title)
        self._top_container = QVBoxLayout()
        self._top_container.setSpacing(6)
        tcl.addLayout(self._top_container)
        self._no_top = QLabel('No sales yet today')
        self._no_top.setStyleSheet(
            f"color:{p['muted']}; font-size:13px; background:transparent; border:none;")
        self._no_top.setAlignment(Qt.AlignCenter)
        self._no_top.setMinimumHeight(60)
        self._top_container.addWidget(self._no_top)
        rcol.addWidget(self._top_card)

        # ── System Status (side rail only — Quick Actions moved full-width) ───
        self._st_card = _Card(self._is_light)
        self._st_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        stcl = self._st_card.body(spacing=2)
        self._st_title = QLabel('System Status')
        self._st_title.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; "
            f"background:transparent; border:none;")
        stcl.addWidget(self._st_title)
        stcl.addWidget(_sep(self._is_light))

        self._st_db_w,   self._st_db,   self._st_db_dot   = _status_row('Database',     'OK',      p['ok'],   self._is_light)
        self._st_api_w,  self._st_api,  self._st_api_dot  = _status_row('API',           'Online',  p['ok'],   self._is_light)
        self._st_sync_w, self._st_sync, self._st_sync_dot = _status_row('Last Sync',     '—',       p['muted'],self._is_light)
        self._st_ver_w,  self._st_ver,  self._st_ver_dot  = _status_row('Version',       'v2.3',    p['info'], self._is_light)
        for w in (self._st_db_w, self._st_api_w, self._st_sync_w, self._st_ver_w):
            stcl.addWidget(w)
        rcol.addWidget(self._st_card)
        rcol.addStretch(1)

        rw = QWidget(); rw.setStyleSheet('background:transparent;')
        rw.setLayout(rcol)
        rw.setMinimumWidth(300)
        rw.setMaximumWidth(360)
        body.addWidget(rw, 4)
        self._root_lay.addLayout(body, 1)

        # Footer
        self._footer = QLabel('MBT POS  ·  MugoByte Technologies  ·  mugobyte.com')
        self._footer.setAlignment(Qt.AlignCenter)
        self._footer.setStyleSheet(
            f"color:{p['muted']}; font-size:11px; "
            f"background:transparent; border:none; padding:6px 0;")
        self._root_lay.addWidget(self._footer)

    # ── Theme toggle ──────────────────────────────────────────────────────────

    def _style_new_sale_btn(self):
        p = _palette()
        gold_fg = p.get('gold_fg', '#0A0F1A')
        gold_lt = p.get('gold_lt', p['gold'])
        self._ns_btn.setStyleSheet(
            f"QPushButton {{ background:{p['gold']}; color:{gold_fg}; "
            f"border:none; border-radius:8px; font-size:13px; font-weight:700; }}"
            f"QPushButton:hover {{ background:{gold_lt}; color:{gold_fg}; }}")

    def _style_void_btn(self):
        if not getattr(self, '_void_btn', None):
            return
        p = _palette()
        self._void_btn.setStyleSheet(
            f"QPushButton {{ background:{qss_alpha(p['err'], 0.12)}; color:{p['err']}; "
            f"border:1px solid {qss_alpha(p['err'], 0.40)}; border-radius:7px; "
            f"font-size:12px; font-weight:700; }}"
            f"QPushButton:hover {{ background:{p['err']}; color:#fff; }}")

    def _style_qa_btns(self):
        p = _palette()
        for btn in getattr(self, '_qa_btns', []):
            key = btn.property('mbtQaAccent') or 'gold'
            acc = p.get(key, p['gold'])
            dim = p.get(f'{key}_dim', p['card2'])
            btn.setStyleSheet(
                f"QPushButton {{ background:{dim}; color:{p['text']}; "
                f"border:1px solid {qss_alpha(acc, 0.28)}; border-radius:10px; "
                f"font-size:13px; font-weight:700; padding:10px 8px; }}"
                f"QPushButton:hover {{ background:{qss_alpha(acc, 0.20)}; border:1px solid {acc}; "
                f"color:{acc}; }}"
                f"QPushButton:pressed {{ background:{qss_alpha(acc, 0.14)}; }}")

    def set_light_mode(self, is_light: bool):
        self._is_light = bool(is_light)
        self._apply_theme()

    def _toggle_theme(self):
        self.theme_changed.emit(not ThemeManager.is_light())

    def _apply_theme(self):
        self._is_light = ThemeManager.is_light()
        p = _palette()

        # Root background — Lovable main column is surface, not app tint
        self.setStyleSheet(f"background:{p['surface']};")

        # Theme button
        self._theme_btn.setText('Dark' if self._is_light else 'Light')
        self._theme_btn.setStyleSheet(
            f"QPushButton {{ background:{p['card2']}; color:{p['text']}; "
            f"border:1px solid {p['border2']}; border-radius:8px; "
            f"font-size:13px; font-weight:600; }}"
            f"QPushButton:hover {{ border-color:{p['gold']}; color:{p['gold']}; }}")

        self._style_new_sale_btn()
        self._style_void_btn()
        self._style_qa_btns()

        # Header labels
        today = date.today()
        weekday = today.strftime('%A')
        rest = today.strftime('%d %B %Y')
        self._date_lbl.setText(
            f'<span style="color:{p["gold"]};font-weight:600">{weekday}</span>'
            f'<span style="color:{p["muted"]}">  ·  </span>'
            f'<span style="color:{p["text2"]}">{rest}</span>')
        self._date_lbl.setStyleSheet("background:transparent; border:none;")
        self._title_lbl.setStyleSheet(
            f"color:{p['text']}; font-size:26px; font-weight:800; "
            f"background:transparent; border:none;")
        self._shop_lbl.setStyleSheet(
            f"color:{p['text2']}; font-size:14px; "
            f"background:transparent; border:none;")

        # KPI cards
        kpi_map = [
            (self._k_sales,    p['gold']),
            (self._k_rev,      p['ok']),
            (self._k_avg,      p['info']),
            (self._k_low,      p['err']),
            (self._k_debt_out, p['err']),
            (self._k_debt_col, p['ok']),
            (self._k_customers,p['warn']),
            (self._k_overdue,  p['err']),
        ]
        for kpi, acc in kpi_map:
            kpi._accent = acc
            kpi.apply_mode(self._is_light)

        # Cards
        for card in (self._sales_card, self._top_card, self._qa_card, self._st_card):
            card.apply_mode(self._is_light)

        for chart_card in (getattr(self, '_trend_card', None), getattr(self, '_pay_card', None)):
            if chart_card is not None:
                chart_card.refresh_theme()

        # Section titles
        for lbl in (self._sales_title, self._top_title, self._qa_title, self._st_title):
            lbl.setStyleSheet(
                f"color:{p['text']}; font-size:15px; font-weight:700; "
                f"background:transparent; border:none;")

        # Table
        self._tbl.setStyleSheet(
            f"QTableWidget {{ background:{p['card']}; border:none; "
            f"color:{p['text']}; font-size:13px; gridline-color:{p['border']}; }}"
            f"QHeaderView::section {{ background:{p['card2']}; color:{p['muted']}; "
            f"font-size:11px; font-weight:700; letter-spacing:0.8px; "
            f"padding:8px 14px; border:none; border-bottom:1px solid {p['border']}; }}"
            f"QTableWidget::item {{ padding:0 14px; }}"
            f"QTableWidget::item:selected {{ background:{p['selected']}; color:{p['text']}; }}")

        self._tbl_footer.setStyleSheet(
            f"color:{p['muted']}; font-size:11px; background:transparent; border:none;")
        self._footer.setStyleSheet(
            f"color:{p['muted']}; font-size:11px; "
            f"background:transparent; border:none; padding:6px 0;")

        # Status rows — style only; do not reload product data during theme switch
        for w, val, dot in ((self._st_db_w, self._st_db, self._st_db_dot),
                             (self._st_api_w, self._st_api, self._st_api_dot)):
            w.setStyleSheet("background:transparent;")
        # Restyle existing top-product rows if present (no DB hit)
        try:
            self._restyle_top_products()
        except Exception:
            pass

    def _restyle_top_products(self):
        """Theme-only restyle for top products list (no API)."""
        p = _palette()
        for i in range(self._top_container.count()):
            item = self._top_container.itemAt(i)
            w = item.widget() if item else None
            if w is None:
                continue
            for child in w.findChildren(QLabel):
                # keep structure; only nudge common text colors when unmarked
                pass
        if getattr(self, '_no_top', None):
            self._no_top.setStyleSheet(
                f"color:{p['muted']}; font-size:13px; background:transparent; border:none;")

    # ── Data loading ──────────────────────────────────────────────────────────

    def on_show(self):
        try:
            cfg  = self.config_getter() or {}
            u    = self.user.get('user', {})
            name = u.get('full_name') or u.get('username', 'Admin')
            shop = cfg.get('shop_name', 'My Shop')
            self._currency = cfg.get('currency_symbol', 'KES')
            self._title_lbl.setText(f'Welcome back, {name}')
            self._shop_lbl.setText(f'{shop}  ·  Daily Overview')
        except Exception:
            pass
        QTimer.singleShot(0, self._load)

    def refresh(self):
        self._load()

    def _load(self):
        today = str(date.today())
        p     = _palette(self._is_light)
        cur   = self._currency

        # ── Sales KPIs ────────────────────────────────────────────────────────
        try:
            d = self.api.get_report_summary(today, today)
            if d:
                s = d.get('summary', {})
                self._k_sales.set_value(str(int(s.get('total_transactions', 0))))
                rev = float(s.get('total_revenue', 0))
                avg = float(s.get('avg_transaction', 0))
                self._k_rev.set_value(f"{cur} {rev:,.0f}")
                self._k_avg.set_value(f"{cur} {avg:,.0f}")
        except Exception as e:
            log.warning(f"Dashboard KPI: {e}")

        # ── Low stock ─────────────────────────────────────────────────────────
        try:
            prods = self.api.get_products() or []
            low   = sum(1 for p2 in prods if float(p2.get('stock', 0)) <= float(p2.get('min_stock', 5)))
            self._k_low.set_value(str(low), p['err'] if low > 0 else p['ok'])
        except Exception as e:
            log.warning(f"Dashboard low stock: {e}")

        # ── Debt KPIs ─────────────────────────────────────────────────────────
        try:
            ds = self.api.get_debt_summary()
            if ds:
                out  = ds.get('outstanding', {})
                col  = ds.get('today_collected', {})
                over = ds.get('overdue', {})
                cust = ds.get('customers_with_debt', 0)
                self._k_debt_out.set_value(
                    f"{cur} {float(out.get('total',0)):,.0f}",
                    p['err'] if float(out.get('total',0)) > 0 else p['ok'])
                self._k_debt_col.set_value(f"{cur} {float(col.get('total',0)):,.0f}")
                self._k_customers.set_value(str(cust))
                self._k_overdue.set_value(
                    str(int(over.get('count', 0))),
                    p['err'] if int(over.get('count', 0)) > 0 else p['ok'])
        except Exception as e:
            log.warning(f"Dashboard debt KPIs: {e}")

        # ── Recent sales table ────────────────────────────────────────────────
        try:
            sales = self.api.get_sales(today, today) or []
            self._tbl.setRowCount(0)
            for i, s in enumerate(sales[:40]):
                self._tbl.insertRow(i)
                status = (s.get('status') or 'completed').lower()
                voided = status == 'voided'

                self._tbl.setItem(i, 0, tbl_item(s.get('receipt_number', '')))
                t = (s.get('created_at', '') or '')
                self._tbl.setItem(i, 1, tbl_item(t[11:16] if len(t) > 11 else t))
                self._tbl.setItem(i, 2, tbl_item(s.get('cashier_name', '')))
                total_col = p['muted'] if voided else p['ok']
                self._tbl.setItem(i, 3, tbl_right(
                    f"{cur} {float(s.get('total', 0)):,.2f}", total_col))
                st_label = '✕ Voided' if voided else '✓ Done'
                st_color = p['err'] if voided else p['ok']
                self._tbl.setItem(i, 4, tbl_center(st_label, st_color))

            n = len(sales)
            self._tbl_footer.setText(
                f"  {n} transaction{'s' if n != 1 else ''} today" +
                (f"  ·  Total: {cur} {sum(float(s.get('total',0)) for s in sales if (s.get('status') or '').lower() != 'voided'):,.2f}" if n > 0 else ''))
            self._on_sale_selected()
        except Exception as e:
            log.warning(f"Dashboard sales table: {e}")

        # ── Top products ──────────────────────────────────────────────────────
        try:
            d = self.api.get_report_summary(today, today)
            top = (d.get('top_products') or [])[:5] if d else []
            self._top_data = top
            self._reload_top_products()
        except Exception as e:
            log.warning(f"Dashboard top products: {e}")

        # ── Charts (7-day trend + payment mix) ───────────────────────────────
        try:
            trend = self.api.get_sales_trend(7) or []
            self._trend_chart.set_data(
                [t.get('revenue', 0) for t in trend],
                [t.get('label', '') for t in trend],
            )
            total_7 = sum(float(t.get('revenue') or 0) for t in trend)
            self._trend_card.set_title(
                f"Sales · Last 7 Days  ·  {cur} {total_7:,.0f}")
        except Exception as e:
            log.warning(f"Dashboard sales trend: {e}")

        try:
            start_7 = (date.today() - timedelta(days=6)).isoformat()
            pay_data = self.api.get_report_summary(start_7, today) or {}
            by_pay = pay_data.get('by_payment') or []
            self._pay_chart.set_data([
                {
                    'label': (r.get('payment_method') or 'Other').title(),
                    'value': float(r.get('total') or 0),
                }
                for r in by_pay
            ])
        except Exception as e:
            log.warning(f"Dashboard payment chart: {e}")

        # ── System status ─────────────────────────────────────────────────────
        p2 = _palette(self._is_light)
        self._st_db.setText('OK')
        self._st_db.setStyleSheet(
            f"color:{p2['ok']}; font-size:13px; font-weight:600; "
            f"background:transparent; border:none;")
        self._st_api.setText('Online')
        self._st_api.setStyleSheet(
            f"color:{p2['ok']}; font-size:13px; font-weight:600; "
            f"background:transparent; border:none;")
        self._st_sync.setText(str(date.today()))
        try:
            from desktop.main import APP_VERSION
            self._st_ver.setText(f"v{APP_VERSION}")
        except Exception:
            pass

    def _reload_top_products(self):
        # Clear existing bar rows
        while self._top_container.count():
            item = self._top_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        top = getattr(self, '_top_data', [])
        p   = _palette(self._is_light)
        cur = self._currency

        if not top:
            self._no_top = QLabel('No sales yet today')
            self._no_top.setStyleSheet(
                f"color:{p['muted']}; font-size:13px; "
                f"background:transparent; border:none;")
            self._no_top.setAlignment(Qt.AlignCenter)
            self._no_top.setMinimumHeight(60)
            self._top_container.addWidget(self._no_top)
            return

        accents = [p['gold'], p['ok'], p['info'], p['warn'], p['err']]
        max_rev = max((float(t.get('revenue', 0)) for t in top), default=1)
        for i, t in enumerate(top):
            rev = float(t.get('revenue', 0))
            pct = int(rev / max_rev * 100) if max_rev > 0 else 0
            name = (t.get('product_name') or '')[:22]
            val_str = f"{cur} {rev:,.0f}"
            bar = _BarRow(name, val_str, pct, accents[i % len(accents)], self._is_light)
            self._top_container.addWidget(bar)

    # ── Void helpers ──────────────────────────────────────────────────────────

    def _on_sale_selected(self):
        if self._void_btn:
            self._void_btn.setEnabled(self._tbl.currentRow() >= 0)

    def _selected_receipt(self):
        row = self._tbl.currentRow()
        if row < 0:
            return ''
        item = self._tbl.item(row, 0)
        return item.text().strip() if item else ''

    def _void_sale_prompt(self):
        if prompt_void_sale(self.api, self):
            self._load()

    def _void_selected_sale(self):
        receipt = self._selected_receipt()
        if not receipt:
            QMessageBox.warning(self, 'Select Sale',
                                'Select a receipt from the table first.')
            return
        if prompt_void_sale(self.api, self, receipt_prefill=receipt):
            self._load()
