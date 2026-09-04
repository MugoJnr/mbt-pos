"""Payment Inbox — unmatched Till payments + ambiguous confirmations."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QLineEdit,
)


class PaymentInboxDialog(QDialog):
    def __init__(self, parent, *, payment_service, currency: str = 'KES'):
        super().__init__(parent)
        self.setWindowTitle('M-Pesa Payment Inbox')
        self.resize(720, 480)
        self.svc = payment_service
        self.currency = currency

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
        btn = QPushButton('Confirm Match')
        btn.clicked.connect(self._confirm)
        row.addWidget(btn)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        root.addLayout(row)

        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        root.addWidget(close)
        self.reload()

    def reload(self):
        data = self.svc.inbox()
        rows = []
        for inc in data.get('incoming') or []:
            rows.append((
                'incoming',
                inc.get('provider_reference') or '',
                float(inc.get('amount') or 0),
                inc.get('status') or '',
                inc.get('phone_masked') or '',
            ))
        for pay in data.get('payments') or []:
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
            user = getattr(self.parent(), 'user', {}) or {}
            name = (user.get('user') or user).get('username') or 'manager'
            self.svc.confirm_match(pid, ref, confirmed_by=name)
            QMessageBox.information(self, 'Matched', 'Match confirmed — complete sale from checkout if cart still open.')
            self.reload()
        except Exception as e:
            QMessageBox.warning(self, 'Confirm', str(e))
