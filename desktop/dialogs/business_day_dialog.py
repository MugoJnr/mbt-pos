"""
Business day sales browser — view / copy / open adjust for a selected date.
Manager+ only for backdating; any sales role can view today's list via POS.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QAbstractItemView,
)

from desktop.utils.theme import C, apply_themed_dialog
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn
from desktop.utils.shop_time import shop_today, business_day_iso
from desktop.utils.quiet_ui import soft_warn, info_toast


class BusinessDaySalesDialog(QDialog):
    """List sales for a business day; copy lines into cart or open receipt."""

    RESULT_NONE = 0
    RESULT_COPY = 1
    RESULT_COPY_DAY = 2

    def __init__(self, parent, api, *, day=None, currency='KES', user=None):
        super().__init__(parent)
        self.api = api
        self.user = user or {}
        self.currency = currency
        self.day = business_day_iso(day or shop_today())
        self.selected_sale_id = None
        self.copy_items = []  # list of cart line dicts
        self.copy_mode = self.RESULT_NONE
        self.on_lines = None
        self._added_ids = set()
        self.setWindowTitle(f'Sales — {self.day}')
        self.setMinimumSize(780, 480)
        apply_themed_dialog(self)
        self._build()
        self._reload()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(f'Business day: <b>{self.day}</b>')
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet(
            f"color:{C['text']};font-size:16px;font-weight:600;background:transparent;")
        head.addWidget(title)
        head.addStretch()
        self._sum = QLabel('')
        self._sum.setStyleSheet(
            f"color:{C['text2']};font-size:13px;background:transparent;")
        head.addWidget(self._sum)
        lay.addLayout(head)

        hint = QLabel(
            'View receipts for this day. Copy lines into the cart for a new sale '
            'on the selected business day. Adjust uses existing Edit (Super Admin).'
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{C['muted']};font-size:12px;background:transparent;")
        lay.addWidget(hint)

        self._tbl = QTableWidget(0, 6)
        self._tbl.setHorizontalHeaderLabels(
            ['Receipt', 'Time', 'Cashier', 'Total', 'Pay', 'Status'])
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._tbl.doubleClicked.connect(self._view_selected)
        lay.addWidget(self._tbl, 1)

        row = QHBoxLayout()
        self._view_btn = SecondaryBtn('View / Adjust', 36)
        self._view_btn.clicked.connect(self._view_selected)
        self._copy_btn = PrimaryBtn('Add this sale', 36)
        self._copy_btn.setToolTip(
            'Put this receipt’s lines into the cart. You can change quantity, '
            'price and discount, then add another receipt as well.')
        self._copy_btn.clicked.connect(lambda: self._copy_selected(replace=False))
        self._replace_btn = SecondaryBtn('Replace cart', 36)
        self._replace_btn.setToolTip('Clear the cart and use only this receipt’s lines')
        self._replace_btn.clicked.connect(lambda: self._copy_selected(replace=True))
        self._copy_day_btn = SecondaryBtn('Add every sale this day', 36)
        self._copy_day_btn.setToolTip(
            'Add each completed sale from this day. Lines already copied are not added twice.')
        self._copy_day_btn.clicked.connect(self._copy_day)
        close_btn = SecondaryBtn('Close', 36)
        close_btn.clicked.connect(self.reject)
        row.addWidget(self._view_btn)
        row.addWidget(self._copy_btn)
        row.addWidget(self._replace_btn)
        row.addWidget(self._copy_day_btn)
        row.addStretch()
        row.addWidget(close_btn)
        lay.addLayout(row)
        self._added = QLabel('Pick a receipt. Added lines stay in the cart, where you can edit them.')
        self._added.setWordWrap(True)
        self._added.setStyleSheet(
            f"color:{C['muted']};font-size:12px;background:transparent;")
        lay.addWidget(self._added)

    def _reload(self):
        sales = []
        try:
            sales = self.api.get_sales(self.day, self.day) or []
        except Exception as e:
            QMessageBox.warning(self, 'Load Failed', str(e))
        self._rows = sales
        self._tbl.setRowCount(0)
        completed_total = 0.0
        completed_n = 0
        for s in sales:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            created = str(s.get('created_at') or '')
            time_s = created[11:16] if len(created) >= 16 else ''
            total = float(s.get('total') or 0)
            status = (s.get('status') or 'completed').lower()
            if status in ('completed', 'return'):
                completed_total += total
                completed_n += 1
            from desktop.utils.payment_tenders import format_sale_payment
            vals = [
                s.get('receipt_number') or '',
                time_s,
                s.get('cashier_name') or '',
                f"{self.currency} {total:,.2f}",
                format_sale_payment(s),
                status,
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.UserRole, s.get('id'))
                if c in (1, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self._tbl.setItem(r, c, item)
        self._sum.setText(
            f'{completed_n} sale(s) · {self.currency} {completed_total:,.2f} completed'
        )

    def _selected_sale_id(self):
        rows = self._tbl.selectionModel().selectedRows() if self._tbl.selectionModel() else []
        if not rows:
            return None
        item = self._tbl.item(rows[0].row(), 0)
        if not item:
            return None
        sid = item.data(Qt.UserRole)
        return int(sid) if sid is not None else None

    def _view_selected(self):
        sid = self._selected_sale_id()
        if not sid:
            soft_warn(self, 'Choose a sale row first.')
            return
        from desktop.dialogs.receipt_detail_dialog import open_receipt_detail
        edited = open_receipt_detail(
            self.api, self, sale_id=sid,
            currency=self.currency, user=self.user,
        )
        if edited:
            self._reload()

    def _lines_from_sale(self, sale: dict) -> list:
        from desktop.utils.copy_sale import copied_cart_lines
        return copied_cart_lines(sale.get('items') or [])

    def _deliver(self, items, *, sale_id, copy_day, replace, customer_id, receipt):
        self.selected_sale_id = sale_id
        self.copy_items = items
        self.copy_mode = self.RESULT_COPY_DAY if copy_day else self.RESULT_COPY
        if callable(self.on_lines):
            self.on_lines(items, {
                'sale_id': sale_id,
                'copy_day': copy_day,
                'replace': replace,
                'customer_id': customer_id,
                'receipt': receipt or '',
            })
            if sale_id:
                self._added_ids.add(int(sale_id))
            label = receipt or (f'sale #{sale_id}' if sale_id else 'those sales')
            self._added.setText(
                f'Added {label}. Change the quantity, price or discount in the cart, '
                'or pick another receipt.')
            return
        self.accept()

    def _copy_selected(self, replace=False):
        sid = self._selected_sale_id()
        if not sid:
            soft_warn(self, 'Choose a sale to copy.')
            return
        sale = self.api.get_sale(sid) or {}
        status = (sale.get('status') or 'completed').lower()
        if status not in ('completed', ''):
            soft_warn(self, 'Only a completed sale can be copied.')
            return
        items = self._lines_from_sale(sale)
        if not items:
            soft_warn(self, 'That sale has no line items to copy.')
            return
        self._deliver(
            items, sale_id=sid, copy_day=False, replace=bool(replace),
            customer_id=sale.get('customer_id'),
            receipt=sale.get('receipt_number') or '',
        )

    def _copy_day(self):
        items = []
        added = []
        for s in self._rows or []:
            status = (s.get('status') or 'completed').lower()
            if status not in ('completed', ''):
                continue
            sid = s.get('id')
            if not sid or int(sid) in self._added_ids:
                continue
            sale = self.api.get_sale(int(sid)) or {}
            if (sale.get('status') or 'completed').lower() not in ('completed', ''):
                continue
            lines = self._lines_from_sale(sale)
            if not lines:
                continue
            items.extend(lines)
            added.append(int(sid))
        if not items:
            info_toast(self, 'No further completed sales to add from this day.')
            return
        self._deliver(
            items, sale_id=None, copy_day=True, replace=False,
            customer_id=None, receipt=f'{len(added)} sales',
        )
        self._added_ids.update(added)


def open_business_day_sales(api, parent, *, day=None, currency='KES', user=None, on_lines=None):
    """Show dialog; returns (mode, items, sale_id) or (0, [], None)."""
    dlg = BusinessDaySalesDialog(
        parent, api, day=day, currency=currency, user=user)
    dlg.on_lines = on_lines
    if dlg.exec_() != QDialog.Accepted:
        return BusinessDaySalesDialog.RESULT_NONE, [], None
    return dlg.copy_mode, dlg.copy_items, dlg.selected_sale_id
