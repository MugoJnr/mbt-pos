"""
MBT POS — Accounting & Financial Management Tab
MugoByte Technologies | mugobyte.com

Dashboard, Chart of Accounts, General Ledger, Journals, Expenses,
Cash/Bank transfers, Period Close, and financial reports.
Theme-aware via ThemeManager / C tokens.
"""
import logging
import os
from datetime import date, datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, apply_themed_dialog
from desktop.utils.widgets import (
    KPICard, H2, Caption, PrimaryBtn, SecondaryBtn, DangerBtn, GhostBtn,
    SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout,
    lovable_tab_qss, wrap_table_card,
)
from desktop.utils.date_controls import make_date_edit
from desktop.utils.select_controls import Select

_log = logging.getLogger(__name__)


def _fmt(n, cur='KES'):
    try:
        return f"{cur} {float(n):,.2f}"
    except Exception:
        return f"{cur} 0.00"


def _role(user):
    return (user.get('user') or user).get('role', 'cashier')


class AccountingTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api
        self.user = user
        self.db_path = db_path
        self.config_getter = config_getter
        self._currency = 'KES'
        self._build()

    def _cfg(self):
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _build(self):
        lay, _ = page_layout(self, margins=(0, 0, 0, 0), spacing=0)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setProperty('mbtLovableTabs', True)
        self._tabs.setStyleSheet(lovable_tab_qss())

        self._dash = _DashboardPage(self)
        self._coa = _AccountsPage(self)
        self._gl = _LedgerPage(self)
        self._journals = _JournalsPage(self)
        self._expenses = _ExpensesPage(self)
        self._transfers = _TransfersPage(self)
        self._periods = _PeriodsPage(self)
        self._reports = _ReportsPage(self)

        self._tabs.addTab(self._dash, 'Dashboard')
        self._tabs.addTab(self._coa, 'Chart of Accounts')
        self._tabs.addTab(self._gl, 'General Ledger')
        self._tabs.addTab(self._journals, 'Journals')
        self._tabs.addTab(self._expenses, 'Expenses')
        self._tabs.addTab(self._transfers, 'Cash / Bank')
        self._tabs.addTab(self._periods, 'Period Close')
        self._tabs.addTab(self._reports, 'Reports')
        self._tabs.currentChanged.connect(self._on_tab)
        lay.addWidget(self._tabs)

    def _on_tab(self, idx):
        w = self._tabs.widget(idx)
        if hasattr(w, 'refresh'):
            try:
                w.refresh()
            except Exception as e:
                _log.warning('Accounting sub-refresh: %s', e)

    def on_show(self):
        try:
            self._currency = (
                self.api.accounting_currency()
                or self._cfg().get('currency_code')
                or self._cfg().get('currency_symbol')
                or 'KES'
            )
        except Exception:
            self._currency = self._cfg().get('currency_symbol', 'KES') or 'KES'
        self._dash.refresh()

    def refresh(self):
        self.on_show()


# ── Dashboard ──────────────────────────────────────────────────────────────────

class _DashboardPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(H2('Accounting Overview'))
        head.addStretch()
        ref = GhostBtn('↺ Refresh', 36)
        ref.clicked.connect(self.refresh)
        head.addWidget(ref)
        lay.addLayout(head)
        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(10)
        lay.addLayout(self._kpi_row)
        self._hint = Caption(
            'Cashiers never post journals — every POS sale, void, debt payment, '
            'and consumption auto-posts a balanced entry.')
        lay.addWidget(self._hint)
        lay.addStretch()

    def refresh(self):
        while self._kpi_row.count():
            item = self._kpi_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        cur = self.p._currency
        data = self.p.api.accounting_dashboard() or {}
        if data.get('error'):
            self._hint.setText(str(data['error']))
            return
        cards = [
            ('Month Revenue', _fmt(data.get('month_revenue'), cur), 'ok'),
            ('Month Expenses', _fmt(data.get('month_expenses'), cur), 'warn'),
            ('Net Profit', _fmt(data.get('month_net'), cur), 'gold'),
            ('Cash', _fmt(data.get('cash_balance'), cur), 'info'),
            ('M-Pesa', _fmt(data.get('mpesa_balance'), cur), 'info'),
            ('AR', _fmt(data.get('ar_balance'), cur), 'warn'),
            ('Journals Today', str(data.get('journals_today') or 0), 'ok'),
            ('Trial Balance',
             'OK' if data.get('trial_balanced') else 'CHECK',
             'ok' if data.get('trial_balanced') else 'err'),
        ]
        for title, val, tone in cards:
            self._kpi_row.addWidget(KPICard(title, val))
        self._hint.setText(
            f"Currency: {cur}  ·  Branch multi-entity & FX: schema-ready stubs (disabled)")

    def _kpi(self, title, value):
        return KPICard(title, value)


