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
        self._copy_btn = PrimaryBtn('Copy Sale → Cart', 36)
        self._copy_btn.setToolTip(
            'Copy line items (product, qty, price, discount) into the POS cart')
        self._copy_btn.clicked.connect(self._copy_selected)
        self._copy_day_btn = SecondaryBtn('Copy Day Totals → Cart', 36)
        self._copy_day_btn.setToolTip(
            'Merge all completed sales lines from this day into the cart')
        self._copy_day_btn.clicked.connect(self._copy_day)
        close_btn = SecondaryBtn('Close', 36)
        close_btn.clicked.connect(self.reject)
        row.addWidget(self._view_btn)
        row.addWidget(self._copy_btn)
        row.addWidget(self._copy_day_btn)
        row.addStretch()
        row.addWidget(close_btn)
        lay.addLayout(row)

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
            vals = [
                s.get('receipt_number') or '',
                time_s,
                s.get('cashier_name') or '',
                f"{self.currency} {total:,.2f}",
                s.get('payment_method') or '',
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
            QMessageBox.information(self, 'Select a Sale', 'Choose a sale row first.')
            return
        from desktop.dialogs.receipt_detail_dialog import open_receipt_detail
        edited = open_receipt_detail(
            self.api, self, sale_id=sid,
            currency=self.currency, user=self.user,
        )
        if edited:
            self._reload()

    def _lines_from_sale(self, sale: dict) -> list:
        out = []
        for it in sale.get('items') or []:
            qty = float(it.get('quantity') or 0)
            if qty <= 0:
                continue
            unit = float(it.get('unit_price') or 0)
            disc = float(it.get('discount') or 0)
            total = float(it.get('total') or max(0.0, qty * unit - disc))
            out.append({
                'product_id': it.get('product_id'),
                'product_name': it.get('product_name') or '',
                'sku': it.get('sku') or '',
                'quantity': qty,
                'unit_price': unit,
                'discount': disc,
                'total': total,
            })
        return out

    def _copy_selected(self):
        sid = self._selected_sale_id()
        if not sid:
            QMessageBox.information(self, 'Select a Sale', 'Choose a sale to copy.')
            return
        sale = self.api.get_sale(sid) or {}
        items = self._lines_from_sale(sale)
        if not items:
            QMessageBox.warning(self, 'Empty', 'That sale has no line items to copy.')
            return
        self.selected_sale_id = sid
        self.copy_items = items
        self.copy_mode = self.RESULT_COPY
        self.accept()

    def _copy_day(self):
        items = []
        for s in self._rows or []:
            status = (s.get('status') or '').lower()
            if status not in ('completed', 'return', ''):
                continue
            sid = s.get('id')
            if not sid:
                continue
            sale = self.api.get_sale(int(sid)) or {}
            items.extend(self._lines_from_sale(sale))
        if not items:
            QMessageBox.information(
                self, 'Nothing to Copy',
                'No completed sale lines on this business day.')
            return
        # Merge identical product lines (same product_id + unit_price)
        merged = {}
        for it in items:
            key = (it.get('product_id'), round(float(it.get('unit_price') or 0), 4))
            if key not in merged:
                merged[key] = dict(it)
            else:
                m = merged[key]
                m['quantity'] = round(float(m['quantity']) + float(it['quantity']), 2)
                m['discount'] = round(float(m['discount']) + float(it['discount']), 2)
                m['total'] = round(float(m['total']) + float(it['total']), 2)
        self.copy_items = list(merged.values())
        self.selected_sale_id = None
        self.copy_mode = self.RESULT_COPY_DAY
        self.accept()


def open_business_day_sales(api, parent, *, day=None, currency='KES', user=None):
    """Show dialog; returns (mode, items, sale_id) or (0, [], None)."""
    dlg = BusinessDaySalesDialog(
        parent, api, day=day, currency=currency, user=user)
    if dlg.exec_() != QDialog.Accepted:
        return BusinessDaySalesDialog.RESULT_NONE, [], None
    return dlg.copy_mode, dlg.copy_items, dlg.selected_sale_id
