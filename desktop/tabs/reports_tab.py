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
                                    wrap_table_card, page_intro)
from desktop.utils.charts import GoldBarChart, PaymentBars, ChartCard
from desktop.utils.select_controls import DatePresetSelect
from desktop.utils.option_lists import date_range_for_preset

_log = logging.getLogger(__name__)
_PR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    _tg_progress = pyqtSignal(str)
    _tg_done     = pyqtSignal(bool, str)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self._last_export_path = None
        self._tg_progress.connect(self._on_tg_progress)
        self._tg_done.connect(self._on_tg_done)
        self._build()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build(self):
        lay, _ = page_layout(self, margins=(24, 24, 24, 24), spacing=16)

        # Lovable-style top actions
        actions = QWidget()
        ar = QHBoxLayout(actions); ar.setContentsMargins(0, 0, 0, 0); ar.setSpacing(8)
        self._exp_btn = PrimaryBtn('⬇  Export Excel', 40)
        self._exp_btn.clicked.connect(self._export)
        self._tg_btn = SecondaryBtn('✈  Telegram', 40)
        self._tg_btn.clicked.connect(self._send_telegram)
        ar.addWidget(self._tg_btn); ar.addWidget(self._exp_btn)
        intro, _ = page_intro('Reports', 'Sales, cash rounding, payment variance, products and payment breakdown.', actions)
        lay.addLayout(intro)

        # ── Filter bar ────────────────────────────────────────────────────────
        fc = Card(); fl = fc.layout_h((16, 12, 16, 12), 8)
        fl.addWidget(self._lbl('Period:'))
        self._preset = DatePresetSelect()
        self._preset.setMinimumWidth(150)
        self._preset.presetChanged.connect(self._on_preset)
        fl.addWidget(self._preset)
        fl.addWidget(self._lbl('From:'))
        self._s = QDateEdit(date.today()); self._s.setCalendarPopup(True)
        self._s.setDisplayFormat('yyyy-MM-dd'); self._s.setMinimumHeight(36)
        fl.addWidget(self._s)
        fl.addWidget(self._lbl('To:'))
        self._e = QDateEdit(date.today()); self._e.setCalendarPopup(True)
        self._e.setDisplayFormat('yyyy-MM-dd'); self._e.setMinimumHeight(36)
        fl.addWidget(self._e)
        fl.addStretch()
        run = PrimaryBtn('▶  Run', 36); run.setFixedWidth(100)
        run.clicked.connect(self.refresh); fl.addWidget(run)
        lay.addWidget(fc)

        # ── KPIs ──────────────────────────────────────────────────────────────
        kr = QHBoxLayout(); kr.setSpacing(12)
        self._k_txn  = KPICard('Transactions', '0',  '', C['gold'])
        self._k_rev  = KPICard('Final Total',  '—',  '', C['ok'])
        self._k_avg  = KPICard('Avg Sale',     '—',  '', C['info'])
        self._k_disc = KPICard('Discounts',    '—',  '', C['warn'])
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
        self._trend_chart = GoldBarChart(height=132)
        self._trend_card = ChartCard('Sales · Last 7 Days', self._trend_chart)
        self._pay_chart = PaymentBars()
        self._pay_card = ChartCard('By Payment', self._pay_chart)
        charts.addWidget(self._trend_card, 3)
        charts.addWidget(self._pay_card, 2)
        lay.addLayout(charts)

        # ── Status / open folder ──────────────────────────────────────────────
        ac = Card(); al = ac.layout_h((16, 10, 16, 10), 8)
        self._open_btn = GhostBtn('📂  Open Folder', 36)
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

        for tbl, specs in [
            (self._stbl,  [(1,140),(2,120),(3,80),(4,90),(5,70),(6,90),(7,80),(8,100),(9,90)]),
            (self._ptbl,  [(1,90),(2,100),(3,110),(4,90)]),
            (self._litbl, [(0,130),(1,130),(2,100),(4,70),(5,50),(6,100),(7,100)]),
            (self._mtbl,  [(1,70),(2,80),(3,110),(4,80)]),
            (self._vtbl,  [(0,130),(1,120),(2,90),(3,70),(4,90),(5,90),(6,80),
                           (7,90),(8,80),(9,80),(10,70),(11,80),(12,50)]),
        ]:
            for col, w in specs:
                tbl.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
                tbl.setColumnWidth(col, w)

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

    def _lbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color:{C['text2']}; font-size:13px; background:transparent;")
        return l

    # ── Data ──────────────────────────────────────────────────────────────────

    def _on_preset(self, key):
        if key == 'custom':
            return
        start, end = date_range_for_preset(key)
        self._s.setDate(start)
        self._e.setDate(end)
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
            self._s.setDate(t - timedelta(days=days))
            self._e.setDate(t)
            if hasattr(self, '_preset'):
                self._preset.set_value('custom')

    def on_show(self):
        try:
            from desktop.utils.auto_fill import AutoFillService
            cfg = self.config_getter() or {}
            AutoFillService.apply_reports_default_dates(self, cfg)
        except Exception:
            pass
        self._load_schedule()
        self.refresh()

    def refresh(self):
        start = self._s.date().toString('yyyy-MM-dd')
        end   = self._e.date().toString('yyyy-MM-dd')
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
            self._pay_chart.set_data([
                {
                    'label': (r.get('payment_method') or 'Other').title(),
                    'value': float(r.get('total') or 0),
                }
                for r in by_pay
            ])
            self._pay_card.set_title(f'By Payment  ·  {start} → {end}')
        except Exception as e:
            _log.warning(f"Reports payment chart: {e}")

        # Sales list tab
        try:
            sales = self.api.get_sales(start, end) or []
            self._stbl.setRowCount(0)
            for i, s2 in enumerate(sales):
                self._stbl.insertRow(i)
                adj = float(s2.get('cash_rounding_adj') or 0)
                tot = float(s2.get('total') or 0)
                orig = float(s2.get('original_total') or 0)
                if orig <= 0:
                    orig = tot - adj
                for j, v in enumerate([
                    s2.get('receipt_number',''),
                    (s2.get('created_at','') or '')[:16],
                    s2.get('cashier_name',''),
                    s2.get('items_summary','') or '',
                    f"{s2.get('discount',0):,.2f}",
                    f"{s2.get('tax',0):,.2f}",
                    f"{cur} {orig:,.2f}",
                    f"{adj:+,.2f}" if adj else '0.00',
                    f"{cur} {tot:,.2f}",
                    (s2.get('payment_method','') or '').upper(),
                ]):
                    self._stbl.setItem(i, j, tbl_item(str(v)))
        except Exception as e:
            _log.warning(f"Reports sales list: {e}")

        # Line items tab — fetch all items
        try:
            sales_full = self.api.get_sales(start, end) or []
            self._litbl.setRowCount(0)
            row = 0
            for sale in sales_full:
                sid   = sale.get('id') or sale.get('sale_id')
                d     = self.api.get_sale(sid) if sid else {}
                items = (d or {}).get('items', [])
                for item in items:
                    self._litbl.insertRow(row)
                    for j, v in enumerate([
                        sale.get('receipt_number',''),
                        (sale.get('created_at','') or '')[:16],
                        sale.get('cashier_name',''),
                        item.get('product_name',''),
                        item.get('sku','') or '',
                        str(item.get('quantity',0)),
                        f"{cur} {item.get('unit_price',0):,.2f}",
                        f"{cur} {item.get('total',0):,.2f}",
                    ]):
                        self._litbl.setItem(row, j, tbl_item(str(v)))
                    row += 1
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
                for j, v in enumerate([
                    p.get('product_name',''),
                    f"{p.get('qty_sold',0):,.0f}",
                    str(p.get('transactions', p.get('count',''))),
                    f"{cur} {p.get('revenue',0):,.2f}",
                    f"{pct:.1f}%",
                ]):
                    self._ptbl.setItem(i, j, tbl_item(str(v)))
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
                for j, v in enumerate([
                    (p.get('payment_method','') or '').upper(),
                    str(p.get('count',0)),
                    f"{p.get('count',0)/total_cnt*100:.1f}%",
                    f"{cur} {p.get('total',0):,.2f}",
                    f"{p.get('total',0)/total_pay*100:.1f}%",
                ]):
                    self._mtbl.setItem(i, j, tbl_item(str(v)))
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
                for j, v in enumerate([
                    (r.get('created_at') or '')[:16],
                    r.get('receipt_number', ''),
                    r.get('cashier_name', ''),
                    (r.get('payment_method') or '').upper(),
                    f"{float(r.get('sale_total') or 0):,.2f}",
                    f"{float(r.get('amount_received') or 0):,.2f}",
                    f"{float(r.get('excess_amount') or 0):,.2f}",
                    (r.get('handling') or '').replace('_', ' ').title(),
                    f"{float(r.get('change_returned') or 0):,.2f}",
                    f"{float(r.get('deposit_amount') or 0) + float(r.get('advance_amount') or 0):,.2f}",
                    f"{float(r.get('tip_amount') or 0):,.2f}",
                    f"{float(r.get('transport_amount') or 0):,.2f}",
                    mgr,
                    str(note)[:40],
                ]):
                    self._vtbl.setItem(i, j, tbl_item(str(v)))
        except Exception as e:
            _log.warning(f"Reports payment variance: {e}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _do_export(self):
        sys.path.insert(0, _PR)
        from backend.export_engine import export_sales_report
        start = self._s.date().toString('yyyy-MM-dd')
        end   = self._e.date().toString('yyyy-MM-dd')
        cfg   = self.config_getter() or {}
        shop  = cfg.get('shop_name', 'My Shop')
        cur   = cfg.get('currency_symbol', 'KES')
        sales = [s for s in (self.api.get_sales(start, end) or [])
                 if (s.get('status') or 'completed') != 'voided']
        ibs   = {}
        for sale in sales:
            sid = sale.get('id') or sale.get('sale_id')
            d   = self.api.get_sale(sid)
            if d:
                ibs[sid] = d.get('items', [])
                sale['item_count'] = len(ibs[sid])
        # Fetch current stock / inventory for Sheet 5
        try:
            products = self.api.get_products() or []
        except Exception:
            products = []
        # Fetch debt data for Sheet 6
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
        fname  = f"MBT_Sales_{start}_to_{end}.xlsx"
        out    = os.path.join(_get_export_dir(), fname)
        return export_sales_report(
            sales, ibs, shop_name=shop, start_date=start,
            end_date=end, output_path=out, currency=cur,
            products_data=products,
            debt_summary=debt_summary,
            aging_report=aging_report,
            debt_invoices=debt_invoices,
            debt_payments=debt_payments)

    def _export(self):
        try:
            self._exp_btn.setEnabled(False); self._exp_btn.setText('Exporting…')
            QApplication.processEvents()
            path = self._do_export()
            self._last_export_path = path
            self._set_status(f"✓ Saved: {path}", ok=True)
            QMessageBox.information(self, 'Exported ✓',
                f'Report saved to:\n{path}\n\n'
                f'Contains 6 sheets:\n'
                f'  • Sales Summary\n'
                f'  • Line Items (with Product Names)\n'
                f'  • Top Products\n'
                f'  • Payment Methods\n'
                f'  • Stock & Inventory\n'
                f'  • Debt Management')
        except Exception as e:
            _log.error(f"Export error: {e}", exc_info=True)
            QMessageBox.critical(self, 'Export Error', str(e))
            self._set_status(f"✗ Export failed: {e}", ok=False)
        finally:
            self._exp_btn.setEnabled(True); self._exp_btn.setText('⬇  Export Excel')

    # ── Telegram ──────────────────────────────────────────────────────────────

    def _send_telegram(self):
        cfg     = self.config_getter() or {}
        token   = cfg.get('telegram_bot_token','').strip()
        chat_id = cfg.get('telegram_chat_id','').strip()
        if not token or not chat_id:
            QMessageBox.warning(self, 'Not Connected',
                'Your Telegram is not connected.\n'
                'Go to Settings → Telegram & click Connect My Telegram.')
            return
        start = self._s.date().toString('yyyy-MM-dd')
        end   = self._e.date().toString('yyyy-MM-dd')
        if QMessageBox.question(self, 'Send via Telegram',
                f'Export and send report ({start} → {end}) to your Telegram?',
                QMessageBox.Yes|QMessageBox.No) != QMessageBox.Yes:
            return

        self._tg_btn.setEnabled(False); self._tg_btn.setText('Sending…')
        self._set_status('Preparing report…', ok=None)

        sys.path.insert(0, _PR)
        from backend.telegram_reporter import send_report_for_range
        send_report_for_range(
            self.api, self.config_getter, start, end,
            on_progress=lambda msg: self._tg_progress.emit(msg),
            on_done=lambda ok, msg: self._tg_done.emit(ok, msg),
        )

    def _on_tg_progress(self, msg: str):
        self._set_status(msg, ok=None)

    def _on_tg_done(self, ok: bool, msg: str):
        self._tg_btn.setEnabled(True); self._tg_btn.setText('✈  Send via Telegram')
        self._set_status(('✓ ' if ok else '✗ ') + msg.split('\n')[0], ok=ok)
        if ok:
            QMessageBox.information(self, 'Sent ✓', msg)
        else:
            QMessageBox.critical(self, 'Send Failed', msg)

    def _set_status(self, msg: str, ok=None):
        color = C['ok'] if ok is True else C['err'] if ok is False else C['text2']
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet(
            f"color:{color}; font-size:11.5px; background:transparent;")

    # ── Folder ────────────────────────────────────────────────────────────────

    def _open_folder(self):
        import subprocess, sys
        folder = _get_export_dir()
        if sys.platform   == 'win32':  subprocess.Popen(['explorer', folder])
        elif sys.platform == 'darwin': subprocess.Popen(['open', folder])
        else:                          subprocess.Popen(['xdg-open', folder])

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
        try:
            settings = self.api.get_settings() or {}
            settings.update({
                'auto_report_daily':   '1' if self._sched_daily.isChecked() else '0',
                'auto_report_weekly':  '1' if self._sched_weekly.isChecked() else '0',
                'auto_report_interval_hours': '4',
                'auto_report_weekday': str(self._sched_day.currentIndex()),
            })
            self.api.update_settings(settings)
            QMessageBox.information(self, 'Saved', 'Report schedule saved.')
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def apply_theme(self, is_light=None):
        """Refresh chart cards + labels when app theme toggles."""
        for card in (getattr(self, '_trend_card', None), getattr(self, '_pay_card', None)):
            if card is not None:
                card.refresh_theme()
        self._status_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        for cb in (self._sched_daily, self._sched_weekly):
            cb.setStyleSheet(f"color:{C['text']}; background:transparent;")