# ── Chart of Accounts ──────────────────────────────────────────────────────────

class _AccountsPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(H2('Chart of Accounts'), 1)
        add = PrimaryBtn('+ Account', 36)
        add.clicked.connect(self._add)
        bar.addWidget(add)
        ref = GhostBtn('↺', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        lay.addLayout(bar)
        self._tbl = make_table(['Code', 'Name', 'Type', 'Normal', 'System', 'Active'])
        lay.addWidget(wrap_table_card(self._tbl), 1)
        self._tbl.doubleClicked.connect(self._edit)

    def refresh(self):
        rows = self.p.api.accounting_accounts(active_only=False) or []
        self._tbl.setRowCount(0)
        for r in rows:
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, tbl_item(r.get('code')))
            self._tbl.setItem(i, 1, tbl_item(r.get('name')))
            self._tbl.setItem(i, 2, tbl_center(r.get('account_type')))
            self._tbl.setItem(i, 3, tbl_center(r.get('normal_balance')))
            self._tbl.setItem(i, 4, tbl_center('Yes' if r.get('is_system') else ''))
            self._tbl.setItem(i, 5, tbl_center('Yes' if r.get('is_active') else 'No'))

    def _add(self):
        self._dialog()

    def _edit(self):
        row = self._tbl.currentRow()
        if row < 0:
            return
        code = self._tbl.item(row, 0).text()
        name = self._tbl.item(row, 1).text()
        atype = self._tbl.item(row, 2).text()
        self._dialog({'code': code, 'name': name, 'account_type': atype})

    def _dialog(self, data=None):
        data = data or {}
        dlg = QDialog(self)
        dlg.setWindowTitle('Account')
        apply_themed_dialog(dlg)
        form = QFormLayout(dlg)
        code = QLineEdit(data.get('code') or '')
        name = QLineEdit(data.get('name') or '')
        atype = Select(items=['asset', 'liability', 'equity', 'income', 'cogs', 'expense'])
        if data.get('account_type'):
            atype.setCurrentText(data['account_type'])
        form.addRow('Code', code)
        form.addRow('Name', name)
        form.addRow('Type', atype)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec_() != QDialog.Accepted:
            return
        res = self.p.api.accounting_save_account({
            'code': code.text().strip(),
            'name': name.text().strip(),
            'account_type': atype.currentText(),
        })
        if res.get('error'):
            QMessageBox.warning(self, 'Account', res['error'])
        self.refresh()


# ── General Ledger ─────────────────────────────────────────────────────────────

class _LedgerPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(H2('General Ledger'))
        self._acct = Select(items=[])
        self._acct.setMinimumWidth(280)
        bar.addWidget(self._acct, 1)
        self._from = make_date_edit()
        self._to = make_date_edit()
        bar.addWidget(self._from)
        bar.addWidget(self._to)
        go = PrimaryBtn('Load', 36)
        go.clicked.connect(self.refresh)
        bar.addWidget(go)
        lay.addLayout(bar)
        self._bal = Caption('')
        lay.addWidget(self._bal)
        self._tbl = make_table(['Date', 'Entry', 'Description', 'Debit', 'Credit', 'Memo'])
        lay.addWidget(wrap_table_card(self._tbl), 1)

    def refresh(self):
        accounts = self.p.api.accounting_accounts() or []
        codes = [f"{a['code']} — {a['name']}" for a in accounts]
        cur = self._acct.currentText()
        self._acct.blockSignals(True)
        self._acct.clear()
        self._acct.addItems(codes)
        if cur:
            idx = self._acct.findText(cur)
            if idx >= 0:
                self._acct.setCurrentIndex(idx)
        self._acct.blockSignals(False)
        text = self._acct.currentText() or ''
        code = text.split('—')[0].strip() if text else ''
        if not code:
            return
        start = self._from.date().toString('yyyy-MM-dd')
        end = self._to.date().toString('yyyy-MM-dd')
        data = self.p.api.accounting_ledger(code, start, end) or {}
        cur = self.p._currency
        self._bal.setText(
            f"Balance: {_fmt(data.get('balance'), cur)}  ·  "
            f"Dr {_fmt(data.get('total_debit'), cur)}  Cr {_fmt(data.get('total_credit'), cur)}"
        )
        self._tbl.setRowCount(0)
        for r in data.get('lines') or []:
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, tbl_item((r.get('entry_date') or '')[:10]))
            self._tbl.setItem(i, 1, tbl_item(r.get('entry_number')))
            self._tbl.setItem(i, 2, tbl_item(r.get('description')))
            self._tbl.setItem(i, 3, tbl_right(_fmt(r.get('debit'), cur) if float(r.get('debit') or 0) else ''))
            self._tbl.setItem(i, 4, tbl_right(_fmt(r.get('credit'), cur) if float(r.get('credit') or 0) else ''))
            self._tbl.setItem(i, 5, tbl_item(r.get('memo')))


