"""
MBT POS ? Debt Management Tab
MugoByte Technologies | mugobyte.com

Full part-payment / credit-sale / debt-collection system:
? Customer management
? Invoice creation (credit sale, part payment)
? Debt collection with installments
? Payment receipts
? Aging report
? Customer ledger
? Export
"""
import logging
from datetime import date
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, qss_alpha, apply_themed_dialog
from desktop.utils.widgets import (
    KPICard, Card, H2, H3, Caption, PrimaryBtn, SecondaryBtn, DangerBtn,
    SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout,
    lovable_tab_qss, GhostBtn, Badge, wrap_table_card,
)
from desktop.utils.option_lists import (
    DEBT_PAYMENT_METHODS, CUSTOMER_TYPES, INVOICE_STATUSES,
)
from desktop.utils.select_controls import Select, SearchableSelect

_log = logging.getLogger(__name__)


# ?????????????????????????????????????????????????????????????????????????????
# Helpers
# ?????????????????????????????????????????????????????????????????????????????

def _fmt(n, cur='KES'):
    try:
        return f"{cur} {float(n):,.2f}"
    except Exception:
        return f"{cur} 0.00"


def _due_display(inv) -> str:
    """Human due date; fall back to sale_date + 30d when DB due_date is null."""
    due = (inv.get('due_date') or '').strip()
    if due:
        return due[:10]
    base = (inv.get('sale_date') or inv.get('created_at') or '')[:10]
    if not base:
        return '\u2014'
    try:
        d = date.fromisoformat(base)
        from datetime import timedelta
        return (d + timedelta(days=30)).isoformat()
    except Exception:
        return '\u2014'


def _cell_tip(item, text: str):
    if item is not None and text:
        item.setToolTip(str(text))
    return item


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
        'pending':   'Pending',
        'partial':   'Partial',
        'paid':      'Paid',
        'overdue':   'Overdue',
        'cancelled': 'Cancelled',
    }.get(s, s.title())


# ?????????????????????????????????????????????????????????????????????????????
# Main Tab
# ?????????????????????????????????????????????????????????????????????????????

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

        # Lovable segmented gold pill tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setProperty('mbtLovableTabs', True)
        self._tabs.setStyleSheet(lovable_tab_qss())

        self._overview_tab    = _OverviewTab(self)
        self._invoices_tab    = _InvoicesTab(self)
        self._customers_tab   = _CustomersTab(self)
        self._payments_tab    = _PaymentsTab(self)
        self._aging_tab       = _AgingTab(self)

        self._tabs.addTab(self._overview_tab,  'Overview')
        self._tabs.addTab(self._invoices_tab,  'Invoices')
        self._tabs.addTab(self._customers_tab, 'Customers')
        self._tabs.addTab(self._payments_tab,  'Payments')
        self._tabs.addTab(self._aging_tab,     'Aging Report')

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

    def _export_debt(self):
        """Export debt invoices, aging, and payments via shared formatter."""
        try:
            from backend.report_export_service import export_debt_report
            cfg = self._cfg() or {}
            shop = cfg.get('shop_name', 'My Shop')
            cur = cfg.get('currency_symbol', 'KES') or 'KES'
            user = self.user.get('user') or self.user
            who = user.get('full_name') or user.get('username') or 'admin'
            invoices = self.api.get_debt_invoices() or []
            payments = self.api.get_debt_payments() or []
            aging = self.api.get_aging_report() or {}
            summary = self.api.get_debt_summary() or {}
            path = export_debt_report(
                invoices=invoices,
                payments=payments,
                aging=aging,
                summary=summary,
                shop_name=shop,
                currency=cur,
                generated_by=who,
                filters='All open invoices - full payment history',
                period=f"As at {date.today().isoformat()}",
            )
            QMessageBox.information(
                self, 'Exported',
                f'Debt report saved:\n{path}\n\n'
                f'Sheets: Debt Invoices  - Aging  - Payments')
            try:
                import os
                os.startfile(path)
            except Exception:
                pass
        except Exception as e:
            _log.error('Debt export failed: %s', e, exc_info=True)
            QMessageBox.critical(self, 'Export Failed', str(e))


