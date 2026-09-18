"""
POS / Finance — Record Expense dialog (offline-first till expenses).
MugoByte Technologies
"""
from __future__ import annotations

import uuid
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from desktop.utils.theme import apply_themed_dialog, C
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, GhostBtn
from desktop.utils.dialog_keys import wire_dialog_keys

QUICK_CATEGORIES = (
    'Transport', 'Fuel', 'Staff Meals', 'Shop Supplies',
    'Repairs & Maintenance', 'Other',
)

PAYMENT_METHODS = (
    ('Cash', 'cash'),
    ('M-Pesa', 'mpesa'),
    ('Bank', 'bank'),
    ('Card', 'card'),
)


def _parse_amount(text: str) -> tuple[float | None, str]:
    raw = (text or '').strip().replace(',', '')
    for prefix in ('kes', 'ksh', 'ksh.', 'kes.'):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):].strip()
    if not raw:
        return None, 'Enter an amount'
    try:
        val = float(raw)
    except ValueError:
        return None, 'Amount must be a number'
    if val != val or val in (float('inf'), float('-inf')):
        return None, 'Amount must be a valid number'
    if val <= 0:
        return None, 'Amount must be greater than zero'
    return round(val, 2), ''


class RecordExpenseDialog(QDialog):
    """Fast cashier expense capture — local commit only, no network."""

    def __init__(self, parent, api, currency='KES', user=None):
        super().__init__(parent)
        self.api = api
        self._currency = currency or 'KES'
        self._user = user or {}
        self._client_txn_id = str(uuid.uuid4())
        self._submitting = False
        self.result_data = None
        self.setWindowTitle('Record Expense')
        self.setMinimumWidth(440)
        self.setModal(True)
        self._build()
        apply_themed_dialog(self)
        wire_dialog_keys(self, primary=self._submit, cancel=self._cancel)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        title = QLabel('Record Expense')
        title.setStyleSheet(
            f"font-size:18px; font-weight:700; color:{C['text']}; "
            f"background:transparent; border:none;")
        lay.addWidget(title)
        sub = QLabel('Money leaving the till — saved offline immediately.')
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; border:none;")
        lay.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft)

        amt_row = QHBoxLayout()
        cur_lbl = QLabel(self._currency)
        cur_lbl.setStyleSheet(
            f"font-size:16px; font-weight:700; color:{C['gold']}; "
            f"background:transparent; border:none; padding-right:6px;")
        self._amount = QLineEdit()
        self._amount.setPlaceholderText('0.00')
        self._amount.setMinimumHeight(44)
        self._amount.setStyleSheet('font-size:18px; font-weight:700;')
        self._amount.setValidator(QDoubleValidator(0.01, 999999999.99, 2, self))
        amt_row.addWidget(cur_lbl)
        amt_row.addWidget(self._amount, 1)
        amt_w = QWidget()
        amt_w.setLayout(amt_row)
        form.addRow('Amount', amt_w)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for label in QUICK_CATEGORIES:
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(32)
            b.setStyleSheet(
                f"QPushButton {{ padding:4px 10px; border:1px solid {C['border']}; "
                f"border-radius:6px; background:{C['card2']}; color:{C['text']}; "
                f"font-size:11px; font-weight:600; }}"
                f"QPushButton:hover {{ border-color:{C['gold']}; color:{C['gold']}; }}"
            )
            b.clicked.connect(lambda _=False, lab=label: self._pick_quick(lab))
            chips.addWidget(b)
        chips.addStretch(1)
        chip_w = QWidget()
        chip_w.setLayout(chips)
        form.addRow('Quick', chip_w)

        self._category = QComboBox()
        self._category.setEditable(True)
        self._category.setMinimumHeight(36)
        cats = []
        try:
            cats = self.api.accounting_expense_categories() or []
        except Exception:
            cats = []
        if not cats:
            from desktop.utils.accounting_engine import EXPENSE_CATEGORY_MAP
            cats = [{'label': a, 'account_code': b} for a, b in EXPENSE_CATEGORY_MAP]
        self._cat_codes = {}
        for c in cats:
            label = c.get('label') or ''
            self._category.addItem(label)
            self._cat_codes[label] = c.get('account_code') or '6000'
        form.addRow('Category', self._category)

        self._description = QLineEdit()
        self._description.setPlaceholderText('e.g. Delivery boda')
        self._description.setMinimumHeight(36)
        form.addRow('Description', self._description)

        self._pay_method = QComboBox()
        self._pay_method.setMinimumHeight(36)
        for label, key in PAYMENT_METHODS:
            self._pay_method.addItem(label, key)
        form.addRow('Payment', self._pay_method)

        lay.addLayout(form)

        self._more_btn = GhostBtn('More details ▾', 32)
        self._more_btn.clicked.connect(self._toggle_more)
        lay.addWidget(self._more_btn)

        self._more = QWidget()
        more_form = QFormLayout(self._more)
        more_form.setContentsMargins(0, 0, 0, 0)
        more_form.setSpacing(8)
        self._payee = QLineEdit()
        self._payee.setPlaceholderText('Who was paid?')
        self._payee.setMinimumHeight(34)
        more_form.addRow('Paid To', self._payee)
        self._reference = QLineEdit()
        self._reference.setPlaceholderText('Receipt / M-Pesa code')
        self._reference.setMinimumHeight(34)
        more_form.addRow('Reference', self._reference)
        self._notes = QTextEdit()
        self._notes.setPlaceholderText('Optional notes')
        self._notes.setMaximumHeight(72)
        more_form.addRow('Notes', self._notes)
        self._more.hide()
        lay.addWidget(self._more)

        when = QLabel(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        when.setStyleSheet(
            f"color:{C['muted']}; font-size:11px; background:transparent; border:none;")
        lay.addWidget(when)

        row = QHBoxLayout()
        self._cancel = SecondaryBtn('Cancel', 40)
        self._cancel.clicked.connect(self.reject)
        self._submit = PrimaryBtn('Record Expense', 44)
        self._submit.clicked.connect(self._on_submit)
        row.addWidget(self._cancel)
        row.addStretch(1)
        row.addWidget(self._submit)
        lay.addLayout(row)

        self._amount.textChanged.connect(self._refresh_submit_label)
        self._amount.setFocus()

    def _pick_quick(self, label: str):
        idx = self._category.findText(label)
        if idx >= 0:
            self._category.setCurrentIndex(idx)
        else:
            self._category.setEditText(label)
        self._description.setFocus()

    def _toggle_more(self):
        visible = not self._more.isVisible()
        self._more.setVisible(visible)
        self._more_btn.setText('More details ▴' if visible else 'More details ▾')

    def _refresh_submit_label(self):
        amt, err = _parse_amount(self._amount.text())
        if err or amt is None:
            self._submit.setText('Record Expense')
        else:
            self._submit.setText(
                f'Record {self._currency} {amt:,.2f} Expense')

    def _on_submit(self):
        if self._submitting:
            return
        amt, err = _parse_amount(self._amount.text())
        if err:
            QMessageBox.warning(self, 'Expense', err)
            self._amount.setFocus()
            return
        category = (self._category.currentText() or '').strip()
        if not category:
            QMessageBox.warning(self, 'Expense', 'Choose a category')
            self._category.setFocus()
            return
        desc = (self._description.text() or '').strip()
        if not desc:
            desc = category
        pay_key = self._pay_method.currentData() or 'cash'
        pay_label = self._pay_method.currentText() or 'Cash'

        confirm = QMessageBox.question(
            self, 'Confirm Expense',
            f'Record {self._currency} {amt:,.2f} expense?\n\n'
            f'Category: {category}\n'
            f'Payment: {pay_label}\n'
            f'{desc}',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        # Soft cash-drawer warning only (does not block — shops may top up).
        if str(pay_key).lower() == 'cash':
            try:
                bal = float(self.api.accounting_cash_balance('1000') or 0)
                if amt > bal + 0.009:
                    warn = QMessageBox.question(
                        self, 'Cash balance',
                        f'Till cash on books is about {self._currency} {bal:,.2f}.\n'
                        f'This expense is {self._currency} {amt:,.2f}.\n\n'
                        'Record anyway?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if warn != QMessageBox.Yes:
                        return
            except Exception:
                pass

        account_code = self._cat_codes.get(category) or '6000'
        payload = {
            'amount': amt,
            'category_label': category,
            'account_code': account_code,
            'description': desc,
            'payment_method': pay_key,
            'vendor_name': (self._payee.text() or '').strip(),
            'reference_number': (self._reference.text() or '').strip(),
            'notes': (self._notes.toPlainText() or '').strip(),
            'client_txn_id': self._client_txn_id,
        }

        self._submitting = True
        self._submit.setEnabled(False)
        try:
            res = self.api.accounting_create_expense(payload)
        except Exception as e:
            self._submitting = False
            self._submit.setEnabled(True)
            QMessageBox.critical(self, 'Expense', f'Could not save expense:\n{e}')
            return

        if not res or not res.get('success'):
            self._submitting = False
            self._submit.setEnabled(True)
            QMessageBox.warning(
                self, 'Expense',
                (res or {}).get('error') or 'Could not save expense',
            )
            return

        self.result_data = res
        QMessageBox.information(
            self, 'Expense recorded',
            f"{res.get('expense_number') or 'Expense'} saved "
            f"({self._currency} {float(res.get('amount') or amt):,.2f}).",
        )
        self.accept()
