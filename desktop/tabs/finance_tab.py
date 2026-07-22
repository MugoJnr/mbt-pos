"""
MBT POS — Finance module (shop-owner first, accountant-ready)

Primary nav (simple):
  Overview · Money · Expenses · Customer Credit · Financial Reports
Advanced (collapsed):
  Chart of Accounts · General Ledger · Journal Entries · Trial Balance ·
  Balance Sheet · Cash Flow · Period Close · Financial Settings

Preserves all accounting_engine / API capabilities behind progressive disclosure.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, apply_themed_dialog, qss_alpha
from desktop.utils.widgets import (
    KPICard, H2, H3, Caption, Body, PrimaryBtn, SecondaryBtn, DangerBtn, GhostBtn,
    SearchBar, make_table, tbl_item, tbl_right, tbl_center, page_layout,
    lovable_tab_qss, wrap_table_card, Card, page_intro, Badge,
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


def _is_advanced_role(user) -> bool:
    """Full Advanced Accounting: accountant / admin only (not cashier or manager)."""
    return _role(user) in ('admin', 'superadmin', 'accountant')


def _can_see_reports(user) -> bool:
    """Financial Reports: managers and above (cashiers stay on day-to-day money pages)."""
    return _role(user) in ('admin', 'superadmin', 'manager', 'accountant')


# ═══════════════════════════════════════════════════════════════════════════════
# Finance shell
# ═══════════════════════════════════════════════════════════════════════════════

class FinanceTab(QWidget):
    """Primary Finance experience — replaces the old Accounting tab UI."""

    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api
        self.user = user
        self.db_path = db_path
        self.config_getter = config_getter
        self._currency = 'KES'
        self._nav_btns = {}
        self._advanced_open = False
        self._build()

    def _cfg(self):
        try:
            return self.config_getter() or {}
        except Exception:
            return {}

    def _build(self):
        root, _ = page_layout(self, margins=(0, 0, 0, 0), spacing=0)
        split = QHBoxLayout()
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        # ── Left nav ─────────────────────────────────────────────────────────
        nav = QWidget()
        nav.setObjectName('financeNav')
        nav.setFixedWidth(220)
        nav.setAttribute(Qt.WA_StyledBackground, True)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(12, 16, 12, 16)
        nl.setSpacing(4)

        title = QLabel('Finance')
        title.setStyleSheet(
            f"color:{C['text']}; font-size:18px; font-weight:800; background:transparent;")
        nl.addWidget(title)
        sub = Caption('Money in, money out, business health')
        sub.setWordWrap(True)
        nl.addWidget(sub)
        nl.addSpacing(10)

        primary = [
            ('overview', 'Overview'),
            ('money', 'Money'),
            ('expenses', 'Expenses'),
            ('credit', 'Customer Credit'),
        ]
        if _can_see_reports(self.user):
            primary.append(('reports', 'Financial Reports'))
        for key, label in primary:
            btn = self._mk_nav(key, label)
            nl.addWidget(btn)

        self._adv_toggle = None
        self._adv_box = None
        self._show_advanced = _is_advanced_role(self.user)
        if self._show_advanced:
            nl.addSpacing(12)
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background:{C['border']}; border:none;")
            nl.addWidget(line)
            nl.addSpacing(8)

            self._adv_toggle = QPushButton('▸  Advanced Accounting')
            self._adv_toggle.setCursor(Qt.PointingHandCursor)
            self._adv_toggle.setStyleSheet(self._nav_style(False, muted=True))
            self._adv_toggle.clicked.connect(self._toggle_advanced)
            nl.addWidget(self._adv_toggle)

            self._adv_box = QWidget()
            self._adv_box.hide()
            al = QVBoxLayout(self._adv_box)
            al.setContentsMargins(8, 0, 0, 0)
            al.setSpacing(2)
            advanced = [
                ('coa', 'Chart of Accounts'),
                ('ledger', 'General Ledger'),
                ('journals', 'Journal Entries'),
                ('trial', 'Trial Balance'),
                ('balance', 'Balance Sheet'),
                ('cashflow', 'Cash Flow'),
                ('periods', 'Period Close'),
                ('fin_settings', 'Financial Settings'),
            ]
            for key, label in advanced:
                btn = self._mk_nav(key, label, indent=True)
                al.addWidget(btn)
            nl.addWidget(self._adv_box)

        nl.addStretch(1)

        tip = Caption(
            'Sales post automatically — you rarely need Advanced.'
            if self._show_advanced else
            'Track money in, money out, and customer credit here.'
        )
        tip.setWordWrap(True)
        nl.addWidget(tip)

        # ── Pages ────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._pages = {}
        self._pages['overview'] = _OverviewPage(self)
        self._pages['money'] = _MoneyPage(self)
        self._pages['expenses'] = _ExpensesPage(self)
        self._pages['credit'] = _CreditPage(self)
        if _can_see_reports(self.user):
            self._pages['reports'] = _ReportsPage(self)
        if self._show_advanced:
            self._pages['coa'] = _AccountsPage(self)
            self._pages['ledger'] = _LedgerPage(self)
            self._pages['journals'] = _JournalsPage(self)
            self._pages['trial'] = _StatementPage(
                self, 'Trial Balance',
                'Do debits equal credits? Your books should balance.')
            self._pages['balance'] = _StatementPage(
                self, 'Balance Sheet',
                'What you own, what you owe, and equity — as of a date.')
            self._pages['cashflow'] = _CashFlowPage(self)
            self._pages['periods'] = _PeriodsPage(self)
            self._pages['fin_settings'] = _FinanceSettingsPage(self)

        for key, page in self._pages.items():
            self._stack.addWidget(page)

        split.addWidget(nav)
        split.addWidget(self._stack, 1)
        root.addLayout(split)

        self._paint_nav()
        self._goto('overview')

    def _mk_nav(self, key: str, label: str, indent=False) -> QPushButton:
        btn = QPushButton(('    ' if indent else '') + label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        btn.setProperty('financeKey', key)
        btn.clicked.connect(lambda _=False, k=key: self._goto(k))
        self._nav_btns[key] = btn
        return btn

    def _nav_style(self, active: bool, muted=False) -> str:
        if active:
            return (
                f"QPushButton{{text-align:left; padding:10px 12px; border:none; "
                f"border-radius:8px; background:{qss_alpha(C['gold'], 0.18)}; "
                f"color:{C['gold']}; font-weight:700; font-size:13px;}}"
            )
        color = C['muted'] if muted else C['text2']
        return (
            f"QPushButton{{text-align:left; padding:10px 12px; border:none; "
            f"border-radius:8px; background:transparent; color:{color}; "
            f"font-weight:600; font-size:13px;}}"
            f"QPushButton:hover{{background:{C['hover']}; color:{C['text']};}}"
        )

    def _paint_nav(self):
        self.setStyleSheet(
            f"QWidget#financeNav{{background:{C['sidebar'] if 'sidebar' in C else C['card2']}; "
            f"border-right:1px solid {C['border']};}}"
        )
        for key, btn in self._nav_btns.items():
            btn.setStyleSheet(self._nav_style(btn.isChecked()))
        if self._adv_toggle is not None:
            self._adv_toggle.setStyleSheet(self._nav_style(False, muted=True))
            self._adv_toggle.setText(
                ('▾  Advanced Accounting' if self._advanced_open else '▸  Advanced Accounting')
            )

    def _toggle_advanced(self):
        if self._adv_box is None:
            return
        self._advanced_open = not self._advanced_open
        self._adv_box.setVisible(self._advanced_open)
        self._paint_nav()

    def _goto(self, key: str):
        if key not in self._pages:
            return
        advanced_keys = {
            'coa', 'ledger', 'journals', 'trial', 'balance',
            'cashflow', 'periods', 'fin_settings',
        }
        if key in advanced_keys and not self._show_advanced:
            return
        if (key in advanced_keys and self._adv_box is not None
                and not self._advanced_open):
            self._advanced_open = True
            self._adv_box.show()
        for k, btn in self._nav_btns.items():
            btn.setChecked(k == key)
        self._paint_nav()
        page = self._pages[key]
        self._stack.setCurrentWidget(page)
        if hasattr(page, 'refresh'):
            try:
                page.refresh()
            except Exception as e:
                _log.warning('Finance page refresh %s: %s', key, e)

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
        self._paint_nav()
        cur = self._stack.currentWidget()
        if hasattr(cur, 'refresh'):
            cur.refresh()

    def refresh(self):
        self.on_show()

    def apply_theme(self, is_light=None):
        self._paint_nav()
        cur = self._stack.currentWidget()
        if hasattr(cur, 'refresh'):
            try:
                cur.refresh()
            except Exception:
                pass


# Back-compat for main.py / tests
AccountingTab = FinanceTab


# ═══════════════════════════════════════════════════════════════════════════════
# Overview — CEO dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class _OverviewPage(QWidget):
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        intro, _ = page_intro(
            'Finance Overview',
            'How much you made, where the money is, and whether the business is healthy.',
        )
        lay.addLayout(intro)

        self._kpi1 = QHBoxLayout(); self._kpi1.setSpacing(12)
        self._kpi2 = QHBoxLayout(); self._kpi2.setSpacing(12)
        lay.addLayout(self._kpi1)
        lay.addLayout(self._kpi2)

        # Business health
        health = Card()
        hl = health.layout_v((18, 16, 18, 16), 10)
        hl.addWidget(H2('Business Health'))
        self._score_lbl = QLabel('—')
        self._score_lbl.setStyleSheet(
            f"color:{C['gold']}; font-size:36px; font-weight:800; background:transparent;")
        self._health_grid = QGridLayout()
        self._health_grid.setHorizontalSpacing(16)
        self._health_grid.setVerticalSpacing(8)
        row = QHBoxLayout()
        row.addWidget(self._score_lbl)
        row.addSpacing(16)
        self._score_sub = Caption('Based on your live sales, cash, profit, and credit data.')
        self._score_sub.setWordWrap(True)
        row.addWidget(self._score_sub, 1)
        hl.addLayout(row)
        hl.addLayout(self._health_grid)
        self._insight = Body('', muted=True)
        self._insight.setWordWrap(True)
        hl.addWidget(self._insight)
        lay.addWidget(health)

        # Quick actions
        actions = QHBoxLayout()
        actions.setSpacing(10)
        a1 = PrimaryBtn('+ Record Expense', 40)
        a1.clicked.connect(lambda: self.p._goto('expenses'))
        a2 = SecondaryBtn('Collect Credit', 40)
        a2.clicked.connect(lambda: self.p._goto('credit'))
        a3 = SecondaryBtn('View Reports', 40)
        a3.clicked.connect(lambda: self.p._goto('reports'))
        a4 = GhostBtn('↺ Refresh', 40)
        a4.clicked.connect(self.refresh)
        actions.addWidget(a1)
        actions.addWidget(a2)
        actions.addWidget(a3)
        actions.addStretch(1)
        actions.addWidget(a4)
        lay.addLayout(actions)
        lay.addStretch(1)

    def _clear_row(self, row: QHBoxLayout):
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self._clear_row(self._kpi1)
        self._clear_row(self._kpi2)
        while self._health_grid.count():
            item = self._health_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cur = self.p._currency
        dash = self.p.api.accounting_dashboard() or {}
        debt = {}
        try:
            debt = self.p.api.get_debt_summary() or {}
        except Exception:
            debt = {}
        today = date.today().isoformat()
        sales_today = 0.0
        expenses_today = 0.0
        try:
            summary = self.p.api.get_report_summary(today, today) or {}
            s = summary.get('summary') or summary
            sales_today = float(s.get('total_revenue') or s.get('revenue') or 0)
        except Exception:
            pass
        try:
            exps = self.p.api.accounting_expenses(today, today) or []
            expenses_today = sum(float(e.get('amount') or 0) for e in exps)
        except Exception:
            pass

        outstanding = float((debt.get('outstanding') or {}).get('total') or 0)
        overdue = float((debt.get('overdue') or {}).get('total') or 0)
        collected = float((debt.get('today_collected') or {}).get('total') or 0)

        row1 = [
            ("Today's Sales", _fmt(sales_today, cur)),
            ('Gross Profit', _fmt(dash.get('month_gross'), cur)),
            ('Net Profit', _fmt(dash.get('month_net'), cur)),
            ("Today's Expenses", _fmt(expenses_today, cur)),
        ]
        row2 = [
            ('Cash', _fmt(dash.get('cash_balance'), cur)),
            ('M-Pesa', _fmt(dash.get('mpesa_balance'), cur)),
            ('Bank', _fmt(dash.get('bank_balance'), cur)),
            ('Customer Credit', _fmt(outstanding, cur)),
        ]
        for t, v in row1:
            self._kpi1.addWidget(KPICard(t, v))
        for t, v in row2:
            self._kpi2.addWidget(KPICard(t, v))

        # Health score from real metrics only
        score = 70
        notes = []
        net = float(dash.get('month_net') or 0)
        cash = float(dash.get('cash_balance') or 0) + float(dash.get('mpesa_balance') or 0)
        if net >= 0:
            score += 10
            notes.append('Profitable this month')
        else:
            score -= 15
            notes.append('Net profit is negative this month')
        if cash > 0:
            score += 8
            notes.append('Cash & M-Pesa on hand')
        else:
            score -= 20
            notes.append('Low cash / M-Pesa balance')
        if outstanding > 0 and overdue / max(outstanding, 1) > 0.35:
            score -= 12
            notes.append('High overdue customer credit')
        elif outstanding == 0:
            score += 5
            notes.append('No outstanding customer credit')
        if dash.get('trial_balanced'):
            score += 5
            notes.append('Books are balanced')
        else:
            score -= 10
            notes.append('Trial balance needs review')
        score = max(0, min(100, score))

        self._score_lbl.setText(str(score))
        color = C['ok'] if score >= 75 else (C['warn'] if score >= 55 else C['err'])
        self._score_lbl.setStyleSheet(
            f"color:{color}; font-size:36px; font-weight:800; background:transparent;")

        status_rows = [
            ('Cash flow', 'Healthy' if cash > expenses_today else 'Watch closely'),
            ('Profitability', 'On track' if net >= 0 else 'Needs attention'),
            ('Customer credit', f'{_fmt(overdue, cur)} overdue' if overdue else 'No overdue'),
            ('Collected today', _fmt(collected, cur)),
            ('Trial balance', 'OK' if dash.get('trial_balanced') else 'Review'),
        ]
        for i, (k, v) in enumerate(status_rows):
            self._health_grid.addWidget(Caption(k), i // 3, (i % 3) * 2)
            vl = QLabel(v)
            vl.setStyleSheet(
                f"color:{C['text']}; font-size:13px; font-weight:700; background:transparent;")
            self._health_grid.addWidget(vl, i // 3, (i % 3) * 2 + 1)

        self._insight.setText(' · '.join(notes[:4]) if notes else 'No issues flagged from current data.')


# ═══════════════════════════════════════════════════════════════════════════════
# Money — cash / bank / M-Pesa
# ═══════════════════════════════════════════════════════════════════════════════

class _MoneyPage(QWidget):
    ACCOUNTS = [
        ('1000', 'Cash'),
        ('1010', 'M-Pesa'),
        ('1020', 'Bank'),
    ]

    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        self._code = '1000'
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)
        intro, _ = page_intro(
            'Money',
            'Where your money sits right now — cash, M-Pesa, and bank.',
        )
        lay.addLayout(intro)

        self._acct_row = QHBoxLayout()
        self._acct_row.setSpacing(12)
        lay.addLayout(self._acct_row)

        bar = QHBoxLayout()
        self._from = make_date_edit()
        self._to = make_date_edit()
        try:
            self._from.setDate(QDate.currentDate().addDays(-30))
        except Exception:
            pass
        bar.addWidget(Caption('From'))
        bar.addWidget(self._from)
        bar.addWidget(Caption('To'))
        bar.addWidget(self._to)
        go = PrimaryBtn('Show Activity', 36)
        go.clicked.connect(self._load_activity)
        bar.addWidget(go)
        xfer = SecondaryBtn('Transfer Between Accounts', 36)
        xfer.clicked.connect(self._transfer)
        bar.addWidget(xfer)
        bar.addStretch(1)
        lay.addLayout(bar)

        self._summary = Caption('')
        lay.addWidget(self._summary)

        self._tbl = make_table(['Date', 'Entry', 'Description', 'In', 'Out', 'Balance'])
        lay.addWidget(wrap_table_card(self._tbl), 1)

    def refresh(self):
        while self._acct_row.count():
            item = self._acct_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        cur = self.p._currency
        dash = self.p.api.accounting_dashboard() or {}
        bals = {
            '1000': dash.get('cash_balance'),
            '1010': dash.get('mpesa_balance'),
            '1020': dash.get('bank_balance'),
        }
        for code, name in self.ACCOUNTS:
            card = KPICard(name, _fmt(bals.get(code), cur))
            card.setCursor(Qt.PointingHandCursor)
            card.mousePressEvent = lambda e, c=code: self._select(c)  # type: ignore
            self._acct_row.addWidget(card)
        self._acct_row.addStretch(1)
        self._load_activity()

    def _select(self, code: str):
        self._code = code
        self._load_activity()

    def _dates(self):
        start = self._from.date().toString('yyyy-MM-dd')
        end = self._to.date().toString('yyyy-MM-dd')
        if not start:
            start = (date.today() - timedelta(days=30)).isoformat()
        if not end:
            end = date.today().isoformat()
        return start, end

    def _load_activity(self):
        start, end = self._dates()
        cur = self.p._currency
        name = dict(self.ACCOUNTS).get(self._code, self._code)
        data = self.p.api.accounting_cash_book(self._code, start, end) or {}
        bal = float(data.get('balance') or 0)
        lines = data.get('lines') or []
        money_in = sum(float(r.get('debit') or 0) for r in lines)
        money_out = sum(float(r.get('credit') or 0) for r in lines)
        # For liability-normal? Cash accounts are debit-normal: debit=in, credit=out
        self._summary.setText(
            f"{name} ({self._code})  ·  In {_fmt(money_in, cur)}  ·  "
            f"Out {_fmt(money_out, cur)}  ·  Balance {_fmt(bal, cur)}"
        )
        self._tbl.setRowCount(0)
        running = bal
        # Show newest first without recalculating opening — list as posted
        for r in reversed(lines):
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            din = float(r.get('debit') or 0)
            dout = float(r.get('credit') or 0)
            self._tbl.setItem(i, 0, tbl_item((r.get('entry_date') or '')[:10]))
            self._tbl.setItem(i, 1, tbl_item(r.get('entry_number')))
            self._tbl.setItem(i, 2, tbl_item(r.get('description')))
            self._tbl.setItem(i, 3, tbl_right(_fmt(din, cur) if din else ''))
            self._tbl.setItem(i, 4, tbl_right(_fmt(dout, cur) if dout else ''))
            self._tbl.setItem(i, 5, tbl_right(''))

    def _transfer(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Transfer Between Accounts')
        apply_themed_dialog(dlg)
        form = QFormLayout(dlg)
        frm = Select(items=['1000 Cash', '1010 M-Pesa', '1020 Bank'])
        to = Select(items=['1000 Cash', '1010 M-Pesa', '1020 Bank'])
        amt = QDoubleSpinBox(); amt.setMaximum(1e12); amt.setDecimals(2)
        desc = QLineEdit(); desc.setPlaceholderText('Optional note')
        form.addRow('From', frm)
        form.addRow('To', to)
        form.addRow('Amount', amt)
        form.addRow('Note', desc)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec_() != QDialog.Accepted:
            return
        res = self.p.api.accounting_create_transfer({
            'from_code': frm.currentText().split()[0],
            'to_code': to.currentText().split()[0],
            'amount': amt.value(),
            'description': desc.text(),
        })
        if res.get('error'):
            QMessageBox.warning(self, 'Transfer', res['error'])
        else:
            QMessageBox.information(self, 'Transfer', f"Posted {res.get('transfer_number')}")
            self.refresh()


# ═══════════════════════════════════════════════════════════════════════════════
# Customer Credit (debt inside Finance)
# ═══════════════════════════════════════════════════════════════════════════════

class _CreditPage(QWidget):
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)
        open_debt = SecondaryBtn('Open Full Debt Tools', 36)
        open_debt.setToolTip('Opens the dedicated Debt Management module for collection workflows.')
        open_debt.clicked.connect(self._open_debt_module)
        intro, _ = page_intro(
            'Customer Credit',
            'Who owes you money, what is overdue, and what you collected today.',
            open_debt,
        )
        lay.addLayout(intro)

        self._kpis = QHBoxLayout(); self._kpis.setSpacing(12)
        lay.addLayout(self._kpis)

        cols = QHBoxLayout(); cols.setSpacing(14)
        left = QVBoxLayout()
        left.addWidget(H3('Largest balances'))
        self._debtors = make_table(['Customer', 'Balance'])
        left.addWidget(wrap_table_card(self._debtors), 1)
        right = QVBoxLayout()
        right.addWidget(H3('Aging'))
        self._aging = make_table(['Bucket', 'Amount', 'Invoices'])
        right.addWidget(wrap_table_card(self._aging), 1)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        lay.addLayout(cols, 1)

    def _clear_kpis(self):
        while self._kpis.count():
            item = self._kpis.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self):
        self._clear_kpis()
        cur = self.p._currency
        debt = self.p.api.get_debt_summary() or {}
        aging = {}
        try:
            aging = self.p.api.get_aging_report() or {}
        except Exception:
            aging = {}

        cards = [
            ('Outstanding', _fmt((debt.get('outstanding') or {}).get('total'), cur)),
            ('Overdue', _fmt((debt.get('overdue') or {}).get('total'), cur)),
            ('Collected Today', _fmt((debt.get('today_collected') or {}).get('total'), cur)),
            ('Customers', str(debt.get('customers_with_debt') or 0)),
        ]
        for t, v in cards:
            self._kpis.addWidget(KPICard(t, v))

        self._debtors.setRowCount(0)
        for r in debt.get('top_debtors') or []:
            i = self._debtors.rowCount()
            self._debtors.insertRow(i)
            self._debtors.setItem(i, 0, tbl_item(r.get('customer_name')))
            self._debtors.setItem(i, 1, tbl_right(_fmt(r.get('total_balance'), cur)))

        labels = {
            'current': 'Current',
            '1_30': '1–30 days',
            '31_60': '31–60 days',
            '61_90': '61–90 days',
            'over_90': '90+ days',
        }
        self._aging.setRowCount(0)
        for key, label in labels.items():
            band = aging.get(key) or {}
            i = self._aging.rowCount()
            self._aging.insertRow(i)
            self._aging.setItem(i, 0, tbl_item(label))
            self._aging.setItem(i, 1, tbl_right(_fmt(band.get('total'), cur)))
            self._aging.setItem(i, 2, tbl_center(str(band.get('count') or 0)))

    def _open_debt_module(self):
        # Ask main window to navigate if available
        w = self.window()
        if hasattr(w, '_goto'):
            try:
                w._goto('debt')
                return
            except Exception:
                pass
        QMessageBox.information(
            self, 'Customer Credit',
            'Use Debt Management in the sidebar for collect payment, invoices, and statements.')


# ═══════════════════════════════════════════════════════════════════════════════
# Statement pages (Trial Balance / Balance Sheet)
# ═══════════════════════════════════════════════════════════════════════════════

class _StatementPage(QWidget):
    def __init__(self, parent: FinanceTab, kind: str, subtitle: str = ''):
        super().__init__()
        self.p = parent
        self.kind = kind
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        intro, _ = page_intro(kind, subtitle or 'Accountant view of your books.')
        lay.addLayout(intro)
        bar = QHBoxLayout()
        self._as_of = make_date_edit()
        bar.addWidget(Caption('As of'))
        bar.addWidget(self._as_of)
        run = PrimaryBtn('Run', 36)
        run.clicked.connect(self.refresh)
        bar.addWidget(run)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setStyleSheet(
            f"QPlainTextEdit{{background:{C['card']}; color:{C['text']}; "
            f"font-family: Consolas, monospace; font-size:12px; border-radius:8px; padding:12px;}}")
        lay.addWidget(self._out, 1)

    def refresh(self):
        cur = self.p._currency
        end = self._as_of.date().toString('yyyy-MM-dd') or date.today().isoformat()
        lines = [self.kind, f'As of {end}', f'Currency: {cur}', '']
        if self.kind == 'Trial Balance':
            data = self.p.api.accounting_trial_balance(end) or {}
            lines.append(
                f"Dr {_fmt(data.get('total_debit'), cur)}  "
                f"Cr {_fmt(data.get('total_credit'), cur)}  "
                f"Balanced={data.get('balanced')}")
            for r in data.get('accounts') or []:
                lines.append(
                    f"  {r['code']} {r['name']}: "
                    f"Dr {_fmt(r['debit'], cur)}  Cr {_fmt(r['credit'], cur)}")
        else:
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
        self._out.setPlainText('\n'.join(lines))


class _CashFlowPage(QWidget):
    """Simple cash-flow view derived from cash/M-Pesa/bank books (real ledger data)."""

    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        intro, _ = page_intro(
            'Cash Flow',
            'Money in and out across Cash, M-Pesa, and Bank from posted journals.')
        lay.addLayout(intro)
        bar = QHBoxLayout()
        self._from = make_date_edit()
        self._to = make_date_edit()
        try:
            self._from.setDate(QDate.currentDate().addDays(-30))
        except Exception:
            pass
        bar.addWidget(Caption('From'))
        bar.addWidget(self._from)
        bar.addWidget(Caption('To'))
        bar.addWidget(self._to)
        run = PrimaryBtn('Run', 36)
        run.clicked.connect(self.refresh)
        bar.addWidget(run)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setStyleSheet(
            f"QPlainTextEdit{{background:{C['card']}; color:{C['text']}; "
            f"font-family: Consolas, monospace; font-size:12px; border-radius:8px; padding:12px;}}")
        lay.addWidget(self._out, 1)

    def refresh(self):
        cur = self.p._currency
        start = self._from.date().toString('yyyy-MM-dd') or (date.today() - timedelta(days=30)).isoformat()
        end = self._to.date().toString('yyyy-MM-dd') or date.today().isoformat()
        lines = ['Cash Flow Summary', f'Period: {start} → {end}', f'Currency: {cur}', '']
        total_in = total_out = 0.0
        for code, name in (('1000', 'Cash'), ('1010', 'M-Pesa'), ('1020', 'Bank')):
            data = self.p.api.accounting_cash_book(code, start, end) or {}
            rows = data.get('lines') or []
            din = sum(float(r.get('debit') or 0) for r in rows)
            dout = sum(float(r.get('credit') or 0) for r in rows)
            total_in += din
            total_out += dout
            lines.append(
                f"{name}: In {_fmt(din, cur)}  Out {_fmt(dout, cur)}  "
                f"Balance {_fmt(data.get('balance'), cur)}")
        lines.append('')
        lines.append(f'Total In:  {_fmt(total_in, cur)}')
        lines.append(f'Total Out: {_fmt(total_out, cur)}')
        lines.append(f'Net change: {_fmt(total_in - total_out, cur)}')
        self._out.setPlainText('\n'.join(lines))


class _FinanceSettingsPage(QWidget):
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        intro, _ = page_intro(
            'Financial Settings',
            'Quick finance preferences. Canonical config lives in Settings → Finance.')
        lay.addLayout(intro)
        form = QFormLayout()
        self._currency = QComboBox()
        for c in ['KES', 'USD', 'EUR', 'GBP', 'TZS', 'UGX', 'ZAR']:
            self._currency.addItem(c)
        form.addRow('Currency', self._currency)
        self._method = QComboBox()
        self._method.addItem('Accrual (recommended)', 'accrual')
        self._method.addItem('Cash basis', 'cash')
        form.addRow('Accounting method', self._method)
        self._costing = QComboBox()
        self._costing.addItem('Weighted average', 'weighted_avg')
        self._costing.addItem('FIFO', 'fifo')
        form.addRow('Inventory costing', self._costing)
        self._fy_month = QComboBox()
        for i, name in enumerate(
            ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], start=1):
            self._fy_month.addItem(f'{name} (month {i})', str(i))
        form.addRow('Fiscal year starts', self._fy_month)
        lay.addLayout(form)
        row = QHBoxLayout()
        save = PrimaryBtn('Save', 40)
        save.clicked.connect(self._save)
        open_settings = SecondaryBtn('Open Settings → Finance', 40)
        open_settings.clicked.connect(self._open_settings)
        row.addWidget(save)
        row.addWidget(open_settings)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)

    def refresh(self):
        cfg = self.p._cfg()
        try:
            api_cfg = self.p.api.get_settings() or {}
            if api_cfg:
                cfg = {**cfg, **api_cfg}
        except Exception:
            pass
        code = str(cfg.get('currency_code') or cfg.get('currency_symbol')
                   or self.p._currency or 'KES').upper()
        idx = self._currency.findText(code)
        self._currency.setCurrentIndex(idx if idx >= 0 else 0)
        m = (cfg.get('accounting_method') or 'accrual').strip().lower()
        mi = self._method.findData(m)
        self._method.setCurrentIndex(mi if mi >= 0 else 0)
        c = (cfg.get('inventory_costing') or 'weighted_avg').strip().lower()
        ci = self._costing.findData(c)
        self._costing.setCurrentIndex(ci if ci >= 0 else 0)
        fy = str(cfg.get('fiscal_year_start_month') or '1')
        fi = self._fy_month.findData(fy)
        self._fy_month.setCurrentIndex(fi if fi >= 0 else 0)

    def _save(self):
        code = self._currency.currentText().strip().upper() or 'KES'
        payload = {
            'currency_code': code,
            'currency_symbol': code,
            'accounting_method': self._method.currentData() or 'accrual',
            'inventory_costing': self._costing.currentData() or 'weighted_avg',
            'fiscal_year_start_month': self._fy_month.currentData() or '1',
        }
        try:
            res = self.p.api.update_settings(payload) if hasattr(self.p.api, 'update_settings') else None
            if res and res.get('error'):
                QMessageBox.warning(self, 'Finance', res['error'])
                return
            self.p._currency = code
            QMessageBox.information(self, 'Finance', 'Settings saved.')
        except Exception as e:
            QMessageBox.warning(self, 'Finance', str(e))

    def _open_settings(self):
        w = self.window()
        if hasattr(w, '_goto'):
            try:
                w._goto('settings')
                return
            except Exception:
                pass
        QMessageBox.information(
            self, 'Finance',
            'Open Settings from the sidebar, then scroll to the Finance section.')

# ── Chart of Accounts ──────────────────────────────────────────────────────────

class _AccountsPage(QWidget):
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        add = PrimaryBtn('+ Account', 36)
        add.clicked.connect(self._add)
        intro, _ = page_intro(
            'Chart of Accounts',
            'The list of accounts your books use — assets, liabilities, income, expenses.',
            add,
        )
        lay.addLayout(intro)
        bar = QHBoxLayout()
        ref = GhostBtn('↺ Refresh', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        bar.addStretch(1)
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
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        intro, _ = page_intro(
            'General Ledger',
            'Every debit and credit posted to a single account over a date range.')
        lay.addLayout(intro)
        bar = QHBoxLayout()
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
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        man = PrimaryBtn('+ Manual Journal', 36)
        man.clicked.connect(self._manual)
        intro, _ = page_intro(
            'Journal Entries',
            'Posted journals from sales, expenses, transfers, and manual adjustments.',
            man,
        )
        lay.addLayout(intro)
        bar = QHBoxLayout()
        rev = SecondaryBtn('Reverse Selected', 36)
        rev.clicked.connect(self._reverse)
        bar.addWidget(rev)
        ref = GhostBtn('↺ Refresh', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        bar.addStretch(1)
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
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        add = PrimaryBtn('+ Record Expense', 36)
        add.clicked.connect(self._add)
        intro, _ = page_intro(
            'Expenses',
            'Money leaving the business — rent, utilities, transport, and more.',
            add,
        )
        lay.addLayout(intro)
        bar = QHBoxLayout()
        edit = SecondaryBtn('Edit', 36)
        edit.clicked.connect(self._edit)
        bar.addWidget(edit)
        dele = DangerBtn('Delete', 36)
        dele.clicked.connect(self._delete)
        bar.addWidget(dele)
        ref = GhostBtn('↺ Refresh', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        bar.addStretch(1)
        lay.addLayout(bar)
        self._tbl = make_table(
            ['Number', 'Date', 'Expense Acct', 'Paid From', 'Amount', 'Description', 'Vendor'])
        lay.addWidget(wrap_table_card(self._tbl), 1)
        self._ids = []
        self._rows_cache = []

    def refresh(self):
        rows = self.p.api.accounting_expenses() or []
        cur = self.p._currency
        self._tbl.setRowCount(0)
        self._ids = []
        self._rows_cache = []
        for r in rows:
            i = self._tbl.rowCount()
            self._tbl.insertRow(i)
            self._ids.append(r.get('id'))
            self._rows_cache.append(r)
            self._tbl.setItem(i, 0, tbl_item(r.get('expense_number')))
            self._tbl.setItem(i, 1, tbl_item((r.get('expense_date') or '')[:10]))
            self._tbl.setItem(i, 2, tbl_item(r.get('account_code')))
            self._tbl.setItem(i, 3, tbl_item(r.get('pay_from_code')))
            self._tbl.setItem(i, 4, tbl_right(_fmt(r.get('amount'), cur)))
            self._tbl.setItem(i, 5, tbl_item(r.get('description')))
            self._tbl.setItem(i, 6, tbl_item(r.get('vendor_name')))

    def _selected_row(self):
        row = self._tbl.currentRow()
        if row < 0 or row >= len(self._ids):
            return None, None
        return row, self._rows_cache[row]

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

    def _edit(self):
        row, cur = self._selected_row()
        if cur is None:
            QMessageBox.information(self, 'Expense', 'Select an expense to edit.')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit {cur.get('expense_number') or 'Expense'}")
        apply_themed_dialog(dlg)
        form = QFormLayout(dlg)
        exp = QLineEdit(str(cur.get('account_code') or '6000'))
        pay = QLineEdit(str(cur.get('pay_from_code') or '1000'))
        amt = QDoubleSpinBox()
        amt.setMaximum(1e9)
        amt.setDecimals(2)
        amt.setValue(float(cur.get('amount') or 0))
        desc = QLineEdit(str(cur.get('description') or ''))
        vendor = QLineEdit(str(cur.get('vendor_name') or ''))
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
        res = self.p.api.accounting_update_expense(self._ids[row], {
            'account_code': exp.text().strip(),
            'pay_from_code': pay.text().strip(),
            'amount': amt.value(),
            'description': desc.text(),
            'vendor_name': vendor.text(),
            'expense_date': (cur.get('expense_date') or '')[:10] or None,
        })
        if res.get('error'):
            QMessageBox.warning(self, 'Expense', res['error'])
        self.refresh()

    def _delete(self):
        row, cur = self._selected_row()
        if cur is None:
            QMessageBox.information(self, 'Expense', 'Select an expense to delete.')
            return
        reason, ok = QInputDialog.getText(
            self, 'Delete Expense',
            f"Reason for deleting {cur.get('expense_number') or 'expense'}:")
        if not ok:
            return
        res = self.p.api.accounting_delete_expense(self._ids[row], reason)
        if res.get('error'):
            QMessageBox.warning(self, 'Delete', res['error'])
        self.refresh()


# ── Transfers ──────────────────────────────────────────────────────────────────

class _TransfersPage(QWidget):
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
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
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        close_btn = DangerBtn('Close Selected Period', 36)
        close_btn.clicked.connect(self._close)
        intro, _ = page_intro(
            'Period Close',
            'Lock a fiscal period so nobody posts into closed dates by mistake.',
            close_btn,
        )
        lay.addLayout(intro)
        bar = QHBoxLayout()
        ref = GhostBtn('↺ Refresh', 36)
        ref.clicked.connect(self.refresh)
        bar.addWidget(ref)
        bar.addStretch(1)
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
    def __init__(self, parent: FinanceTab):
        super().__init__()
        self.p = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        intro, _ = page_intro(
            'Financial Reports',
            'Profit, cash books, balance sheet, trial balance, and aging — from live ledgers.')
        lay.addLayout(intro)
        bar = QHBoxLayout()
        self._kind = Select(items=[
            'Profit & Loss', 'Cash Flow Summary', 'Expense Reports',
            'Cash Book', 'M-Pesa Book', 'Bank Book',
            'Balance Sheet', 'Trial Balance',
            'AR Aging', 'AP Aging',
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
        elif kind == 'Cash Flow Summary':
            total_in = total_out = 0.0
            for code, name in (('1000', 'Cash'), ('1010', 'M-Pesa'), ('1020', 'Bank')):
                book = self.p.api.accounting_cash_book(code, start, end) or {}
                rows = book.get('lines') or []
                din = sum(float(r.get('debit') or 0) for r in rows)
                dout = sum(float(r.get('credit') or 0) for r in rows)
                total_in += din
                total_out += dout
                lines.append(f"{name}: In {_fmt(din, cur)}  Out {_fmt(dout, cur)}")
            lines.append(f"Net change: {_fmt(total_in - total_out, cur)}")
            data = {'total_in': total_in, 'total_out': total_out}
        elif kind == 'Expense Reports':
            rows = self.p.api.accounting_expenses(start, end) or []
            total = sum(float(r.get('amount') or 0) for r in rows)
            lines.append(f"Total expenses: {_fmt(total, cur)} ({len(rows)} entries)")
            for r in rows[:200]:
                lines.append(
                    f"  {(r.get('expense_date') or '')[:10]} {r.get('expense_number')} "
                    f"{_fmt(r.get('amount'), cur)} {r.get('description') or ''}")
            data = {'rows': rows, 'total': total}
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
        elif kind in ('Cash Book', 'M-Pesa Book', 'Bank Book'):
            code = {'Cash Book': '1000', 'M-Pesa Book': '1010', 'Bank Book': '1020'}[kind]
            data = self.p.api.accounting_cash_book(code, start, end) or {}
            lines.append(f"{kind} ({code}) balance: {_fmt(data.get('balance'), cur)}")
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
