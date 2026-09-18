"""Payment Inbox — unmatched Till payments + ambiguous confirmations."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QLineEdit,
)

from desktop.utils.dialog_keys import wire_dialog_keys
from desktop.utils.theme import apply_themed_dialog


class PaymentInboxDialog(QDialog):
    def __init__(self, parent, *, payment_service, currency: str = 'KES'):
        super().__init__(parent)
        if payment_service is None:
            raise ValueError('payment_service is required')
        self.setWindowTitle('M-Pesa Payment Inbox')
        self.resize(720, 480)
        self.svc = payment_service
        self.currency = currency or 'KES'

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            'Unmatched Till/Paybill credits and payments needing confirmation. '
            'Never auto-assign ambiguous matches.'
        ))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ['Type', 'Reference / Payment', 'Amount', 'Status', 'Phone']
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.pay_id = QLineEdit()
        self.pay_id.setPlaceholderText('Pending payment id')
        self.ref = QLineEdit()
        self.ref.setPlaceholderText('Incoming provider reference')
        row.addWidget(self.pay_id)
        row.addWidget(self.ref)
        self._confirm_btn = QPushButton('Confirm Match')
        self._confirm_btn.clicked.connect(self._confirm)
        row.addWidget(self._confirm_btn)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        root.addLayout(row)

        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        root.addWidget(close)
        wire_dialog_keys(self, primary=self._confirm_btn, cancel=close)
        try:
            apply_themed_dialog(self)
        except Exception:
            pass
        self.reload()

    def reload(self):
        try:
            data = self.svc.inbox() or {}
        except Exception as e:
            self.table.setRowCount(0)
            QMessageBox.warning(
                self, 'Payment Inbox',
                f'Could not load inbox:\n{e}',
            )
            return
        if not isinstance(data, dict):
            data = {'incoming': [], 'payments': []}
        rows = []
        for inc in data.get('incoming') or []:
            if not isinstance(inc, dict):
                continue
            rows.append((
                'incoming',
                inc.get('provider_reference') or '',
                float(inc.get('amount') or 0),
                inc.get('status') or '',
                inc.get('phone_masked') or '',
            ))
        for pay in data.get('payments') or []:
            if not isinstance(pay, dict):
                continue
            rows.append((
                'payment',
                pay.get('id') or '',
                float(pay.get('amount_expected') or 0),
                pay.get('status') or '',
                pay.get('phone_masked') or '',
            ))
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for c, val in enumerate(r):
                if c == 2:
                    val = f'{self.currency} {float(val):,.2f}'
                self.table.setItem(i, c, QTableWidgetItem(str(val)))

    def _confirm(self):
        pid = self.pay_id.text().strip()
        ref = self.ref.text().strip()
        if not pid or not ref:
            QMessageBox.warning(self, 'Confirm', 'Payment id and reference required.')
            return
        try:
            parent = self.parent()
            user = getattr(parent, 'user', {}) or {} if parent is not None else {}
            if isinstance(user, dict) and isinstance(user.get('user'), dict):
                name = user.get('user', {}).get('username') or 'manager'
            elif isinstance(user, dict):
                name = user.get('username') or 'manager'
            else:
                name = 'manager'
            self.svc.confirm_match(pid, ref, confirmed_by=name)
            QMessageBox.information(
                self, 'Matched',
                'Match confirmed — complete sale from checkout if cart still open.',
            )
            self.reload()
        except Exception as e:
            QMessageBox.warning(self, 'Confirm', str(e))
