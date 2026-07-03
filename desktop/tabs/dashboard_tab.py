"""MBT POS - Dashboard | MugoByte Technologies"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from datetime        import date
from desktop.utils.theme   import C
from desktop.utils.widgets import (KPICard, Card, H2, H3, Caption, PrimaryBtn,
                                    DangerBtn, IconBtn, make_table, tbl_item, tbl_right, page_layout)
from desktop.utils.security import can_void_sales, prompt_void_sale

class DashboardTab(QWidget):
    navigate = pyqtSignal(str)

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api; self.user = user
        self.db_path = db_path; self.config_getter = config_getter
        self._build()
        self._t = QTimer(self); self._t.timeout.connect(self._load); self._t.start(60000)

    def _build(self):
        lay, _ = page_layout(self, margins=(28,24,28,28), spacing=24)

        # Header
        hdr = QHBoxLayout(); hdr.setSpacing(0)
        col = QVBoxLayout(); col.setSpacing(4)
        self._date_lbl = H3(date.today().strftime('%A  ·  %d %B %Y'))
        self._title = QLabel('Welcome back')
        self._title.setStyleSheet(f"color:{C['text']}; font-size:26px; font-weight:800; background:transparent;")
        self._shop = QLabel('Loading...')
        self._shop.setStyleSheet(f"color:{C['text2']}; font-size:14px; background:transparent;")
        col.addWidget(self._date_lbl); col.addWidget(self._title); col.addWidget(self._shop)
        hdr.addLayout(col); hdr.addStretch()
        nb = PrimaryBtn('+ New Sale', 42); nb.setFixedWidth(140)
        nb.clicked.connect(lambda: self.navigate.emit('sales')); hdr.addWidget(nb)
        lay.addLayout(hdr)

        # KPI row
        kr = QHBoxLayout(); kr.setSpacing(16)
        self._k_sales = KPICard("Today's Sales",   '0',   'transactions', C['gold'])
        self._k_rev   = KPICard("Today's Revenue", '—',   'gross income', C['ok'])
        self._k_avg   = KPICard("Avg Transaction", '—',   'per receipt',  C['info'])
        self._k_low   = KPICard("Low Stock",        '0',  'items',        C['err'])
        for k in (self._k_sales, self._k_rev, self._k_avg, self._k_low): kr.addWidget(k)
        lay.addLayout(kr)

        # Body row
        body = QHBoxLayout(); body.setSpacing(20)

        # Recent sales card
        sc = Card(); scl = sc.layout_v((22,20,22,20), 16)
        sh = QHBoxLayout()
        sh.addWidget(H2('Recent Sales')); sh.addStretch()
        self._void_sel_btn = DangerBtn('Void Sale', 32)
        self._void_sel_btn.setToolTip('Void selected receipt (admin only)')
        self._void_sel_btn.clicked.connect(self._void_selected_sale)
        self._void_sel_btn.setVisible(can_void_sales(self.user))
        sh.addWidget(self._void_sel_btn)
        rf = IconBtn('↺', 32, 32); rf.setToolTip('Refresh'); rf.clicked.connect(self._load)
        sh.addWidget(rf); scl.addLayout(sh)
        self._tbl = make_table(['Receipt No.', 'Time', 'Cashier', 'Total'], stretch_col=0, row_height=40)
        for ci, w in [(1,140),(2,120),(3,110)]:
            self._tbl.horizontalHeader().setSectionResizeMode(ci, QHeaderView.Fixed)
            self._tbl.setColumnWidth(ci, w)
        self._tbl.setMinimumHeight(240)
        self._tbl.itemSelectionChanged.connect(self._on_sale_selected)
        scl.addWidget(self._tbl)
        body.addWidget(sc, 3)

        # Right column
        rc = QVBoxLayout(); rc.setSpacing(16)

        # Quick actions
        qa = Card(); ql = qa.layout_v((20,18,20,18), 12)
        ql.addWidget(H2('Quick Actions')); ql.addSpacing(2)
        quick = [('🛒','New Sale','sales'),('📦','Add Product','inventory'),
                 ('📊','Run Report','reports'),('⚙','Settings','settings')]
        if can_void_sales(self.user):
            quick.append(('🗑','Void Sale','__void__'))
        for icon, lbl, tid in quick:
            btn = QPushButton(f' {icon}   {lbl}'); btn.setMinimumHeight(42)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background:{C['card2']}; color:{C['text']}; border:1px solid {C['border2']}; "
                f"border-radius:8px; padding:10px 14px; font-size:13.5px; text-align:left; }}"
                f"QPushButton:hover {{ background:{C['selected']}; color:{C['gold']}; border-color:{C['gold']}; }}"
                f"QPushButton:pressed {{ background:{C['app']}; color:{C['text']}; }}")
            if tid == '__void__':
                btn.clicked.connect(self._void_sale_prompt)
            else:
                btn.clicked.connect(lambda _, t=tid: self.navigate.emit(t))
            ql.addWidget(btn)
        rc.addWidget(qa)

        # System status
        st = Card(); stl = st.layout_v((20,18,20,18), 12)
        stl.addWidget(H2('System Status'))
        self._st_db   = self._srow(stl, 'Database')
        self._st_api  = self._srow(stl, 'API')
        self._st_sync = self._srow(stl, 'Last Sync')
        rc.addWidget(st); rc.addStretch()
        rw = QWidget(); rw.setStyleSheet('background:transparent;')
        rw.setFixedWidth(260); rw.setLayout(rc)
        body.addWidget(rw)
        lay.addLayout(body)

        foot = Caption('MBT POS  ·  Powered by MugoByte Technologies  ·  mugobyte.com')
        foot.setAlignment(Qt.AlignCenter); lay.addWidget(foot)

    def _srow(self, pl, label):
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0)
        l = QLabel(label); l.setStyleSheet(f"color:{C['text2']}; font-size:13px; background:transparent;")
        v = QLabel('● OK'); v.setStyleSheet(f"color:{C['ok']}; font-size:13px; font-weight:700; background:transparent;")
        row.addWidget(l); row.addStretch(); row.addWidget(v); pl.addLayout(row)
        return v

    def on_show(self):
        try:
            cfg = self.config_getter() or {}
            u = self.user.get('user', {})
            name = u.get('full_name') or u.get('username', '')
            shop = cfg.get('shop_name', 'My Shop')
            self._title.setText(f'Welcome back, {name}')
            self._shop.setText(f'{shop}  ·  Daily Overview')
        except Exception: pass
        QTimer.singleShot(0, self._load)

    def refresh(self): self._load()

    def _on_sale_selected(self):
        if not hasattr(self, '_void_sel_btn'):
            return
        row = self._tbl.currentRow()
        enabled = row >= 0 and self._void_sel_btn.isVisible()
        self._void_sel_btn.setEnabled(enabled)

    def _selected_receipt(self) -> str:
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
                                'Select a receipt from Recent Sales first.')
            return
        if prompt_void_sale(self.api, self, receipt_prefill=receipt):
            self._load()

    def _load(self):
        today = str(date.today())
        try:
            d = self.api.get_report_summary(today, today)
            if d:
                s   = d.get('summary', {})
                cur = (self.config_getter() or {}).get('currency_symbol', 'KES')
                self._k_sales.set_value(str(int(s.get('total_transactions', 0))))
                self._k_rev.set_value(f"{cur} {s.get('total_revenue', 0):,.0f}")
                self._k_avg.set_value(f"{cur} {s.get('avg_transaction', 0):,.0f}")
        except Exception as e:
            import logging; logging.getLogger(__name__).warning(f"Dashboard KPI load: {e}")
        try:
            prods = self.api.get_products() or []
            low   = sum(1 for p in prods if p.get('stock', 0) <= p.get('min_stock', 5))
            self._k_low.set_value(str(low), C['err'] if low > 0 else C['ok'])
        except Exception as e:
            import logging; logging.getLogger(__name__).warning(f"Dashboard low-stock: {e}")
        try:
            sales = self.api.get_sales(today, today) or []
            self._tbl.setRowCount(0)
            for i, s in enumerate(sales[:30]):
                self._tbl.insertRow(i)
                receipt = s.get('receipt_number', '')
                status = (s.get('status') or 'completed').lower()
                self._tbl.setItem(i, 0, tbl_item(receipt))
                self._tbl.setItem(i, 1, tbl_item((s.get('created_at', '') or '')[:16]))
                self._tbl.setItem(i, 2, tbl_item(s.get('cashier_name', '')))
                total_colour = C['muted'] if status == 'voided' else C['ok']
                total_item = tbl_right(f"{s.get('total', 0):,.2f}", total_colour)
                if status == 'voided':
                    total_item.setToolTip('Voided')
                self._tbl.setItem(i, 3, total_item)
            self._on_sale_selected()
        except Exception as e:
            import logging; logging.getLogger(__name__).warning(f"Dashboard sales table: {e}")
        self._st_db.setText('● OK'); self._st_api.setText('● Online')
