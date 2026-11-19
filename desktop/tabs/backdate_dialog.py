"""Request list for backdated sales. New sales use the normal till cart."""
from PyQt5.QtCore import QDate, Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
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


def _ksh(amount) -> str:
    return f"KSh {float(amount or 0):,.2f}"


def receipt_text(detail: dict) -> str:
    """Readable proposed receipt. This is the request, not a completed sale."""
    if not detail:
        return 'Select a request to see the proposed receipt.'
    summary = detail.get('summary') or {}
    lines = []
    banner = detail.get('disapproval') or {}
    if banner:
        lines.extend([
            banner.get('headline') or 'PREVIOUSLY APPROVED — SUBSEQUENTLY DISAPPROVED',
            f"Originally approved: {banner.get('approved_at') or '—'} by {banner.get('approved_by') or '—'}",
            f"Disapproved: {banner.get('disapproved_at') or '—'} by {banner.get('disapproved_by') or '—'}",
            f"Disapproval reason: {banner.get('reason') or '—'}",
            f"Original transaction: {banner.get('sale_reference') or '—'}",
            'The previous posting was reversed. The request is waiting for review again.',
            '',
        ])
    lines.extend([
        f"{detail.get('reference') or 'Request'}  ·  {_status_label(detail.get('status'))}",
        f"Cashier: {detail.get('cashier_name') or '—'}",
        f"Requested business date: {detail.get('business_date') or '—'}",
        f"Submitted: {detail.get('submitted_at') or 'Not submitted'}",
        f"Created: {detail.get('created_at') or '—'}",
        f"Reason: {detail.get('reason') or '—'}",
    ])
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


