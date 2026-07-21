"""
Super Admin — Edit Sale Receipt dialog.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from desktop.utils.theme import C, apply_themed_dialog
from desktop.utils.widgets import DangerBtn, PrimaryBtn, SecondaryBtn


PAY_METHODS = (
    'Cash', 'M-Pesa', 'Card', 'Bank Transfer', 'Credit Sale', 'Part Payment', 'Mixed',
)


class EditSaleDialog(QDialog):
    """Full receipt editor — Super Admin only (caller must gate)."""

    def __init__(self, parent, api, sale: dict, currency: str = 'KES'):
        super().__init__(parent)
        self.api = api
        self.sale = sale or {}
        self.currency = currency
        self.setWindowTitle(f"Edit Sale — {self.sale.get('receipt_number') or ''}")
        self.setMinimumSize(780, 560)
        apply_themed_dialog(self)
        self._products = []
        try:
            self._products = api.get_products() or []
        except Exception:
            self._products = []
        self._customers = []
        try:
            self._customers = api.get_customers() or []
        except Exception:
            self._customers = []
        self._build()
        self._load_sale()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        tip = QLabel(
            'Edit quantities, prices, discounts, payment, and customer. '
            'Inventory and customer balances update when you save.'
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
        lay.addWidget(tip)

        form = QFormLayout()
        self._pay = QComboBox()
        self._pay.addItems(PAY_METHODS)
        form.addRow('Payment method', self._pay)

        self._cust = QComboBox()
        self._cust.addItem('Walk-in Customer', None)
        for c in self._customers:
            label = c.get('name') or f"#{c.get('id')}"
            phone = (c.get('phone') or '').strip()
            if phone:
                label = f'{label}  ·  {phone}'
            self._cust.addItem(label, c.get('id'))
        form.addRow('Customer', self._cust)

        self._header_disc = QDoubleSpinBox()
        self._header_disc.setRange(0, 1_000_000)
        self._header_disc.setDecimals(2)
        self._header_disc.valueChanged.connect(self._recalc)
        form.addRow('Header discount', self._header_disc)

        self._amount_paid = QDoubleSpinBox()
        self._amount_paid.setRange(0, 1_000_000)
        self._amount_paid.setDecimals(2)
        form.addRow('Amount paid', self._amount_paid)

        self._total_lbl = QLabel('—')
        self._total_lbl.setStyleSheet(
            f"color:{C['gold']};font-size:16px;font-weight:800;background:transparent;")
        form.addRow('Total', self._total_lbl)
        lay.addLayout(form)

        # Lines table
        self._tbl = QTableWidget(0, 5)
        self._tbl.setHorizontalHeaderLabels(
            ['Product', 'Qty', 'Unit Price', 'Discount', ''])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 90), (2, 110), (3, 100), (4, 70)):
            self._tbl.setColumnWidth(col, w)
        self._tbl.verticalHeader().setVisible(False)
        lay.addWidget(self._tbl, 1)

        row_btns = QHBoxLayout()
        add_btn = SecondaryBtn('+ Add Product', 36)
        add_btn.clicked.connect(self._add_blank_row)
        row_btns.addWidget(add_btn)
        row_btns.addStretch()
        lay.addLayout(row_btns)

        self._reason = QTextEdit()
        self._reason.setPlaceholderText('Reason for edit (required)…')
        self._reason.setFixedHeight(64)
        lay.addWidget(self._reason)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = PrimaryBtn('Save Changes', 42)
        save.clicked.connect(self._save)
        actions.addWidget(save)
        lay.addLayout(actions)

    def _load_sale(self):
        method = (self.sale.get('payment_method') or 'Cash').strip()
        idx = self._pay.findText(method, Qt.MatchFixedString)
        if idx < 0:
            # fuzzy
            for i in range(self._pay.count()):
                if self._pay.itemText(i).lower() == method.lower():
                    idx = i
                    break
        self._pay.setCurrentIndex(max(0, idx))

        cid = self.sale.get('customer_id')
        if cid is not None:
            cidx = self._cust.findData(int(cid))
            if cidx >= 0:
                self._cust.setCurrentIndex(cidx)

        self._header_disc.setValue(float(self.sale.get('discount') or 0))
        self._amount_paid.setValue(float(self.sale.get('amount_paid') or 0))

        self._tbl.setRowCount(0)
        for it in (self.sale.get('items') or []):
            self._add_row(
                product_id=it.get('product_id'),
                name=it.get('product_name') or '',
                qty=float(it.get('quantity') or 1),
                price=float(it.get('unit_price') or 0),
                disc=float(it.get('discount') or 0),
            )
        if self._tbl.rowCount() == 0:
            self._add_blank_row()
        self._recalc()

    def _add_blank_row(self):
        self._add_row(product_id=None, name='', qty=1, price=0, disc=0)

    def _add_row(self, *, product_id, name, qty, price, disc):
        r = self._tbl.rowCount()
        self._tbl.insertRow(r)

        prod = QComboBox()
        prod.addItem('— select —', None)
        for p in self._products:
            label = p.get('name') or f"#{p.get('id')}"
            sku = (p.get('sku') or '').strip()
            if sku:
                label = f'{label} ({sku})'
            prod.addItem(label, p.get('id'))
            if product_id and p.get('id') == product_id:
                prod.setCurrentIndex(prod.count() - 1)
        if product_id and prod.currentData() != product_id:
            # Keep orphan line name
            prod.insertItem(1, name or f'#{product_id}', product_id)
            prod.setCurrentIndex(1)
        prod.currentIndexChanged.connect(lambda *_: self._on_prod_changed(r))
        self._tbl.setCellWidget(r, 0, prod)

        qty_w = QDoubleSpinBox()
        qty_w.setRange(0.001, 1_000_000)
        qty_w.setDecimals(3)
        qty_w.setValue(max(0.001, qty))
        qty_w.valueChanged.connect(self._recalc)
        self._tbl.setCellWidget(r, 1, qty_w)

        price_w = QDoubleSpinBox()
        price_w.setRange(0, 1_000_000)
        price_w.setDecimals(2)
        price_w.setValue(max(0.0, price))
        price_w.valueChanged.connect(self._recalc)
        self._tbl.setCellWidget(r, 2, price_w)

        disc_w = QDoubleSpinBox()
        disc_w.setRange(0, 1_000_000)
        disc_w.setDecimals(2)
        disc_w.setValue(max(0.0, disc))
        disc_w.valueChanged.connect(self._recalc)
        self._tbl.setCellWidget(r, 3, disc_w)

        rm = DangerBtn('✕', 32)
        rm.setFixedWidth(56)
        rm.clicked.connect(lambda *_a, row=r: self._remove_row(row))
        self._tbl.setCellWidget(r, 4, rm)

    def _on_prod_changed(self, row: int):
        prod = self._tbl.cellWidget(row, 0)
        price_w = self._tbl.cellWidget(row, 2)
        if not prod or not price_w:
            return
        pid = prod.currentData()
        if not pid:
            return
        for p in self._products:
            if p.get('id') == pid:
                price_w.setValue(float(p.get('price') or p.get('selling_price') or 0))
                break
        self._recalc()

    def _remove_row(self, row: int):
        # row index may drift after deletes — remove by sender's visual row
        for r in range(self._tbl.rowCount()):
            w = self._tbl.cellWidget(r, 4)
            if w is self.sender() or r == row:
                self._tbl.removeRow(r)
                break
        if self._tbl.rowCount() == 0:
            self._add_blank_row()
        self._recalc()

    def _collect_items(self) -> list:
        items = []
        for r in range(self._tbl.rowCount()):
            prod = self._tbl.cellWidget(r, 0)
            qty_w = self._tbl.cellWidget(r, 1)
            price_w = self._tbl.cellWidget(r, 2)
            disc_w = self._tbl.cellWidget(r, 3)
            if not prod or not qty_w:
                continue
            pid = prod.currentData()
            if pid is None:
                continue
            name = ''
            sku = ''
            for p in self._products:
                if p.get('id') == pid:
                    name = p.get('name') or ''
                    sku = p.get('sku') or ''
                    break
            if not name:
                name = prod.currentText()
            qty = float(qty_w.value())
            price = float(price_w.value() if price_w else 0)
            disc = float(disc_w.value() if disc_w else 0)
            items.append({
                'product_id': int(pid),
                'product_name': name,
                'sku': sku,
                'quantity': qty,
                'unit_price': price,
                'discount': disc,
                'total': round(max(0.0, qty * price - disc), 2),
            })
        return items

    def _recalc(self, *_args):
        items = self._collect_items()
        sub = sum(i['quantity'] * i['unit_price'] for i in items)
        line_disc = sum(i['discount'] for i in items)
        header = float(self._header_disc.value())
        total = max(0.0, sub - header - line_disc)
        self._total_lbl.setText(f'{self.currency} {total:,.2f}')
        return total

    def _save(self):
        reason = (self._reason.toPlainText() or '').strip()
        if not reason:
            QMessageBox.warning(self, 'Required', 'Enter a reason for this edit.')
            return
        items = self._collect_items()
        if not items:
            QMessageBox.warning(self, 'Required', 'Add at least one product line.')
            return
        total = self._recalc()
        payload = {
            'reason': reason,
            'items': items,
            'discount': float(self._header_disc.value()),
            'payment_method': self._pay.currentText(),
            'customer_id': self._cust.currentData(),
            'amount_paid': float(self._amount_paid.value()),
            'total': total,
        }
        res = self.api.edit_sale(int(self.sale['id']), payload)
        if res.get('error'):
            QMessageBox.critical(self, 'Edit Failed', str(res['error']))
            return
        QMessageBox.information(
            self, 'Sale Updated',
            f"Receipt {res.get('receipt_number')} updated.\n"
            f"New total: {self.currency} {float(res.get('total') or 0):,.2f}"
        )
        self.accept()


def prompt_edit_sale(api, parent, *, receipt_prefill: str = '',
                     currency: str = 'KES', user=None) -> bool:
    """Load sale by receipt → edit dialog. Returns True on successful save."""
    from desktop.utils.security import ask_superadmin_pin, require_permission
    from desktop.utils.api_client import _db

    if user is not None and not require_permission(user, 'sales.edit', parent):
        return False

    receipt, ok = _ask_receipt(parent, receipt_prefill)
    if not ok or not receipt:
        return False

    db = _db()
    try:
        row = db.execute(
            "SELECT id, status FROM sales WHERE receipt_number=?", (receipt,)
        ).fetchone()
    finally:
        db.close()
    if not row:
        QMessageBox.warning(parent, 'Not Found', f'No sale found: {receipt}')
        return False
    if (row['status'] or '').lower() != 'completed':
        QMessageBox.warning(parent, 'Cannot Edit', 'Only completed sales can be edited.')
        return False

    if not ask_superadmin_pin(api, parent, reason=f'Edit sale {receipt}'):
        return False

    sale = api.get_sale(int(row['id']))
    if not sale:
        QMessageBox.warning(parent, 'Not Found', f'Could not load sale {receipt}')
        return False

    dlg = EditSaleDialog(parent, api, sale, currency=currency)
    return dlg.exec_() == QDialog.Accepted


def _ask_receipt(parent, prefill: str = ''):
    from PyQt5.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(
        parent, 'Edit Sale', 'Receipt number:',
        text=(prefill or '').strip(),
    )
    return (text or '').strip(), bool(ok)