# ?????????????????????????????????????????????????????????????????????????????
# Overview sub-tab
# ?????????????????????????????????????????????????????????????????????????????

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
        exp_btn = SecondaryBtn('Export Excel', 40)
        exp_btn.setToolTip('Export invoices, aging bands, and payments to Excel')
        exp_btn.clicked.connect(self.p._export_debt)
        hrow.addWidget(exp_btn)
        col_btn = PrimaryBtn('+ Collect Payment', 40)
        col_btn.clicked.connect(lambda: self.p._invoices_tab._collect_payment_dialog())
        hrow.addWidget(col_btn)
        # Debts must originate from a completed POS sale ? no orphan create
        pos_hint = SecondaryBtn('Credit via POS', 40)
        pos_hint.setToolTip(
            'Create credit / part-payment sales on the POS tab. '
            'Debts cannot be created here without a sale.')
        pos_hint.clicked.connect(self._hint_use_pos)
        hrow.addWidget(pos_hint)
        lay.addLayout(hrow)

        # KPI row ? use em-dash placeholders (never leave literal "?")
        kr = QHBoxLayout(); kr.setSpacing(16)
        self._k_out   = KPICard('Outstanding',     '?',  'total debt',       C['err'])
        self._k_over  = KPICard('Overdue',          '?',  'past due date',    C['warn'])
        self._k_col   = KPICard("Today's Collected",'?',  'payments today',   C['ok'])
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
        odl.addWidget(H3('Overdue Accounts'))
        self._overdue_tbl = make_table(
            ['Invoice', 'Customer', 'Phone', 'Balance', 'Due Date', 'Days Overdue'],
            stretch_col=1, row_height=38)
        for ci, w in [(0, 130), (2, 110), (3, 120), (4, 100), (5, 130)]:
            self._overdue_tbl.setColumnWidth(ci, w)
        self._overdue_tbl.setMinimumHeight(180)
        odl.addWidget(self._overdue_tbl)
        lay.addWidget(od)

    def _hint_use_pos(self):
        QMessageBox.information(
            self, 'Credit Sales via POS',
            'Credit and part-payment sales are created on the POS tab.\n\n'
            '1. Add items to the cart\n'
            '2. Choose Payment Method ? Credit Sale (or Part Payment)\n'
            '3. Select or create a customer (stay on POS)\n'
            '4. Complete checkout ? debt is linked to the sale automatically\n\n'
            'Debt Management is for collecting payments and viewing history only.')

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


