"""Suppliers list + receive stock dialogs (V05 receiving MVP)."""
from desktop.utils.quiet_ui import info_toast

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QComboBox, QFormLayout,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C, ThemeManager
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn

class SuppliersDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle('Suppliers')
        self.setMinimumSize(520, 400)
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

        close = SecondaryBtn('Close', 40)
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        from desktop.utils.dialog_keys import wire_dialog_keys
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
    """One supplier, many products, no second PIN."""

    def __init__(self, api, parent=None, products: list = None):
        super().__init__(parent)
        self.api = api
        self.products = [p for p in (products or api.get_products() or []) if p.get('is_active', 1)]
        self._lines = []
        self._token = ''
        self.setWindowTitle('Receive Stock')
        self.setMinimumSize(720, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        tip = QLabel('One delivery can include several products. Your login is enough — no extra PIN.')
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(tip)

        form = QFormLayout()
        self._sup = QComboBox(); self._sup.setMinimumHeight(40)
        for s in (api.get_suppliers() or []):
            self._sup.addItem(s.get('name') or f"#{s.get('id')}", s.get('id'))
        self._ref = QLineEdit(); self._ref.setPlaceholderText('Invoice or delivery note')
        self._ref.setMinimumHeight(36)
        self._notes = QLineEdit(); self._notes.setMinimumHeight(36)
        form.addRow('Supplier', self._sup)
        form.addRow('Reference', self._ref)
        form.addRow('Notes', self._notes)
        lay.addLayout(form)

        add_row = QHBoxLayout()
        self._prod = QComboBox(); self._prod.setMinimumHeight(40)
        for p in self.products:
            self._prod.addItem(f"{p.get('name')}  (stock {p.get('stock')})", p.get('id'))
        self._prod.currentIndexChanged.connect(self._fill_cost)
        self._fill_cost()
        self._qty = QDoubleSpinBox()
        self._qty.setRange(0.001, 999999)
        self._qty.setDecimals(3)
        self._qty.setValue(1)
        self._qty.setMinimumHeight(40)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(0, 9999999)
        self._cost.setDecimals(2)
        self._cost.setMinimumHeight(40)
        add_btn = SecondaryBtn('Add product', 40)
        add_btn.clicked.connect(self._add_line)
        add_row.addWidget(self._prod, 2)
        add_row.addWidget(self._qty)
        add_row.addWidget(self._cost)
        add_row.addWidget(add_btn)
        lay.addLayout(add_row)

        self._tbl = QTableWidget(0, 5)
        self._tbl.setHorizontalHeaderLabels(['Product', 'Qty', 'Cost', 'Line total', ''])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self._tbl, 1)
        self._total = QLabel('Grand total: 0.00')
        self._total.setStyleSheet(f"color:{C['text']}; font-size:14px; font-weight:700;")
        lay.addWidget(self._total)

        row = QHBoxLayout()
        manage = SecondaryBtn('Suppliers…', 40)
        manage.clicked.connect(self._manage_suppliers)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        go = PrimaryBtn('Save delivery', 44)
        go.clicked.connect(self._submit)
        row.addWidget(manage)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        from desktop.utils.dialog_keys import wire_dialog_keys
        wire_dialog_keys(self, primary=go, cancel=cancel)

    def _manage_suppliers(self):
        SuppliersDialog(self.api, self).exec_()
        cur = self._sup.currentData()
        self._sup.clear()
        for s in (self.api.get_suppliers() or []):
            self._sup.addItem(s.get('name') or f"#{s.get('id')}", s.get('id'))
        idx = self._sup.findData(cur)
        if idx >= 0:
            self._sup.setCurrentIndex(idx)

    def _refresh_table(self):
        self._tbl.setRowCount(0)
        grand = 0.0
        for i, line in enumerate(self._lines):
            self._tbl.insertRow(i)
            self._tbl.setItem(i, 0, QTableWidgetItem(line['name']))
            self._tbl.setItem(i, 1, QTableWidgetItem(f"{line['quantity']:g}"))
            self._tbl.setItem(i, 2, QTableWidgetItem(f"{line['unit_cost']:,.2f}"))
            self._tbl.setItem(i, 3, QTableWidgetItem(f"{line['line_total']:,.2f}"))
            grand += line['line_total']
            remove = SecondaryBtn('Remove', 32)
            remove.clicked.connect(lambda _=False, idx=i: self._remove_line(idx))
            self._tbl.setCellWidget(i, 4, remove)
        self._total.setText(f"Grand total: {grand:,.2f}")

    def _fill_cost(self):
        pid = self._prod.currentData()
        product = next((p for p in self.products if p.get('id') == pid), None)
        if product is not None:
            self._cost.setValue(float(product.get('cost_price') or 0))

    def _add_line(self):
        pid = self._prod.currentData()
        if not pid:
            QMessageBox.warning(self, 'Required', 'Select a product.')
            return
        if any(line['product_id'] == int(pid) for line in self._lines):
            QMessageBox.warning(self, 'Already added', 'That product is already on this delivery.')
            return
        qty = float(self._qty.value())
        cost = float(self._cost.value())
        name = self._prod.currentText().split('  (stock')[0]
        self._lines.append({
            'product_id': int(pid), 'name': name, 'quantity': qty,
            'unit_cost': cost, 'line_total': round(qty * cost, 2),
        })
        self._refresh_table()

    def _remove_line(self, idx):
        if 0 <= idx < len(self._lines):
            self._lines.pop(idx)
            self._refresh_table()

    def _submit(self):
        if not self._sup.currentData():
            QMessageBox.warning(self, 'Required', 'Select a supplier.')
            return
        if not self._lines:
            QMessageBox.warning(self, 'Required', 'Add at least one product.')
            return
        if not self._token:
            import uuid
            self._token = uuid.uuid4().hex
        res = self.api.receive_delivery(
            self._sup.currentData(),
            self._lines,
            reference=self._ref.text().strip(),
            notes=self._notes.text().strip(),
            client_token=self._token,
        )
        if res and res.get('success'):
            info_toast(
                self,
                f"{res.get('receipt_number')} · {len(res.get('lines') or self._lines)} products · {res.get('grand_total')}",
            )
            self.accept()
            return
        QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Receive failed.'))