# ── Journals ───────────────────────────────────────────────────────────────────

class _JournalsPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(H2('Journal Entries'), 1)
        man = PrimaryBtn('+ Manual Journal', 36)
        man.clicked.connect(self._manual)
        bar.addWidget(man)
        rev = SecondaryBtn('Reverse Selected', 36)
        rev.clicked.connect(self._reverse)
        bar.addWidget(rev)
        ref = GhostBtn('↺', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        lay.addLayout(bar)
        self._tbl = make_table(
            ['#', 'Date', 'Entry #', 'Description', 'Source', 'Type', 'Debit', 'Credit'])
        lay.addWidget(wrap_table_card(self._tbl), 1)
        self._tbl.doubleClicked.connect(self._detail)
        self._ids = []

    def refresh(self):
        rows = self.p.api.accounting_journals() or []
        cur = self.p._currency
        self._tbl.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            self._ids.append(r.get('id'))
            self._tbl.setItem(i, 0, tbl_center(str(r.get('id'))))
            self._tbl.setItem(i, 1, tbl_item((r.get('entry_date') or '')[:10]))
            self._tbl.setItem(i, 2, tbl_item(r.get('entry_number')))
            self._tbl.setItem(i, 3, tbl_item(r.get('description')))
            self._tbl.setItem(i, 4, tbl_item(
                f"{r.get('source_module') or ''}:{r.get('source_id') or ''}"))
            self._tbl.setItem(i, 5, tbl_center(r.get('entry_type')))
            self._tbl.setItem(i, 6, tbl_right(_fmt(r.get('total_debit'), cur)))
            self._tbl.setItem(i, 7, tbl_right(_fmt(r.get('total_credit'), cur)))

    def _detail(self):
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._ids):
            return
        j = self.p.api.accounting_journal(self._ids[row]) or {}
        lines = j.get('lines') or []
        msg = '\n'.join(
            f"{ln.get('account_code')} {ln.get('account_name')}: "
            f"Dr {ln.get('debit')} Cr {ln.get('credit')}"
            for ln in lines
        )
        QMessageBox.information(self, j.get('entry_number') or 'Journal', msg or 'No lines')

    def _manual(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Manual Journal')
        dlg.resize(560, 360)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        desc = QLineEdit()
        desc.setPlaceholderText('Description')
        lay.addWidget(desc)
        form = QFormLayout()
        a1 = QLineEdit('1000')
        a2 = QLineEdit('6000')
        amt = QDoubleSpinBox()
        amt.setMaximum(1e9)
        amt.setDecimals(2)
        form.addRow('Debit account', a2)
        form.addRow('Credit account', a1)
        form.addRow('Amount', amt)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        lay.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec_() != QDialog.Accepted:
            return
        res = self.p.api.accounting_post_manual({
            'description': desc.text() or 'Manual journal',
            'lines': [
                {'account_code': a2.text().strip(), 'debit': amt.value()},
                {'account_code': a1.text().strip(), 'credit': amt.value()},
            ],
        })
        if res.get('error'):
            QMessageBox.warning(self, 'Journal', res['error'])
        else:
            try:
                from desktop.utils.audio_manager import play as _audio_play
                _audio_play('accounting_post')
            except Exception:
                pass
            QMessageBox.information(self, 'Journal', f"Posted {res.get('entry_number')}")
        self.refresh()

    def _reverse(self):
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._ids):
            return
        reason, ok = QInputDialog.getText(self, 'Reverse', 'Reason:')
        if not ok:
            return
        res = self.p.api.accounting_reverse(self._ids[row], reason)
        if res.get('error'):
            QMessageBox.warning(self, 'Reverse', res['error'])
        self.refresh()