# ?????????????????????????????????????????????????????????????????????????????
# Invoices sub-tab
# ?????????????????????????????????????????????????????????????????????????????

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
        self._search = SearchBar('Search by customer, invoice, phone?')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)

        self._status_filter = Select()
        self._status_filter.set_items(
            [('All Statuses', '')] + [(s, s.lower()) for s in INVOICE_STATUSES])
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

        new_btn = SecondaryBtn('Credit via POS ?', 42)
        new_btn.setToolTip(
            'Debts must link to a completed POS sale. '
            'Use Credit Sale / Part Payment on the POS tab.')
        new_btn.clicked.connect(self._blocked_orphan_create)
        tb.addWidget(new_btn)

        ref_btn = SecondaryBtn('?', 42)
        ref_btn.clicked.connect(self.refresh)
        tb.addWidget(ref_btn)
        lay.addLayout(tb)

        # Table: Invoice, Customer, Sale Date, Original, Paid, Balance, Status, Due, Actions
        self._tbl = make_table(
            ['Invoice', 'Customer', 'Sale Date', 'Original', 'Paid', 'Balance',
             'Status', 'Due Date', 'Actions'],
            stretch_col=1, row_height=52)
        for ci, w in [(0, 140), (2, 130), (3, 110), (4, 110), (5, 110),
                      (6, 110), (7, 110), (8, 230)]:
            self._tbl.setColumnWidth(ci, w)
        self._tbl.cellClicked.connect(self._on_row_clicked)
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
        sf = (self._status_filter.current_value() or '').lower()
        filtered = []
        for inv in self._invoices:
            if sf and inv.get('status', '') != sf:
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

            due = inv.get('due_date', '') or ''
            due_disp = _due_display(inv)
            if status not in ('paid', 'cancelled') and due:
                try:
                    if date.fromisoformat(due[:10]) < date.today():
                        status = 'overdue'
                except Exception:
                    pass
            elif status not in ('paid', 'cancelled') and due_disp not in ('', '\u2014', '?'):
                try:
                    if date.fromisoformat(due_disp) < date.today():
                        status = 'overdue'
                except Exception:
                    pass

            sale_date = (inv.get('sale_date') or inv.get('created_at') or '')[:16] or '\u2014'
            inv_num = inv.get('invoice_number', '') or ''
            cust_name = inv.get('customer_name', '') or ''
            self._tbl.setItem(i, 0, _cell_tip(tbl_item(inv_num), inv_num))
            self._tbl.setItem(i, 1, _cell_tip(tbl_item(cust_name), cust_name))
            self._tbl.setItem(i, 2, tbl_center(sale_date))
            self._tbl.setItem(i, 3, tbl_right(_fmt(inv.get('total_amount', 0), cur)))
            self._tbl.setItem(i, 4, tbl_right(_fmt(inv.get('amount_paid', 0), cur), C['ok']))
            self._tbl.setItem(i, 5, tbl_right(_fmt(bal, cur),
                                              C['err'] if bal > 0 else C['ok']))
            status_txt = _status_label(status)
            s_item = tbl_center(status_txt, _status_color(status))
            _cell_tip(s_item, status_txt)
            self._tbl.setItem(i, 6, s_item)
            due_item = tbl_center(due_disp)
            _cell_tip(due_item, due_disp if due_disp not in ('\u2014', '?') else 'No due date set')
            self._tbl.setItem(i, 7, due_item)
            # Store invoice id on first column for row click
            self._tbl.item(i, 0).setData(Qt.UserRole, inv.get('id'))
            self._tbl.item(i, 0).setData(Qt.UserRole + 1, inv.get('sale_id'))
            self._tbl.item(i, 0).setData(Qt.UserRole + 2, inv.get('receipt_number'))

            # Actions
            cell = QWidget(); cell.setStyleSheet('background:transparent;')
            cl   = QHBoxLayout(cell); cl.setContentsMargins(4, 2, 4, 2); cl.setSpacing(6)

            if status not in ('paid', 'cancelled'):
                pay_btn = QPushButton('Collect')
                pay_btn.setMinimumHeight(34)
                pay_btn.setMinimumWidth(78)
                pay_btn.setCursor(Qt.PointingHandCursor)
                pay_btn.setToolTip('Collect payment on this invoice')
                pay_btn.setStyleSheet(
                    f"QPushButton{{background:{qss_alpha(C['ok'], 0.13)};color:{C['ok']};"
                    f"border:1px solid {qss_alpha(C['ok'], 0.40)};border-radius:6px;"
                    f"font-size:12px;font-weight:700;padding:4px 12px;}}"
                    f"QPushButton:hover{{background:{C['ok']};color:#fff;}}")
                pay_btn.clicked.connect(
                    lambda _, inv_id=inv['id'], inv_num=inv.get('invoice_number',''),
                    cname=inv.get('customer_name',''), b=bal:
                    self._collect_payment_dialog(inv_id, inv_num, cname, b))
                cl.addWidget(pay_btn)

            view_btn = QPushButton('History')
            view_btn.setMinimumHeight(34)
            view_btn.setMinimumWidth(78)
            view_btn.setCursor(Qt.PointingHandCursor)
            view_btn.setToolTip('View payment history')
            view_btn.setStyleSheet(
                f"QPushButton{{background:{qss_alpha(C['info'], 0.13)};color:{C['info']};"
                f"border:1px solid {qss_alpha(C['info'], 0.40)};border-radius:6px;"
                f"font-size:12px;font-weight:700;padding:4px 12px;}}"
                f"QPushButton:hover{{background:{C['info']};color:#fff;}}")
            view_btn.clicked.connect(
                lambda _, inv_id=inv['id']: self._view_history(inv_id))
            cl.addWidget(view_btn)

            cl.addStretch()
            self._tbl.setCellWidget(i, 8, cell)

        n_out = sum(1 for inv in invs if inv.get('status') not in ('paid', 'cancelled'))
        self._stats.setText(
            f"  {len(invs)} invoices  ?  "
            f"{n_out} outstanding  ?  "
            f"Total balance: {_fmt(total_balance, cur)}"
            f"  ?  Click a row to open the original sale")

    def _blocked_orphan_create(self):
        QMessageBox.information(
            self, 'No Orphan Debts',
            'Debts must be created from a completed POS credit / part-payment sale.\n\n'
            'Go to POS ? choose Credit Sale or Part Payment ? complete checkout.\n'
            'The debt is linked automatically to the sale invoice.')

    def _on_row_clicked(self, row, _col):
        item = self._tbl.item(row, 0)
        if not item:
            return
        inv_id = item.data(Qt.UserRole)
        sale_id = item.data(Qt.UserRole + 1)
        receipt = item.data(Qt.UserRole + 2) or ''
        if sale_id:
            dlg = _SaleDebtDetailDialog(self.p, sale_id=sale_id, invoice_id=inv_id)
            dlg.exec_()
        elif inv_id:
            self._view_history(inv_id)
        else:
            QMessageBox.warning(
                self, 'No Linked Sale',
                f'This debt has no linked sale ({receipt or "no receipt"}). '
                'Orphan debts cannot be paid ? use POS for new credit sales.')

    def _new_invoice_dialog(self):
        # Legacy entry point ? blocked to prevent orphan debts
        self._blocked_orphan_create()

    def _collect_payment_dialog(self, invoice_id=None, inv_num='',
                                customer_name='', balance=0.0):
        dlg = _CollectPaymentDialog(self.p, self,
                                    invoice_id=invoice_id,
                                    invoice_number=inv_num,
                                    customer_name=customer_name,
                                    current_balance=balance)
        if dlg.exec_() == QDialog.Accepted:
            from desktop.utils.state_reset import StateResetManager
            StateResetManager.after_debt_payment(self.p)

    def _view_history(self, invoice_id):
        dlg = _InvoiceHistoryDialog(self.p, invoice_id)
        dlg.exec_()


