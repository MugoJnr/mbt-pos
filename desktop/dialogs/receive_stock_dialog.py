"""Suppliers list + receive stock dialogs (V05 receiving MVP)."""
import uuid

from desktop.utils.quiet_ui import info_toast

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QComboBox, QFormLayout,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C, ThemeManager
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn
from desktop.utils.dialog_keys import wire_dialog_keys


class SuppliersDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle('Suppliers')
        self.setMinimumSize(820, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        self._name = QLineEdit(); self._name.setMinimumHeight(36)
        self._phone = QLineEdit(); self._phone.setMinimumHeight(36)
        self._notes = QLineEdit(); self._notes.setMinimumHeight(36)
        form.addRow('Name', self._name)
        form.addRow('Phone', self._phone)
        form.addRow('Notes', self._notes)
        lay.addLayout(form)

        add_row = QHBoxLayout()
        add_btn = PrimaryBtn('Add Supplier', 40)
        add_btn.clicked.connect(self._add)
        add_row.addStretch(1)
        add_row.addWidget(add_btn)
        lay.addLayout(add_row)

        self._tbl = QTableWidget(0, 3)
        self._tbl.setHorizontalHeaderLabels(['Name', 'Phone', 'Notes'])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self._tbl, 1)

        hist = QLabel('Supplier Delivery History')
        hist.setStyleSheet(f"color:{C['text']}; font-size:15px; font-weight:700;")
        lay.addWidget(hist)
        self._hist = QTableWidget(0, 7)
        self._hist.setHorizontalHeaderLabels(
            ['GRN', 'Date', 'Supplier', 'Vendor Ref', 'Payment', 'Lines', 'Total'])
        self._hist.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._hist.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist.doubleClicked.connect(self._show_purchase)
        lay.addWidget(self._hist, 1)

        close = SecondaryBtn('Close', 40)
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        wire_dialog_keys(self, primary=add_btn, cancel=close)
        self._reload()

    def _reload(self):
        rows = self.api.get_suppliers() or []
        self._tbl.setRowCount(0)
        for s in rows:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            self._tbl.setItem(r, 0, QTableWidgetItem(str(s.get('name') or '')))
            self._tbl.setItem(r, 1, QTableWidgetItem(str(s.get('phone') or '')))
            self._tbl.setItem(r, 2, QTableWidgetItem(str(s.get('notes') or '')))
        self._hist.setRowCount(0)
        for purchase in (self.api.get_purchases(limit=300) or []):
            row = self._hist.rowCount()
            self._hist.insertRow(row)
            values = (
                purchase.get('purchase_number') or '',
                purchase.get('delivery_date') or '',
                purchase.get('supplier_name') or '',
                purchase.get('reference') or '',
                purchase.get('payment_method') or 'credit',
                purchase.get('line_count') or 0,
                f"{float(purchase.get('total') or 0):,.2f}",
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, purchase.get('id'))
                if col in (5, 6):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._hist.setItem(row, col, item)

    def _show_purchase(self, _index=None):
        row = self._hist.currentRow()
        item = self._hist.item(row, 0) if row >= 0 else None
        purchase_id = item.data(Qt.UserRole) if item else None
        if not purchase_id:
            return
        result = self.api.get_purchase(int(purchase_id)) or {}
        purchase = result.get('purchase') or {}
        lines = [
            f"{line.get('product_name')} · {float(line.get('quantity') or 0):g} "
            f"× {float(line.get('unit_cost') or 0):,.2f} "
            f"= {float(line.get('total') or 0):,.2f}"
            for line in (purchase.get('items') or [])
        ]
        QMessageBox.information(
            self, purchase.get('purchase_number') or 'Supplier Delivery',
            f"Supplier: {purchase.get('supplier_name') or '-'}\n"
            f"Date: {purchase.get('delivery_date') or '-'}\n"
            f"Vendor reference: {purchase.get('reference') or '-'}\n\n"
            f"Payment: {purchase.get('payment_method') or 'credit'}\n\n"
            + '\n'.join(lines)
            + f"\n\nTotal: {float(purchase.get('total') or 0):,.2f}",
        )

    def _add(self):
        res = self.api.create_supplier({
            'name': self._name.text(),
            'phone': self._phone.text(),
            'notes': self._notes.text(),
        })
        if res and res.get('success'):
            self._name.clear(); self._phone.clear(); self._notes.clear()
            self._reload()
        else:
            QMessageBox.warning(self, 'Supplier', (res or {}).get('error', 'Failed'))