# ── Expenses ───────────────────────────────────────────────────────────────────

class _ExpensesPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(H2('Expenses'), 1)
        add = PrimaryBtn('+ Expense', 36)
        add.clicked.connect(self._add)
        bar.addWidget(add)
        ref = GhostBtn('↺', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        lay.addLayout(bar)
        self._tbl = make_table(
            ['Number', 'Date', 'Expense Acct', 'Paid From', 'Amount', 'Description', 'Vendor'])
        lay.addWidget(wrap_table_card(self._tbl), 1)

    def refresh(self):
        rows = self.p.api.accounting_expenses() or []
        cur = self.p._currency
        self._tbl.setRowCount(0)
        for r in rows:
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, tbl_item(r.get('expense_number')))
            self._tbl.setItem(i, 1, tbl_item((r.get('expense_date') or '')[:10]))
            self._tbl.setItem(i, 2, tbl_item(r.get('account_code')))
            self._tbl.setItem(i, 3, tbl_item(r.get('pay_from_code')))
            self._tbl.setItem(i, 4, tbl_right(_fmt(r.get('amount'), cur)))
            self._tbl.setItem(i, 5, tbl_item(r.get('description')))
            self._tbl.setItem(i, 6, tbl_item(r.get('vendor_name')))

    def _add(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Record Expense')
        apply_themed_dialog(dlg)
        form = QFormLayout(dlg)
        exp = QLineEdit('6000')
        pay = QLineEdit('1000')
        amt = QDoubleSpinBox()
        amt.setMaximum(1e9)
        amt.setDecimals(2)
        desc = QLineEdit()
        vendor = QLineEdit()
        form.addRow('Expense account', exp)
        form.addRow('Pay from', pay)
        form.addRow('Amount', amt)
        form.addRow('Description', desc)
        form.addRow('Vendor', vendor)
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        if dlg.exec_() != QDialog.Accepted:
            return
        res = self.p.api.accounting_create_expense({
            'account_code': exp.text().strip(),
            'pay_from_code': pay.text().strip(),
            'amount': amt.value(),
            'description': desc.text(),
            'vendor_name': vendor.text(),
        })
        if res.get('error'):
            QMessageBox.warning(self, 'Expense', res['error'])
        self.refresh()


# ── Transfers ──────────────────────────────────────────────────────────────────

class _TransfersPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(H2('Cash / Bank Transfer'))
        form = QFormLayout()
        self._from = QLineEdit('1000')
        self._to = QLineEdit('1020')
        self._amt = QDoubleSpinBox()
        self._amt.setMaximum(1e9)
        self._amt.setDecimals(2)
        self._desc = QLineEdit()
        form.addRow('From account', self._from)
        form.addRow('To account', self._to)
        form.addRow('Amount', self._amt)
        form.addRow('Description', self._desc)
        lay.addLayout(form)
        go = PrimaryBtn('Post Transfer', 40)
        go.clicked.connect(self._post)
        lay.addWidget(go, 0, Qt.AlignLeft)
        lay.addWidget(Caption(
            'Moves value between cash/bank/mobile accounts with a balanced journal.'))
        lay.addStretch()

    def refresh(self):
        pass

    def _post(self):
        res = self.p.api.accounting_create_transfer({
            'from_code': self._from.text().strip(),
            'to_code': self._to.text().strip(),
            'amount': self._amt.value(),
            'description': self._desc.text(),
        })
        if res.get('error'):
            QMessageBox.warning(self, 'Transfer', res['error'])
        else:
            QMessageBox.information(
                self, 'Transfer', f"Posted {res.get('transfer_number')}")
            self._amt.setValue(0)


# ── Period Close ───────────────────────────────────────────────────────────────

class _PeriodsPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(H2('Accounting Periods'), 1)
        close_btn = DangerBtn('Close Selected Period', 36)
        close_btn.clicked.connect(self._close)
        bar.addWidget(close_btn)
        ref = GhostBtn('↺', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        lay.addLayout(bar)
        self._tbl = make_table(['ID', 'Name', 'Start', 'End', 'Status', 'Closed At'])
        lay.addWidget(wrap_table_card(self._tbl), 1)
        self._ids = []

    def refresh(self):
        rows = self.p.api.accounting_periods() or []
        self._tbl.setRowCount(0)
        self._ids = []
        for r in rows:
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            self._ids.append(r.get('id'))
            self._tbl.setItem(i, 0, tbl_center(str(r.get('id'))))
            self._tbl.setItem(i, 1, tbl_item(r.get('name')))
            self._tbl.setItem(i, 2, tbl_item(r.get('start_date')))
            self._tbl.setItem(i, 3, tbl_item(r.get('end_date')))
            self._tbl.setItem(i, 4, tbl_center(r.get('status')))
            self._tbl.setItem(i, 5, tbl_item((r.get('closed_at') or '')[:19]))

    def _close(self):
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._ids):
            return
        conf = QMessageBox.question(
            self, 'Close Period',
            'Close this period? Posting to closed dates will be blocked.')
        if conf != QMessageBox.Yes:
            return
        res = self.p.api.accounting_close_period(self._ids[row])
        if res.get('error'):
            QMessageBox.warning(self, 'Close Period', res['error'])
        else:
            QMessageBox.information(self, 'Close Period', 'Period closed.')
        self.refresh()


# ── Reports ────────────────────────────────────────────────────────────────────

class _ReportsPage(QWidget):
    def __init__(self, parent: AccountingTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        self._kind = Select(items=[
            'Profit & Loss', 'Balance Sheet', 'Trial Balance',
            'Cash Book', 'AR Aging', 'AP Aging',
        ])
        bar.addWidget(self._kind, 1)
        self._from = make_date_edit()
        self._to = make_date_edit()
        bar.addWidget(self._from)
        bar.addWidget(self._to)
        run = PrimaryBtn('Run', 36)
        run.clicked.connect(self.refresh)
        bar.addWidget(run)
        exp = SecondaryBtn('Export Excel', 36)
        exp.clicked.connect(self._export)
        bar.addWidget(exp)
        lay.addLayout(bar)
        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setStyleSheet(
            f"QPlainTextEdit{{background:{C['card']}; color:{C['text']}; "
            f"font-family: Consolas, monospace; font-size:12px; border-radius:8px; padding:12px;}}")
        lay.addWidget(self._out, 1)
        self._last = None

    def _dates(self):
        start = self._from.date().toString('yyyy-MM-dd')
        end = self._to.date().toString('yyyy-MM-dd')
        if not start:
            start = f'{date.today().year}-01-01'
        if not end:
            end = date.today().isoformat()
        return start, end

    def refresh(self):
        kind = self._kind.currentText()
        start, end = self._dates()
        cur = self.p._currency
        lines = [f'{kind}', f'Period: {start} → {end}', f'Currency: {cur}', '']
        data = {}
        if kind == 'Profit & Loss':
            data = self.p.api.accounting_pnl(start, end) or {}
            lines.append(f"Income: {_fmt(data.get('total_income'), cur)}")
            for r in data.get('income') or []:
                lines.append(f"  {r['code']} {r['name']}: {_fmt(r['amount'], cur)}")
            lines.append(f"COGS: {_fmt(data.get('total_cogs'), cur)}")
            for r in data.get('cogs') or []:
                lines.append(f"  {r['code']} {r['name']}: {_fmt(r['amount'], cur)}")
            lines.append(f"Gross Profit: {_fmt(data.get('gross_profit'), cur)}")
            lines.append(f"Expenses: {_fmt(data.get('total_expenses'), cur)}")
            for r in data.get('expenses') or []:
                lines.append(f"  {r['code']} {r['name']}: {_fmt(r['amount'], cur)}")
            lines.append(f"Net Profit: {_fmt(data.get('net_profit'), cur)}")
        elif kind == 'Balance Sheet':
            data = self.p.api.accounting_balance_sheet(end) or {}
            lines.append(f"Assets: {_fmt(data.get('total_assets'), cur)}")
            for r in data.get('assets') or []:
                lines.append(f"  {r['code']} {r['name']}: {_fmt(r['amount'], cur)}")
            lines.append(f"Liabilities: {_fmt(data.get('total_liabilities'), cur)}")
            for r in data.get('liabilities') or []:
                lines.append(f"  {r['code']} {r['name']}: {_fmt(r['amount'], cur)}")
            lines.append(f"Equity: {_fmt(data.get('total_equity'), cur)}")
            for r in data.get('equity') or []:
                lines.append(f"  {r['code']} {r['name']}: {_fmt(r['amount'], cur)}")
            lines.append(
                f"Balanced: {data.get('balanced')}  "
                f"(L+E {_fmt(data.get('total_liabilities_equity'), cur)})")
        elif kind == 'Trial Balance':
            data = self.p.api.accounting_trial_balance(end, start) or {}
            lines.append(
                f"Dr {_fmt(data.get('total_debit'), cur)}  "
                f"Cr {_fmt(data.get('total_credit'), cur)}  "
                f"Balanced={data.get('balanced')}")
            for r in data.get('accounts') or []:
                lines.append(
                    f"  {r['code']} {r['name']}: "
                    f"Dr {_fmt(r['debit'], cur)}  Cr {_fmt(r['credit'], cur)}")
        elif kind == 'Cash Book':
            data = self.p.api.accounting_cash_book('1000', start, end) or {}
            lines.append(f"Cash balance: {_fmt(data.get('balance'), cur)}")
            for r in data.get('lines') or []:
                lines.append(
                    f"  {(r.get('entry_date') or '')[:10]} {r.get('entry_number')} "
                    f"Dr {r.get('debit')} Cr {r.get('credit')} {r.get('description')}")
        elif kind == 'AR Aging':
            data = self.p.api.accounting_ar_aging() or {}
            b = data.get('buckets') or {}
            lines.append(f"Total AR (debts): {_fmt(data.get('total'), cur)}")
            lines.append(f"GL AR: {_fmt(data.get('gl_ar_balance'), cur)}")
            lines.append(f"Buckets: {b}")
            lines.append(data.get('note') or '')
            for c in data.get('customers') or []:
                lines.append(
                    f"  {c.get('customer_name')}: {_fmt(c.get('balance'), cur)} "
                    f"({c.get('invoices')} inv)")
        else:
            data = self.p.api.accounting_ap_aging() or {}
            lines.append(f"GL AP: {_fmt(data.get('gl_ap_balance'), cur)}")
            lines.append(data.get('note') or '')
        if data.get('error'):
            lines = [str(data['error'])]
        self._last = {'kind': kind, 'data': data, 'lines': lines, 'start': start, 'end': end}
        self._out.setPlainText('\n'.join(lines))

    def _export(self):
        if not self._last:
            self.refresh()
        try:
            from backend.report_export_service import export_workbook, SheetSpec
        except Exception:
            # Fallback: write text
            path = os.path.join(
                os.path.expanduser('~'), 'Desktop', 'MBT POS Exports',
                f"accounting_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join((self._last or {}).get('lines') or []))
            QMessageBox.information(self, 'Export', f'Saved:\n{path}')
            return
        try:
            kind = (self._last or {}).get('kind') or 'Report'
            data = (self._last or {}).get('data') or {}
            rows = []
            headers = ['Line']
            if kind == 'Trial Balance':
                headers = ['Code', 'Name', 'Debit', 'Credit']
                rows = [[a['code'], a['name'], a['debit'], a['credit']]
                        for a in data.get('accounts') or []]
            elif kind == 'Profit & Loss':
                headers = ['Section', 'Code', 'Name', 'Amount']
                for sec, key in (('Income', 'income'), ('COGS', 'cogs'),
                                 ('Expense', 'expenses')):
                    for a in data.get(key) or []:
                        rows.append([sec, a['code'], a['name'], a['amount']])
            else:
                rows = [[ln] for ln in (self._last.get('lines') or [])]
            out_dir = os.path.join(os.path.expanduser('~'), 'Desktop', 'MBT POS Exports')
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(
                out_dir, f"accounting_{kind.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            # Prefer simple openpyxl via report service helpers if available
            try:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = kind[:31]
                ws.append(headers)
                for r in rows:
                    ws.append(r)
                wb.save(path)
            except Exception as e:
                raise e
            QMessageBox.information(self, 'Export', f'Saved:\n{path}')
        except Exception as e:
            QMessageBox.warning(self, 'Export', str(e))
