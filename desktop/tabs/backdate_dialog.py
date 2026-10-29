"""Request list for backdated sales. New sales use the normal till cart."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout,
)

from desktop.utils.theme import apply_themed_dialog

_LABELS = {
    'draft': 'Draft',
    'submitted': 'Pending approval',
    'returned': 'Returned for correction',
    'approved': 'Approved',
    'rejected': 'Rejected',
    'withdrawn': 'Withdrawn',
}
_REVIEW_ROLES = {'manager', 'admin', 'superadmin'}


def _status_label(status: str) -> str:
    return _LABELS.get((status or '').strip().lower(), status or '')


def receipt_text(detail: dict) -> str:
    """Readable proposed receipt. This is the request, not a completed sale."""
    if not detail:
        return 'Select a request to see the proposed receipt.'
    summary = detail.get('summary') or {}
    lines = [
        f"{detail.get('reference') or 'Request'}  ·  {_status_label(detail.get('status'))}",
        f"Cashier: {detail.get('cashier_name') or '—'}",
        f"Requested business date: {detail.get('business_date') or '—'}",
        f"Submitted: {detail.get('submitted_at') or 'Not submitted'}",
        f"Created: {detail.get('created_at') or '—'}",
        f"Reason: {detail.get('reason') or '—'}",
    ]
    if detail.get('reviewer_name') or detail.get('review_note'):
        lines.append(
            f"Reviewer: {detail.get('reviewer_name') or '—'}  "
            f"at {detail.get('decided_at') or '—'}"
        )
        if detail.get('review_note'):
            lines.append(f"Decision: {detail.get('review_note')}")
    lines.append('')
    for index, sale in enumerate(detail.get('sales') or [], start=1):
        customer = sale.get('customer_name') or 'Walk-in'
        lines.append(f"Sale {index}  ·  {customer}  ·  {sale.get('payment_method') or 'Cash'}")
        if sale.get('posted_receipt'):
            lines.append(f"Posted receipt: {sale.get('posted_receipt')}")
        for line in sale.get('lines') or []:
            sku = f" ({line.get('sku')})" if line.get('sku') else ''
            discount = float(line.get('discount') or 0)
            discount_text = f"   discount {discount:,.2f}" if discount else ''
            lines.append(f"  {line.get('product_name') or 'Product'}{sku}")
            lines.append(
                f"      {line.get('quantity')} × {float(line.get('unit_price') or 0):,.2f}"
                f"{discount_text}"
                f"   = {float(line.get('total') or 0):,.2f}"
            )
        paid = float(sale.get('amount_paid') or 0)
        lines.append(
            f"  Received {paid:,.2f}"
            f"   cash {float(sale.get('cash_paid') or 0):,.2f}"
            f"   electronic {float(sale.get('electronic_paid') or 0):,.2f}"
        )
        if sale.get('mpesa_ref'):
            lines.append(f"  M-Pesa reference {sale.get('mpesa_ref')} (not verified by the till)")
        if sale.get('notes'):
            lines.append(f"  Note: {sale.get('notes')}")
        lines.append('')
    lines.append(
        f"Total {float(summary.get('total_sales') or 0):,.2f}"
        f"   Cash {float(summary.get('cash_sales') or 0):,.2f}"
        f"   M-Pesa {float(summary.get('mpesa_sales') or 0):,.2f}"
        f"   Bank {float(summary.get('bank_sales') or 0):,.2f}"
        f"   Credit {float(summary.get('credit_sales') or 0):,.2f}"
        f"   Debt {float(summary.get('outstanding_debt') or 0):,.2f}"
    )
    for warning in detail.get('warnings') or []:
        lines.append(f"Warning: {warning}")
    if detail.get('events'):
        lines.append('')
        lines.append('History')
        for event in detail.get('events') or []:
            lines.append(
                f"  {event.get('created_at') or ''}  {event.get('actor_name') or ''}  "
                f"{event.get('action') or ''}  {event.get('note') or ''}".rstrip()
            )
    return '\n'.join(lines)


class BackdateDialog(QDialog):
    def __init__(self, api, user, parent=None):
        super().__init__(parent)
        self.api = api
        self.user = (user or {}).get('user') or user or {}
        self.setWindowTitle('Backdating Requests')
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        apply_themed_dialog(self)
        self._rows = []
        self._current = None
        self._build()
        self._reload()

    def closeEvent(self, event):
        from desktop.utils.date_controls import release_window_topmost
        release_window_topmost(self)
        release_window_topmost(self.parent())
        super().closeEvent(event)

    def _role(self) -> str:
        return str(self.user.get('role') or '').strip().lower()

    def _user_id(self):
        try:
            return int(self.user.get('id'))
        except (TypeError, ValueError):
            return None

    def _build(self):
        root = QVBoxLayout(self)
        title = QLabel('Backdating Requests')
        title.setStyleSheet('font-size:18px;font-weight:700;')
        root.addWidget(title)
        explain = QLabel(
            'This list does not start a sale. Choose New Backdated Sale to use the normal cart. '
            'A request does not change stock, cash, or debt until it is approved.'
        )
        explain.setWordWrap(True)
        root.addWidget(explain)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search reference, cashier, or reason')
        self.search.textChanged.connect(self._apply_filter)
        self.status_filter = QComboBox()
        for value, label in (
            ('', 'All'),
            ('submitted', 'Pending approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('returned', 'Returned for correction'),
            ('draft', 'Draft'),
            ('withdrawn', 'Withdrawn'),
        ):
            self.status_filter.addItem(label, value)
        self.status_filter.currentIndexChanged.connect(self._reload)
        new_btn = QPushButton('New Backdated Sale')
        new_btn.clicked.connect(self._new_sale)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self._reload)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.status_filter)
        tools.addWidget(refresh)
        tools.addWidget(new_btn)
        root.addLayout(tools)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ['Reference', 'Cashier', 'Business date', 'Amount', 'Status']
        )
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        header.setMinimumSectionSize(90)
        self.table.currentCellChanged.connect(lambda row, *_: self._open_row(row))
        self.empty = QLabel('No requests yet. New Backdated Sale prepares one in the cart.')
        self.empty.setWordWrap(True)
        left.addWidget(self.table, 1)
        left.addWidget(self.empty)
        body.addLayout(left, 5)

        right = QVBoxLayout()
        self.receipt = QTextEdit()
        self.receipt.setReadOnly(True)
        self.receipt.setLineWrapMode(QTextEdit.WidgetWidth)
        self.receipt.setPlainText('Select a request to see the proposed receipt.')
        right.addWidget(self.receipt, 1)
        actions = QHBoxLayout()
        self.approve_btn = QPushButton('Approve and post')
        self.reject_btn = QPushButton('Reject')
        self.return_btn = QPushButton('Return for correction')
        self.withdraw_btn = QPushButton('Withdraw')
        self.approve_btn.clicked.connect(self._approve)
        self.reject_btn.clicked.connect(lambda: self._decide('reject'))
        self.return_btn.clicked.connect(lambda: self._decide('return'))
        self.withdraw_btn.clicked.connect(self._withdraw)
        for button in (self.approve_btn, self.return_btn, self.reject_btn, self.withdraw_btn):
            actions.addWidget(button)
        right.addLayout(actions)
        close = QPushButton('Back to till')
        close.clicked.connect(self.accept)
        right.addWidget(close)
        body.addLayout(right, 4)
        root.addLayout(body, 1)
        self._set_actions(None)

    def _reload(self):
        result = self.api.list_backdate_requests({
            'status': self.status_filter.currentData() or '',
        }) or {}
        if result.get('error'):
            QMessageBox.warning(self, 'Backdating', result['error'])
            return
        self._rows = result.get('requests') or []
        self._current = None
        self.receipt.setPlainText('Select a request to see the proposed receipt.')
        self._set_actions(None)
        self._apply_filter()

    def _visible_rows(self):
        needle = self.search.text().strip().lower()
        rows = []
        for item in self._rows:
            blob = ' '.join(
                str(item.get(key) or '')
                for key in ('reference', 'cashier_name', 'reason', 'business_date', 'status')
            ).lower()
            if needle and needle not in blob:
                continue
            rows.append(item)
        return rows

    def _apply_filter(self):
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            summary = item.get('summary') or {}
            amount = f"{float(summary.get('total_sales') or 0):,.2f}"
            values = [
                item.get('reference') or '',
                item.get('cashier_name') or '',
                item.get('business_date') or '',
                amount,
                _status_label(item.get('status')),
            ]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self.empty.setVisible(not rows)
        self._shown = rows

    def _open_row(self, index):
        rows = getattr(self, '_shown', [])
        if index < 0 or index >= len(rows):
            return
        detail = self.api.get_backdate_request(rows[index]['id'])
        if not detail or detail.get('error'):
            QMessageBox.warning(self, 'Backdating', (detail or {}).get('error') or 'Could not open the request.')
            return
        self._current = detail
        self.receipt.setPlainText(receipt_text(detail))
        self._set_actions(detail)

    def _set_actions(self, detail):
        status = (detail or {}).get('status')
        own = False
        if detail and self._user_id() is not None:
            own = int(detail.get('cashier_id') or 0) == self._user_id()
        can_review = self._role() in _REVIEW_ROLES and status == 'submitted' and not own
        self.approve_btn.setEnabled(can_review)
        self.reject_btn.setEnabled(can_review)
        self.return_btn.setEnabled(can_review)
        self.withdraw_btn.setEnabled(
            bool(detail) and own and status in ('draft', 'submitted', 'returned')
        )
        if own and status == 'submitted':
            self.approve_btn.setToolTip('You cannot approve your own request.')
        else:
            self.approve_btn.setToolTip('Posts the sale once. Stock and debt change only after this succeeds.')

    def _new_sale(self):
        parent = self.parent()
        self.accept()
        begin = getattr(parent, 'begin_backdated_sale', None)
        if begin:
            begin()

    def _approve(self):
        detail = self._current
        if not detail:
            return
        if QMessageBox.question(
            self, 'Approve backdated sale',
            f"Post {detail.get('reference')} once? This creates the sale, stock movement, and any debt.",
        ) != QMessageBox.Yes:
            return
        result = self.api.approve_backdate_request(detail['id'], detail.get('version'))
        self._after(result, 'Approved. The sale was posted once.')

    def _decide(self, action):
        detail = self._current
        if not detail:
            return
        prompt = 'Why is this request being rejected?' if action == 'reject' else 'What should the cashier correct?'
        reason, ok = QInputDialog.getText(self, 'Backdating', prompt)
        reason = (reason or '').strip()
        if not ok or len(reason) < 3:
            QMessageBox.warning(self, 'Backdating', 'Enter a reason of at least 3 characters.')
            return
        if action == 'reject':
            result = self.api.reject_backdate_request(detail['id'], reason, detail.get('version'))
            message = 'Rejected. No sale, stock movement, or debt was created.'
        else:
            result = self.api.return_backdate_request(detail['id'], reason, detail.get('version'))
            message = 'Returned for correction. Nothing was posted.'
        self._after(result, message)

    def _withdraw(self):
        detail = self._current
        if not detail:
            return
        reason, ok = QInputDialog.getText(self, 'Backdating', 'Why are you withdrawing this request?')
        reason = (reason or '').strip()
        if not ok or not reason:
            return
        result = self.api.withdraw_backdate_request(detail['id'], reason, detail.get('version'))
        self._after(result, 'The request was withdrawn.')

    def _after(self, result, message):
        if not result or result.get('error'):
            QMessageBox.warning(self, 'Backdating', (result or {}).get('error') or 'The request was not saved.')
            return
        self._reload()
        self._current = result
        self.receipt.setPlainText(receipt_text(result))
        self._set_actions(result)
        QMessageBox.information(self, 'Backdating', message)