# ?????????????????????????????????????????????????????????????????????????????
# Customers sub-tab
# ?????????????????????????????????????????????????????????????????????????????

class _CustomersTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._customers = []
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(24, 20, 24, 20), spacing=16)

        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search customers?')
        self._search.textChanged.connect(self._filter)
        tb.addWidget(self._search, 1)
        add_btn = PrimaryBtn('+ New Customer', 42)
        add_btn.clicked.connect(self._add_customer)
        tb.addWidget(add_btn)
        ref_btn = SecondaryBtn('?', 42)
        ref_btn.clicked.connect(self.refresh)
        tb.addWidget(ref_btn)
        lay.addLayout(tb)

        self._tbl = make_table(
            ['Name', 'Phone', 'Email', 'Outstanding', 'Open Inv.', 'Actions'],
            stretch_col=0, row_height=52)
        for ci, w in [(1, 120), (2, 160), (3, 130), (4, 90), (5, 220)]:
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
            cl   = QHBoxLayout(cell); cl.setContentsMargins(4, 2, 4, 2); cl.setSpacing(6)

            ledger_btn = QPushButton('Ledger')
            ledger_btn.setMinimumHeight(34)
            ledger_btn.setMinimumWidth(78)
            ledger_btn.setCursor(Qt.PointingHandCursor)
            ledger_btn.setToolTip('Open customer ledger')
            ledger_btn.setStyleSheet(
                f"QPushButton{{background:{qss_alpha(C['info'], 0.13)};color:{C['info']};"
                f"border:1px solid {qss_alpha(C['info'], 0.40)};border-radius:6px;"
                f"font-size:12px;font-weight:700;padding:4px 12px;}}"
                f"QPushButton:hover{{background:{C['info']};color:#fff;}}")
            ledger_btn.clicked.connect(
                lambda _, cid=c['id']: self._open_ledger(cid))
            cl.addWidget(ledger_btn)

            edit_btn = QPushButton('Edit')
            edit_btn.setMinimumHeight(34)
            edit_btn.setMinimumWidth(64)
            edit_btn.setCursor(Qt.PointingHandCursor)
            edit_btn.setToolTip('Edit customer')
            edit_btn.setStyleSheet(
                f"QPushButton{{background:{C['card2']};color:{C['text']};"
                f"border:1px solid {C['border2']};border-radius:6px;"
                f"font-size:12px;font-weight:700;padding:4px 12px;}}"
                f"QPushButton:hover{{background:{C['hover']};color:{C['gold']};}}")
            edit_btn.clicked.connect(
                lambda _, cid=c['id']: self._edit_customer(cid))
            cl.addWidget(edit_btn)

            cl.addStretch()
            self._tbl.setCellWidget(i, 5, cell)

    def _add_customer(self):
        dlg = _CustomerDialog(self.p, self)
        if dlg.exec_() == QDialog.Accepted:
            from desktop.utils.state_reset import StateResetManager
            StateResetManager.clear_search(getattr(self, '_search', None))
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


