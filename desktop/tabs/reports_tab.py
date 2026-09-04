"""MBT POS - Reports | MugoByte Technologies"""
import os, sys, logging
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from datetime import date, timedelta
from desktop.utils.theme   import C
from desktop.utils.widgets import (KPICard, Card, H2, Caption, PrimaryBtn,
                                    SecondaryBtn, DangerBtn, SuccessBtn, GhostBtn,
                                    make_table, tbl_item, tbl_right,
                                    tbl_center, page_layout, Badge, lovable_tab_qss,
                                    wrap_table_card, page_intro,
                                    apply_table_row_backgrounds, retint_table_items,
                                    align_header_right, fit_columns_to_content,
                                    apply_cell_tooltips, attach_table_empty_state)
from desktop.utils.security import has_permission
from desktop.utils.charts import GoldBarChart, PaymentBars, ChartCard
from desktop.utils.select_controls import DatePresetSelect, refresh_select_controls
from desktop.utils.option_lists import date_range_for_preset
from desktop.utils.date_controls import (
    make_date_edit, add_labeled, refresh_filter_labels, refresh_date_edits,
    DATE_API_FMT,
)

_log = logging.getLogger(__name__)
_PR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Statuses counted by ApiClient.get_report_summary / get_sale_items_for_range.
# The Sales List and the Excel export must use exactly this predicate or the
# table shows rows (e.g. voided sales) that the KPI totals excluded.
REPORT_SALE_STATUSES = ('completed', 'return')


def is_reportable_sale(sale) -> bool:
    """True when a sale row belongs in reported revenue."""
    status = ((sale or {}).get('status') or 'completed')
    return str(status).strip().lower() in REPORT_SALE_STATUSES


def reportable_sales(sales) -> list:
    return [s for s in (sales or []) if is_reportable_sale(s)]


def _get_export_dir():
    for d in (os.path.join(os.path.expanduser('~'), 'Desktop'),
              os.path.join(os.path.expanduser('~'), 'Documents'),
              os.path.expanduser('~')):
        if os.path.isdir(d):
            folder = os.path.join(d, 'MBT POS Exports')
            os.makedirs(folder, exist_ok=True)
            return folder
    folder = os.path.join(_PR, 'exports')
    os.makedirs(folder, exist_ok=True)
    return folder