class ReceiveStockDialog(QDialog):
    def __init__(self, api, parent=None, products: list = None):
        super().__init__(parent)
        self.api = api
        self.products = products or api.get_products() or []
        self._lines = []
        self._client_txn_id = str(uuid.uuid4())
        self.setWindowTitle('Receive Supplier Delivery')
        self.setMinimumSize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        tip = QLabel(
            'Receive one supplier invoice with multiple products. '
            'All lines save together under one GRN and appear as one delivery.')
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(tip)

        form = QFormLayout()
        self._sup = QComboBox(); self._sup.setMinimumHeight(40)
        self._sup.addItem('Select supplier…', None)
        for s in (api.get_suppliers() or []):
            self._sup.addItem(s.get('name') or f"#{s.get('id')}", s.get('id'))
        self._ref = QLineEdit(); self._ref.setMinimumHeight(40)
        self._ref.setPlaceholderText('Vendor invoice / delivery note')
        self._payment = QComboBox(); self._payment.setMinimumHeight(40)
        for label, value in (
            ('Supplier credit / unpaid', 'credit'), ('Paid cash', 'cash'),
            ('Paid M-Pesa', 'mpesa'), ('Paid bank', 'bank'), ('Paid card', 'card'),
        ):
            self._payment.addItem(label, value)
        self._notes = QLineEdit(); self._notes.setMinimumHeight(40)
        form.addRow('Supplier *', self._sup)
        form.addRow('Vendor reference', self._ref)
        form.addRow('Payment', self._payment)
        form.addRow('Delivery notes', self._notes)
        lay.addLayout(form)

        line_form = QFormLayout()
        self._prod = QComboBox(); self._prod.setMinimumHeight(40)
        for p in self.products:
            if not p.get('is_active', 1):
                continue
            label = f"{p.get('name')}  (stock {p.get('stock')})"
            self._prod.addItem(label, p.get('id'))
        self._qty = QDoubleSpinBox()
        self._qty.setRange(0.001, 999999)
        self._qty.setDecimals(3)
        self._qty.setValue(1)
        self._qty.setMinimumHeight(40)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(0.01, 9999999)
        self._cost.setDecimals(2)
        self._cost.setMinimumHeight(40)
        self._prod.currentIndexChanged.connect(self._prefill_cost)
        line_form.addRow('Product', self._prod)
        line_form.addRow('Qty received', self._qty)
        line_form.addRow('Buying price each', self._cost)
        lay.addLayout(line_form)

        line_buttons = QHBoxLayout()
        add_line = SecondaryBtn('Add Product Line', 40)
        add_line.clicked.connect(self._add_line)
        remove_line = SecondaryBtn('Remove Selected', 40)
        remove_line.clicked.connect(self._remove_line)
        new_product = SecondaryBtn('New Product…', 40)
        new_product.clicked.connect(self._new_product)
        line_buttons.addWidget(add_line)
        line_buttons.addWidget(remove_line)
        line_buttons.addWidget(new_product)
        line_buttons.addStretch(1)
        lay.addLayout(line_buttons)

        self._tbl = QTableWidget(0, 4)
        self._tbl.setHorizontalHeaderLabels(
            ['Product', 'Quantity', 'Buy Price', 'Line Total'])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self._tbl, 1)
        self._total = QLabel('Delivery total: 0.00')
        self._total.setAlignment(Qt.AlignRight)
        self._total.setStyleSheet(
            f"color:{C['gold']}; font-size:17px; font-weight:700;")
        lay.addWidget(self._total)
        self._prefill_cost()

        row = QHBoxLayout()
        manage = SecondaryBtn('Suppliers…', 40)
        manage.clicked.connect(self._manage_suppliers)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        go = PrimaryBtn('Receive All as One', 44)
        go.clicked.connect(self._submit)
        row.addWidget(manage)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        wire_dialog_keys(self, primary=go, cancel=cancel)

    def _manage_suppliers(self):
        SuppliersDialog(self.api, self).exec_()
        cur = self._sup.currentData()
        self._sup.clear()
        self._sup.addItem('Select supplier…', None)
        for s in (self.api.get_suppliers() or []):
            self._sup.addItem(s.get('name') or f"#{s.get('id')}", s.get('id'))
        idx = self._sup.findData(cur)
        if idx >= 0:
            self._sup.setCurrentIndex(idx)

    def _new_product(self):
        """Register a first-time item without leaving the delivery.

        The buying price is captured once here and carried onto the line, so it
        is never entered twice for the same delivery.
        """
        dlg = _NewProductDlg(self, suggested_cost=float(self._cost.value()))
        if dlg.exec_() != QDialog.Accepted:
            return
        payload = dlg.payload()
        res = self.api.create_product(payload) or {}
        if not res.get('success'):
            QMessageBox.critical(
                self, 'Error', res.get('error') or 'Product could not be registered.')
            return
        pid = int(res.get('id') or 0)
        product = {
            'id': pid,
            'name': payload['name'],
            'sku': payload.get('sku') or '',
            'cost_price': payload['cost_price'],
            'price': payload['price'],
            'stock': 0,
            'is_active': 1,
        }
        self.products.append(product)
        self._prod.addItem(f"{product['name']}  (stock 0)", pid)
        self._prod.setCurrentIndex(self._prod.count() - 1)
        self._cost.setValue(payload['cost_price'])
        info_toast(self, f"{payload['name']} registered · add the quantity received")

    def _prefill_cost(self):
        pid = self._prod.currentData()
        product = next(
            (p for p in self.products if int(p.get('id') or 0) == int(pid or 0)),
            None,
        )
        if product:
            self._cost.setValue(max(0.01, float(product.get('cost_price') or 0.01)))

    def _add_line(self):
        pid = int(self._prod.currentData() or 0)
        if not pid:
            QMessageBox.warning(self, 'Required', 'Select a product.')
            return
        if any(line['product_id'] == pid for line in self._lines):
            QMessageBox.warning(
                self, 'Duplicate product',
                'This product is already on the delivery. Remove it or edit the line.')
            return
        product = next(
            (p for p in self.products if int(p.get('id') or 0) == pid), {})
        line = {
            'product_id': pid,
            'product_name': product.get('name') or f'#{pid}',
            'quantity': float(self._qty.value()),
            'unit_cost': float(self._cost.value()),
        }
        self._lines.append(line)
        self._render_lines()
        self._qty.setValue(1)

    def _remove_line(self):
        row = self._tbl.currentRow()
        if 0 <= row < len(self._lines):
            self._lines.pop(row)
            self._render_lines()

    def _render_lines(self):
        self._tbl.setRowCount(0)
        total = 0.0
        for line in self._lines:
            row = self._tbl.rowCount()
            self._tbl.insertRow(row)
            line_total = line['quantity'] * line['unit_cost']
            total += line_total
            for col, value in enumerate((
                line['product_name'], f"{line['quantity']:g}",
                f"{line['unit_cost']:,.2f}", f"{line_total:,.2f}",
            )):
                item = QTableWidgetItem(str(value))
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._tbl.setItem(row, col, item)
        self._total.setText(f'Delivery total: {total:,.2f}')

    def _submit(self):
        if not self._sup.currentData():
            QMessageBox.warning(self, 'Required', 'Select or register the supplier.')
            return
        if not self._lines:
            self._add_line()
        if not self._lines:
            return
        res = self.api.receive_purchase({
            'client_txn_id': self._client_txn_id,
            'supplier_id': self._sup.currentData(),
            'reference': self._ref.text().strip(),
            'payment_method': self._payment.currentData(),
            'notes': self._notes.text().strip(),
            'items': [
                {
                    'product_id': line['product_id'],
                    'quantity': line['quantity'],
                    'unit_cost': line['unit_cost'],
                }
                for line in self._lines
            ],
        })
        if res and res.get('success'):
            info_toast(
                self,
                f"{res.get('purchase_number')} received · "
                f"{res.get('line_count')} product lines")
            self.accept()
            return
        QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Receive failed.'))


