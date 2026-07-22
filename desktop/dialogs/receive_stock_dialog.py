"""Suppliers list + receive stock dialogs (V05 receiving MVP)."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QComboBox, QFormLayout,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C, ThemeManager
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn
from desktop.utils.security import ask_superadmin_pin


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
    def __init__(self, api, parent=None, products: list = None):
        super().__init__(parent)
        self.api = api
        self.products = products or api.get_products() or []
        self.setWindowTitle('Receive Stock')
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        tip = QLabel('Increase stock from a supplier delivery (PURCHASE movement).')
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(tip)

        form = QFormLayout()
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
        self._sup = QComboBox(); self._sup.setMinimumHeight(40)
        self._sup.addItem('(No supplier)', None)
        for s in (api.get_suppliers() or []):
            self._sup.addItem(s.get('name') or f"#{s.get('id')}", s.get('id'))
        self._notes = QLineEdit(); self._notes.setMinimumHeight(40)
        form.addRow('Product', self._prod)
        form.addRow('Qty received', self._qty)
        form.addRow('Supplier', self._sup)
        form.addRow('Notes', self._notes)
        lay.addLayout(form)

        row = QHBoxLayout()
        manage = SecondaryBtn('Suppliers…', 40)
        manage.clicked.connect(self._manage_suppliers)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        go = PrimaryBtn('Receive', 44)
        go.clicked.connect(self._submit)
        row.addWidget(manage)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)

    def _manage_suppliers(self):
        SuppliersDialog(self.api, self).exec_()
        cur = self._sup.currentData()
        self._sup.clear()
        self._sup.addItem('(No supplier)', None)
        for s in (self.api.get_suppliers() or []):
            self._sup.addItem(s.get('name') or f"#{s.get('id')}", s.get('id'))
        idx = self._sup.findData(cur)
        if idx >= 0:
            self._sup.setCurrentIndex(idx)

    def _submit(self):
        pid = self._prod.currentData()
        if not pid:
            QMessageBox.warning(self, 'Required', 'Select a product.')
            return
        if not ask_superadmin_pin(self.api, self, reason='Receive stock'):
            return
        res = self.api.receive_stock(
            int(pid), float(self._qty.value()),
            supplier_id=self._sup.currentData(),
            notes=self._notes.text().strip(),
        )
        if res and res.get('success'):
            QMessageBox.information(
                self, 'Received',
                f"Stock {res.get('old_stock')} → {res.get('new_stock')}")
            self.accept()
            return
        QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Receive failed.'))
