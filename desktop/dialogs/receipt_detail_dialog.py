"""
Receipt detail viewer — any sale status (completed / voided).
Super Admin can Edit (incl. reinstate voided) from here.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from desktop.utils.theme import C, apply_themed_dialog
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, DangerBtn


class ReceiptDetailDialog(QDialog):
    """Full receipt with line items. Edit/Void actions when permitted."""

    def __init__(self, parent, api, sale: dict, *, currency: str = 'KES', user=None):
        super().__init__(parent)
        self.api = api
        self.sale = sale or {}
        self.currency = currency
        self.user = user or {}
        self.edited = False
        rn = self.sale.get('receipt_number') or self.sale.get('id') or ''
        self.setWindowTitle(f'Receipt — {rn}')
        self.setMinimumSize(720, 520)
        apply_themed_dialog(self)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        status = (self.sale.get('status') or 'completed').lower()
        badge_color = C['err'] if status in ('void', 'voided') else C.get('ok', C.get('accent', '#27AE60'))
        title = QLabel(f"Receipt {self.sale.get('receipt_number') or ''}")
        title.setStyleSheet(
            f"color:{C['text']};font-size:18px;font-weight:800;background:transparent;")
        lay.addWidget(title)

        meta = QLabel(
            f"<b>Status:</b> <span style='color:{badge_color}'>{status.upper()}</span> &nbsp; "
            f"<b>Date:</b> {(self.sale.get('created_at') or '')[:19]} &nbsp; "
            f"<b>Cashier:</b> {self.sale.get('cashier_name') or '—'}<br>"
            f"<b>Payment:</b> {self.sale.get('payment_method') or '—'} &nbsp; "
            f"<b>Customer:</b> {self.sale.get('customer_name') or 'Walk-in'} "
            f"{('· ' + self.sale.get('customer_phone')) if self.sale.get('customer_phone') else ''}<br>"
            f"<b>Subtotal:</b> {self.currency} {float(self.sale.get('subtotal') or 0):,.2f} &nbsp; "
            f"<b>Discount:</b> {self.currency} {float(self.sale.get('discount') or 0):,.2f} &nbsp; "
            f"<b>Tax:</b> {self.currency} {float(self.sale.get('tax') or 0):,.2f}<br>"
            f"<b>Total:</b> <span style='color:{C.get('gold', C['text'])};font-size:15px'>"
            f"{self.currency} {float(self.sale.get('total') or 0):,.2f}</span> &nbsp; "
            f"<b>Paid:</b> {self.currency} {float(self.sale.get('amount_paid') or 0):,.2f}"
        )
        meta.setTextFormat(Qt.RichText)
        meta.setWordWrap(True)
        meta.setStyleSheet(
            f"color:{C['text']};font-size:13px;background:{C.get('card', '#1E2A38')};"
            f"border:1px solid {C['border']};border-radius:10px;padding:12px;")
        lay.addWidget(meta)

        notes = (self.sale.get('notes') or '').strip()
        if notes:
            nl = QLabel(f"<b>Notes:</b> {notes}")
            nl.setWordWrap(True)
            nl.setTextFormat(Qt.RichText)
            nl.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
            lay.addWidget(nl)

        items = self.sale.get('items') or []
        tbl = QTableWidget(len(items), 5)
        tbl.setHorizontalHeaderLabels(['Product', 'Qty', 'Unit Price', 'Discount', 'Line Total'])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        for r, it in enumerate(items):
            vals = [
                it.get('product_name') or '—',
                f"{float(it.get('quantity') or 0):g}",
                f"{float(it.get('unit_price') or 0):,.2f}",
                f"{float(it.get('discount') or 0):,.2f}",
                f"{float(it.get('total') or 0):,.2f}",
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c > 0:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                tbl.setItem(r, c, cell)
        if not items:
            tbl.setRowCount(1)
            empty = QTableWidgetItem('No line items on this receipt')
            empty.setFlags(Qt.ItemIsEnabled)
            tbl.setItem(0, 0, empty)
            tbl.setSpan(0, 0, 1, 5)
        lay.addWidget(tbl, 1)

        # Linked debt snapshot if present
        debt = self.sale.get('debt') or {}
        if debt:
            dl = QLabel(
                f"<b>Linked debt:</b> {debt.get('invoice_number') or '—'} · "
                f"status {debt.get('status') or '—'} · "
                f"balance {self.currency} {float(debt.get('balance') or 0):,.2f}"
            )
            dl.setTextFormat(Qt.RichText)
            dl.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
            lay.addWidget(dl)

        btns = QHBoxLayout()
        btns.addStretch()

        role = (self.user.get('role') or '').lower()
        is_voided = status in ('void', 'voided')

        if role == 'superadmin':
            edit_lbl = 'Reinstate & Edit…' if is_voided else 'Edit Sale…'
            edit_b = PrimaryBtn(edit_lbl, 40)
            edit_b.clicked.connect(self._edit)
            btns.addWidget(edit_b)

        if not is_voided:
            try:
                from desktop.utils.security import can_void_sales
                if can_void_sales(self.user):
                    void_b = DangerBtn('Void Sale…', 40)
                    void_b.clicked.connect(self._void)
                    btns.addWidget(void_b)
            except Exception:
                pass

        close_b = SecondaryBtn('Close', 40)
        close_b.clicked.connect(self.reject)
        btns.addWidget(close_b)
        lay.addLayout(btns)

    def _edit(self):
        from desktop.dialogs.edit_sale_dialog import prompt_edit_sale
        rn = self.sale.get('receipt_number') or ''
        ok = prompt_edit_sale(
            self.api, self, receipt_prefill=rn,
            currency=self.currency, user=self.user,
            allow_voided=True,
        )
        if ok:
            self.edited = True
            # Reload and refresh UI
            try:
                fresh = self.api.get_sale(int(self.sale['id'])) or {}
                if fresh:
                    self.sale = fresh
            except Exception:
                pass
            self.accept()

    def _void(self):
        from desktop.utils.security import prompt_void_sale
        rn = self.sale.get('receipt_number') or ''
        if prompt_void_sale(self.api, self, receipt_prefill=rn):
            self.edited = True
            self.accept()


def open_receipt_detail(api, parent, *, sale_id=None, receipt: str = '',
                        currency: str = 'KES', user=None) -> bool:
    """Resolve sale by id or receipt number and show detail. Returns True if edited."""
    sale = {}
    if sale_id:
        try:
            sale = api.get_sale(int(sale_id)) or {}
        except Exception:
            sale = {}
    if not sale and receipt:
        from desktop.utils.api_client import _db
        db = _db()
        try:
            row = db.execute(
                "SELECT id FROM sales WHERE receipt_number=?", (receipt.strip(),)
            ).fetchone()
        finally:
            db.close()
        if row:
            sale = api.get_sale(int(row['id'])) or {}
    if not sale:
        QMessageBox.warning(parent, 'Not Found', 'Could not load that receipt.')
        return False
    dlg = ReceiptDetailDialog(parent, api, sale, currency=currency, user=user)
    dlg.exec_()
    return bool(dlg.edited)