# ?????????????????????????????????????????????????????????????????????????????
# Payments sub-tab
# ?????????????????????????????????????????????????????????????????????????????

class _PaymentsTab(QWidget):
    def __init__(self, parent_tab: DebtTab):
        super().__init__()
        self.p = parent_tab
        self._build()

    def _build(self):
        lay, _ = page_layout(self, margins=(24, 20, 24, 20), spacing=16)

        tb = QHBoxLayout(); tb.setSpacing(10)
        self._search = SearchBar('Search by receipt, customer?')
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

        ref_btn = SecondaryBtn('?', 42)
        ref_btn.clicked.connect(self.refresh)
        tb.addWidget(ref_btn)
        lay.addLayout(tb)

        self._tbl = make_table(
            ['Payment Receipt', 'Invoice #', 'Customer', 'Amount', 'Method',
             'Balance After', 'Cashier', 'Date / Time'],
            stretch_col=2, row_height=44)
        for ci, w in [(0, 170), (1, 160), (3, 120), (4, 90), (5, 120), (6, 110), (7, 160)]:
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
            receipt = p.get('payment_receipt', '') or ''
            inv_n = p.get('invoice_number', '') or ''
            cust = p.get('customer_name', '') or ''
            when = (p.get('created_at', '') or '')[:19]
            self._tbl.setItem(i, 0, _cell_tip(tbl_item(receipt), receipt))
            self._tbl.setItem(i, 1, _cell_tip(tbl_item(inv_n), inv_n))
            self._tbl.setItem(i, 2, _cell_tip(tbl_item(cust), cust))
            self._tbl.setItem(i, 3, tbl_right(_fmt(amt, cur), C['ok']))
            self._tbl.setItem(i, 4, tbl_center(p.get('payment_method', 'cash').title()))
            self._tbl.setItem(i, 5, tbl_right(_fmt(p.get('balance_after', 0), cur)))
            self._tbl.setItem(i, 6, tbl_item(p.get('cashier_name', '') or ''))
            self._tbl.setItem(i, 7, _cell_tip(tbl_item(when), when))
        self._stats.setText(
            f"  {len(payments)} payments  ?  Total collected: {_fmt(total, cur)}")


# ?????????????????????????????????????????????????????????????????????????????
# Aging Report sub-tab
# ?????????????????????????????????????????????????????????????????????????????

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
        self._b_cur  = KPICard('Current (Not Due)',  '?', 'amount',  C['ok'])
        self._b_30   = KPICard('1?30 Days Overdue',  '?', 'amount',  C['warn'])
        self._b_60   = KPICard('31?60 Days Overdue', '?', 'amount',  C['warn'])
        self._b_90   = KPICard('61?90 Days Overdue', '?', 'amount',  C['err'])
        self._b_over = KPICard('Over 90 Days',       '?', 'amount',  C['err'])
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

        ref_btn = SecondaryBtn('?  Refresh', 40)
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
                self._tbl.setItem(i, 5, tbl_center(_due_display(inv)))
                color = C['err'] if delta > 30 else (C['warn'] if delta > 0 else C['ok'])
                self._tbl.setItem(i, 6, tbl_center(
                    f"{delta}d overdue" if delta > 0 else 'On time', color))
        except Exception as e:
            _log.warning(f"Aging table: {e}")


# ?????????????????????????????????????????????????????????????????????????????
# Dialogs
# ?????????????????????????????????????????????????????????????????????????????

