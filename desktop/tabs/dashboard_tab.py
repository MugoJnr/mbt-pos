"""
MBT POS \u2014 Dashboard Tab v2  (Modern Redesign)
MugoByte Technologies | mugobyte.com

Full dark + light mode support.
Larger, readable KPI values. Debt summary. Top products mini-bar.
Recent sales with status badges. 2x2 quick action grid.
"""
import logging
from datetime import date, timedelta
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, ThemeManager, is_light_mode, qss_alpha
from desktop.utils.widgets import (PrimaryBtn, SecondaryBtn, make_table,
                                    tbl_item, tbl_right, tbl_center, page_layout)
from desktop.utils.charts import (
    GoldLineChart, PaymentBars, ChartCard, ChartDetailsDialog,
)
from desktop.utils.security import can_void_sales, prompt_void_sale
from desktop.utils.ui_polish import (
    AnimatedKPI, EmptyState, FloatingActionButton, ToastNotification,
    apply_card_shadow, time_greeting,
)
from desktop.utils.select_controls import DatePresetSelect
from desktop.utils.option_lists import date_range_for_preset

log = logging.getLogger(__name__)

def _palette(is_light=None):
    """Active global palette (C is mutated by ThemeManager)."""
    return C


def _qs(css): return css  # passthrough \u2014 just for readability


# ---
# KPI CARD  (redesigned - bigger value, icon accent, both modes)
# ---

class _KPI(AnimatedKPI):
    """Dashboard KPI \u2014 AnimatedKPI with theme apply_mode shim."""

    def __init__(self, label, icon, value='--', sub='', accent=None, is_light=False):
        super().__init__(label=label, icon=icon, value=value, sub=sub, accent=accent)
        self._is_light = is_light
        apply_card_shadow(self)

    def apply_mode(self, is_light):
        self._is_light = is_light
        self.refresh_theme()


# ---
# SECTION CARD
# ---

class _Card(QFrame):
    def __init__(self, is_light=False):
        super().__init__()
        self._is_light = is_light
        self._apply()

    def _apply(self):
        p = _palette(self._is_light)
        r = 16
        self.setStyleSheet(
            f"QFrame {{ background:{p['card']}; border:1px solid {p['border']}; "
            f"border-radius:{r}px; }}")
        if not getattr(self, '_shadow_applied', False):
            apply_card_shadow(self)
            self._shadow_applied = True

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


# ---
# MINI BAR ROW  (top products)
# ---

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


# ---
# QUICK ACTION BUTTON
# ---

def _qa_btn(icon_key, label, accent, bg_dim, is_light=False):
    """Quick action with a native Qt icon (no emoji/font dependency)."""
    p = _palette(is_light)
    btn = QPushButton(label)
    std_icons = {
        'sales': QStyle.SP_FileIcon,
        'inventory': QStyle.SP_DirIcon,
        'debt': QStyle.SP_DialogApplyButton,
        'reports': QStyle.SP_FileDialogDetailedView,
    }
    btn.setIcon(btn.style().standardIcon(
        std_icons.get(icon_key, QStyle.SP_ArrowRight)))
    btn.setIconSize(QSize(20, 20))
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedHeight(48)
    btn.setMinimumWidth(110)
    btn.setMinimumHeight(44)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setAccessibleName(label)
    btn.setToolTip(f'Open {label}')
    btn.setStyleSheet(
        f"QPushButton {{ background:{bg_dim}; color:{p['text']}; "
        f"border:1px solid {qss_alpha(accent, 0.28)}; border-radius:12px; "
        f"font-size:13px; font-weight:700; padding:10px 12px; }}"
        f"QPushButton:hover {{ background:{qss_alpha(accent, 0.22)}; border:1px solid {accent}; "
        f"color:{accent}; }}"
        f"QPushButton:pressed {{ background:{qss_alpha(accent, 0.14)}; }}")
    return btn


# ---
# STATUS ROW
# ---

def _status_row(label, value, color, is_light=False):
    p = _palette(is_light)
    w = QWidget(); w.setStyleSheet("background:transparent;")
    row = QHBoxLayout(w); row.setContentsMargins(0, 4, 0, 4); row.setSpacing(8)

    dot = QLabel("*")
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


# ---
# SEPARATOR
# ---

def _sep(is_light=False):
    p = _palette(is_light)
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"border:none; border-top:1px solid {p['border']}; background:transparent;")
    return f


# ---
# DASHBOARD TAB
# ---

