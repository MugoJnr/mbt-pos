"""Return / exchange dialog — partial restock against a completed receipt."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QComboBox, QPushButton,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C, ThemeManager
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn
from desktop.utils.security import ask_superadmin_pin


class ReturnSaleDialog(QDialog):
    def __init__(self, api, parent=None, receipt_prefill: str = ''):
        super().__init__(parent)
        self.api = api
        self._sale = None
        self._items = []
        self.setWindowTitle('Return / Exchange')
        self.setMinimumSize(640, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        tip = QLabel(
            'Look up a completed receipt, set quantities to return, then confirm with PIN. '
            'Stock is restored and a refund (negative sale) is recorded.')
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(tip)

        row = QHBoxLayout()
        self._receipt = QLineEdit()
        self._receipt.setPlaceholderText('Receipt number…')
        self._receipt.setMinimumHeight(40)
        self._receipt.setText(receipt_prefill or '')
        self._receipt.returnPressed.connect(self._lookup)
        lookup = SecondaryBtn('Lookup', 40)
        lookup.clicked.connect(self._lookup)
        row.addWidget(self._receipt, 1)
        row.addWidget(lookup)
        lay.addLayout(row)

        self._meta = QLabel('')
        self._meta.setStyleSheet(f"color:{C['text']}; font-size:13px; font-weight:600;")
        lay.addWidget(self._meta)

        self._tbl = QTableWidget(0, 5)
        self._tbl.setHorizontalHeaderLabels(
            ['Product', 'Sold', 'Already returned', 'Remaining', 'Return qty'])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self._tbl.setMinimumHeight(220)
        lay.addWidget(self._tbl, 1)

        self._reason = QLineEdit()
        self._reason.setPlaceholderText('Reason (required)…')
        self._reason.setMinimumHeight(40)
        lay.addWidget(self._reason)

        method_row = QHBoxLayout()
        method_row.addWidget(QLabel('Refund method'))
        self._method = QComboBox()
        self._method.addItems(['Cash', 'M-Pesa', 'Card', 'Bank Transfer', 'Store Credit'])
        self._method.setMinimumHeight(40)
        method_row.addWidget(self._method, 1)
        lay.addLayout(method_row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        self._go = PrimaryBtn('Process Return', 44)
        self._go.clicked.connect(self._submit)
        self._go.setEnabled(False)
        btns.addWidget(cancel)
        btns.addWidget(self._go)
        lay.addLayout(btns)

        self._apply_theme()
        if receipt_prefill:
            self._lookup()

    def _apply_theme(self):
        light = ThemeManager.is_light()
        bg = C.get('card', '#fff' if light else '#1a2332')
        fg = C.get('text', '#111' if light else '#eee')
        self.setStyleSheet(f"QDialog {{ background:{bg}; color:{fg}; }}")

    def _lookup(self):
        rn = self._receipt.text().strip()
        res = self.api.get_sale_for_return(rn)
        if not res or res.get('error'):
            QMessageBox.warning(self, 'Lookup', (res or {}).get('error', 'Not found'))
            self._sale = None
            self._items = []
            self._tbl.setRowCount(0)
            self._go.setEnabled(False)
            return
        self._sale = res['sale']
        self._items = res['items']
        self._meta.setText(
            f"Receipt {self._sale.get('receipt_number')} · "
            f"{self._sale.get('payment_method')} · "
            f"Total {float(self._sale.get('total') or 0):,.2f}"
        )
        self._tbl.setRowCount(0)
        for it in self._items:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            self._tbl.setItem(r, 0, QTableWidgetItem(str(it.get('product_name') or '')))
            self._tbl.setItem(r, 1, QTableWidgetItem(f"{float(it.get('sold_qty') or 0):g}"))
            self._tbl.setItem(r, 2, QTableWidgetItem(f"{float(it.get('returned_qty') or 0):g}"))
            rem = float(it.get('remaining_qty') or 0)
            self._tbl.setItem(r, 3, QTableWidgetItem(f"{rem:g}"))
            spin = QDoubleSpinBox()
            spin.setRange(0, rem)
            spin.setDecimals(3)
            spin.setSingleStep(1 if rem >= 1 else 0.25)
            spin.setMinimumHeight(36)
            spin.setEnabled(rem > 0.0001)
            self._tbl.setCellWidget(r, 4, spin)
        self._go.setEnabled(any(float(i.get('remaining_qty') or 0) > 0 for i in self._items))

    def _submit(self):
        if not self._sale:
            return
        reason = self._reason.text().strip()
        if not reason:
            QMessageBox.warning(self, 'Required', 'Enter a return reason.')
            return
        payload = []
        for r, it in enumerate(self._items):
            spin = self._tbl.cellWidget(r, 4)
            qty = float(spin.value()) if spin else 0.0
            if qty > 0.0001:
                payload.append({
                    'sale_item_id': it['id'],
                    'quantity': qty,
                })
        if not payload:
            QMessageBox.warning(self, 'Empty', 'Set at least one return quantity.')
            return
        if not ask_superadmin_pin(
                self.api, self, reason=f"Return {self._sale.get('receipt_number')}"):
            return
        res = self.api.return_sale(
            int(self._sale['id']), payload, reason,
            refund_method=self._method.currentText(),
        )
        if res and res.get('success'):
            QMessageBox.information(
                self, 'Return recorded',
                f"Refund: {float(res.get('refund_total') or 0):,.2f}\n"
                f"Return receipt: {res.get('receipt_number')}\n"
                f"Stock restored.")
            self.accept()
            return
        QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Return failed.'))


def prompt_return_sale(api, parent=None, receipt_prefill: str = '') -> bool:
    dlg = ReturnSaleDialog(api, parent, receipt_prefill=receipt_prefill)
    return dlg.exec_() == QDialog.Accepted