class _CustomerDialog(QDialog):
    def __init__(self, parent_tab: DebtTab, parent_widget, customer=None):
        super().__init__(parent_widget)
        self.p      = parent_tab
        self._cust  = customer
        self.setWindowTitle('Edit Customer' if customer else 'New Customer')
        self.setMinimumWidth(460)
        apply_themed_dialog(self)
        self._build()
        from desktop.utils.state_reset import StateResetManager
        if not customer:
            StateResetManager.clear_modal_on_close(
                self, wipe=lambda: StateResetManager.reset_customer_form(self))
        else:
            StateResetManager.clear_modal_on_close(self)

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
        self.phone = fld('Phone (optional)  e.g. 0712345678')
        self.email = fld('customer@email.com')
        self.cust_type = Select(items=list(CUSTOMER_TYPES))
        self.cust_type.setMinimumHeight(40)
        self.addr  = fld('Physical address')
        self.nid   = fld('National ID')
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0, 9999999); self.limit.setDecimals(2)
        self.limit.setMinimumHeight(40)
        self.notes = QLineEdit(); self.notes.setMinimumHeight(40)

        if self._cust:
            self.name.setText(self._cust.get('name', ''))
            self.phone.setText(self._cust.get('phone', '') or '')
            self.email.setText(self._cust.get('email', '') or '')
            self.addr.setText(self._cust.get('address', '') or '')
            self.nid.setText(self._cust.get('national_id', '') or '')
            self.limit.setValue(float(self._cust.get('credit_limit', 0) or 0))
            self.notes.setText(self._cust.get('notes', '') or '')
            ctype = self._cust.get('customer_type') or self._cust.get('type') or 'Retail'
            self.cust_type.set_value(ctype)
        lay.addRow(lbl('Name *'), self.name)
        lay.addRow(lbl('Phone'), self.phone)
        lay.addRow(lbl('Email'), self.email)
        lay.addRow(lbl('Customer Type'), self.cust_type)
        lay.addRow(lbl('Address'), self.addr)
        lay.addRow(lbl('National ID'), self.nid)
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
        phone = self.phone.text().strip()
        from desktop.utils.auto_fill import AutoFillService, phone_format_ok
        if phone and not phone_format_ok(phone):
            QMessageBox.warning(
                self, 'Invalid Phone',
                'Enter a valid phone number (e.g. 0712345678) or leave it blank.')
            return
        data = {
            'name':         self.name.text().strip(),
            'phone':        phone,
            'email':        self.email.text().strip(),
            'address':      self.addr.text().strip(),
            'national_id':  self.nid.text().strip(),
            'credit_limit': self.limit.value(),
            'notes':        self.notes.text().strip(),
            'customer_type': self.cust_type.current_label(),
        }
        try:
            if self._cust:
                res = self.p.api.update_customer(self._cust['id'], data)
            else:
                if phone:
                    existing = AutoFillService.prompt_use_existing_customer(
                        self, self.p.api, phone)
                    if existing == -1:
                        return
                    if existing is not None:
                        self.accept()
                        return
                res = self.p.api.create_customer(data)
            if res and res.get('success'):
                self.accept()
            else:
                QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Failed.'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))


