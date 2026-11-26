"""Return / exchange dialog — partial restock against a completed receipt."""
from desktop.utils.quiet_ui import info_toast

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QComboBox, QPushButton,
)
from PyQt5.QtCore import Qt
import uuid

from desktop.utils.theme import C, ThemeManager
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn
from desktop.utils.security import collect_superadmin_pin


class ReturnSaleDialog(QDialog):
    def __init__(self, api, parent=None, receipt_prefill: str = ''):
        super().__init__(parent)
        self.api = api
        self._sale = None
        self._items = []
        self._client_token = uuid.uuid4().hex
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

        goods_row = QHBoxLayout()
        goods_row.addWidget(QLabel('Goods'))
        self._condition = QComboBox()
        self._condition.addItem('Can be sold again', 'sellable')
        self._condition.addItem('Damaged — do not restock', 'damaged')
        self._condition.setMinimumHeight(40)
        goods_row.addWidget(self._condition, 1)
        lay.addLayout(goods_row)

        self._preview = QLabel('')
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(self._preview)

        role = (getattr(api, '_role', '') or '').lower()
        self._can_direct = role in ('admin', 'superadmin', 'manager')
        self._needs_pin = role != 'superadmin'
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        self._request = SecondaryBtn('Send Request', 44)
        self._request.clicked.connect(lambda: self._submit(use_pin=False))
        self._request.setEnabled(False)
        self._go = PrimaryBtn(
            'Process Return' if self._can_direct else 'Super Admin Authorisation', 44,
        )
        self._go.clicked.connect(lambda: self._submit(use_pin=self._needs_pin))
        self._go.setEnabled(False)
        btns.addWidget(cancel)
        if not self._can_direct:
            btns.addWidget(self._request)
        btns.addWidget(self._go)
        from desktop.utils.dialog_keys import wire_dialog_keys
        wire_dialog_keys(self, primary=self._go, cancel=cancel, submit_exempt=(self._receipt,))
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
            self._request.setEnabled(False)
            self._preview.setText('')
            return
        self._sale = res['sale']
        self._items = res['items']
        from desktop.utils.payment_tenders import refund_method_label
        label = refund_method_label(self._sale.get('payment_method'))
        method_index = self._method.findText(label)
        if method_index >= 0:
            self._method.setCurrentIndex(method_index)
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
            spin.setSingleStep(0.01)
            spin.setMinimumHeight(36)
            spin.setEnabled(rem > 0.0001)
            self._tbl.setCellWidget(r, 4, spin)
        open_lines = any(float(i.get('remaining_qty') or 0) > 0 for i in self._items)
        self._go.setEnabled(open_lines)
        self._request.setEnabled(open_lines)

    def _order_discount_factor(self) -> float:
        """Share of an order-level discount. Line discounts are already in the line total."""
        lines_net = round(sum(float(it.get('total') or 0) for it in self._items), 2)
        payable = round(float((self._sale or {}).get('total') or 0), 2)
        if lines_net <= 0.009:
            return 1.0
        return payable / lines_net

    def _chosen_lines(self):
        payload = []
        preview = 0.0
        names = []
        for r, it in enumerate(self._items):
            spin = self._tbl.cellWidget(r, 4)
            qty = float(spin.value()) if spin else 0.0
            if qty <= 0.0001:
                continue
            sold = float(it.get('sold_qty') or it.get('quantity') or 0)
            disc = float(it.get('discount') or 0)
            share = round(disc * (qty / sold), 2) if sold else 0.0
            line_total = round(qty * float(it.get('unit_price') or 0) - share, 2)
            line_total = round(line_total * self._order_discount_factor(), 2)
            preview = round(preview + line_total, 2)
            payload.append({'sale_item_id': it['id'], 'quantity': qty})
            names.append(f"{qty:g} {it.get('product_name') or 'item'} at {line_total:,.2f}")
        return payload, preview, names

    def _submit(self, use_pin: bool = False):
        if not self._sale:
            return
        reason = self._reason.text().strip()
        if not reason:
            QMessageBox.warning(self, 'Required', 'Enter a return reason.')
            return
        payload, preview, names = self._chosen_lines()
        if not payload:
            QMessageBox.warning(self, 'Empty', 'Set at least one return quantity.')
            return
        goods = self._condition.currentText()
        self._preview.setText(
            f"Refund KSh {preview:,.2f} for {', '.join(names)}. Goods: {goods}."
        )
        pin = ''
        pin_username = ''
        if use_pin:
            pin = collect_superadmin_pin(
                self.api, self,
                reason=(
                    f"Return {self._sale.get('receipt_number')}: "
                    f"{', '.join(names)}. Refund KSh {preview:,.2f}. {goods}."
                ),
            )
            if not pin or pin == 'session-authorized':
                return
            pin_username = getattr(self.api, '_authoriser_username', '') or ''
        res = self.api.return_sale(
            int(self._sale['id']), payload, reason,
            refund_method=self._method.currentText(),
            client_token=self._client_token,
            pin=pin,
            pin_username=pin_username,
            condition=self._condition.currentData() or 'sellable',
        )
        if res and res.get('pending_approval'):
            info_toast(
                self,
                res.get('message') or 'Return request sent. Nothing was refunded yet.',
            )
            self.accept()
            return
        if res and res.get('success') and res.get('executed'):
            info_toast(
                self,
                f"Return recorded · {res.get('receipt_number') or 'ok'} · KSh {float(res.get('refund_total') or 0):,.2f}",
            )
            self.accept()
            return
        QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Return failed.'))


def prompt_return_sale(api, parent=None, receipt_prefill: str = '') -> bool:
    dlg = ReturnSaleDialog(api, parent, receipt_prefill=receipt_prefill)
    return dlg.exec_() == QDialog.Accepted
