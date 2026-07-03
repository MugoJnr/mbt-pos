"""
MBT POS — Debt Management Tab
MugoByte Technologies | mugobyte.com

Full part-payment / credit-sale / debt-collection system:
• Customer management
• Invoice creation (credit sale, part payment)
• Debt collection with installments
• Payment receipts
• Aging report
• Customer ledger
• Export
"""
import logging
from datetime import date
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C
from desktop.utils.widgets import (
    KPICard, Card, H2, H3, Caption, PrimaryBtn, SecondaryBtn, DangerBtn,
    SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout
)

_log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(n, cur='KES'):
    try:
        return f"{cur} {float(n):,.2f}"
    except Exception:
        return f"{cur} 0.00"


def _status_color(s):
    return {
        'pending':   C['warn'],
        'partial':   C['info'],
        'paid':      C['ok'],
        'overdue':   C['err'],
        'cancelled': C['muted'],
    }.get(s, C['text2'])


def _status_label(s):
    return {
        'pending':   '⏳ Pending',
        'partial':   '◑ Partial',
        'paid':      '✓ Paid',
        'overdue':   '⚠ Overdue',
        'cancelled': '✕ Cancelled',
    }.get(s, s.title())


# ─────────────────────────────────────────────────────────────────────────────
# Main Tab
# ─────────────────────────────────────────────────────────────────────────────

class DebtTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api            = api
        self.user           = user
        self.db_path        = db_path
        self.config_getter  = config_getter
        self._currency      = 'KES'
        self._build()

    def _role(self):
        return (self.user.get('user') or self.user).get('role', 'cashier')

    def _cfg(self):
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _build(self):
        lay, _ = page_layout(self, margins=(0, 0, 0, 0), spacing=0)

        # Sub-tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane  {{ border: none; background: {C['app']}; }}
            QTabBar::tab      {{ padding: 10px 22px; font-size: 13px; font-weight: 600;
                                 color: {C['text2']}; background: {C['surface']};
                                 border: none; border-bottom: 3px solid transparent; }}
            QTabBar::tab:selected {{ color: {C['gold']}; border-bottom: 3px solid {C['gold']}; }}
            QTabBar::tab:hover    {{ color: {C['text']}; }}
        """)

        self._overview_tab    = _OverviewTab(self)
        self._invoices_tab    = _InvoicesTab(self)
        self._customers_tab   = _CustomersTab(self)
        self._payments_tab    = _PaymentsTab(self)
        self._aging_tab       = _AgingTab(self)

        self._tabs.addTab(self._overview_tab,  '⊞  Overview')
        self._tabs.addTab(self._invoices_tab,  '📄  Invoices')
        self._tabs.addTab(self._customers_tab, '👥  Customers')
        self._tabs.addTab(self._payments_tab,  '💳  Payments')
        self._tabs.addTab(self._aging_tab,     '📊  Aging Report')

        self._tabs.currentChanged.connect(self._on_tab_change)
        lay.addWidget(self._tabs)

    def _on_tab_change(self, idx):
        w = self._tabs.widget(idx)
        if hasattr(w, 'refresh'):
            try:
                w.refresh()
            except Exception as e:
                _log.warning(f"DebtTab sub-refresh: {e}")

    def on_show(self):
        self._currency = self._cfg().get('currency_symbol', 'KES') or 'KES'
        self._overview_tab.refresh()

    def refresh(self):
        self.on_show()


# ─────────────────────────────────────────────────────────────────────────────
# Overview sub-tab
# ─────────────────────────────────────────────────────────────────────────────

class _OverviewTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(28, 24, 28, 24), spacing=20)

        # Header row
        hrow = QHBoxLayout()
        hrow.addWidget(H2('Debt Overview'))
        hrow.addStretch()
        col_btn = PrimaryBtn('+ Collect Payment', 42)
        col_btn.clicked.connect(lambda: self.p._invoices_tab._collect_payment_dialog())
        hrow.addWidget(col_btn)
        new_inv = SecondaryBtn('+ Credit Sale', 42)
        new_inv.clicked.connect(lambda: self.p._invoices_tab._new_invoice_dialog())
        hrow.addWidget(new_inv)
        lay.addLayout(hrow)

        # KPI row
        kr = QHBoxLayout(); kr.setSpacing(16)
        self._k_out   = KPICard('Outstanding',     '—',  'total debt',       C['err'])
        self._k_over  = KPICard('Overdue',          '—',  'past due date',    C['warn'])
        self._k_col   = KPICard("Today's Collected",'—',  'payments today',   C['ok'])
        self._k_cust  = KPICard('Customers w/ Debt','0',  'active accounts',  C['info'])
        for k in (self._k_out, self._k_over, self._k_col, self._k_cust):
            kr.addWidget(k)
        lay.addLayout(kr)

        # Body
        body = QHBoxLayout(); body.setSpacing(20)

        # Top debtors
        td = Card(); tdl = td.layout_v((20, 16, 20, 16), 12)
        tdl.addWidget(H3('Largest Debtors'))
        self._debtors_tbl = make_table(
            ['Customer', 'Outstanding'], stretch_col=0, row_height=38)
        self._debtors_tbl.setColumnWidth(1, 140)
        self._debtors_tbl.setMaximumHeight(250)
        tdl.addWidget(self._debtors_tbl)
        body.addWidget(td, 3)

        # Recent activity
        ra = Card(); ral = ra.layout_v((20, 16, 20, 16), 12)
        ral.addWidget(H3('Recent Payments'))
        self._recent_tbl = make_table(
            ['Receipt', 'Customer', 'Amount', 'Time'], stretch_col=1, row_height=38)
        for ci, w in [(0, 110), (2, 120), (3, 130)]:
            self._recent_tbl.setColumnWidth(ci, w)
        self._recent_tbl.setMaximumHeight(250)
        ral.addWidget(self._recent_tbl)
        body.addWidget(ra, 4)

        lay.addLayout(body)

        # Overdue list
        od = Card(); odl = od.layout_v((20, 16, 20, 16), 12)
        odl.addWidget(H3('⚠  Overdue Accounts'))
        self._overdue_tbl = make_table(
            ['Invoice', 'Customer', 'Phone', 'Balance', 'Due Date', 'Days Overdue'],
            stretch_col=1, row_height=38)
        for ci, w in [(0, 130), (2, 110), (3, 120), (4, 100), (5, 110)]:
            self._overdue_tbl.setColumnWidth(ci, w)
        self._overdue_tbl.setMinimumHeight(180)
        odl.addWidget(self._overdue_tbl)
        lay.addWidget(od)

    def refresh(self):
        cur = self.p._currency
        try:
            s = self.p.api.get_debt_summary()

            out   = s.get('outstanding', {})
            over  = s.get('overdue', {})
            today = s.get('today_collected', {})

            self._k_out.set_value(_fmt(out.get('total', 0), cur),
                                  C['err'] if out.get('total', 0) > 0 else C['ok'])
            self._k_over.set_value(_fmt(over.get('total', 0), cur),
                                   C['err'] if over.get('total', 0) > 0 else C['ok'])
            self._k_col.set_value(_fmt(today.get('total', 0), cur))
            self._k_cust.set_value(str(s.get('customers_with_debt', 0)))

            # Top debtors
            self._debtors_tbl.setRowCount(0)
            for i, d in enumerate(s.get('top_debtors', [])):
                self._debtors_tbl.insertRow(i)
                self._debtors_tbl.setItem(i, 0, tbl_item(d.get('customer_name', '')))
                self._debtors_tbl.setItem(i, 1, tbl_right(
                    _fmt(d.get('total_balance', 0), cur), C['err']))
        except Exception as e:
            _log.warning(f"Debt overview KPI: {e}")

        try:
            payments = self.p.api.get_debt_payments() or []
            self._recent_tbl.setRowCount(0)
            for i, p in enumerate(payments[:15]):
                self._recent_tbl.insertRow(i)
                self._recent_tbl.setItem(i, 0, tbl_item(p.get('payment_receipt', '')))
                self._recent_tbl.setItem(i, 1, tbl_item(p.get('customer_name', '')))
                self._recent_tbl.setItem(i, 2, tbl_right(
                    _fmt(p.get('amount', 0), cur), C['ok']))
                self._recent_tbl.setItem(i, 3, tbl_item(
                    (p.get('created_at', '') or '')[:16]))
        except Exception as e:
            _log.warning(f"Debt overview recent payments: {e}")

        try:
            overdue = self.p.api.get_overdue_invoices() or []
            self._overdue_tbl.setRowCount(0)
            for i, inv in enumerate(overdue):
                self._overdue_tbl.insertRow(i)
                due = inv.get('due_date', '') or ''
                try:
                    delta = (date.today() - date.fromisoformat(due)).days if due else 0
                except Exception:
                    delta = 0
                self._overdue_tbl.setItem(i, 0, tbl_item(inv.get('invoice_number', '')))
                self._overdue_tbl.setItem(i, 1, tbl_item(inv.get('customer_name', '')))
                self._overdue_tbl.setItem(i, 2, tbl_item(inv.get('customer_phone', '') or ''))
                bal_item = tbl_right(_fmt(inv.get('balance', 0), cur), C['err'])
                self._overdue_tbl.setItem(i, 3, bal_item)
                self._overdue_tbl.setItem(i, 4, tbl_center(due))
                days_item = tbl_center(f"{delta}d", C['err'] if delta > 0 else C['warn'])
                self._overdue_tbl.setItem(i, 5, days_item)
        except Exception as e:
            _log.warning(f"Debt overview overdue: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Invoices sub-tab
# ─────────────────────────────────────────────────────────────────────────────

class _InvoicesTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._invoices = []
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(24, 20, 24, 20), spacing=16)

        # Toolbar
        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search by customer, invoice, phone…')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)

        self._status_filter = QComboBox()
        self._status_filter.addItems(['All Statuses', 'Pending', 'Partial', 'Paid', 'Overdue', 'Cancelled'])
        self._status_filter.setMinimumHeight(40)
        self._status_filter.currentTextChanged.connect(self._filter)
        tb.addWidget(self._status_filter)

        self._date_from = QDateEdit()
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._date_from.setCalendarPopup(True)
        self._date_from.setMinimumHeight(40)
        self._date_from.dateChanged.connect(self.refresh)
        tb.addWidget(QLabel('From')); tb.addWidget(self._date_from)

        self._date_to = QDateEdit()
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setCalendarPopup(True)
        self._date_to.setMinimumHeight(40)
        self._date_to.dateChanged.connect(self.refresh)
        tb.addWidget(QLabel('To')); tb.addWidget(self._date_to)

        new_btn = PrimaryBtn('+ Credit Sale / Part Payment', 42)
        new_btn.clicked.connect(self._new_invoice_dialog)
        tb.addWidget(new_btn)

        ref_btn = SecondaryBtn('↺', 42)
        ref_btn.clicked.connect(self.refresh)
        tb.addWidget(ref_btn)
        lay.addLayout(tb)

        # Table
        self._tbl = make_table(
            ['Invoice #', 'Customer', 'Phone', 'Total', 'Paid', 'Balance', 'Status', 'Due Date', 'Actions'],
            stretch_col=1, row_height=44)
        for ci, w in [(0, 130), (2, 110), (3, 110), (4, 110), (5, 110), (6, 100), (7, 100), (8, 200)]:
            self._tbl.setColumnWidth(ci, w)
        lay.addWidget(self._tbl)

        self._stats = Caption('')
        lay.addWidget(self._stats)

    def refresh(self):
        try:
            start = self._date_from.date().toString('yyyy-MM-dd')
            end   = self._date_to.date().toString('yyyy-MM-dd')
            self._invoices = self.p.api.get_debt_invoices(start=start, end=end) or []
        except Exception as e:
            _log.warning(f"Invoice refresh: {e}")
            self._invoices = []
        self._filter()

    def _filter(self):
        q = self._search.text().lower()
        sf = self._status_filter.currentText().lower()
        filtered = []
        for inv in self._invoices:
            if sf not in ('all statuses', '') and inv.get('status', '') != sf:
                continue
            if q and not any(q in str(inv.get(k, '')).lower()
                             for k in ('invoice_number', 'customer_name', 'customer_phone', 'receipt_number')):
                continue
            filtered.append(inv)
        self._populate(filtered)

    def _populate(self, invs):
        cur = self.p._currency
        self._tbl.setRowCount(0)
        total_balance = 0.0
        for i, inv in enumerate(invs):
            self._tbl.insertRow(i)
            bal = float(inv.get('balance', 0))
            total_balance += bal
            status = inv.get('status', 'pending')

            # Compute overdue
            due = inv.get('due_date', '')
            if status not in ('paid', 'cancelled') and due:
                try:
                    if date.fromisoformat(due) < date.today():
                        status = 'overdue'
                except Exception:
                    pass

            self._tbl.setItem(i, 0, tbl_item(inv.get('invoice_number', '')))
            self._tbl.setItem(i, 1, tbl_item(inv.get('customer_name', '')))
            self._tbl.setItem(i, 2, tbl_item(inv.get('customer_phone', '') or ''))
            self._tbl.setItem(i, 3, tbl_right(_fmt(inv.get('total_amount', 0), cur)))
            self._tbl.setItem(i, 4, tbl_right(_fmt(inv.get('amount_paid', 0), cur), C['ok']))
            self._tbl.setItem(i, 5, tbl_right(_fmt(bal, cur),
                                              C['err'] if bal > 0 else C['ok']))
            s_item = tbl_center(_status_label(status), _status_color(status))
            self._tbl.setItem(i, 6, s_item)
            self._tbl.setItem(i, 7, tbl_center(due or '—'))

            # Actions
            cell = QWidget(); cell.setStyleSheet('background:transparent;')
            cl   = QHBoxLayout(cell); cl.setContentsMargins(6, 4, 6, 4); cl.setSpacing(6)

            if status not in ('paid', 'cancelled'):
                pay_btn = QPushButton('💳 Collect')
                pay_btn.setMinimumHeight(32)
                pay_btn.setCursor(Qt.PointingHandCursor)
                pay_btn.setStyleSheet(
                    f"QPushButton{{background:{C['ok']}22;color:{C['ok']};"
                    f"border:1px solid {C['ok']}66;border-radius:6px;"
                    f"font-size:12px;font-weight:700;padding:2px 10px;}}"
                    f"QPushButton:hover{{background:{C['ok']};color:#fff;}}")
                pay_btn.clicked.connect(
                    lambda _, inv_id=inv['id'], inv_num=inv.get('invoice_number',''),
                    cname=inv.get('customer_name',''), b=bal:
                    self._collect_payment_dialog(inv_id, inv_num, cname, b))
                cl.addWidget(pay_btn)

            view_btn = QPushButton('📋 History')
            view_btn.setMinimumHeight(32)
            view_btn.setCursor(Qt.PointingHandCursor)
            view_btn.setStyleSheet(
                f"QPushButton{{background:{C['info']}22;color:{C['info']};"
                f"border:1px solid {C['info']}66;border-radius:6px;"
                f"font-size:12px;font-weight:700;padding:2px 10px;}}"
                f"QPushButton:hover{{background:{C['info']};color:#fff;}}")
            view_btn.clicked.connect(
                lambda _, inv_id=inv['id']: self._view_history(inv_id))
            cl.addWidget(view_btn)

            cl.addStretch()
            self._tbl.setCellWidget(i, 8, cell)

        n_out = sum(1 for inv in invs if inv.get('status') not in ('paid', 'cancelled'))
        self._stats.setText(
            f"  {len(invs)} invoices  ·  "
            f"{n_out} outstanding  ·  "
            f"Total balance: {_fmt(total_balance, cur)}")

    def _new_invoice_dialog(self):
        dlg = _NewInvoiceDialog(self.p, self)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()
            self.p._overview_tab.refresh()

    def _collect_payment_dialog(self, invoice_id=None, inv_num='',
                                customer_name='', balance=0.0):
        dlg = _CollectPaymentDialog(self.p, self,
                                    invoice_id=invoice_id,
                                    invoice_number=inv_num,
                                    customer_name=customer_name,
                                    current_balance=balance)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()
            self.p._overview_tab.refresh()
            self.p._payments_tab.refresh()

    def _view_history(self, invoice_id):
        dlg = _InvoiceHistoryDialog(self.p, invoice_id)
        dlg.exec_()


# ─────────────────────────────────────────────────────────────────────────────
# Customers sub-tab
# ─────────────────────────────────────────────────────────────────────────────

class _CustomersTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._customers = []
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(24, 20, 24, 20), spacing=16)

        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search customers…')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)
        add_btn = PrimaryBtn('+ New Customer', 42)
        add_btn.clicked.connect(self._add_customer)
        tb.addWidget(add_btn)
        ref_btn = SecondaryBtn('↺', 42)
        ref_btn.clicked.connect(self.refresh)
        tb.addWidget(ref_btn)
        lay.addLayout(tb)

        self._tbl = make_table(
            ['Name', 'Phone', 'Email', 'Outstanding', 'Open Invoices', 'Actions'],
            stretch_col=0, row_height=44)
        for ci, w in [(1, 120), (2, 160), (3, 130), (4, 110), (5, 180)]:
            self._tbl.setColumnWidth(ci, w)
        lay.addWidget(self._tbl)

    def refresh(self):
        try:
            self._customers = self.p.api.get_customers() or []
        except Exception as e:
            _log.warning(f"Customers refresh: {e}")
            self._customers = []
        self._filter()

    def _filter(self):
        q = self._search.text().lower()
        filtered = [c for c in self._customers
                    if not q or q in c.get('name', '').lower()
                    or q in (c.get('phone') or '').lower()]
        self._populate(filtered)

    def _populate(self, custs):
        cur = self.p._currency
        self._tbl.setRowCount(0)
        for i, c in enumerate(custs):
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, tbl_item(c.get('name', '')))
            self._tbl.setItem(i, 1, tbl_item(c.get('phone', '') or ''))
            self._tbl.setItem(i, 2, tbl_item(c.get('email', '') or ''))
            bal = float(c.get('total_outstanding', 0))
            self._tbl.setItem(i, 3, tbl_right(_fmt(bal, cur),
                                               C['err'] if bal > 0 else C['text']))
            self._tbl.setItem(i, 4, tbl_center(str(c.get('open_invoices', 0))))

            # Actions
            cell = QWidget(); cell.setStyleSheet('background:transparent;')
            cl   = QHBoxLayout(cell); cl.setContentsMargins(6, 4, 6, 4); cl.setSpacing(6)

            ledger_btn = QPushButton('📒 Ledger')
            ledger_btn.setMinimumHeight(32)
            ledger_btn.setCursor(Qt.PointingHandCursor)
            ledger_btn.setStyleSheet(
                f"QPushButton{{background:{C['info']}22;color:{C['info']};"
                f"border:1px solid {C['info']}66;border-radius:6px;"
                f"font-size:12px;font-weight:700;padding:2px 10px;}}"
                f"QPushButton:hover{{background:{C['info']};color:#fff;}}")
            ledger_btn.clicked.connect(
                lambda _, cid=c['id']: self._open_ledger(cid))
            cl.addWidget(ledger_btn)

            edit_btn = QPushButton('✏ Edit')
            edit_btn.setMinimumHeight(32)
            edit_btn.setCursor(Qt.PointingHandCursor)
            edit_btn.setStyleSheet(
                f"QPushButton{{background:{C['card2']};color:{C['text']};"
                f"border:1px solid {C['border2']};border-radius:6px;"
                f"font-size:12px;font-weight:700;padding:2px 10px;}}"
                f"QPushButton:hover{{background:{C['hover']};color:{C['gold']};}}")
            edit_btn.clicked.connect(
                lambda _, cid=c['id']: self._edit_customer(cid))
            cl.addWidget(edit_btn)

            cl.addStretch()
            self._tbl.setCellWidget(i, 5, cell)

    def _add_customer(self):
        dlg = _CustomerDialog(self.p, self)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()

    def _edit_customer(self, cid):
        cust = next((c for c in self._customers if c['id'] == cid), None)
        if not cust:
            return
        dlg = _CustomerDialog(self.p, self, cust)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()

    def _open_ledger(self, cid):
        dlg = _CustomerLedgerDialog(self.p, cid)
        dlg.exec_()


# ─────────────────────────────────────────────────────────────────────────────
# Payments sub-tab
# ─────────────────────────────────────────────────────────────────────────────

class _PaymentsTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(24, 20, 24, 20), spacing=16)

        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search by receipt, customer…')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)

        self._date_from = QDateEdit()
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._date_from.setCalendarPopup(True)
        self._date_from.setMinimumHeight(40)
        self._date_from.dateChanged.connect(self.refresh)
        tb.addWidget(QLabel('From')); tb.addWidget(self._date_from)

        self._date_to = QDateEdit()
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setCalendarPopup(True)
        self._date_to.setMinimumHeight(40)
        self._date_to.dateChanged.connect(self.refresh)
        tb.addWidget(QLabel('To')); tb.addWidget(self._date_to)

        ref_btn = SecondaryBtn('↺', 42)
        ref_btn.clicked.connect(self.refresh)
        tb.addWidget(ref_btn)
        lay.addLayout(tb)

        self._tbl = make_table(
            ['Payment Receipt', 'Invoice #', 'Customer', 'Amount', 'Method',
             'Balance After', 'Cashier', 'Date / Time'],
            stretch_col=2, row_height=40)
        for ci, w in [(0, 130), (1, 130), (3, 120), (4, 90), (5, 120), (6, 100), (7, 140)]:
            self._tbl.setColumnWidth(ci, w)
        lay.addWidget(self._tbl)
        self._stats = Caption('')
        lay.addWidget(self._stats)
        self._payments = []

    def refresh(self):
        try:
            start = self._date_from.date().toString('yyyy-MM-dd')
            end   = self._date_to.date().toString('yyyy-MM-dd')
            self._payments = self.p.api.get_debt_payments(start=start, end=end) or []
        except Exception as e:
            _log.warning(f"Payments refresh: {e}")
            self._payments = []
        self._filter()

    def _filter(self):
        q = self._search.text().lower()
        filtered = [p for p in self._payments
                    if not q or q in p.get('payment_receipt', '').lower()
                    or q in p.get('customer_name', '').lower()
                    or q in p.get('invoice_number', '').lower()]
        self._populate(filtered)

    def _populate(self, payments):
        cur = self.p._currency
        self._tbl.setRowCount(0)
        total = 0.0
        for i, p in enumerate(payments):
            self._tbl.insertRow(i)
            amt = float(p.get('amount', 0)); total += amt
            self._tbl.setItem(i, 0, tbl_item(p.get('payment_receipt', '')))
            self._tbl.setItem(i, 1, tbl_item(p.get('invoice_number', '') or ''))
            self._tbl.setItem(i, 2, tbl_item(p.get('customer_name', '')))
            self._tbl.setItem(i, 3, tbl_right(_fmt(amt, cur), C['ok']))
            self._tbl.setItem(i, 4, tbl_center(p.get('payment_method', 'cash').title()))
            self._tbl.setItem(i, 5, tbl_right(_fmt(p.get('balance_after', 0), cur)))
            self._tbl.setItem(i, 6, tbl_item(p.get('cashier_name', '') or ''))
            self._tbl.setItem(i, 7, tbl_item((p.get('created_at', '') or '')[:16]))
        self._stats.setText(
            f"  {len(payments)} payments  ·  Total collected: {_fmt(total, cur)}")


# ─────────────────────────────────────────────────────────────────────────────
# Aging Report sub-tab
# ─────────────────────────────────────────────────────────────────────────────

class _AgingTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(28, 24, 28, 24), spacing=20)
        lay.addWidget(H2('Debt Aging Report'))

        # Band cards
        self._bands = QHBoxLayout(); self._bands.setSpacing(16)
        self._b_cur  = KPICard('Current (Not Due)',  '—', 'amount',  C['ok'])
        self._b_30   = KPICard('1–30 Days Overdue',  '—', 'amount',  C['warn'])
        self._b_60   = KPICard('31–60 Days Overdue', '—', 'amount',  C['warn'])
        self._b_90   = KPICard('61–90 Days Overdue', '—', 'amount',  C['err'])
        self._b_over = KPICard('Over 90 Days',       '—', 'amount',  C['err'])
        for b in (self._b_cur, self._b_30, self._b_60, self._b_90, self._b_over):
            self._bands.addWidget(b)
        lay.addLayout(self._bands)

        # Detailed table
        self._tbl = make_table(
            ['Invoice #', 'Customer', 'Phone', 'Total', 'Balance', 'Due Date', 'Days Overdue'],
            stretch_col=1, row_height=40)
        for ci, w in [(0, 130), (2, 110), (3, 110), (4, 110), (5, 100), (6, 110)]:
            self._tbl.setColumnWidth(ci, w)
        lay.addWidget(self._tbl)

        ref_btn = SecondaryBtn('↺  Refresh', 40)
        ref_btn.clicked.connect(self.refresh)
        lay.addWidget(ref_btn)

    def refresh(self):
        cur = self.p._currency
        try:
            aging = self.p.api.get_aging_report()
            self._b_cur.set_value(_fmt(aging.get('current', {}).get('total', 0), cur))
            self._b_30.set_value(_fmt(aging.get('1_30', {}).get('total', 0), cur))
            self._b_60.set_value(_fmt(aging.get('31_60', {}).get('total', 0), cur))
            self._b_90.set_value(_fmt(aging.get('61_90', {}).get('total', 0), cur))
            self._b_over.set_value(_fmt(aging.get('over_90', {}).get('total', 0), cur))
        except Exception as e:
            _log.warning(f"Aging report bands: {e}")

        try:
            all_inv = self.p.api.get_debt_invoices() or []
            # Show all non-paid invoices
            pending = [i for i in all_inv if i.get('status') not in ('paid', 'cancelled')]
            self._tbl.setRowCount(0)
            for i, inv in enumerate(pending):
                self._tbl.insertRow(i)
                due = inv.get('due_date', '') or ''
                try:
                    delta = (date.today() - date.fromisoformat(due)).days if due else 0
                except Exception:
                    delta = 0
                self._tbl.setItem(i, 0, tbl_item(inv.get('invoice_number', '')))
                self._tbl.setItem(i, 1, tbl_item(inv.get('customer_name', '')))
                self._tbl.setItem(i, 2, tbl_item(inv.get('customer_phone', '') or ''))
                self._tbl.setItem(i, 3, tbl_right(_fmt(inv.get('total_amount', 0), cur)))
                self._tbl.setItem(i, 4, tbl_right(
                    _fmt(inv.get('balance', 0), cur), C['err']))
                self._tbl.setItem(i, 5, tbl_center(due or '—'))
                color = C['err'] if delta > 30 else (C['warn'] if delta > 0 else C['ok'])
                self._tbl.setItem(i, 6, tbl_center(
                    f"{delta}d overdue" if delta > 0 else 'On time', color))
        except Exception as e:
            _log.warning(f"Aging table: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# Dialogs
# ═════════════════════════════════════════════════════════════════════════════

class _CustomerDialog(QDialog):
    def __init__(self, parent_tab: DebtTab, parent_widget, customer=None):
        super().__init__(parent_widget)
        self.p      = parent_tab
        self._cust  = customer
        self.setWindowTitle('Edit Customer' if customer else 'New Customer')
        self.setMinimumWidth(460)
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)
        self._build()

    def _build(self):
        lay = QFormLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        def lbl(t):
            l = QLabel(t)
            l.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:600;")
            return l

        def fld(ph=''):
            f = QLineEdit(); f.setMinimumHeight(40); f.setPlaceholderText(ph)
            return f

        self.name  = fld('Full name *')
        self.phone = fld('e.g. 0712345678')
        self.email = fld('customer@email.com')
        self.addr  = fld('Physical address')
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0, 9999999); self.limit.setDecimals(2)
        self.limit.setMinimumHeight(40)
        self.notes = QLineEdit(); self.notes.setMinimumHeight(40)

        if self._cust:
            self.name.setText(self._cust.get('name', ''))
            self.phone.setText(self._cust.get('phone', '') or '')
            self.email.setText(self._cust.get('email', '') or '')
            self.addr.setText(self._cust.get('address', '') or '')
            self.limit.setValue(float(self._cust.get('credit_limit', 0) or 0))
            self.notes.setText(self._cust.get('notes', '') or '')

        lay.addRow(lbl('Name *'), self.name)
        lay.addRow(lbl('Phone'), self.phone)
        lay.addRow(lbl('Email'), self.email)
        lay.addRow(lbl('Address'), self.addr)
        lay.addRow(lbl('Credit Limit'), self.limit)
        lay.addRow(lbl('Notes'), self.notes)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        lay.addRow(sep)

        br = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 42); cancel.clicked.connect(self.reject)
        save   = PrimaryBtn('Save Customer', 42); save.clicked.connect(self._save)
        br.addWidget(cancel, 1); br.addWidget(save, 1)
        lay.addRow(br)

    def _save(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, 'Required', 'Name is required.')
            return
        data = {
            'name':         self.name.text().strip(),
            'phone':        self.phone.text().strip(),
            'email':        self.email.text().strip(),
            'address':      self.addr.text().strip(),
            'credit_limit': self.limit.value(),
            'notes':        self.notes.text().strip(),
        }
        try:
            if self._cust:
                res = self.p.api.update_customer(self._cust['id'], data)
            else:
                res = self.p.api.create_customer(data)
            if res and res.get('success'):
                self.accept()
            else:
                QMessageBox.critical(self, 'Error', res.get('error', 'Failed.'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))


class _NewInvoiceDialog(QDialog):
    """Create a credit sale or part-payment invoice."""

    def __init__(self, parent_tab: DebtTab, parent_widget,
                 prefill_total=0.0, prefill_paid=0.0,
                 prefill_sale_id=None, prefill_receipt=''):
        super().__init__(parent_widget)
        self.p = parent_tab
        self.setWindowTitle('Credit Sale / Part Payment')
        self.setMinimumWidth(520)
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)
        self._prefill_total   = prefill_total
        self._prefill_paid    = prefill_paid
        self._prefill_sale_id = prefill_sale_id
        self._prefill_receipt = prefill_receipt
        self._customers = []
        self._build()
        self._load_customers()

    def _build(self):
        lay = QFormLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        def lbl(t):
            l = QLabel(t)
            l.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:600;")
            return l

        # Customer
        cust_row = QHBoxLayout()
        self.cust_combo = QComboBox()
        self.cust_combo.setMinimumHeight(42)
        self.cust_combo.setEditable(True)
        self.cust_combo.setInsertPolicy(QComboBox.NoInsert)
        self.cust_combo.lineEdit().setPlaceholderText('Select or search customer…')
        cust_row.addWidget(self.cust_combo, 1)
        new_cust = SecondaryBtn('+ New', 42)
        new_cust.setFixedWidth(70)
        new_cust.clicked.connect(self._add_new_customer)
        cust_row.addWidget(new_cust)
        lay.addRow(lbl('Customer *'), cust_row)

        # Receipt / Invoice reference
        self.receipt = QLineEdit()
        self.receipt.setMinimumHeight(40)
        self.receipt.setPlaceholderText('e.g. RCP-20260629-0001 (optional)')
        self.receipt.setText(self._prefill_receipt)
        lay.addRow(lbl('Sale Receipt'), self.receipt)

        # Amounts
        cur = self.p._currency
        self.total = QDoubleSpinBox()
        self.total.setRange(0.01, 9999999); self.total.setDecimals(2)
        self.total.setMinimumHeight(42); self.total.setPrefix(f'{cur} ')
        self.total.setValue(self._prefill_total)
        self.total.valueChanged.connect(self._update_balance)
        lay.addRow(lbl('Total Amount *'), self.total)

        self.paid = QDoubleSpinBox()
        self.paid.setRange(0, 9999999); self.paid.setDecimals(2)
        self.paid.setMinimumHeight(42); self.paid.setPrefix(f'{cur} ')
        self.paid.setValue(self._prefill_paid)
        self.paid.valueChanged.connect(self._update_balance)
        lay.addRow(lbl('Amount Paid Now'), self.paid)

        self.balance_lbl = QLabel(f'{cur} 0.00')
        self.balance_lbl.setStyleSheet(
            f"color:{C['err']};font-size:18px;font-weight:800;"
            f"background:transparent;")
        lay.addRow(lbl('Outstanding Balance'), self.balance_lbl)

        # Payment method
        self.method = QComboBox()
        self.method.addItems(['Cash', 'M-Pesa', 'Card', 'Cheque', 'Bank Transfer'])
        self.method.setMinimumHeight(40)
        lay.addRow(lbl('Payment Method'), self.method)

        # Due date
        self.due = QDateEdit()
        self.due.setDate(QDate.currentDate().addDays(30))
        self.due.setCalendarPopup(True)
        self.due.setMinimumHeight(40)
        self.due_check = QCheckBox('Set due date')
        self.due.setEnabled(False)
        self.due_check.stateChanged.connect(lambda s: self.due.setEnabled(bool(s)))
        due_row = QHBoxLayout()
        due_row.addWidget(self.due_check)
        due_row.addWidget(self.due)
        lay.addRow(lbl('Due Date'), due_row)

        self.notes = QLineEdit()
        self.notes.setMinimumHeight(40)
        self.notes.setPlaceholderText('Optional notes…')
        lay.addRow(lbl('Notes'), self.notes)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        lay.addRow(sep)

        br = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 42); cancel.clicked.connect(self.reject)
        save   = PrimaryBtn('Create Invoice', 42); save.clicked.connect(self._save)
        br.addWidget(cancel, 1); br.addWidget(save, 1)
        lay.addRow(br)

        self._update_balance()

    def _load_customers(self):
        try:
            self._customers = self.p.api.get_customers() or []
        except Exception:
            self._customers = []
        self.cust_combo.clear()
        for c in self._customers:
            label = f"{c['name']}"
            if c.get('phone'):
                label += f"  ({c['phone']})"
            self.cust_combo.addItem(label, c['id'])

    def _add_new_customer(self):
        dlg = _CustomerDialog(self.p, self)
        if dlg.exec_() == QDialog.Accepted:
            self._load_customers()

    def _update_balance(self):
        bal = max(0.0, round(self.total.value() - self.paid.value(), 2))
        cur = self.p._currency
        self.balance_lbl.setText(f'{cur} {bal:,.2f}')
        self.balance_lbl.setStyleSheet(
            f"color:{C['err'] if bal > 0 else C['ok']};"
            f"font-size:18px;font-weight:800;background:transparent;")

    def _save(self):
        idx = self.cust_combo.currentIndex()
        cid = self.cust_combo.itemData(idx) if idx >= 0 else None
        if not cid:
            QMessageBox.warning(self, 'Required', 'Please select a customer.')
            return
        if self.total.value() <= 0:
            QMessageBox.warning(self, 'Required', 'Total amount must be greater than zero.')
            return

        data = {
            'customer_id':    cid,
            'sale_id':        self._prefill_sale_id,
            'receipt_number': self.receipt.text().strip() or None,
            'total_amount':   self.total.value(),
            'amount_paid':    self.paid.value(),
            'payment_method': self.method.currentText().lower(),
            'due_date':       self.due.date().toString('yyyy-MM-dd')
                              if self.due_check.isChecked() else None,
            'notes':          self.notes.text().strip(),
        }
        try:
            res = self.p.api.create_debt_invoice(data)
            if res and res.get('success'):
                cur = self.p._currency
                bal = res.get('balance', 0)
                inv = res.get('invoice_number', '')
                QMessageBox.information(self, 'Invoice Created ✓',
                    f"Invoice: {inv}\n"
                    f"Outstanding Balance: {_fmt(bal, cur)}\n\n"
                    f"{'✓ PAID IN FULL' if bal == 0 else '⚠ Balance due — remind customer of payment terms.'}")
                self.accept()
            else:
                QMessageBox.critical(self, 'Error', res.get('error', 'Failed to create invoice.'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))


class _CollectPaymentDialog(QDialog):
    def __init__(self, parent_tab: DebtTab, parent_widget,
                 invoice_id=None, invoice_number='',
                 customer_name='', current_balance=0.0):
        super().__init__(parent_widget)
        self.p                = parent_tab
        self._invoice_id      = invoice_id
        self._invoice_number  = invoice_number
        self._customer_name   = customer_name
        self._current_balance = current_balance
        self.setWindowTitle('Collect Debt Payment')
        self.setMinimumWidth(480)
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)
        self._invoices = []
        self._build()
        if not invoice_id:
            self._load_invoices()

    def _build(self):
        lay = QFormLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        def lbl(t):
            l = QLabel(t)
            l.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:600;")
            return l

        cur = self.p._currency

        if self._invoice_id:
            # Pre-selected invoice
            info = QLabel(
                f"<b>{self._customer_name}</b><br>"
                f"Invoice: {self._invoice_number}<br>"
                f"Outstanding: <span style='color:{C['err']};font-size:16px;font-weight:800;'>"
                f"{_fmt(self._current_balance, cur)}</span>")
            info.setTextFormat(Qt.RichText)
            info.setStyleSheet(
                f"color:{C['text']};font-size:14px;"
                f"background:{C['card']};border:1px solid {C['border']};"
                f"border-radius:8px;padding:12px;")
            lay.addRow(info)
        else:
            # Must select invoice
            self.inv_combo = QComboBox()
            self.inv_combo.setMinimumHeight(42)
            self.inv_combo.currentIndexChanged.connect(self._on_invoice_selected)
            lay.addRow(lbl('Invoice *'), self.inv_combo)

            self._balance_info = QLabel('—')
            self._balance_info.setStyleSheet(
                f"color:{C['err']};font-size:16px;font-weight:800;background:transparent;")
            lay.addRow(lbl('Outstanding'), self._balance_info)

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 9999999); self.amount.setDecimals(2)
        self.amount.setMinimumHeight(42); self.amount.setPrefix(f'{cur} ')
        if self._invoice_id:
            self.amount.setValue(self._current_balance)
        lay.addRow(lbl('Payment Amount *'), self.amount)

        self.method = QComboBox()
        self.method.addItems(['Cash', 'M-Pesa', 'Card', 'Cheque', 'Bank Transfer'])
        self.method.setMinimumHeight(40)
        lay.addRow(lbl('Payment Method'), self.method)

        self.notes = QLineEdit()
        self.notes.setMinimumHeight(40)
        self.notes.setPlaceholderText('Optional notes…')
        lay.addRow(lbl('Notes'), self.notes)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        lay.addRow(sep)

        br = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 42); cancel.clicked.connect(self.reject)
        collect = PrimaryBtn('Collect Payment', 42); collect.clicked.connect(self._collect)
        br.addWidget(cancel, 1); br.addWidget(collect, 1)
        lay.addRow(br)

    def _load_invoices(self):
        try:
            self._invoices = self.p.api.get_debt_invoices(
                status=['pending', 'partial']) or []
        except Exception:
            self._invoices = []
        if hasattr(self, 'inv_combo'):
            self.inv_combo.clear()
            for inv in self._invoices:
                label = (f"{inv.get('invoice_number','')}  —  "
                         f"{inv.get('customer_name','')}  —  "
                         f"{_fmt(inv.get('balance',0), self.p._currency)} due")
                self.inv_combo.addItem(label, inv['id'])
            self._on_invoice_selected(0)

    def _on_invoice_selected(self, idx):
        if idx < 0 or idx >= len(self._invoices):
            return
        inv = self._invoices[idx]
        bal = float(inv.get('balance', 0))
        self._current_balance = bal
        self._invoice_id      = inv['id']
        if hasattr(self, '_balance_info'):
            self._balance_info.setText(_fmt(bal, self.p._currency))
        self.amount.setValue(bal)

    def _collect(self):
        if not self._invoice_id:
            QMessageBox.warning(self, 'Required', 'Select an invoice.')
            return
        amt = self.amount.value()
        if amt <= 0:
            QMessageBox.warning(self, 'Invalid', 'Amount must be greater than zero.')
            return
        try:
            res = self.p.api.record_debt_payment(
                self._invoice_id,
                amt,
                self.method.currentText().lower(),
                self.notes.text().strip()
            )
            if res and res.get('success'):
                cur = self.p._currency
                bal_after = res.get('balance_after', 0)
                receipt   = res.get('payment_receipt', '')
                status    = res.get('status', '')
                msg = (f"Payment Receipt: {receipt}\n"
                       f"Amount Paid: {_fmt(amt, cur)}\n"
                       f"Balance After: {_fmt(bal_after, cur)}\n\n"
                       f"{'✓ PAID IN FULL' if status == 'paid' else f'Remaining: {_fmt(bal_after, cur)}'}")
                QMessageBox.information(self, 'Payment Recorded ✓', msg)
                self.accept()
            else:
                QMessageBox.critical(self, 'Error', res.get('error', 'Failed.'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))


class _InvoiceHistoryDialog(QDialog):
    def __init__(self, parent_tab: DebtTab, invoice_id: int):
        super().__init__()
        self.p          = parent_tab
        self.invoice_id = invoice_id
        self.setWindowTitle('Payment History')
        self.setMinimumSize(680, 460)
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        lay.addWidget(H2('Invoice Payment History'))
        self._info = QLabel()
        self._info.setStyleSheet(
            f"color:{C['text']};font-size:13px;background:{C['card']};"
            f"border:1px solid {C['border']};border-radius:8px;padding:12px;")
        lay.addWidget(self._info)
        self._tbl = make_table(
            ['Payment Receipt', 'Amount', 'Method', 'Balance After', 'Cashier', 'Date'],
            stretch_col=0, row_height=38)
        for ci, w in [(1, 120), (2, 90), (3, 120), (4, 100), (5, 140)]:
            self._tbl.setColumnWidth(ci, w)
        lay.addWidget(self._tbl)
        close = SecondaryBtn('Close', 40); close.clicked.connect(self.close)
        lay.addWidget(close)

    def _load(self):
        cur = self.p._currency
        try:
            payments = self.p.api.get_debt_payments(invoice_id=self.invoice_id) or []
            inv_list = self.p.api.get_debt_invoices() or []
            inv = next((i for i in inv_list if i['id'] == self.invoice_id), None)
            if inv:
                self._info.setText(
                    f"Invoice: <b>{inv.get('invoice_number','')}</b>    "
                    f"Customer: <b>{inv.get('customer_name','')}</b>    "
                    f"Total: <b>{_fmt(inv.get('total_amount',0), cur)}</b>    "
                    f"Paid: <b>{_fmt(inv.get('amount_paid',0), cur)}</b>    "
                    f"Balance: <b style='color:{C['err']};'>{_fmt(inv.get('balance',0), cur)}</b>    "
                    f"Status: <b>{_status_label(inv.get('status',''))}</b>")
            self._tbl.setRowCount(0)
            for i, p in enumerate(payments):
                self._tbl.insertRow(i)
                self._tbl.setItem(i, 0, tbl_item(p.get('payment_receipt', '')))
                self._tbl.setItem(i, 1, tbl_right(_fmt(p.get('amount', 0), cur), C['ok']))
                self._tbl.setItem(i, 2, tbl_center(p.get('payment_method', '').title()))
                self._tbl.setItem(i, 3, tbl_right(_fmt(p.get('balance_after', 0), cur)))
                self._tbl.setItem(i, 4, tbl_item(p.get('cashier_name', '') or ''))
                self._tbl.setItem(i, 5, tbl_item((p.get('created_at', '') or '')[:16]))
        except Exception as e:
            _log.warning(f"InvoiceHistory: {e}")


class _CustomerLedgerDialog(QDialog):
    def __init__(self, parent_tab: DebtTab, customer_id: int):
        super().__init__()
        self.p   = parent_tab
        self.cid = customer_id
        self.setWindowTitle('Customer Ledger')
        self.setMinimumSize(800, 560)
        from desktop.utils.theme import MBT_STYLESHEET
        self.setStyleSheet(MBT_STYLESHEET)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(14)
        self._header = QLabel()
        self._header.setStyleSheet(
            f"color:{C['text']};font-size:13px;background:{C['card']};"
            f"border:1px solid {C['border']};border-radius:8px;padding:14px;")
        self._header.setTextFormat(Qt.RichText)
        lay.addWidget(self._header)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._inv_tbl = make_table(
            ['Invoice #', 'Sale Receipt', 'Total', 'Paid', 'Balance', 'Status', 'Created'],
            stretch_col=1, row_height=38)
        for ci, w in [(0, 130), (2, 110), (3, 110), (4, 110), (5, 100), (6, 130)]:
            self._inv_tbl.setColumnWidth(ci, w)

        self._pay_tbl = make_table(
            ['Payment Receipt', 'Invoice', 'Amount', 'Method', 'Balance After', 'Date'],
            stretch_col=0, row_height=38)
        for ci, w in [(1, 130), (2, 110), (3, 90), (4, 120), (5, 140)]:
            self._pay_tbl.setColumnWidth(ci, w)

        self._tabs.addTab(self._inv_tbl, 'Invoices')
        self._tabs.addTab(self._pay_tbl, 'Payments')
        lay.addWidget(self._tabs)
        close = SecondaryBtn('Close', 40); close.clicked.connect(self.close)
        lay.addWidget(close)

    def _load(self):
        cur = self.p._currency
        try:
            c = self.p.api.get_customer(self.cid)
            if c:
                self._header.setText(
                    f"<b>{c.get('name','')}</b>   "
                    f"📞 {c.get('phone','') or '—'}   "
                    f"✉ {c.get('email','') or '—'}<br>"
                    f"Outstanding: <b style='color:{C['err']};'>{_fmt(c.get('total_outstanding',0), cur)}</b>   "
                    f"Total Paid: <b style='color:{C['ok']};'>{_fmt(c.get('total_paid',0), cur)}</b>   "
                    f"Open Invoices: <b>{len([i for i in (c.get('invoices') or []) if i.get('status') not in ('paid','cancelled')])}</b>")

                # Invoices
                self._inv_tbl.setRowCount(0)
                for i, inv in enumerate(c.get('invoices', [])):
                    self._inv_tbl.insertRow(i)
                    self._inv_tbl.setItem(i, 0, tbl_item(inv.get('invoice_number', '')))
                    self._inv_tbl.setItem(i, 1, tbl_item(inv.get('receipt_number', '') or ''))
                    self._inv_tbl.setItem(i, 2, tbl_right(_fmt(inv.get('total_amount', 0), cur)))
                    self._inv_tbl.setItem(i, 3, tbl_right(_fmt(inv.get('amount_paid', 0), cur), C['ok']))
                    bal = float(inv.get('balance', 0))
                    self._inv_tbl.setItem(i, 4, tbl_right(
                        _fmt(bal, cur), C['err'] if bal > 0 else C['ok']))
                    self._inv_tbl.setItem(i, 5, tbl_center(
                        _status_label(inv.get('status', '')),
                        _status_color(inv.get('status', ''))))
                    self._inv_tbl.setItem(i, 6, tbl_item(
                        (inv.get('created_at', '') or '')[:16]))

                # Payments
                self._pay_tbl.setRowCount(0)
                for i, p in enumerate(c.get('payments', [])):
                    self._pay_tbl.insertRow(i)
                    self._pay_tbl.setItem(i, 0, tbl_item(p.get('payment_receipt', '')))
                    self._pay_tbl.setItem(i, 1, tbl_item(p.get('invoice_number', '') or ''))
                    self._pay_tbl.setItem(i, 2, tbl_right(_fmt(p.get('amount', 0), cur), C['ok']))
                    self._pay_tbl.setItem(i, 3, tbl_center(p.get('payment_method', '').title()))
                    self._pay_tbl.setItem(i, 4, tbl_right(_fmt(p.get('balance_after', 0), cur)))
                    self._pay_tbl.setItem(i, 5, tbl_item((p.get('created_at', '') or '')[:16]))
        except Exception as e:
            _log.warning(f"CustomerLedger: {e}")