class _NewInvoiceDialog(QDialog):
    """
    Hard-disabled orphan create path.
    Debts are created only from POS Credit Sale / Part Payment checkout.
    """

    def __init__(self, parent_tab: DebtTab, parent_widget,
                 prefill_total=0.0, prefill_paid=0.0,
                 prefill_sale_id=None, prefill_receipt=''):
        super().__init__(parent_widget)
        self.p = parent_tab
        self.setWindowTitle('Credit Sales via POS')
        self.setMinimumWidth(480)
        apply_themed_dialog(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(H2('Use POS for Credit Sales'))
        msg = QLabel(
            'Manual Create Invoice / Credit Sale / Part Payment from Debt '
            'Management is disabled.\n\n'
            'Debts must come from a completed POS sale:\n'
            '1. Go to the POS tab\n'
            '2. Add items and choose Credit Sale or Part Payment\n'
            '3. Select a customer and complete checkout\n\n'
            'Debt Management is for collecting payments and viewing history only.')
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"color:{C['text']};font-size:14px;background:transparent;")
        lay.addWidget(msg)
        close = PrimaryBtn('OK', 42)
        close.clicked.connect(self.reject)
        lay.addWidget(close)

    def _save(self):
        self.reject()


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
        apply_themed_dialog(self)
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

            self._balance_info = QLabel('?')
            self._balance_info.setStyleSheet(
                f"color:{C['err']};font-size:16px;font-weight:800;background:transparent;")
            lay.addRow(lbl('Outstanding'), self._balance_info)

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 9999999); self.amount.setDecimals(2)
        self.amount.setMinimumHeight(42); self.amount.setPrefix(f'{cur} ')
        if self._invoice_id:
            self.amount.setValue(self._current_balance)
        lay.addRow(lbl('Payment Amount *'), self.amount)

        self.method = Select(items=list(DEBT_PAYMENT_METHODS))
        self.method.setMinimumHeight(40)
        lay.addRow(lbl('Payment Method'), self.method)

        self.reference = QLineEdit()
        self.reference.setMinimumHeight(40)
        self.reference.setPlaceholderText('M-Pesa code / cheque # / bank ref?')
        lay.addRow(lbl('Reference'), self.reference)

        self.notes = QLineEdit()
        self.notes.setMinimumHeight(40)
        self.notes.setPlaceholderText('Optional notes?')
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
                label = (f"{inv.get('invoice_number','')}  ?  "
                         f"{inv.get('customer_name','')}  ?  "
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
                self.notes.text().strip(),
                payment_reference=(self.reference.text().strip()
                                   if hasattr(self, 'reference') else ''),
            )
            if res and res.get('success'):
                cur = self.p._currency
                bal_after = res.get('balance_after', 0)
                receipt   = res.get('payment_receipt', '')
                status    = res.get('status', '')
                msg = (f"Payment Receipt: {receipt}\n"
                       f"Amount Paid: {_fmt(amt, cur)}\n"
                       f"Balance After: {_fmt(bal_after, cur)}\n\n"
                       f"{'? PAID IN FULL' if status == 'paid' else f'Remaining: {_fmt(bal_after, cur)}'}")
                QMessageBox.information(self, 'Payment Recorded ?', msg)
                try:
                    from desktop.utils.state_reset import StateResetManager
                    StateResetManager.reset_debt_payment(self)
                except Exception:
                    pass
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
        apply_themed_dialog(self)
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
            ['Date', 'Amount', 'Method', 'Reference', 'Received By', 'Balance After'],
            stretch_col=3, row_height=38)
        for ci, w in [(0, 140), (1, 110), (2, 90), (4, 110), (5, 120)]:
            self._tbl.setColumnWidth(ci, w)
        lay.addWidget(self._tbl)
        close = SecondaryBtn('Close', 40); close.clicked.connect(self.close)
        lay.addWidget(close)

    def _load(self):
        cur = self.p._currency
        try:
            payments = self.p.api.get_debt_payments(invoice_id=self.invoice_id) or []
            inv = {}
            if hasattr(self.p.api, 'get_debt_invoice'):
                inv = self.p.api.get_debt_invoice(self.invoice_id) or {}
            if not inv:
                inv_list = self.p.api.get_debt_invoices() or []
                inv = next((i for i in inv_list if i['id'] == self.invoice_id), None) or {}
            if inv:
                self._info.setText(
                    f"Invoice: <b>{inv.get('invoice_number','')}</b>    "
                    f"Receipt: <b>{inv.get('receipt_number','') or '?'}</b>    "
                    f"Customer: <b>{inv.get('customer_name','')}</b>    "
                    f"Original: <b>{_fmt(inv.get('total_amount',0), cur)}</b>    "
                    f"Paid: <b>{_fmt(inv.get('amount_paid',0), cur)}</b>    "
                    f"Balance: <b style='color:{C['err']};'>{_fmt(inv.get('balance',0), cur)}</b>    "
                    f"Status: <b>{_status_label(inv.get('status',''))}</b>")
            self._tbl.setRowCount(0)
            for i, p in enumerate(payments):
                self._tbl.insertRow(i)
                self._tbl.setItem(i, 0, tbl_item((p.get('created_at', '') or '')[:16]))
                self._tbl.setItem(i, 1, tbl_right(_fmt(p.get('amount', 0), cur), C['ok']))
                self._tbl.setItem(i, 2, tbl_center((p.get('payment_method') or '').title()))
                self._tbl.setItem(i, 3, tbl_item(p.get('payment_reference') or p.get('payment_receipt') or '?'))
                self._tbl.setItem(i, 4, tbl_item(p.get('cashier_name', '') or ''))
                self._tbl.setItem(i, 5, tbl_right(_fmt(p.get('balance_after', 0), cur)))
        except Exception as e:
            _log.warning(f"InvoiceHistory: {e}")