class _NewProductDlg(QDialog):
    """First-time product registered from inside a supplier delivery."""

    def __init__(self, parent=None, suggested_cost: float = 0.0):
        super().__init__(parent)
        self.setWindowTitle('Register First-Time Product')
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        tip = QLabel(
            'The buying price is saved once: it becomes this product\u2019s latest '
            'cost and the buying price on this delivery line.')
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(tip)

        form = QFormLayout()
        self._name = QLineEdit(); self._name.setMinimumHeight(40)
        self._sku = QLineEdit(); self._sku.setMinimumHeight(40)
        self._unit = QLineEdit('pcs'); self._unit.setMinimumHeight(40)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(0.01, 9999999)
        self._cost.setDecimals(2)
        self._cost.setMinimumHeight(40)
        self._cost.setValue(max(0.01, float(suggested_cost or 0.01)))
        self._price = QDoubleSpinBox()
        self._price.setRange(0.01, 9999999)
        self._price.setDecimals(2)
        self._price.setMinimumHeight(40)
        form.addRow('Product name *', self._name)
        form.addRow('SKU / code', self._sku)
        form.addRow('Unit', self._unit)
        form.addRow('Buying price each *', self._cost)
        form.addRow('Selling price *', self._price)
        lay.addLayout(form)

        row = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        save = PrimaryBtn('Register & Add', 44)
        save.clicked.connect(self._validate)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)
        wire_dialog_keys(self, primary=save, cancel=cancel)

    def _validate(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, 'Required', 'Product name is required.')
            return
        if self._cost.value() <= 0 or self._price.value() <= 0:
            QMessageBox.warning(
                self, 'Required',
                'Buying price and selling price must both be greater than zero.')
            return
        self.accept()

    def payload(self) -> dict:
        return {
            'name': self._name.text().strip(),
            'sku': self._sku.text().strip(),
            'unit': self._unit.text().strip() or 'pcs',
            'cost_price': float(self._cost.value()),
            'price': float(self._price.value()),
            'stock': 0,
        }