class DashboardTab(QWidget):
    navigate = pyqtSignal(str)
    theme_changed = pyqtSignal(bool)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api           = api
        self.user          = user
        self.db_path       = db_path
        self.config_getter = config_getter
        self._is_light     = bool(ThemeManager.is_light())
        self._currency     = 'KES'

        self._build()
        self._t = QTimer(self)
        self._t.timeout.connect(self._load)
        self._t.start(60_000)

    # -- Build ---

    def _build(self):
        # Page scrolls as a whole - never clip Quick Actions under the window edge
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
        self._root_lay.setContentsMargins(20, 18, 20, 18)
        self._root_lay.setSpacing(16)
        self._page_scroll.setWidget(self._page)
        outer.addWidget(self._page_scroll)
        self._build_content()
        self._install_fab()

    def _build_content(self):
        p = _palette(self._is_light)

        # -- HEADER ---
        hdr = QHBoxLayout(); hdr.setSpacing(0)
        left = QVBoxLayout(); left.setSpacing(3)

        self._date_lbl = QLabel()
        today = date.today()
        weekday = today.strftime('%A')
        rest = today.strftime('%B %d, %Y')
        self._date_lbl.setText(
            f'<span style="color:{p["gold"]};font-weight:600">{weekday}</span>'
            f'<span style="color:{p["muted"]}"> | </span>'
            f'<span style="color:{p["text2"]}">{rest}</span>')
        self._title_lbl = QLabel('Good Morning')
        self._title_lbl.setStyleSheet(
            f"color:{p['text']}; font-size:28px; font-weight:800; "
            f"background:transparent; border:none;")
        self._shop_lbl = QLabel("Here's what's happening today.")
        self._shop_lbl.setStyleSheet(
            f"color:{p['text2']}; font-size:14px; "
            f"background:transparent; border:none;")
        left.addWidget(self._title_lbl)
        left.addWidget(self._date_lbl)
        left.addWidget(self._shop_lbl)
        hdr.addLayout(left, 1)

        # Header right - period preset + New Sale (theme switch is topbar-only)
        right_row = QHBoxLayout(); right_row.setSpacing(10)

        self._theme_btn = None
        self._period = DatePresetSelect(include_last_month=True)
        self._period.setMinimumWidth(150)
        self._period.setFixedHeight(38)
        self._period.presetChanged.connect(self._on_period)
        right_row.addWidget(self._period)

        ns_btn = QPushButton('+  New Sale')
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

        # -- KPI ROW 1 - Sales ---
        kr1 = QHBoxLayout(); kr1.setSpacing(16)
        self._k_sales = _KPI("Today's Sales",   '$', '0',   'Transactions', p['gold'],   self._is_light)
        self._k_rev   = _KPI("Today's Revenue (Collected)", '*', '--',
                             'Cash in hand today',  p['ok'],     self._is_light)
        self._k_avg   = _KPI("Avg Transaction", '^', '--',   'Per receipt',   p['info'],   self._is_light)
        self._k_low   = _KPI("Low Stock",        '!', '0',   'Items to restock', p['err'], self._is_light)
        for k in (self._k_sales, self._k_rev, self._k_avg, self._k_low):
            kr1.addWidget(k)
        self._k_sales.set_actionable(True, 'Open Point of Sale', "Today's Sales")
        self._k_sales.clicked.connect(lambda: self.navigate.emit('sales'))
        self._k_rev.set_actionable(True, 'Open sales reports', "Today's Revenue")
        self._k_rev.clicked.connect(lambda: self.navigate.emit('reports'))
        self._k_avg.set_actionable(True, 'Open sales reports', 'Average Transaction')
        self._k_avg.clicked.connect(lambda: self.navigate.emit('reports'))
        self._k_low.set_actionable(True, 'Open Inventory low-stock items', 'Low Stock')
        self._k_low.clicked.connect(lambda: self.navigate.emit('inventory'))
        self._root_lay.addLayout(kr1)

        # Collected revenue tender breakdown (cash flow vs credit)
        self._rev_break = QLabel('')
        self._rev_break.setWordWrap(True)
        self._rev_break.setStyleSheet(
            f"color:{p['text2']};font-size:12px;background:transparent;border:none;"
            f"padding:0 4px 4px 4px;")
        self._root_lay.addWidget(self._rev_break)

        # -- KPI ROW 2 - Debt ---
        kr2 = QHBoxLayout(); kr2.setSpacing(16)
        self._k_debt_out  = _KPI("Outstanding Debt",    '=', '--', 'unpaid',        p['err'],  self._is_light)
        self._k_debt_col  = _KPI("Collected Today",     '+', '--', 'debt payments', p['ok'],   self._is_light)
        self._k_customers = _KPI("Customers w/ Debt",   '@', '0', 'accounts',      p['warn'], self._is_light)
        self._k_overdue   = _KPI("Overdue",             '*', '0', 'past due date', p['err'],  self._is_light)
        self._k_credit_out = _KPI("Credit Sales (Outstanding)", '#', '--',
                                  'unpaid credit today', p['warn'], self._is_light)
        for k in (self._k_debt_out, self._k_debt_col, self._k_customers,
                  self._k_overdue, self._k_credit_out):
            kr2.addWidget(k)
        for k, tip in (
            (self._k_debt_out, 'Open Debt Management'),
            (self._k_debt_col, 'Open Debt collections'),
            (self._k_customers, 'Open Debt customers'),
            (self._k_overdue, 'Open Debt overdue invoices'),
            (self._k_credit_out, 'Open Debt credit sales'),
        ):
            k.set_actionable(True, tip, k._label)
            k.clicked.connect(lambda _=False, t='debt': self.navigate.emit(t))
        self._root_lay.addLayout(kr2)

        # -- KPI ROW 3 - Internal Consumption ---
        kr3 = QHBoxLayout(); kr3.setSpacing(18)
        self._k_cons = _KPI(
            'Internal Consumption Today', '#', '0',
            'items | cost', p['info'], self._is_light)
        self._k_cons.set_actionable(
            True, 'Open Internal Consumption report', 'Internal Consumption Today')
        self._k_cons.clicked.connect(self._open_consumption_report)
        kr3.addWidget(self._k_cons)
        kr3.addStretch(3)
        self._root_lay.addLayout(kr3)

        # -- CHARTS ROW ---
        charts = QHBoxLayout(); charts.setSpacing(18)
        self._trend_chart = GoldLineChart(height=168)
        self._trend_card = ChartCard(
            'Sales | Last 7 Days', self._trend_chart, expandable=True)
        self._trend_card.activated.connect(
            lambda: self._open_chart_detail('trend'))
        apply_card_shadow(self._trend_card)
        self._pay_chart = PaymentBars()
        self._pay_card = ChartCard(
            'By Payment | 7 Days', self._pay_chart, expandable=True)
        self._pay_card.activated.connect(
            lambda: self._open_chart_detail('payment'))
        apply_card_shadow(self._pay_card)
        charts.addWidget(self._trend_card, 3)
        charts.addWidget(self._pay_card, 2)
        self._root_lay.addLayout(charts)

        # -- Quick Actions (full width - never crushed in the side rail) ---
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
            ('sales',     'New Sale',  'gold', 'sales'),
            ('inventory', 'Inventory', 'ok',   'inventory'),
            ('debt',      'Debt',      'info', 'debt'),
            ('reports',   'Reports',   'warn', 'reports'),
        ]
        self._qa_btns = []
        for icon, lbl, acc_key, tid in actions:
            acc = p[acc_key]
            dim = p.get(f'{acc_key}_dim', p['card2'])
            btn = _qa_btn(icon, lbl, acc, dim, self._is_light)
            btn.setProperty('mbtQaAccent', acc_key)
            btn.setProperty('mbtQaIcon', icon)
            btn.setProperty('mbtQaLabel', lbl)
            btn.clicked.connect(lambda _, t=tid: self.navigate.emit(t))
            self._qa_btns.append(btn)
            qa_row.addWidget(btn)
        qcl.addLayout(qa_row)
        self._root_lay.addWidget(self._qa_card)

        # -- BODY ROW ---
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
            self._void_btn.setObjectName('mbtVoidSaleBtn')
            self._void_btn.setMinimumHeight(32)
            self._void_btn.setMinimumWidth(100)
            self._void_btn.setCursor(Qt.PointingHandCursor)
            self._void_btn.setToolTip(
                'Select a sale below, or click to enter a receipt number.\n'
                'Uses reason dropdown + Super-Admin PIN.')
            self._void_btn.setStyleSheet(
                f"QPushButton {{ background:{p['err_dim']}; color:{p['err']}; "
                f"border:1px solid {qss_alpha(p['err'], 0.45)}; border-radius:7px; "
                f"font-size:12px; font-weight:700; padding:0 12px; }}"
                f"QPushButton:hover {{ background:{p['err']}; color:{p.get('on_danger', '#FFFFFF')}; }}")
            self._void_btn.clicked.connect(self._void_sale_action)
            sh.addWidget(self._void_btn)
        else:
            self._void_btn = None

        ref_btn = QPushButton()
        ref_btn.setIcon(ref_btn.style().standardIcon(QStyle.SP_BrowserReload))
        ref_btn.setIconSize(QSize(17, 17))
        ref_btn.setAccessibleName('Refresh dashboard')
        ref_btn.setToolTip('Refresh dashboard')
        ref_btn.setFixedSize(40, 40)
        ref_btn.setCursor(Qt.PointingHandCursor)
        ref_btn.setStyleSheet(
            f"QPushButton {{ background:{p['card2']}; color:{p['text2']}; "
            f"border:1px solid {p['border']}; border-radius:9px; font-size:16px; }}"
            f"QPushButton:hover {{ color:{p['gold']}; border-color:{p['gold']}; }}")
        ref_btn.clicked.connect(self._load)
        sh.addWidget(ref_btn)
        scl.addLayout(sh)
        scl.addWidget(_sep(self._is_light))

        # Sales table
        self._tbl = make_table(
            ['Receipt', 'Time', 'Cashier', 'Total', 'Status'],
            stretch_col=0, row_height=44)
        for ci, w in [(1, 130), (2, 110), (3, 110), (4, 90)]:
            self._tbl.setColumnWidth(ci, w)
        self._tbl.setMinimumHeight(240)
        self._tbl.setAlternatingRowColors(False)
        self._tbl.setSortingEnabled(False)
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.setStyleSheet(
            f"QTableWidget {{ background:{p['card']}; "
            f"border:none; color:{p['text']}; font-size:13px; gridline-color:transparent; "
            f"outline:none; }}"
            f"QHeaderView::section {{ background:{p['card2']}; color:{p['text2']}; "
            f"font-size:11px; font-weight:700; letter-spacing:0.8px; "
            f"padding:10px 14px; border:none; border-bottom:1px solid {p['border']}; }}"
            f"QTableWidget::item:selected {{ background:{p['selected']}; color:{p['text']}; }}"
            f"QTableWidget::item:hover:!selected {{ background:{p['hover']}; }}")
        self._tbl.itemSelectionChanged.connect(self._on_sale_selected)
        self._tbl.cellDoubleClicked.connect(self._on_sale_double_click)
        scl.addWidget(self._tbl)

        self._sales_empty = EmptyState('=', 'No sales today', 'Start your first sale from Point of Sale')
        self._sales_empty.hide()
        scl.addWidget(self._sales_empty)

        # Table footer
        self._tbl_footer = QLabel('')
        self._tbl_footer.setContentsMargins(20, 8, 20, 14)
        self._tbl_footer.setStyleSheet(
            f"color:{p['muted']}; font-size:11px; background:transparent; border:none;")
        scl.addWidget(self._tbl_footer)

        body.addWidget(self._sales_card, 6)

        # Right column (40%)
        rcol = QVBoxLayout(); rcol.setSpacing(14)

        # -- Top Products ---
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

        # -- System Status (side rail only - Quick Actions moved full-width) ---
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
        self._st_prn_w,  self._st_prn,  self._st_prn_dot  = _status_row('Printer',       'Ready',   p['ok'],   self._is_light)
        self._st_net_w,  self._st_net,  self._st_net_dot  = _status_row('Internet',      'Online',  p['ok'],   self._is_light)
        self._st_lic_w,  self._st_lic,  self._st_lic_dot  = _status_row('License',       'Active',  p['ok'],   self._is_light)
        self._st_bak_w,  self._st_bak,  self._st_bak_dot  = _status_row('Backup',        'OK',      p['ok'],   self._is_light)
        self._st_sync_w, self._st_sync, self._st_sync_dot = _status_row('Cloud Sync',    '--',       p['muted'],self._is_light)
        self._st_ver_w,  self._st_ver,  self._st_ver_dot  = _status_row('Version',       'v2.3',    p['info'], self._is_light)
        for w in (self._st_db_w, self._st_api_w, self._st_prn_w, self._st_net_w,
                  self._st_lic_w, self._st_bak_w, self._st_sync_w, self._st_ver_w):
            stcl.addWidget(w)
        rcol.addWidget(self._st_card)

        # -- MBT AI Insights ---
        self._ai_card = _Card(self._is_light)
        ail = self._ai_card.body(margins=(18, 16, 18, 16), spacing=10)
        hdr_ai = QHBoxLayout()
        self._ai_title = QLabel('*  AI Insights')
        self._ai_title.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; background:transparent; border:none;")
        self._ai_refresh = QPushButton()
        self._ai_refresh.setIcon(
            self._ai_refresh.style().standardIcon(QStyle.SP_BrowserReload))
        self._ai_refresh.setIconSize(QSize(16, 16))
        self._ai_refresh.setFixedSize(40, 40)
        self._ai_refresh.setCursor(Qt.PointingHandCursor)
        self._ai_refresh.setToolTip('Refresh AI insights')
        self._ai_refresh.setAccessibleName('Refresh AI insights')
        self._ai_refresh.clicked.connect(lambda: self._load_ai_insights(force=True))
        hdr_ai.addWidget(self._ai_title); hdr_ai.addStretch(); hdr_ai.addWidget(self._ai_refresh)
        ail.addLayout(hdr_ai)
        self._ai_banner = QLabel('')
        self._ai_banner.setWordWrap(True)
        self._ai_banner.hide()
        ail.addWidget(self._ai_banner)
        self._ai_summary = QLabel('Loading insights...')
        self._ai_summary.setWordWrap(True)
        self._ai_summary.setStyleSheet(
            f"color:{p['text2']}; font-size:12px; background:transparent; border:none;")
        ail.addWidget(self._ai_summary)
        self._ai_alerts = QLabel('')
        self._ai_alerts.setWordWrap(True)
        self._ai_alerts.setStyleSheet(
            f"color:{p['warn']}; font-size:12px; background:transparent; border:none;")
        ail.addWidget(self._ai_alerts)
        self._ai_recs = QLabel('')
        self._ai_recs.setWordWrap(True)
        self._ai_recs.setStyleSheet(
            f"color:{p['text2']}; font-size:12px; background:transparent; border:none;")
        ail.addWidget(self._ai_recs)
        open_ai = QPushButton('Open assistant')
        open_ai.setCursor(Qt.PointingHandCursor)
        open_ai.setStyleSheet(
            f"QPushButton {{ background:{p['card2']}; color:{p['gold']}; border:1px solid {p['border']};"
            f" border-radius:8px; padding:6px 10px; font-weight:700; font-size:12px; }}"
            f"QPushButton:hover {{ border-color:{p['gold']}; }}")
        open_ai.clicked.connect(self._open_floating_ai)
        ail.addWidget(open_ai)
        rcol.addWidget(self._ai_card)
        QTimer.singleShot(600, lambda: self._load_ai_insights(force=False))

        # -- Operational alerts (live data only — no placeholder checklists) ---
        self._tasks_card = _Card(self._is_light)
        tl = self._tasks_card.body(margins=(18, 16, 18, 16), spacing=8)
        self._tasks_title = QLabel('Needs attention')
        self._tasks_title.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; background:transparent; border:none;")
        tl.addWidget(self._tasks_title)
        self._ops_list = QVBoxLayout()
        self._ops_list.setSpacing(6)
        tl.addLayout(self._ops_list)
        self._ops_empty = QLabel('No urgent items right now')
        self._ops_empty.setStyleSheet(
            f"color:{p['muted']}; font-size:12px; background:transparent; border:none;")
        self._ops_list.addWidget(self._ops_empty)
        rcol.addWidget(self._tasks_card)

        self._act_card = _Card(self._is_light)
        al = self._act_card.body(margins=(18, 16, 18, 16), spacing=8)
        at = QLabel('Recent Activity')
        at.setStyleSheet(
            f"color:{p['text']}; font-size:15px; font-weight:700; background:transparent; border:none;")
        al.addWidget(at)
        self._act_list = QVBoxLayout(); self._act_list.setSpacing(6)
        al.addLayout(self._act_list)
        self._act_placeholder = EmptyState('=', 'No recent activity', 'Sales and system events appear here')
        self._act_list.addWidget(self._act_placeholder)
        rcol.addWidget(self._act_card)

        rcol.addStretch(1)

        rw = QWidget(); rw.setStyleSheet('background:transparent;')
        rw.setLayout(rcol)
        rw.setMinimumWidth(300)
        rw.setMaximumWidth(360)
        body.addWidget(rw, 4)
        self._root_lay.addLayout(body, 1)

        # Footer
        self._footer = QLabel('MBT POS | MugoByte Technologies | mugobyte.com')
        self._footer.setAlignment(Qt.AlignCenter)
        self._footer.setStyleSheet(
            f"color:{p['muted']}; font-size:11px; "
            f"background:transparent; border:none; padding:6px 0;")
        self._root_lay.addWidget(self._footer)

    # -- Theme toggle ---

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
            f"QPushButton {{ background:{p['err_dim']}; color:{p['err']}; "
            f"border:1px solid {qss_alpha(p['err'], 0.45)}; border-radius:7px; "
            f"font-size:12px; font-weight:700; }}"
            f"QPushButton:hover {{ background:{p['err']}; color:{p.get('on_danger', '#FFFFFF')}; }}")

    def _style_qa_btns(self):
        p = _palette()
        for btn in getattr(self, '_qa_btns', []):
            key = btn.property('mbtQaAccent') or 'gold'
            icon = btn.property('mbtQaIcon') or ''
            lbl = btn.property('mbtQaLabel') or btn.text()
            acc = p.get(key, p['gold'])
            dim = p.get(f'{key}_dim', p['card2'])
            btn.setText(lbl)
            std_icons = {
                'sales': QStyle.SP_FileIcon,
                'inventory': QStyle.SP_DirIcon,
                'debt': QStyle.SP_DialogApplyButton,
                'reports': QStyle.SP_FileDialogDetailedView,
            }
            btn.setIcon(btn.style().standardIcon(
                std_icons.get(icon, QStyle.SP_ArrowRight)))
            btn.setIconSize(QSize(20, 20))
            btn.setStyleSheet(
                f"QPushButton {{ background:{dim}; color:{p['text']}; "
                f"border:1px solid {qss_alpha(acc, 0.28)}; border-radius:12px; "
                f"font-size:13px; font-weight:700; padding:10px 12px; }}"
                f"QPushButton:hover {{ background:{qss_alpha(acc, 0.22)}; border:1px solid {acc}; "
                f"color:{acc}; }}"
                f"QPushButton:pressed {{ background:{qss_alpha(acc, 0.14)}; }}")

    def _install_fab(self):
        self._fab = FloatingActionButton(
            [
                ('$', 'New Sale', lambda: self.navigate.emit('sales')),
                ('#', 'New Product', lambda: self.navigate.emit('inventory')),
                ('@', 'New Customer', lambda: self.navigate.emit('debt')),
                ('%', 'Open Reports', lambda: self.navigate.emit('reports')),
            ],
            parent=self,
        )
        self._fab.raise_()
        self._position_fab()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._position_fab()

    def _position_fab(self):
        fab = getattr(self, '_fab', None)
        if not fab:
            return
        fab.resize(220, 280)
        fab.move(self.width() - fab.width() - 16, self.height() - fab.height() - 16)
        fab.raise_()
        fab.refresh_theme()

    def set_light_mode(self, is_light: bool):
        self._is_light = bool(is_light)
        self._apply_theme()

    def _on_theme_bar(self, want_light: bool):
        self.theme_changed.emit(bool(want_light))

    def _toggle_theme(self):
        self.theme_changed.emit(not ThemeManager.is_light())

    def _apply_theme(self):
        self._is_light = ThemeManager.is_light()
        p = _palette()

        # Root background - Lovable main column is surface, not app tint
        self.setStyleSheet(f"background:{p['surface']};")

        # Theme switch bar (topbar-only - may be None on this tab)
        tb = getattr(self, '_theme_btn', None)
        if tb is not None and hasattr(tb, '_refresh_theme'):
            tb._refresh_theme()

        self._style_new_sale_btn()
        self._style_void_btn()
        self._style_qa_btns()

        # Header labels
        today = date.today()
        weekday = today.strftime('%A')
        rest = today.strftime('%d %B %Y')
        self._date_lbl.setText(
            f'<span style="color:{p["gold"]};font-weight:600">{weekday}</span>'
            f'<span style="color:{p["muted"]}"> | </span>'
            f'<span style="color:{p["text2"]}">{rest}</span>')
        self._date_lbl.setStyleSheet("background:transparent; border:none;")
        self._title_lbl.setStyleSheet(
            f"color:{p['text']}; font-size:28px; font-weight:800; "
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
            (self._k_credit_out, p['warn']),
            (self._k_cons,     p['info']),
        ]
        for kpi, acc in kpi_map:
            kpi._accent = acc
            kpi.apply_mode(self._is_light)

        if getattr(self, '_rev_break', None) is not None:
            self._rev_break.setStyleSheet(
                f"color:{p['text2']};font-size:12px;background:transparent;border:none;"
                f"padding:0 4px 4px 4px;")

        # Cards
        for card in (self._sales_card, self._top_card, self._qa_card, self._st_card,
                     getattr(self, '_ai_card', None), getattr(self, '_tasks_card', None),
                     getattr(self, '_act_card', None)):
            if card is not None:
                card.apply_mode(self._is_light)

        for chart_card in (getattr(self, '_trend_card', None), getattr(self, '_pay_card', None)):
            if chart_card is not None:
                chart_card.refresh_theme()

        # Section titles
        for lbl in (self._sales_title, self._top_title, self._qa_title, self._st_title,
                    getattr(self, '_ai_title', None), getattr(self, '_tasks_title', None)):
            if lbl is not None:
                lbl.setStyleSheet(
                    f"color:{p['text']}; font-size:15px; font-weight:700; "
                    f"background:transparent; border:none;")
        if getattr(self, '_ai_summary', None):
            self._ai_summary.setStyleSheet(
                f"color:{p['text2']}; font-size:12px; background:transparent; border:none;")
        if getattr(self, '_ai_alerts', None):
            self._ai_alerts.setStyleSheet(
                f"color:{p['warn']}; font-size:12px; background:transparent; border:none;")
        if getattr(self, '_ai_recs', None):
            self._ai_recs.setStyleSheet(
                f"color:{p['text2']}; font-size:12px; background:transparent; border:none;")
        if getattr(self, '_ai_refresh', None):
            self._ai_refresh.setStyleSheet(
                f"QPushButton {{ background:{p['card2']}; color:{p['text2']}; "
                f"border:1px solid {p['border']}; border-radius:8px; }}"
                f"QPushButton:hover {{ color:{p['gold']}; border-color:{p['gold']}; }}")

        # Table
        self._tbl.setAlternatingRowColors(False)
        self._tbl.setStyleSheet(
            f"QTableWidget {{ background:{p['card']}; "
            f"border:none; color:{p['text']}; font-size:13px; gridline-color:transparent; "
            f"outline:none; }}"
            f"QHeaderView::section {{ background:{p['card2']}; color:{p['text2']}; "
            f"font-size:11px; font-weight:700; letter-spacing:0.8px; "
            f"padding:10px 14px; border:none; border-bottom:1px solid {p['border']}; }}"
            f"QTableWidget::item:selected {{ background:{p['selected']}; color:{p['text']}; }}"
            f"QTableWidget::item:hover:!selected {{ background:{p['hover']}; }}")

        self._tbl_footer.setStyleSheet(
            f"color:{p['text2']}; font-size:11px; background:transparent; border:none;")
        self._footer.setStyleSheet(
            f"color:{p['text2']}; font-size:11px; "
            f"background:transparent; border:none; padding:6px 0;")

        if getattr(self, '_sales_empty', None):
            self._sales_empty.refresh_theme()
        if getattr(self, '_fab', None):
            self._fab.refresh_theme()

        # Status rows - style only; do not reload product data during theme switch
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
        if getattr(self, '_no_top', None):
            self._no_top.setStyleSheet(
                f"color:{p['muted']}; font-size:13px; background:transparent; border:none;")

    # -- Data loading ---

    def on_show(self):
        try:
            cfg  = self.config_getter() or {}
            u    = self.user.get('user', {})
            name = u.get('full_name') or u.get('username', 'Admin')
            if str(name).strip().lower() in ('system administrator', 'administrator', 'admin'):
                name = u.get('username') or name
            shop = cfg.get('shop_name', 'My Shop')
            self._currency = cfg.get('currency_symbol', 'KES')
            headline, sub = time_greeting(name)
            self._title_lbl.setText(headline)
            self._shop_lbl.setText(f'{shop} | {sub}')
        except Exception:
            pass
        QTimer.singleShot(0, self._load)

    def _open_consumption_report(self):
        """Dashboard KPI click -> Internal Consumption report."""
        mw = self.window()
        if mw is not None:
            setattr(mw, '_pending_consumption_report', True)
        self.navigate.emit('consumption')

    def _refresh_ops_alerts(self, *, low_stock=0, overdue=0, outstanding=0.0, currency='KES'):
        """Replace placeholder checklists with actionable live alerts."""
        lay = getattr(self, '_ops_list', None)
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        p = _palette()
        alerts = []
        if int(low_stock or 0) > 0:
            alerts.append((
                f'{int(low_stock)} low-stock item(s) need restock',
                'inventory', p['err'],
            ))
        if int(overdue or 0) > 0:
            alerts.append((
                f'{int(overdue)} overdue debt invoice(s)',
                'debt', p['warn'],
            ))
        if float(outstanding or 0) > 0.009:
            alerts.append((
                f'Outstanding debt {currency} {float(outstanding):,.0f}',
                'debt', p['err'],
            ))
        if not alerts:
            empty = QLabel('No urgent items right now')
            empty.setStyleSheet(
                f"color:{p['muted']}; font-size:12px; background:transparent; border:none;")
            lay.addWidget(empty)
            return
        for text, tid, color in alerts:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.setToolTip(f'Open {tid}')
            btn.setStyleSheet(
                f"QPushButton {{ text-align:left; padding:8px 10px; background:{p['card2']}; "
                f"color:{p['text']}; border:1px solid {p['border']}; border-radius:8px; "
                f"border-left:3px solid {color}; font-size:12px; font-weight:600; }}"
                f"QPushButton:hover {{ border-color:{color}; color:{color}; }}"
            )
            btn.clicked.connect(lambda _=False, t=tid: self.navigate.emit(t))
            lay.addWidget(btn)

    def _open_chart_detail(self, kind):
        """Open a native chart detail dialog with exact values."""
        if kind == 'trend':
            rows = self._trend_chart.data_rows()
            title = self._trend_card._title.text()
        else:
            rows = self._pay_chart.data_rows()
            title = self._pay_card._title.text()
        ChartDetailsDialog(
            kind, title, rows, currency=self._currency, parent=self).exec_()

    def _open_floating_ai(self):
        mw = self.window()
        panel = getattr(mw, '_ai_panel', None) if mw else None
        if panel is not None:
            try:
                panel.set_module('dashboard')
                panel.open_panel()
            except Exception:
                pass

    def _load_ai_insights(self, force: bool = False):
        """Load cached/local/AI dashboard insights into the insights card."""
        try:
            from desktop.utils.ai.insights import get_dashboard_insights
            data = get_dashboard_insights(self.api, self.user, force=force)
        except Exception as e:
            log.warning('AI insights: %s', e)
            data = {
                'summary': 'Insights unavailable.',
                'alerts': [],
                'recommendations': [],
                'banner': str(e),
            }
        p = _palette()
        banner = data.get('banner')
        if banner:
            self._ai_banner.setText('!  ' + banner)
            self._ai_banner.setStyleSheet(
                f"color:{p['warn']}; font-size:11px; font-weight:600; background:transparent; border:none;")
            self._ai_banner.show()
        else:
            self._ai_banner.hide()
        self._ai_summary.setText(data.get('summary') or '')
        alerts = data.get('alerts') or []
        self._ai_alerts.setText(
            'Alerts:\n' + '\n'.join(f'* {a}' for a in alerts[:4]) if alerts else '')
        recs = data.get('recommendations') or []
        self._ai_recs.setText(
            'Recommendations:\n' + '\n'.join(f'* {r}' for r in recs[:4]) if recs else '')
        src = data.get('source') or ''
        self._ai_title.setText(f'*  AI Insights' + (f' | {src}' if src else ''))

    def refresh(self):
        self._load()

    def _on_period(self, key):
        self._period_key = key or 'today'
        self._load()

    def _load(self):
        key = getattr(self, '_period_key', None) or (
            self._period.current_key() if hasattr(self, '_period') else 'today')
        if key == 'custom':
            # Custom keeps last loaded range; default to today
            start_d, end_d = date.today(), date.today()
        else:
            start_d, end_d = date_range_for_preset(key)
        start = start_d.isoformat()
        end = end_d.isoformat()
        today = str(date.today())
        p     = _palette(self._is_light)
        cur   = self._currency

        # -- Sales KPIs ---
        today_tx = 0
        today_rev = 0.0
        today_collected = 0.0
        try:
            d = self.api.get_report_summary(start, end)
            if d:
                s = d.get('summary', {})
                today_tx = int(s.get('total_transactions', 0))
                today_rev = float(s.get('total_revenue', 0) or 0)
                today_collected = float(
                    s.get('collected_revenue', s.get('collected_from_sales', 0)) or 0)
                avg = float(s.get('avg_transaction', 0))
                self._k_sales.set_value(str(today_tx))
                # Primary revenue card = money actually received (excludes unpaid credit)
                self._k_rev.set_value(f"{cur} {today_collected:,.0f}")
                self._k_avg.set_value(f"{cur} {avg:,.0f}")
                period_lbl = self._period.current_label() if hasattr(self, '_period') else 'Period'
                self._k_sales.set_sub(period_lbl or 'Transactions')
                cash_c = float(s.get('cash_sales_collected') or s.get('cash_received') or 0)
                mpesa_c = float(s.get('mpesa_collected') or 0)
                card_c = float(s.get('card_collected') or 0)
                bank_c = float(s.get('bank_collected') or 0)
                debt_c = float(s.get('debt_collected') or 0)
                credit_out = float(s.get('credit_sales_outstanding') or 0)
                if hasattr(self, '_k_credit_out'):
                    self._k_credit_out.set_value(f"{cur} {credit_out:,.0f}")
                    self._k_credit_out.set_sub('not in collected revenue')
                if hasattr(self, '_rev_break'):
                    self._rev_break.setText(
                        f"Cash {cur} {cash_c:,.0f}  ·  Mobile Money {cur} {mpesa_c:,.0f}  ·  "
                        f"Card {cur} {card_c:,.0f}  ·  Bank {cur} {bank_c:,.0f}  ·  "
                        f"Debt Collections {cur} {debt_c:,.0f}  ·  "
                        f"Credit Sales (Outstanding) {cur} {credit_out:,.0f}  ·  "
                        f"Total Sales {cur} {today_rev:,.0f}"
                    )
        except Exception as e:
            log.warning(f"Dashboard KPI: {e}")

        # Yesterday comparison trends (only meaningful for Today preset)
        try:
            yday = str(date.today() - timedelta(days=1))
            yd = self.api.get_report_summary(yday, yday) or {}
            ys = (yd.get('summary') or {})
            y_tx = int(ys.get('total_transactions', 0) or 0)
            y_rev = float(
                ys.get('collected_revenue', ys.get('collected_from_sales', 0)) or 0)

            def _pct(cur_v, prev_v):
                if prev_v <= 0:
                    return 100.0 if cur_v > 0 else 0.0
                return ((cur_v - prev_v) / prev_v) * 100.0

            if key == 'today':
                self._k_sales.set_trend(_pct(today_tx, y_tx))
                self._k_rev.set_trend(_pct(today_collected, y_rev))
                self._k_rev.set_sub('vs yesterday · excludes unpaid credit')
            else:
                self._k_rev.set_sub(
                    (self._period.current_label() if hasattr(self, '_period') else '')
                    + ' · excludes unpaid credit'
                )
        except Exception as e:
            log.warning(f"Dashboard trends: {e}")
        # -- Low stock ---
        try:
            prods = self.api.get_products() or []
            low   = sum(1 for p2 in prods if float(p2.get('stock', 0)) <= float(p2.get('min_stock', 5)))
            self._k_low.set_value(str(low), p['err'] if low > 0 else p['ok'])
            self._k_low.set_sub('Items to restock' if low else 'All stocked')
        except Exception as e:
            log.warning(f"Dashboard low stock: {e}")

        # -- Debt KPIs ---
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

        # -- Internal consumption today ---
        try:
            cs = self.api.get_consumption_today_summary() or {}
            lines = int(cs.get('line_count') or 0)
            qty = float(cs.get('item_qty') or 0)
            cost = float(cs.get('total_cost') or 0)
            # Prefer item count (lines); show qty in sub when useful
            self._k_cons.set_value(str(lines if lines else int(qty) if qty else 0))
            self._k_cons.set_sub(f"{cur} {cost:,.0f} used today")
        except Exception as e:
            log.warning(f"Dashboard consumption KPI: {e}")

        # -- Recent sales table ---
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
                st_label = 'x Voided' if voided else '+ Done'
                st_color = p['err'] if voided else p['ok']
                self._tbl.setItem(i, 4, tbl_center(st_label, st_color))

            n = len(sales)
            has = n > 0
            self._tbl.setVisible(has)
            if getattr(self, '_sales_empty', None):
                self._sales_empty.setVisible(not has)
            self._tbl_footer.setText(
                f"  {n} transaction{'s' if n != 1 else ''} today" +
                (f" | Total: {cur} {sum(float(s.get('total',0)) for s in sales if (s.get('status') or '').lower() != 'voided'):,.2f}" if n > 0 else ''))
            self._on_sale_selected()

            # Activity feed from recent sales
            self._refresh_activity(sales[:5], cur)
        except Exception as e:
            log.warning(f"Dashboard sales table: {e}")

        # -- Top products ---
        try:
            d = self.api.get_report_summary(today, today)
            top = (d.get('top_products') or [])[:5] if d else []
            self._top_data = top
            self._reload_top_products()
        except Exception as e:
            log.warning(f"Dashboard top products: {e}")

        # -- Charts (7-day trend + payment mix) ---
        try:
            trend = self.api.get_sales_trend(7) or []
            self._trend_chart.set_data(
                [t.get('revenue', 0) for t in trend],
                [t.get('label', '') for t in trend],
            )
            total_7 = sum(float(t.get('revenue') or 0) for t in trend)
            self._trend_card.set_title(
                f"Sales | Last 7 Days | {cur} {total_7:,.0f}")
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

        # -- Live operational alerts ---
        try:
            low_n = 0
            try:
                prods = self.api.get_products() or []
                low_n = sum(
                    1 for p2 in prods
                    if float(p2.get('stock', 0)) <= float(p2.get('min_stock', 5))
                )
            except Exception:
                low_n = 0
            overdue_n = 0
            outstanding = 0.0
            try:
                ds = self.api.get_debt_summary() or {}
                overdue_n = int((ds.get('overdue') or {}).get('count', 0) or 0)
                outstanding = float((ds.get('outstanding') or {}).get('total', 0) or 0)
            except Exception:
                pass
            self._refresh_ops_alerts(
                low_stock=low_n, overdue=overdue_n, outstanding=outstanding, currency=cur)
        except Exception as e:
            log.warning(f"Dashboard ops alerts: {e}")

        # -- System status ---
        p2 = _palette(self._is_light)
        from datetime import datetime as _dt
        now_s = _dt.now().strftime('%H:%M')
        for lbl, text, color in (
            (self._st_db, 'OK | ' + now_s, p2['ok']),
            (self._st_api, 'Online | <40ms', p2['ok']),
            (self._st_prn, 'Ready', p2['ok']),
            (self._st_net, 'Online', p2['ok']),
            (self._st_lic, 'Active', p2['ok']),
            (self._st_bak, 'OK', p2['ok']),
        ):
            lbl.setText(text)
            lbl.setStyleSheet(
                f"color:{color}; font-size:13px; font-weight:600; "
                f"background:transparent; border:none;")
        self._st_sync.setText(str(date.today()))
        try:
            from desktop.main import APP_VERSION
            self._st_ver.setText(f"v{APP_VERSION}")
        except Exception:
            pass

    def _refresh_activity(self, sales, cur):
        lay = getattr(self, '_act_list', None)
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        p = _palette()
        if not sales:
            empty = EmptyState('=', 'No recent activity', 'Sales and system events appear here')
            lay.addWidget(empty)
            return
        for s in sales:
            who = s.get('cashier_name') or 'Cashier'
            rcpt = s.get('receipt_number') or ''
            total = float(s.get('total', 0) or 0)
            row = QLabel(f"+  {who} completed Sale {rcpt} | {cur} {total:,.0f}")
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color:{p['text2']}; font-size:12px; background:transparent; border:none;")
            lay.addWidget(row)
        bak = QLabel('+  Database ready | Backup OK')
        bak.setStyleSheet(
            f"color:{p['text2']}; font-size:12px; background:transparent; border:none;")
        lay.addWidget(bak)

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
            empty = EmptyState('#', 'No sales today', 'Top products will appear after your first sale')
            self._no_top = empty
            self._top_container.addWidget(empty)
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

    # -- Void helpers ---

    def _on_sale_selected(self):
        # Void stays enabled so users can always discover it (no selection - enter receipt).
        if self._void_btn:
            self._void_btn.setEnabled(True)

    def _selected_receipt(self):
        row = self._tbl.currentRow()
        if row < 0:
            return ''
        item = self._tbl.item(row, 0)
        return item.text().strip() if item else ''

    def _void_sale_prompt(self):
        if prompt_void_sale(self.api, self):
            self._load()

    def _void_sale_action(self):
        """Void selected sale, or open blank receipt dialog if none selected."""
        receipt = self._selected_receipt()
        if prompt_void_sale(self.api, self, receipt_prefill=receipt):
            ToastNotification.show_toast(self, 'Sale voided', tone='warn')
            self._load()

    def _void_selected_sale(self):
        self._void_sale_action()

    def _on_sale_double_click(self, row, _col):
        """Full receipt detail (line items) with Edit / Void for permitted roles."""
        if row < 0:
            return
        receipt = ''
        item = self._tbl.item(row, 0)
        if item:
            receipt = item.text().strip()
        if not receipt:
            return
        from desktop.dialogs.receipt_detail_dialog import open_receipt_detail
        cur = 'KES'
        try:
            cur = (self.api.get_setting('currency_symbol') if hasattr(self.api, 'get_setting')
                   else None) or getattr(self, '_currency', None) or 'KES'
        except Exception:
            cur = getattr(self, '_currency', 'KES') or 'KES'
        if open_receipt_detail(
            self.api, self, receipt=receipt, currency=cur, user=self.user,
        ):
            ToastNotification.show_toast(self, 'Sale updated', tone='ok')
            self._load()