class _CustomerLedgerDialog(QDialog):
    def __init__(self, parent_tab: DebtTab, customer_id: int):
        super().__init__()
        self.p   = parent_tab
        self.cid = customer_id
        self.setWindowTitle('Customer Ledger')
        self.setMinimumSize(800, 560)
        apply_themed_dialog(self)
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
                    f"?? {c.get('phone','') or '?'}   "
                    f"? {c.get('email','') or '?'}<br>"
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

class _SaleDebtDetailDialog(QDialog):
    """Sale details for credit: method, customer, original, paid, outstanding + debt history."""

    def __init__(self, parent_tab: DebtTab, sale_id=None, invoice_id=None):
        super().__init__()
        self.p = parent_tab
        self.sale_id = sale_id
        self.invoice_id = invoice_id
        self.setWindowTitle("Sale / Debt Details")
        self.setMinimumSize(640, 420)
        apply_themed_dialog(self)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)
        lay.addWidget(H2("Credit Sale Details"))
        self._info = QLabel()
        self._info.setWordWrap(True)
        self._info.setTextFormat(Qt.RichText)
        self._info.setStyleSheet(
            f"color:{C['text']};font-size:13px;background:{C['card']};"
            f"border:1px solid {C['border']};border-radius:8px;padding:14px;")
        lay.addWidget(self._info)
        br = QHBoxLayout()
        hist = PrimaryBtn("View Debt History", 42)
        hist.clicked.connect(self._open_history)
        close = SecondaryBtn("Close", 42)
        close.clicked.connect(self.close)
        br.addWidget(hist, 1)
        br.addWidget(close, 1)
        lay.addLayout(br)

    def _load(self):
        cur = self.p._currency
        sale = {}
        try:
            if self.sale_id:
                sale = self.p.api.get_sale(int(self.sale_id)) or {}
        except Exception as e:
            _log.warning(f"SaleDebtDetail: {e}")
        debt = sale.get("debt") or {}
        if not debt and self.invoice_id:
            try:
                debt = self.p.api.get_debt_invoice(int(self.invoice_id)) or {}
            except Exception:
                debt = {}
        if debt and not self.invoice_id:
            self.invoice_id = debt.get("id")
        method = (sale.get("payment_method") or "credit").replace("_", " ").title()
        cust = sale.get("customer_name") or debt.get("customer_name") or "?"
        original = float(sale.get("debt_original") or debt.get("total_amount") or sale.get("total") or 0)
        paid = float(sale.get("debt_paid") or debt.get("amount_paid") or 0)
        bal = float(sale.get("debt_outstanding") or debt.get("balance") or 0)
        rn = sale.get("receipt_number") or debt.get("receipt_number") or "?"
        inv = debt.get("invoice_number") or sale.get("debt_invoice_number") or "?"
        status = debt.get("status") or sale.get("debt_status") or sale.get("status") or "?"
        self._info.setText(
            f"<b>Receipt:</b> {rn}<br>"
            f"<b>Debt Invoice:</b> {inv}<br>"
            f"<b>Payment Method:</b> {method}<br>"
            f"<b>Customer:</b> {cust}<br>"
            f"<b>Sale Date:</b> {(sale.get('created_at') or debt.get('sale_date') or '')[:16] or '?'}<br>"
            f"<b>Original:</b> {_fmt(original, cur)} &nbsp; "
            f"<b>Paid:</b> {_fmt(paid, cur)} &nbsp; "
            f"<b style='color:{C['err']};'>Outstanding:</b> {_fmt(bal, cur)}<br>"
            f"<b>Status:</b> {_status_label(status)}"
        )

    def _open_history(self):
        if not self.invoice_id:
            QMessageBox.information(self, "No Debt", "No linked debt invoice for this sale.")
            return
        dlg = _InvoiceHistoryDialog(self.p, int(self.invoice_id))
        dlg.exec_()