def open_backdated_sale(start) -> bool:
    """Start a past-day cart on Point of Sale.

    The request list now opens from Receipts. The cart still lives on the sales
    tab, so the walk has to leave the dialog's immediate parent.
    """
    widget = start
    host = None
    sales = None
    while widget is not None:
        if callable(getattr(widget, 'begin_backdated_sale', None)):
            sales = widget
        if callable(getattr(widget, '_goto', None)):
            host = widget
        parent = getattr(widget, 'parent', None)
        widget = parent() if callable(parent) else None
    if host is not None:
        host._goto('sales')
        tab = (getattr(host, '_tabs', {}) or {}).get('sales')
        if tab is not None and callable(getattr(tab, 'begin_backdated_sale', None)):
            sales = tab
    if sales is None:
        return False
    sales.begin_backdated_sale()
    return True


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
        self._timer = QTimer(self)
        self._timer.setInterval(20000)
        self._timer.timeout.connect(self._refresh_quiet)
        self._timer.start()
        self._reload()

    def closeEvent(self, event):
        timer = getattr(self, '_timer', None)
        if timer is not None:
            timer.stop()
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
        self.freshness = QLabel('Loading requests…')
        self.freshness.setWordWrap(True)
        root.addWidget(self.freshness)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search reference, cashier, or reason')
        self.search.textChanged.connect(self._apply_filter)
        self.date_filter = QComboBox()
        for value, label in (
            ('all', 'All dates'),
            ('today', 'Today'),
            ('yesterday', 'Yesterday'),
            ('date', 'Selected date'),
        ):
            self.date_filter.addItem(label, value)
        self.date_filter.currentIndexChanged.connect(self._date_mode_changed)
        self.day_edit = QDateEdit()
        self.day_edit.setCalendarPopup(True)
        self.day_edit.setDisplayFormat('dd MMM yyyy')
        self.day_edit.setDate(QDate.currentDate().addDays(-1))
        self.day_edit.setVisible(False)
        self.day_edit.dateChanged.connect(lambda *_: self._reload())
        self.reset_dates = QPushButton('Reset date filter')
        self.reset_dates.clicked.connect(self._reset_dates)
        self.group_toggle = QCheckBox('Group by requested sales date')
        self.group_toggle.setChecked(True)
        self.group_toggle.toggled.connect(lambda *_: self._apply_filter())
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
        self.status_filter.currentIndexChanged.connect(lambda *_: self._reload())
        new_btn = QPushButton('New Backdated Sale')
        new_btn.clicked.connect(self._new_sale)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self._reload)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.status_filter)
        tools.addWidget(self.date_filter)
        tools.addWidget(self.day_edit)
        tools.addWidget(self.reset_dates)
        tools.addWidget(refresh)
        tools.addWidget(new_btn)
        root.addLayout(tools)
        group_tools = QHBoxLayout()
        group_tools.addWidget(self.group_toggle)
        self.approve_all_btn = QPushButton('Approve all pending')
        self.approve_all_btn.clicked.connect(self._approve_all)
        self.approve_day_btn = QPushButton('Approve all for selected day')
        self.approve_day_btn.clicked.connect(self._approve_selected_day)
        group_tools.addWidget(self.approve_all_btn)
        group_tools.addWidget(self.approve_day_btn)
        group_tools.addStretch(1)
        root.addLayout(group_tools)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.group_host = QWidget()
        self.group_layout = QVBoxLayout(self.group_host)
        self.group_layout.setContentsMargins(0, 0, 0, 0)
        self.group_layout.addStretch(1)
        self.group_scroll = QScrollArea()
        self.group_scroll.setWidgetResizable(True)
        self.group_scroll.setWidget(self.group_host)
        left.addWidget(self.group_scroll, 1)
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
        self.disapprove_btn = QPushButton('Disapprove approved sale')
        self.approve_btn.clicked.connect(self._approve)
        self.reject_btn.clicked.connect(lambda: self._decide('reject'))
        self.return_btn.clicked.connect(lambda: self._decide('return'))
        self.withdraw_btn.clicked.connect(self._withdraw)
        self.disapprove_btn.clicked.connect(self._disapprove)
        for button in (
            self.approve_btn, self.return_btn, self.reject_btn,
            self.disapprove_btn, self.withdraw_btn,
        ):
            actions.addWidget(button)
        right.addLayout(actions)
        close = QPushButton('Back to till')
        close.clicked.connect(self.accept)
        right.addWidget(close)
        body.addLayout(right, 4)
        root.addLayout(body, 1)
        self._set_actions(None)

    def _refresh_quiet(self):
        """While this list is open, pick up a decision made on the web. A closed dialog does not poll."""
        self._reload(quiet=True)

    def _date_params(self) -> dict:
        mode = self.date_filter.currentData() or 'all'
        if mode == 'date':
            day = self.day_edit.date()
            return {'business_date': f"{day.year():04d}-{day.month():02d}-{day.day():02d}"}
        if mode in ('today', 'yesterday'):
            return {'date': mode}
        return {'date': 'all'}

    def _date_mode_changed(self):
        self.day_edit.setVisible((self.date_filter.currentData() or '') == 'date')
        self._reload()

    def _reset_dates(self):
        self.date_filter.setCurrentIndex(0)
        self.day_edit.setDate(QDate.currentDate().addDays(-1))

    def _reload(self, quiet=False):
        filters = {'status': self.status_filter.currentData() or ''}
        filters.update(self._date_params())
        result = self.api.list_backdate_requests(filters) or {}
        if result.get('error'):
            self.freshness.setText('Could not refresh. This list may be out of date.')
            if not quiet:
                QMessageBox.warning(self, 'Backdating', result['error'])
            return
        open_id = (self._current or {}).get('id')
        open_status = (self._current or {}).get('status')
        self._rows = result.get('requests') or []
        self._groups = result.get('groups') or []
        self._pending_count = int(result.get('pending_count') or 0)
        self._pending_total = float(result.get('pending_total') or 0)
        self.freshness.setText('Updated just now.')
        self.table.blockSignals(True)
        try:
            self._apply_filter()
        finally:
            self.table.blockSignals(False)
        if not quiet:
            self._current = None
            self.receipt.setPlainText('Select a request to see the proposed receipt.')
            self._set_actions(None)
            return
        if not open_id:
            return
        match = next((row for row in self._rows if row.get('id') == open_id), None)
        if match is None or match.get('status') != open_status:
            detail = self.api.get_backdate_request(open_id) or {}
            if detail.get('error'):
                self.freshness.setText('Could not refresh the open request. Do not treat it as current.')
                return
            self._current = detail
            self.receipt.setPlainText(receipt_text(detail))
            self._set_actions(detail)

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
        self.empty.setVisible(not rows and not self.group_toggle.isChecked())
        self._shown = rows
        self._render_groups(rows)
        reviewing = self._role() in _REVIEW_ROLES
        self.approve_all_btn.setEnabled(reviewing and self._pending_count > 0)
        selected_day = (self._date_params().get('business_date') or '')
        if self._date_params().get('date') == 'yesterday':
            selected_day = next((group.get('business_date') for group in self._groups), '')
        day_group = next((group for group in self._groups if group.get('business_date') == selected_day), None)
        self.approve_day_btn.setEnabled(bool(reviewing and day_group and day_group.get('eligible_count')))
        self.approve_day_btn.setText(
            f"Approve all for {selected_day}" if selected_day else 'Approve all for selected day'
        )

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
        self.disapprove_btn.setEnabled(
            self._role() in _REVIEW_ROLES and status == 'approved' and not own
        )
        if own and status == 'submitted':
            self.approve_btn.setToolTip('You cannot approve your own request.')
        else:
            self.approve_btn.setToolTip('Posts the sale once. Stock and debt change only after this succeeds.')
        self.disapprove_btn.setToolTip(
            'Reverses the posted sale and returns the request to pending review.'
        )

    def _new_sale(self):
        parent = self.parent()
        self.accept()
        if not open_backdated_sale(parent):
            QMessageBox.warning(
                parent,
                'Backdating',
                'Point of Sale is not open, so the past-day cart could not start.',
            )

    def _render_groups(self, rows):
        while self.group_layout.count():
            item = self.group_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not self.group_toggle.isChecked():
            self.group_scroll.setVisible(False)
            return
        self.group_scroll.setVisible(True)
        buckets = {}
        for item in rows:
            if item.get('status') != 'submitted':
                continue
            day = item.get('business_date') or 'No date'
            bucket = buckets.setdefault(day, {'count': 0, 'total': 0.0})
            bucket['count'] += 1
            bucket['total'] += float((item.get('summary') or {}).get('total_sales') or 0)
        if not buckets:
            empty = QLabel('No pending requests in this list to group.')
            empty.setWordWrap(True)
            self.group_layout.addWidget(empty)
        for day in sorted(buckets, reverse=True):
            bucket = buckets[day]
            label = QLabel(f"{day}  ·  {bucket['count']} pending  ·  {_ksh(bucket['total'])}")
            label.setWordWrap(True)
            self.group_layout.addWidget(label)
        self.group_layout.addStretch(1)

    def _approve_all(self):
        if self._pending_count <= 0:
            return
        if QMessageBox.question(
            self, 'Approve all pending',
            f"Approve {self._pending_count} pending request(s) totalling {_ksh(self._pending_total)}?\n"
            'Each request is posted on its own. A failure does not undo the ones that already posted.',
        ) != QMessageBox.Yes:
            return
        self._after_bulk(self.api.bulk_approve_backdate_requests('all', ''))

    def _approve_selected_day(self):
        params = self._date_params()
        day = params.get('business_date') or ''
        if params.get('date') == 'yesterday':
            day = next(
                (group.get('business_date') for group in self._groups if group.get('eligible_count')),
                '',
            )
        group = next((item for item in self._groups if item.get('business_date') == day), None)
        if not group or not group.get('eligible_count'):
            QMessageBox.warning(
                self, 'Backdating',
                'Choose a requested sales date that still has requests you can approve.',
            )
            return
        if QMessageBox.question(
            self, 'Approve one day',
            f"Approve {group.get('eligible_count')} request(s) for {day} "
            f"totalling {_ksh(group.get('eligible_total'))}?\n"
            'Each request is posted on its own.',
        ) != QMessageBox.Yes:
            return
        self._after_bulk(self.api.bulk_approve_backdate_requests('day', day))

    def _after_bulk(self, result):
        if not result or result.get('error'):
            QMessageBox.warning(self, 'Backdating', (result or {}).get('error') or 'Nothing was approved.')
            self._reload()
            return
        self._reload()
        QMessageBox.information(
            self, 'Backdating',
            f"Approved {result.get('approved', 0)}. "
            f"Failed {result.get('failed', 0)}. "
            f"Skipped {result.get('skipped', 0)}. "
            f"Posted {_ksh(result.get('approved_total'))}.",
        )

    def _disapprove(self):
        detail = self._current
        if not detail or detail.get('status') != 'approved':
            return
        reason, ok = QInputDialog.getText(
            self, 'Disapprove approved sale', 'Why is this approved sale being reversed?',
        )
        reason = (reason or '').strip()
        if not ok or len(reason) < 3:
            QMessageBox.warning(self, 'Backdating', 'Enter a reason of at least 3 characters.')
            return
        if QMessageBox.question(
            self, 'Disapprove approved sale',
            'This reverses the posted sale, stock, and debt, and returns the request to pending. '
            'The original receipt stays in history.',
        ) != QMessageBox.Yes:
            return
        result = self.api.disapprove_backdate_request(detail['id'], reason, detail.get('version'))
        self._after(result, 'Disapproved. The posted sale was reversed and the request is pending again.')

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
