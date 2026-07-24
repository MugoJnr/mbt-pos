"""
Payment Variance dialog — handle excess payments (Kenya POS).
MugoByte Technologies

Primary overpayment choices (UPDATED):
  • Return Change (default)
  • Record as Additional Customer Payment
  • Cancel

Advanced till allocations (deposit / tip / transport / …) remain available
under “Other allocations” so existing finance paths stay intact.
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QComboBox, QLineEdit, QFrame, QMessageBox, QWidget,
)
from PyQt5.QtCore import Qt
from desktop.utils.theme import apply_themed_dialog, C
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn


# Primary cashier choices (shown first)
PRIMARY_OPTIONS = (
    ('return_change', 'Return Change'),
    ('additional_payment', 'Record as Additional Customer Payment'),
)

# Secondary / advanced till allocations
ADVANCED_OPTIONS = (
    ('deposit', 'Customer Deposit (Store Credit)'),
    ('transport', 'Transport / Delivery Fee'),
    ('tip', 'Tip (Tips account)'),
    ('advance', 'Advance Payment (future invoices)'),
    ('miscellaneous', 'Miscellaneous'),
)

# Back-compat alias used by smoke scripts / imports
HANDLING_OPTIONS = PRIMARY_OPTIONS + ADVANCED_OPTIONS

MISC_CATEGORIES = (
    'Rounding', 'Staff Error Adjustment', 'Preference', 'Delivery Surcharge',
    'Service Charge', 'Other',
)

HANDLING_LABELS = {
    'return_change': 'Return Change',
    'additional_payment': 'Additional Customer Payment',
    'deposit': 'Customer Deposit',
    'transport': 'Transport/Delivery Fee',
    'tip': 'Tip',
    'advance': 'Advance Payment',
    'miscellaneous': 'Miscellaneous',
}


class PaymentVarianceDialog(QDialog):
    """Block checkout until cashier chooses how to handle Received > Expected."""

    def __init__(self, parent, currency, sale_total, amount_received, excess,
                 settings=None, has_customer=False, customer_name=''):
        super().__init__(parent)
        self.setWindowTitle('Overpayment Confirmation')
        self.setMinimumWidth(480)
        self.setModal(True)
        self._currency = currency or 'KES'
        self._sale_total = float(sale_total)
        self._received = float(amount_received)
        self._excess = round(float(excess), 2)
        self._settings = settings or {}
        self._has_customer = bool(has_customer)
        self.result_data = None
        self._build(customer_name)

    def _build(self, customer_name):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        title = QLabel(
            f'Customer paid {self._currency} {self._excess:,.2f} more than the invoice'
        )
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color:{C['text']};font-size:15px;font-weight:800;background:transparent;")
        lay.addWidget(title)

        summary = QFrame()
        summary.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};"
            f"border-radius:8px;}}")
        sl = QVBoxLayout(summary)
        sl.setContentsMargins(14, 10, 14, 10)
        sl.setSpacing(4)
        for lbl, val in (
            ('Invoice total', f"{self._currency} {self._sale_total:,.2f}"),
            ('Amount received', f"{self._currency} {self._received:,.2f}"),
            ('Difference (excess)', f"{self._currency} {self._excess:,.2f}"),
        ):
            row = QHBoxLayout()
            a = QLabel(lbl)
            a.setStyleSheet(f"color:{C['text2']};font-size:13px;background:transparent;")
            b = QLabel(val)
            b.setStyleSheet(
                f"color:{C['gold'] if 'Difference' in lbl else C['text']};"
                f"font-size:13px;font-weight:700;background:transparent;")
            row.addWidget(a); row.addStretch(); row.addWidget(b)
            sl.addLayout(row)
        if customer_name:
            cn = QLabel(f'Customer: {customer_name}')
            cn.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
            sl.addWidget(cn)
        lay.addWidget(summary)

        hint = QLabel('How should the overpayment be handled?')
        hint.setStyleSheet(
            f"color:{C['text2']};font-size:12px;background:transparent;")
        lay.addWidget(hint)

        self._group = QButtonGroup(self)
        self._radios = {}
        enable_dep = self._settings.get('variance_enable_deposits', '1') == '1'
        enable_tip = self._settings.get('variance_enable_tips', '1') == '1'
        enable_tr = self._settings.get('variance_enable_transport', '1') == '1'

        # Build misc fields BEFORE connecting toggled — setChecked fires immediately.
        self._misc_box = QWidget()
        ml = QVBoxLayout(self._misc_box)
        ml.setContentsMargins(24, 0, 0, 0)
        ml.setSpacing(6)
        self._misc_cat = QComboBox()
        self._misc_cat.setMinimumHeight(36)
        self._misc_cat.addItems(MISC_CATEGORIES)
        self._misc_reason = QLineEdit()
        self._misc_reason.setPlaceholderText('Reason required for Miscellaneous...')
        self._misc_reason.setMinimumHeight(36)
        ml.addWidget(QLabel('Category'))
        ml.addWidget(self._misc_cat)
        ml.addWidget(QLabel('Reason'))
        ml.addWidget(self._misc_reason)
        self._misc_box.hide()

        for key, label in PRIMARY_OPTIONS:
            rb = QRadioButton(label)
            rb.setStyleSheet(
                f"color:{C['text']};font-size:14px;font-weight:700;background:transparent;")
            if key == 'return_change':
                rb.setToolTip('Give the excess back to the customer (default).')
            elif key == 'additional_payment':
                rb.setToolTip(
                    'Keep the full amount received as sales income for this sale. '
                    'Recorded internally only — customer receipt stays standard.')
            self._group.addButton(rb)
            self._radios[key] = rb
            lay.addWidget(rb)
            rb.toggled.connect(self._on_option)

        adv_hdr = QLabel('Other allocations (optional)')
        adv_hdr.setStyleSheet(
            f"color:{C['muted']};font-size:11px;font-weight:700;letter-spacing:0.4px;"
            f"background:transparent;margin-top:6px;")
        lay.addWidget(adv_hdr)

        for key, label in ADVANCED_OPTIONS:
            rb = QRadioButton(label)
            rb.setStyleSheet(f"color:{C['text']};font-size:13px;background:transparent;")
            if key == 'deposit' and not enable_dep:
                rb.setEnabled(False)
                rb.setToolTip('Deposits disabled in Settings -> Payment Variance')
            if key == 'tip' and not enable_tip:
                rb.setEnabled(False)
                rb.setToolTip('Tips disabled in Settings -> Payment Variance')
            if key == 'transport' and not enable_tr:
                rb.setEnabled(False)
                rb.setToolTip('Transport fee disabled in Settings -> Payment Variance')
            if key == 'advance' and not enable_dep:
                rb.setEnabled(False)
            self._group.addButton(rb)
            self._radios[key] = rb
            lay.addWidget(rb)
            rb.toggled.connect(self._on_option)

        lay.addWidget(self._misc_box)
        self._radios['return_change'].setChecked(True)

        notes_lbl = QLabel('Internal notes (optional — not printed on customer receipt)')
        notes_lbl.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
        lay.addWidget(notes_lbl)
        self._notes = QLineEdit()
        self._notes.setPlaceholderText('Optional note for audit trail…')
        self._notes.setMinimumHeight(36)
        lay.addWidget(self._notes)

        btns = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        ok = PrimaryBtn('Confirm', 40)
        ok.clicked.connect(self._confirm)
        btns.addWidget(cancel)
        btns.addStretch()
        btns.addWidget(ok)
        lay.addLayout(btns)

        apply_themed_dialog(self)
        from desktop.utils.state_reset import StateResetManager
        StateResetManager.clear_modal_on_close(self)

    def _on_option(self, checked=False):
        box = getattr(self, '_misc_box', None)
        if box is None:
            return
        box.setVisible(self._radios['miscellaneous'].isChecked())

    def _selected_handling(self):
        for key, rb in self._radios.items():
            if rb.isChecked():
                return key
        return None

    def _confirm(self):
        handling = self._selected_handling()
        if not handling:
            QMessageBox.warning(self, 'Required', 'Select how to handle the excess.')
            return
        require_cust = self._settings.get('variance_require_customer_deposit', '1') == '1'
        if handling in ('deposit', 'advance') and require_cust and not self._has_customer:
            QMessageBox.warning(
                self, 'Customer Required',
                'Select a customer before allocating excess as Deposit or Advance.')
            return
        misc_cat = reason = ''
        if handling == 'miscellaneous':
            misc_cat = self._misc_cat.currentText().strip()
            reason = self._misc_reason.text().strip()
            if not misc_cat or not reason:
                QMessageBox.warning(
                    self, 'Required',
                    'Miscellaneous requires a category and a reason.')
                return
        self.result_data = {
            'handling': handling,
            'excess_amount': self._excess,
            'misc_category': misc_cat,
            'reason': reason,
            'notes': self._notes.text().strip(),
            'manager_approved': False,
            'manager_name': '',
        }
        self.accept()