class ReportsTab(QWidget):
    # Signals for thread-safe UI updates
    _report_progress = pyqtSignal(str)
    _report_done     = pyqtSignal(bool, str)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self._last_export_path = None
        self._report_progress.connect(self._on_report_progress)
        self._report_done.connect(self._on_report_done)
        self._build()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build(self):
        lay, _ = page_layout(self)

        # Lovable-style top actions
        actions = QWidget()
        ar = QHBoxLayout(actions); ar.setContentsMargins(0, 0, 0, 0); ar.setSpacing(8)
        self._exp_btn = PrimaryBtn('Export Excel', 40)
        try:
            from desktop.utils.nav_icons import apply_button_icon
            apply_button_icon(self._exp_btn, 'export', 15)
        except Exception:
            pass
        self._exp_btn.clicked.connect(self._export)
        self._pdf_btn = SecondaryBtn('Export PDF', 40)
        self._pdf_btn.setToolTip(
            'Save a direct PDF of this period (same totals as the KPIs)')
        try:
            from desktop.utils.nav_icons import apply_button_icon
            apply_button_icon(self._pdf_btn, 'export', 15)
        except Exception:
            pass
        self._pdf_btn.clicked.connect(self._export_pdf)
        self._email_btn = SecondaryBtn('Email Report', 40)
        try:
            from desktop.utils.nav_icons import apply_button_icon
            apply_button_icon(self._email_btn, 'email', 15)
        except Exception:
            pass
        self._email_btn.setToolTip('Send via cloud notification / email (Telegram permanently removed)')
        self._email_btn.clicked.connect(self._send_cloud_report)
        ar.addWidget(self._email_btn); ar.addWidget(self._pdf_btn)
        ar.addWidget(self._exp_btn)
        intro, _ = page_intro('Reports', 'Sales, cash rounding, payment variance, products and payment breakdown.', actions)
        lay.addLayout(intro)

        # ── Filter bar (single clean row — labels are plain text, not pills) ──
        today = date.today()
        fc = Card()
        fl = fc.layout_h((16, 12, 16, 12), 10)
        self._preset = DatePresetSelect()
        self._preset.setMinimumWidth(160)
        self._preset.presetChanged.connect(self._on_preset)
        self._s = make_date_edit(today)
        self._e = make_date_edit(today)
        add_labeled(fl, 'Period', self._preset, spacing=14)
        add_labeled(fl, 'From', self._s, spacing=14)
        add_labeled(fl, 'To', self._e, spacing=10)
        fl.addStretch()
        run = PrimaryBtn('Run', 40)
        run.setFixedWidth(100)
        try:
            from desktop.utils.nav_icons import apply_button_icon
            apply_button_icon(run, 'refresh', 15)
        except Exception:
            pass
        run.clicked.connect(self.refresh)
        fl.addWidget(run)
        lay.addWidget(fc)
        self._filter_card = fc

        # ── KPIs ──────────────────────────────────────────────────────────────
        kr = QHBoxLayout(); kr.setSpacing(12)
        self._k_txn  = KPICard('Transactions', '0',  '', C['gold'], icon='count')
        self._k_rev  = KPICard("Today's Revenue", '—',  'gross sales', C['ok'], icon='revenue')
        self._k_avg  = KPICard('Avg Sale',     '—',  '', C['gold'], icon='avg')
        self._k_disc = KPICard('Discounts',    '—',  '', C['warn'], icon='alert')
        for k in (self._k_txn,self._k_rev,self._k_avg,self._k_disc): kr.addWidget(k)
        lay.addLayout(kr)

        # Daily Sales + Cash Rounding + Actual Cash Received
        self._round_kpis = QWidget()
        rkr = QHBoxLayout(self._round_kpis); rkr.setContentsMargins(0, 0, 0, 0); rkr.setSpacing(10)
        self._rk_orig = KPICard('Original Total', '—', '', C['info'])
        self._rk_round = KPICard('Cash Rounding', '—', '', C['gold'])
        self._rk_cash = KPICard('Actual Cash Received', '—', '', C['ok'])
        for k in (self._rk_orig, self._rk_round, self._rk_cash):
            rkr.addWidget(k)
        lay.addWidget(self._round_kpis)

        # ── Charts (Lovable MiniBar + By Payment) ─────────────────────────────
        charts = QHBoxLayout(); charts.setSpacing(14)
        self._trend_chart = GoldBarChart(height=148)
        self._trend_card = ChartCard('Sales · Last 7 Days', self._trend_chart)
        self._pay_chart = PaymentBars()
        self._pay_card = ChartCard('By Payment', self._pay_chart)
        charts.addWidget(self._trend_card, 3)
        charts.addWidget(self._pay_card, 2)
        lay.addLayout(charts)

        # ── AI Summary (optional, online) ─────────────────────────────────────
        self._ai_sum_card = Card()
        ail = self._ai_sum_card.layout_v((16, 12, 16, 12), 8)
        arow = QHBoxLayout()
        self._ai_sum_title = QLabel('AI Summary')
        self._ai_sum_title.setStyleSheet(
            f"color:{C['text']}; font-size:14px; font-weight:700; background:transparent;")
        self._ai_sum_btn = SecondaryBtn('Generate', 32)
        self._ai_sum_btn.clicked.connect(self._ai_summary)
        arow.addWidget(self._ai_sum_title); arow.addStretch(); arow.addWidget(self._ai_sum_btn)
        ail.addLayout(arow)
        self._ai_sum_body = QLabel('Click Generate for an AI briefing of the current report period.')
        self._ai_sum_body.setWordWrap(True)
        self._ai_sum_body.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        ail.addWidget(self._ai_sum_body)
        lay.addWidget(self._ai_sum_card)

        # ── Status / open folder ──────────────────────────────────────────────
        ac = Card(); al = ac.layout_h((16, 10, 16, 10), 8)
        self._open_btn = GhostBtn('Open Exports Folder', 36)
        self._open_btn.setToolTip('Open the folder where exported Excel reports are saved')
        self._open_btn.clicked.connect(self._open_folder)
        self._status_lbl = QLabel('')
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        al.addWidget(self._open_btn)
        al.addWidget(self._status_lbl, 1)
        lay.addWidget(ac)

        # ── Auto-schedule row ─────────────────────────────────────────────────
        sc = Card(); sl = sc.layout_h((16, 10, 16, 10), 12)
        sl.addWidget(self._lbl('Auto-send:'))
        self._sched_daily = QCheckBox('Daily when online (reconnect + every 4 hrs)')
        self._sched_daily.setStyleSheet("color:{0}; background:transparent;".format(C['text']))
        sl.addWidget(self._sched_daily)
        self._sched_weekly = QCheckBox('Also weekly on')
        self._sched_weekly.setStyleSheet("color:{0}; background:transparent;".format(C['text']))
        sl.addWidget(self._sched_weekly)
        self._sched_day = QComboBox(); self._sched_day.setMinimumHeight(36)
        self._sched_day.setFixedWidth(120)
        for d in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']:
            self._sched_day.addItem(d)
        sl.addWidget(self._sched_day)
        save_sched = SecondaryBtn('Save Schedule', 36); save_sched.setFixedWidth(130)
        save_sched.clicked.connect(self._save_schedule); sl.addWidget(save_sched)
        sl.addStretch()
        lay.addWidget(sc)
        self._sched_card = sc
        self._save_sched_btn = save_sched

        # ── Data tabs in card (Lovable) ───────────────────────────────────────
        tabs = QTabWidget(); tabs.setMinimumHeight(320)
        tabs.setProperty('mbtLovableTabs', True)
        tabs.setStyleSheet(lovable_tab_qss())
        self._stbl = make_table(
            ['Receipt','Date / Time','Cashier','Items','Discount','Tax',
             'Original','Rounding','Final','Payment'],
            stretch_col=0, row_height=40)
        self._ptbl = make_table(
            ['Product Name','Units Sold','Transactions',f'Revenue','% of Total'],
            stretch_col=0, row_height=40)
        self._litbl = make_table(
            ['Receipt','Date','Cashier','Product Name','SKU','Qty','Unit Price','Total'],
            stretch_col=3, row_height=38)
        self._mtbl = make_table(
            ['Payment Method','Count','% Count',f'Revenue','% Revenue'],
            stretch_col=0, row_height=40)
        self._vtbl = make_table(
            ['Date','Sale #','Cashier','Method','Sale Total','Received','Excess',
             'Handling','Returned','Deposit','Tip','Transport','Mgr','Notes'],
            stretch_col=13, row_height=38)

        # Money columns stay interactive and are re-sized from real font metrics
        # after every load — fixed 90/100px widths elided even "KES 250.00".
        for tbl, money, specs in [
            (self._stbl,  (4, 5, 6, 7, 8),
             [(1,140),(2,120),(3,80),(4,90),(5,70),(6,110),(7,80),(8,120),(9,90)]),
            (self._ptbl,  (3,),
             [(1,90),(2,100),(3,110),(4,90)]),
            (self._litbl, (6, 7),
             [(0,130),(1,130),(2,100),(4,70),(5,50),(6,110),(7,110)]),
            (self._mtbl,  (3,),
             [(1,70),(2,80),(3,110),(4,80)]),
            (self._vtbl,  (4, 5, 6, 8, 9, 10, 11),
             [(0,130),(1,120),(2,90),(3,70),(4,90),(5,90),(6,80),
              (7,90),(8,80),(9,80),(10,70),(11,80),(12,50)]),
        ]:
            floors = {}
            for col, w in specs:
                if col in money:
                    floors[col] = w
                    tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
                else:
                    tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
                tbl.setColumnWidth(col, w)
            tbl.setProperty('mbtMoneyCols', list(money))
            tbl._mbt_money_cols = tuple(money)
            tbl._mbt_col_floors = floors
        # Numeric columns — headers + cells right-aligned for scannability
        align_header_right(self._stbl, 4, 5, 6, 7, 8)
        align_header_right(self._litbl, 5, 6, 7)
        align_header_right(self._ptbl, 1, 2, 3, 4)
        align_header_right(self._mtbl, 1, 2, 3, 4)
        align_header_right(self._vtbl, 4, 5, 6, 8, 9, 10, 11)

        # Variance KPI strip (shown under variance tab conceptually — always above tabs)
        self._var_kpis = QWidget()
        vkr = QHBoxLayout(self._var_kpis); vkr.setContentsMargins(0, 0, 0, 0); vkr.setSpacing(10)
        self._vk_extra = KPICard('Extra Received', '—', '', C['warn'])
        self._vk_ret   = KPICard('Returned',       '—', '', C['info'])
        self._vk_dep   = KPICard('Deposits',       '—', '', C['ok'])
        self._vk_tip   = KPICard('Tips',           '—', '', C['gold'])
        self._vk_tr    = KPICard('Transport',      '—', '', C['gold'])
        for k in (self._vk_extra, self._vk_ret, self._vk_dep, self._vk_tip, self._vk_tr):
            vkr.addWidget(k)
        lay.addWidget(self._var_kpis)

        tabs.addTab(self._stbl,  'Sales List')
        tabs.addTab(self._litbl, 'Line Items')
        tabs.addTab(self._ptbl,  'Top Products')
        tabs.addTab(self._mtbl,  'By Payment')
        tabs.addTab(self._vtbl,  'Payment Variance')
        lay.addWidget(wrap_table_card(tabs), 1)

        for tbl, icon, title, sub in (
            (self._stbl, 'reports', 'No sales in this period',
             'Pick another date range, or record a sale on the POS tab'),
            (self._litbl, 'reports', 'No line items in this period',
             'Line detail appears once sales are completed in this range'),
            (self._ptbl, 'inventory', 'No product sales yet',
             'Best sellers rank here once items are sold in this range'),
            (self._mtbl, 'revenue', 'No payments in this period',
             'Cash, M-Pesa, card and bank splits appear here'),
            (self._vtbl, 'alert', 'No payment variance recorded',
             'Overpayments, tips, deposits and change appear here'),
        ):
            attach_table_empty_state(tbl, icon, title, sub)

        self._apply_permissions()

    def can_export(self) -> bool:
        return has_permission(self.user, 'reports.export')

    def _apply_permissions(self):
        """Viewing reports stays open; anything that emits a file/email needs
        ``reports.export``."""
        allowed = self.can_export()
        for name in ('_exp_btn', '_pdf_btn', '_email_btn', '_save_sched_btn'):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setVisible(allowed)
                btn.setEnabled(allowed)
        for name in ('_sched_daily', '_sched_weekly', '_sched_day'):
            w = getattr(self, name, None)
            if w is not None:
                w.setEnabled(allowed)
        card = getattr(self, '_sched_card', None)
        if card is not None:
            card.setVisible(allowed)

    def _finish_table(self, tbl):
        """Content-aware money widths + hover tooltips, then zebra + empty state."""
        try:
            money = getattr(tbl, '_mbt_money_cols', ()) or ()
            if money:
                fit_columns_to_content(
                    tbl, money, floors=getattr(tbl, '_mbt_col_floors', None))
            apply_cell_tooltips(tbl)
        except Exception as e:
            _log.debug('Reports column fit: %s', e)
        apply_table_row_backgrounds(tbl)

    def _lbl(self, t):
        """Plain schedule/filter caption — no pill border."""
        from desktop.utils.date_controls import filter_label
        return filter_label(t)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _on_preset(self, key):
        if key == 'custom':
            return
        start, end = date_range_for_preset(key)
        self._s.setDate(QDate(start.year, start.month, start.day))
        self._e.setDate(QDate(end.year, end.month, end.day))
        self.refresh()

    def _quick(self, days):
        # Legacy quick buttons → map onto presets
        if days == 0:
            self._on_preset('today')
        elif days == -1:
            self._on_preset('month')
        elif days == 7:
            self._on_preset('week')
        else:
            t = date.today()
            self._s.setDate(QDate(t.year, t.month, t.day).addDays(-days))
            self._e.setDate(QDate.currentDate())
            if hasattr(self, '_preset'):
                self._preset.set_value('custom')

    def on_show(self):
        try:
            from desktop.utils.auto_fill import AutoFillService
            cfg = self.config_getter() or {}
            AutoFillService.apply_reports_default_dates(self, cfg)
        except Exception:
            pass
        # Guarantee To ≤ today (never a far-future default)
        if self._e.date() > QDate.currentDate():
            self._e.setDate(QDate.currentDate())
        if self._s.date() > self._e.date():
            self._s.setDate(self._e.date())
        self._load_schedule()
        self.refresh()

    def _ai_summary(self):
        """Optional AI briefing for the selected report period."""
        start = self._s.date().toString(DATE_API_FMT)
        end = self._e.date().toString(DATE_API_FMT)
        self._ai_sum_body.setText('Generating…')
        try:
            from desktop.utils.ai.service import get_ai_service
            from desktop.utils.ai.connectivity import get_connectivity, OFFLINE_BANNER
            st = get_ai_service().status()
            if not st.get('online'):
                self._ai_sum_body.setText(st.get('banner') or OFFLINE_BANNER)
                return
            data = self.api.get_report_summary(start, end) or {}
            text = get_ai_service().summarize_report(
                self.api, self.user,
                {'period': {'start': start, 'end': end}, 'report': data},
            )
            self._ai_sum_body.setText(text)
        except Exception as e:
            _log.warning('AI report summary: %s', e)
            self._ai_sum_body.setText(f'AI summary unavailable: {e}')

    def refresh(self):
        start = self._s.date().toString(DATE_API_FMT)
        end   = self._e.date().toString(DATE_API_FMT)
        cfg   = self.config_getter() or {}
        cur   = cfg.get('currency_symbol', 'KES')

        try:
            data = self.api.get_report_summary(start, end)
        except Exception as e:
            _log.warning(f"Reports summary: {e}"); return
        if not data: return

        s = data.get('summary', {})
        self._k_txn.set_value(str(int(s.get('total_transactions', 0))))
        self._k_rev.set_value(f"{cur} {s.get('total_revenue', 0):,.2f}")
        collected = float(s.get('collected_revenue', s.get('collected_from_sales', 0)) or 0)
        if hasattr(self._k_rev, 'set_sub'):
            self._k_rev.set_sub(f"Collected {cur} {collected:,.2f}")
        self._k_avg.set_value(f"{cur} {s.get('avg_transaction', 0):,.2f}")
        self._k_disc.set_value(f"{cur} {s.get('total_discounts', 0):,.2f}")
        if hasattr(self, '_rk_orig'):
            orig = float(s.get('original_total') or s.get('total_revenue') or 0)
            rnd = float(s.get('total_cash_rounding') or 0)
            cash_rx = float(s.get('cash_received') or 0)
            self._rk_orig.set_value(f"{cur} {orig:,.2f}")
            self._rk_round.set_value(f"{cur} {rnd:+,.2f}" if rnd else f"{cur} 0.00")
            self._rk_cash.set_value(f"{cur} {cash_rx:,.2f}")

        # Charts — 7-day trend always; payment bars use selected range
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
            _log.warning(f"Reports trend chart: {e}")

        try:
            by_pay = data.get('by_payment') or []
            merged: dict[str, float] = {}
            labels: dict[str, str] = {}
            order: list[str] = []
            for r in by_pay:
                raw = (r.get('payment_method') or 'Other').strip() or 'Other'
                key = raw.lower().replace(' ', '')
                if key in ('mpesa', 'm-pesa'):
                    key = 'm-pesa'
                    pretty = 'M-Pesa'
                else:
                    pretty = raw.title()
                if key not in merged:
                    merged[key] = 0.0
                    labels[key] = pretty
                    order.append(key)
                merged[key] += float(r.get('total') or 0)
            self._pay_chart.set_data([
                {'label': labels[k], 'value': merged[k]}
                for k in order
            ])
            self._pay_card.set_title(f'By Payment  ·  {start} → {end}')
        except Exception as e:
            _log.warning(f"Reports payment chart: {e}")

        # Sales list tab
        try:
            sales = reportable_sales(self.api.get_sales(start, end))
            self._stbl.setRowCount(0)
            for i, s2 in enumerate(sales):
                self._stbl.insertRow(i)
                adj = float(s2.get('cash_rounding_adj') or 0)
                tot = float(s2.get('total') or 0)
                orig = float(s2.get('original_total') or 0)
                if orig <= 0:
                    orig = tot - adj
                cells = [
                    tbl_item(str(s2.get('receipt_number', '') or '')),
                    tbl_item(str((s2.get('created_at', '') or '')[:16])),
                    tbl_item(str(s2.get('cashier_name', '') or '')),
                    tbl_item(str(s2.get('items_summary', '') or '')),
                    tbl_right(f"{float(s2.get('discount') or 0):,.2f}"),
                    tbl_right(f"{float(s2.get('tax') or 0):,.2f}"),
                    tbl_right(f"{cur} {orig:,.2f}", tone='gold'),
                    tbl_right(f"{adj:+,.2f}" if adj else '0.00'),
                    tbl_right(f"{cur} {tot:,.2f}", tone='gold'),
                    tbl_center((s2.get('payment_method', '') or '').upper()),
                ]
                for j, item in enumerate(cells):
                    self._stbl.setItem(i, j, item)
            self._finish_table(self._stbl)
        except Exception as e:
            _log.warning(f"Reports sales list: {e}")

        # Line items — single batch query (UI capped so large catalogs stay responsive)
        _UI_LINE_LIMIT = 500
        try:
            items = []
            if hasattr(self.api, 'get_sale_items_for_range'):
                items = self.api.get_sale_items_for_range(start, end) or []
            self._litbl.setRowCount(0)
            shown = items[:_UI_LINE_LIMIT]
            for row, item in enumerate(shown):
                self._litbl.insertRow(row)
                qty = float(item.get('quantity') or 0)
                qty_s = f"{qty:,.0f}" if abs(qty - round(qty)) < 0.05 else f"{qty:,.2f}"
                cells = [
                    tbl_item(str(item.get('receipt_number', '') or '')),
                    tbl_item(str((item.get('sale_created_at') or item.get('created_at') or '')[:16])),
                    tbl_item(str(item.get('cashier_name', '') or '')),
                    tbl_item(str(item.get('product_name', '') or '')),
                    tbl_item(str(item.get('sku', '') or '')),
                    tbl_right(qty_s),
                    tbl_right(f"{cur} {float(item.get('unit_price') or 0):,.2f}"),
                    tbl_right(f"{cur} {float(item.get('total') or 0):,.2f}", tone='gold'),
                ]
                for j, cell in enumerate(cells):
                    self._litbl.setItem(row, j, cell)
            if len(items) > _UI_LINE_LIMIT:
                self._set_status(
                    f"Line Items showing {_UI_LINE_LIMIT} of {len(items)} "
                    f"(full detail in Excel export)",
                    ok=None,
                )
            self._finish_table(self._litbl)
        except Exception as e:
            _log.warning(f"Reports line items: {e}")

        # Top products tab
        try:
            top = data.get('top_products', [])
            self._ptbl.setRowCount(0)
            total_rev = sum(p.get('revenue',0) for p in top) or 1
            for i, p in enumerate(top):
                self._ptbl.insertRow(i)
                pct = p.get('revenue',0)/total_rev*100
                cells = [
                    tbl_item(str(p.get('product_name', '') or '')),
                    tbl_right(f"{float(p.get('qty_sold') or 0):,.0f}"),
                    tbl_right(str(p.get('transactions', p.get('count', '')) or '')),
                    tbl_right(f"{cur} {float(p.get('revenue') or 0):,.2f}", tone='gold'),
                    tbl_right(f"{pct:.1f}%"),
                ]
                for j, cell in enumerate(cells):
                    self._ptbl.setItem(i, j, cell)
            self._finish_table(self._ptbl)
        except Exception as e:
            _log.warning(f"Reports top products: {e}")

        # By payment tab
        try:
            by_pay = data.get('by_payment', [])
            self._mtbl.setRowCount(0)
            total_cnt = sum(p.get('count',0) for p in by_pay) or 1
            total_pay = sum(p.get('total',0) for p in by_pay) or 1
            for i, p in enumerate(by_pay):
                self._mtbl.insertRow(i)
                cells = [
                    tbl_item((p.get('payment_method', '') or '').upper()),
                    tbl_right(str(int(p.get('count') or 0))),
                    tbl_right(f"{float(p.get('count') or 0)/total_cnt*100:.1f}%"),
                    tbl_right(f"{cur} {float(p.get('total') or 0):,.2f}", tone='gold'),
                    tbl_right(f"{float(p.get('total') or 0)/total_pay*100:.1f}%"),
                ]
                for j, cell in enumerate(cells):
                    self._mtbl.setItem(i, j, cell)
            self._finish_table(self._mtbl)
        except Exception as e:
            _log.warning(f"Reports by payment: {e}")

        # Payment Variance tab
        try:
            vdata = self.api.get_payment_variance_report(start, end) or {}
            summary = vdata.get('summary') or {}
            if hasattr(self, '_vk_extra'):
                self._vk_extra.set_value(f"{cur} {summary.get('extra_received', 0):,.2f}")
                self._vk_ret.set_value(f"{cur} {summary.get('returned', 0):,.2f}")
                self._vk_dep.set_value(
                    f"{cur} {summary.get('deposits', 0) + summary.get('advances', 0):,.2f}")
                self._vk_tip.set_value(f"{cur} {summary.get('tips', 0):,.2f}")
                self._vk_tr.set_value(f"{cur} {summary.get('transport', 0):,.2f}")
            rows = vdata.get('rows') or []
            self._vtbl.setRowCount(0)
            for i, r in enumerate(rows):
                self._vtbl.insertRow(i)
                note = (r.get('reason') or r.get('notes') or r.get('misc_category') or '')
                mgr = 'Yes' if r.get('manager_approved') else ''
                if r.get('manager_name'):
                    mgr = str(r.get('manager_name'))[:12]
                cells = [
                    tbl_item(str((r.get('created_at') or '')[:16])),
                    tbl_item(str(r.get('receipt_number', '') or '')),
                    tbl_item(str(r.get('cashier_name', '') or '')),
                    tbl_center((r.get('payment_method') or '').upper()),
                    tbl_right(f"{float(r.get('sale_total') or 0):,.2f}"),
                    tbl_right(f"{float(r.get('amount_received') or 0):,.2f}"),
                    tbl_right(f"{float(r.get('excess_amount') or 0):,.2f}"),
                    tbl_item((r.get('handling') or '').replace('_', ' ').title()),
                    tbl_right(f"{float(r.get('change_returned') or 0):,.2f}"),
                    tbl_right(f"{float(r.get('deposit_amount') or 0) + float(r.get('advance_amount') or 0):,.2f}"),
                    tbl_right(f"{float(r.get('tip_amount') or 0):,.2f}"),
                    tbl_right(f"{float(r.get('transport_amount') or 0):,.2f}"),
                    tbl_center(mgr),
                    tbl_item(str(note)[:40]),
                ]
                for j, cell in enumerate(cells):
                    self._vtbl.setItem(i, j, cell)
            self._finish_table(self._vtbl)
        except Exception as e:
            _log.warning(f"Reports payment variance: {e}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _do_export(self):
        sys.path.insert(0, _PR)
        from backend.export_engine import export_sales_report, export_sales_report_html
        from backend.report_export_service import get_export_dir as _shared_export_dir
        start = self._s.date().toString(DATE_API_FMT)
        end   = self._e.date().toString(DATE_API_FMT)
        cfg   = self.config_getter() or {}
        shop  = cfg.get('shop_name', 'My Shop')
        cur   = cfg.get('currency_symbol', 'KES')
        user_name = (
            (self.user.get('user') or self.user).get('full_name')
            or (self.user.get('user') or self.user).get('username')
            or 'admin'
        )
        sales = reportable_sales(self.api.get_sales(start, end))
        ibs = {}
        # Prefer one batch query over N get_sale round-trips
        try:
            flat = self.api.get_sale_items_for_range(start, end) or []
            for item in flat:
                sid = item.get('sale_id')
                if sid is None:
                    continue
                ibs.setdefault(sid, []).append(item)
            for sale in sales:
                sid = sale.get('id') or sale.get('sale_id')
                sale['item_count'] = len(ibs.get(sid, []))
        except Exception:
            for sale in sales:
                sid = sale.get('id') or sale.get('sale_id')
                d = self.api.get_sale(sid)
                if d:
                    ibs[sid] = d.get('items', [])
                    sale['item_count'] = len(ibs[sid])
        try:
            products = self.api.get_products() or []
        except Exception:
            products = []
        try:
            debt_summary = self.api.get_debt_summary() or {}
        except Exception:
            debt_summary = {}
        try:
            aging_report = self.api.get_aging_report() or {}
        except Exception:
            aging_report = {}
        try:
            debt_invoices = self.api.get_debt_invoices(start=start, end=end) or []
        except Exception:
            debt_invoices = []
        try:
            debt_payments = self.api.get_debt_payments(start=start, end=end) or []
        except Exception:
            debt_payments = []
        try:
            vdata = self.api.get_payment_variance_report(start, end) or {}
            variance_rows = vdata.get('rows') or []
            variance_summary = vdata.get('summary') or {}
        except Exception:
            variance_rows, variance_summary = [], {}
        fname = f"MBT_Sales_{start}_to_{end}.xlsx"
        out = os.path.join(_shared_export_dir(), fname)
        filt = f"Date {start} → {end} · completed sales only"
        xlsx_path = export_sales_report(
            sales, ibs, shop_name=shop, start_date=start,
            end_date=end, output_path=out, currency=cur,
            products_data=products,
            debt_summary=debt_summary,
            aging_report=aging_report,
            debt_invoices=debt_invoices,
            debt_payments=debt_payments,
            variance_rows=variance_rows,
            variance_summary=variance_summary,
            generated_by=user_name,
            filters=filt,
        )
        # Companion printable HTML (browser Print → PDF) — R02 printable export
        try:
            html_out = os.path.join(
                _shared_export_dir(), f"MBT_Sales_{start}_to_{end}.html")
            self._last_html_export_path = export_sales_report_html(
                sales, ibs, shop_name=shop, start_date=start,
                end_date=end, output_path=html_out, currency=cur,
                generated_by=user_name, filters=filt,
            )
        except Exception as e:
            _log.warning(f"HTML report export skipped: {e}")
            self._last_html_export_path = None
        return xlsx_path

    def _export(self):
        from desktop.utils.security import require_permission
        if not require_permission(self.user, 'reports.export', self):
            return
        try:
            self._exp_btn.setEnabled(False); self._exp_btn.setText('Exporting…')
            QApplication.processEvents()
            path = self._do_export()
            self._last_export_path = path
            self._set_status(f"✓ Saved: {path}", ok=True)
            html_note = ''
            html_path = getattr(self, '_last_html_export_path', None)
            if html_path:
                html_note = (
                    f'\n\nPrintable HTML (Print → PDF):\n{html_path}'
                )
            QMessageBox.information(self, 'Exported ✓',
                f'Report saved to:\n{path}\n\n'
                f'Contains 7 sheets:\n'
                f'  • Sales Summary\n'
                f'  • Line Items (with Product Names)\n'
                f'  • Top Products\n'
                f'  • Payment Methods\n'
                f'  • Stock & Inventory\n'
                f'  • Debt Management\n'
                f'  • Payment Variance'
                f'{html_note}')
        except Exception as e:
            _log.error(f"Export error: {e}", exc_info=True)
            QMessageBox.critical(self, 'Export Error', str(e))
            self._set_status(f"✗ Export failed: {e}", ok=False)
        finally:
            self._exp_btn.setEnabled(True); self._exp_btn.setText('Export Excel')

    def _do_export_pdf(self) -> str:
        """Direct PDF for the selected period — no browser Print step needed."""
        sys.path.insert(0, _PR)
        from backend.report_export_service import export_sales_report_pdf
        start = self._s.date().toString(DATE_API_FMT)
        end   = self._e.date().toString(DATE_API_FMT)
        cfg   = self.config_getter() or {}
        account = self.user.get('user') or self.user
        data = self.api.get_report_summary(start, end) or {}
        sales = reportable_sales(self.api.get_sales(start, end))
        return export_sales_report_pdf(
            sales,
            data.get('summary') or {},
            shop_name=cfg.get('shop_name', 'My Shop'),
            start_date=start, end_date=end,
            currency=cfg.get('currency_symbol', 'KES'),
            top_products=data.get('top_products') or [],
            by_payment=data.get('by_payment') or [],
            generated_by=(account.get('full_name')
                          or account.get('username') or 'admin'),
            filters=f'Date {start} to {end} · completed and return sales only',
        )

    def _export_pdf(self):
        from desktop.utils.security import require_permission
        if not require_permission(self.user, 'reports.export', self):
            return
        try:
            self._pdf_btn.setEnabled(False); self._pdf_btn.setText('Exporting…')
            QApplication.processEvents()
            path = self._do_export_pdf()
            self._last_pdf_export_path = path
            self._set_status(f"✓ Saved: {path}", ok=True)
            QMessageBox.information(
                self, 'Exported ✓',
                f'PDF report saved to:\n{path}\n\n'
                f'Totals match the KPI cards for this period.')
        except Exception as e:
            _log.error(f"PDF export error: {e}", exc_info=True)
            QMessageBox.critical(self, 'Export Error', str(e))
            self._set_status(f"✗ PDF export failed: {e}", ok=False)
        finally:
            self._pdf_btn.setEnabled(True); self._pdf_btn.setText('Export PDF')

    # ── Cloud / email report (Telegram permanently removed) ───────────────────

    def _send_cloud_report(self):
        from desktop.utils.security import require_permission
        if not require_permission(self.user, 'reports.export', self):
            return
        start = self._s.date().toString(DATE_API_FMT)
        end   = self._e.date().toString(DATE_API_FMT)
        if QMessageBox.question(self, 'Send Report',
                f'Generate and send report ({start} → {end}) via cloud notifications / email?',
                QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:
            return

        self._email_btn.setEnabled(False); self._email_btn.setText('Sending…')
        self._set_status('Preparing report…', ok=None)

        from backend.cloud.report_engine import ReportEngine
        from mbt_paths import get_db_path
        import threading

        def _run():
            engine = ReportEngine(get_db_path(), config_getter=self.config_getter)
            ok, msg = engine.send_report_now('custom')
            self._report_done.emit(ok, msg)
        threading.Thread(target=_run, daemon=True).start()

    def _on_report_progress(self, msg: str):
        self._set_status(msg, ok=None)

    def _on_report_done(self, ok: bool, msg: str):
        self._email_btn.setEnabled(True); self._email_btn.setText('Email Report')
        self._set_status(('✓ ' if ok else '✗ ') + (msg or '').split('\n')[0], ok=ok)
        if ok:
            QMessageBox.information(self, 'Report Sent', msg or 'Report queued.')
        else:
            QMessageBox.warning(self, 'Send Failed', msg or 'Could not send report.')

    def _set_status(self, msg: str, ok=None):
        color = C['ok'] if ok is True else C['err'] if ok is False else C['text2']
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet(
            f"color:{color}; font-size:11.5px; background:transparent;")

    # ── Folder ────────────────────────────────────────────────────────────────

    def _open_folder(self):
        import os, subprocess, sys
        folder = ''
        try:
            folder = _get_export_dir()
            if sys.platform == 'win32':
                os.startfile(folder)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            # No shell association, folder removed, or a denied path — the
            # click must not take the window down with it.
            detail = f'\n\nYou can browse to it manually:\n{folder}' if folder else ''
            QMessageBox.warning(
                self, 'Open Exports Folder',
                f'Could not open the exports folder.\n\n{e}{detail}')

    # ── Schedule ──────────────────────────────────────────────────────────────

    def _load_schedule(self):
        try:
            cfg = self.api.get_settings() or {}
            self._sched_daily.setChecked(cfg.get('auto_report_daily','0')=='1')
            self._sched_weekly.setChecked(cfg.get('auto_report_weekly','0')=='1')
            self._sched_day.setCurrentIndex(int(cfg.get('auto_report_weekday','0')))
        except Exception as e:
            _log.warning(f"Load schedule: {e}")

    def _save_schedule(self):
        from desktop.utils.security import require_permission
        if not require_permission(self.user, 'reports.export', self):
            return
        try:
            res = self.api.update_settings({
                'auto_report_daily':   '1' if self._sched_daily.isChecked() else '0',
                'auto_report_weekly':  '1' if self._sched_weekly.isChecked() else '0',
                'auto_report_interval_hours': '4',
                'auto_report_weekday': str(self._sched_day.currentIndex()),
            })
            if res and res.get('error'):
                QMessageBox.warning(self, 'Reports', res['error'])
                return
            QMessageBox.information(self, 'Saved', 'Report schedule saved.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def apply_theme(self, is_light=None):
        """Refresh chart cards + labels when app theme toggles."""
        for card in (
            getattr(self, '_filter_card', None),
            getattr(self, '_trend_card', None),
            getattr(self, '_pay_card', None),
        ):
            if card is not None and hasattr(card, 'refresh_theme'):
                card.refresh_theme()
        refresh_filter_labels(self)
        refresh_date_edits(self)
        try:
            refresh_select_controls(self)
        except Exception:
            pass
        if hasattr(self, '_preset') and hasattr(self._preset, 'refresh_theme'):
            self._preset.refresh_theme()
        self._status_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; border:none;")
        for cb in (self._sched_daily, self._sched_weekly):
            cb.setStyleSheet(f"color:{C['text']}; background:transparent;")
        for tbl in (self._stbl, self._litbl, self._ptbl, self._mtbl, self._vtbl):
            try:
                retint_table_items(tbl)
                apply_table_row_backgrounds(tbl)
            except Exception:
                pass
