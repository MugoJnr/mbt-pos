"""Supplier debts. Separate from customer receivables."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QInputDialog,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, H2, Body


def _money(value) -> str:
    return f"{float(value or 0):,.2f}"


class SupplierDebtPanel(QWidget):
    def __init__(self, debt_tab):
        super().__init__(debt_tab)
        self.debt_tab = debt_tab
        self.api = debt_tab.api
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(H2('Supplier debts'))
        lay.addWidget(Body(
            'Money the shop owes suppliers. This is not customer debt.',
            muted=True,
        ))
        self._summary = QLabel('Outstanding  0.00')
        self._summary.setStyleSheet(f"color:{C['text']}; font-size:15px; font-weight:800;")
        self._summary.setWordWrap(True)
        lay.addWidget(self._summary)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels([
            'Delivery', 'Supplier', 'Invoice', 'Total', 'Outstanding', 'Status',
        ])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setShowGrid(False)
        self._table.cellDoubleClicked.connect(lambda *_: self._open())
        lay.addWidget(self._table, 1)
        row = QHBoxLayout()
        open_btn = SecondaryBtn('Open receipt', 40)
        open_btn.clicked.connect(self._open)
        row.addWidget(open_btn)
        role = (getattr(self.api, '_role', '') or '').lower()
        if role in ('cashier', 'manager', 'admin', 'superadmin'):
            pay_btn = PrimaryBtn('Record payment', 40)
            pay_btn.clicked.connect(self._pay)
            row.addWidget(pay_btn)
        row.addStretch(1)
        lay.addLayout(row)

    def refresh(self):
        data = {}
        if hasattr(self.api, 'supplier_payable_summary'):
            data = self.api.supplier_payable_summary() or {}
        self._summary.setText(
            f"Supplier outstanding  {_money(data.get('outstanding'))}"
            f"     Unpaid {int(data.get('unpaid_count') or 0)}"
            f"     Partial {int(data.get('partial_count') or 0)}"
            f"     Overdue {_money(data.get('overdue_amount'))}"
            f"     Supplier credit {_money(data.get('advance'))}"
        )
        rows = [row for row in (data.get('invoices') or []) if row.get('payment_status') != 'VOIDED']
        self._table.setRowCount(0)
        for i, row in enumerate(rows):
            self._table.insertRow(i)
            self._table.setItem(i, 0, QTableWidgetItem(str(row.get('receipt_number') or '')))
            self._table.setItem(i, 1, QTableWidgetItem(str(row.get('supplier_name') or '')))
            self._table.setItem(i, 2, QTableWidgetItem(str(row.get('reference_note') or '')))
            self._table.setItem(i, 3, QTableWidgetItem(_money(row.get('grand_total'))))
            self._table.setItem(i, 4, QTableWidgetItem(_money(row.get('outstanding'))))
            self._table.setItem(i, 5, QTableWidgetItem(str(row.get('payment_status') or '')))
            self._table.item(i, 0).setData(Qt.UserRole, row.get('id'))
            self._table.item(i, 1).setData(Qt.UserRole, row.get('supplier_id'))

    def _current(self):
        row = self._table.currentRow()
        if row < 0:
            return None, None
        return (
            self._table.item(row, 0).data(Qt.UserRole),
            self._table.item(row, 1).data(Qt.UserRole),
        )

    def _open(self):
        receipt_id, _supplier = self._current()
        if not receipt_id:
            return
        full = self.api.get_stock_receipt(receipt_id)
        if not full or full.get('error'):
            QMessageBox.warning(self, 'Delivery', (full or {}).get('error', 'Could not open that delivery.'))
            return
        from desktop.dialogs.receive_stock_dialog import DeliveryReceiptDialog
        DeliveryReceiptDialog(self.api, full, self).exec_()
        self.refresh()

    def _pay(self):
        receipt_id, supplier_id = self._current()
        if not supplier_id:
            QMessageBox.warning(self, 'Payment', 'Select a supplier invoice first.')
            return
        amount, ok = QInputDialog.getDouble(
            self, 'Supplier payment', 'Amount to pay. Oldest open invoices are settled first.',
            0, 0, 99999999, 2,
        )
        if not ok or amount <= 0:
            return
        res = self.api.record_supplier_payment(supplier_id, amount, method='cash', mode='oldest')
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Payment', (res or {}).get('error', 'Could not record the payment.'))
            return
        self.refresh()
