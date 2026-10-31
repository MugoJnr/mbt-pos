"""Suppliers list + receive stock dialogs."""
from desktop.utils.quiet_ui import info_toast

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QFormLayout, QSizePolicy, QWidget, QSplitter,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C, apply_themed_dialog
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, DangerBtn, H2, Body
from desktop.utils.select_controls import SearchableSelect


def _money(value) -> str:
    return f"{float(value or 0):,.2f}"


def _qty(value) -> str:
    text = f"{float(value or 0):.4f}".rstrip('0').rstrip('.')
    return text or '0'


class SuppliersDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle('Suppliers')
        self.setMinimumSize(640, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        lay.addWidget(H2('Suppliers'))
        lay.addWidget(Body('Add a supplier once. Later deliveries can select the same name.', muted=True))

        form = QFormLayout()
        form.setSpacing(8)
        self._name = QLineEdit()
        self._name.setPlaceholderText('Supplier name')
        self._name.setMinimumHeight(40)
        self._phone = QLineEdit()
        self._phone.setPlaceholderText('Phone')
        self._phone.setMinimumHeight(40)
        self._notes = QLineEdit()
        self._notes.setPlaceholderText('Notes')
        self._notes.setMinimumHeight(40)
        form.addRow('Name', self._name)
        form.addRow('Phone', self._phone)
        form.addRow('Notes', self._notes)
        lay.addLayout(form)

        add_row = QHBoxLayout()
        add_btn = PrimaryBtn('Add supplier', 40)
        add_btn.clicked.connect(self._add)
        add_row.addStretch(1)
        add_row.addWidget(add_btn)
        lay.addLayout(add_row)

        self._tbl = QTableWidget(0, 3)
        self._tbl.setHorizontalHeaderLabels(['Name', 'Phone', 'Notes'])
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setShowGrid(False)
        lay.addWidget(self._tbl, 1)

        close = SecondaryBtn('Close', 40)
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        from desktop.utils.dialog_keys import wire_dialog_keys
        wire_dialog_keys(self, primary=add_btn, cancel=close)
        apply_themed_dialog(self)
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
            self._name.clear()
            self._phone.clear()
            self._notes.clear()
            self._reload()
        else:
            QMessageBox.warning(self, 'Supplier', (res or {}).get('error', 'Failed'))


class _NewSupplierDialog(QDialog):
    """Name only. Phone and notes stay on the full Suppliers list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('New supplier')
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(H2('New supplier'))
        self._name = QLineEdit()
        self._name.setPlaceholderText('Supplier name')
        self._name.setMinimumHeight(40)
        lay.addWidget(self._name)
        row = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        add = PrimaryBtn('Add supplier', 40)
        add.clicked.connect(self._accept_name)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(add)
        lay.addLayout(row)
        from desktop.utils.dialog_keys import wire_dialog_keys
        wire_dialog_keys(self, primary=add, cancel=cancel)
        apply_themed_dialog(self)
        self._name.setFocus()

    def _accept_name(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, 'Supplier', 'Supplier name is required.')
            return
        self.accept()

    def supplier_name(self) -> str:
        return self._name.text().strip()


class ReceiveStockDialog(QDialog):
    """One supplier, many products, no second PIN."""

    def __init__(self, api, parent=None, products: list = None):
        super().__init__(parent)
        self.api = api
        self.products = [p for p in (products or api.get_products() or []) if p.get('is_active', 1)]
        self._by_id = {int(p.get('id')): p for p in self.products if p.get('id') is not None}
        self._lines = []
        self._token = ''
        self.setWindowTitle('Receive stock')
        self.setMinimumSize(860, 560)
        self.resize(1120, 740)
        self.setSizeGripEnabled(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(H2('Receive stock'))
        lay.addWidget(Body(
            'One delivery can include several products. Search, set the quantity and cost, then save once.',
            muted=True,
        ))

        form = QFormLayout()
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        supplier_items = [
            (s.get('name') or f"Supplier {s.get('id')}", s.get('id'))
            for s in (api.get_suppliers() or [])
        ]
        sup_host = QWidget()
        sup_col = QVBoxLayout(sup_host)
        sup_col.setContentsMargins(0, 0, 0, 0)
        sup_col.setSpacing(6)
        self._sup = SearchableSelect(placeholder='Search suppliers', items=supplier_items)
        self._sup.setMinimumHeight(40)
        self._sup.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        new_sup = SecondaryBtn('New supplier', 36)
        new_sup.setFixedWidth(148)
        new_sup.clicked.connect(self._new_supplier)
        sup_col.addWidget(self._sup)
        sup_col.addWidget(new_sup, 0, Qt.AlignLeft)
        self._ref = QLineEdit()
        self._ref.setPlaceholderText('Invoice or delivery note')
        self._ref.setMinimumHeight(40)
        self._notes = QLineEdit()
        self._notes.setPlaceholderText('Optional note for this delivery')
        self._notes.setMinimumHeight(40)
        self._paid = QDoubleSpinBox()
        self._paid.setRange(0, 99999999)
        self._paid.setDecimals(2)
        self._paid.setPrefix('KES ')
        self._paid.setMinimumHeight(40)
        self._paid.setMinimumWidth(96)
        self._paid.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._paid.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._pay_method = QLineEdit()
        self._pay_method.setPlaceholderText('cash')
        self._pay_method.setText('cash')
        self._pay_method.setMinimumHeight(40)
        self._pay_method.setMinimumWidth(64)
        self._pay_method.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._pay_ref = QLineEdit()
        self._pay_ref.setPlaceholderText('Payment reference')
        self._pay_ref.setMinimumHeight(40)
        self._pay_ref.setMinimumWidth(80)
        self._pay_ref.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._due = QLineEdit()
        self._due.setPlaceholderText('Due YYYY-MM-DD')
        self._due.setMinimumHeight(40)
        self._due.setMinimumWidth(96)
        self._due.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        pay_host = QWidget()
        pay_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        pay_grid = QGridLayout(pay_host)
        pay_grid.setContentsMargins(0, 0, 0, 0)
        pay_grid.setHorizontalSpacing(8)
        pay_grid.setVerticalSpacing(8)
        pay_grid.addWidget(self._paid, 0, 0)
        pay_grid.addWidget(self._pay_method, 0, 1)
        pay_grid.addWidget(self._pay_ref, 1, 0)
        pay_grid.addWidget(self._due, 1, 1)
        pay_grid.setColumnStretch(0, 1)
        pay_grid.setColumnStretch(1, 1)
        form.addRow('Supplier', sup_host)
        form.addRow('Reference', self._ref)
        form.addRow('Notes', self._notes)
        self._extra = QDoubleSpinBox()
        self._extra.setRange(0, 9999999)
        self._extra.setDecimals(2)
        self._extra.setPrefix('KES ')
        self._extra.setMinimumHeight(40)
        self._extra.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._extra.setToolTip(
            'Transport or handling for this delivery. It is split across the products by their buy value. Leave at zero when there is none.'
        )
        self._extra.valueChanged.connect(lambda _v: self._paint_total())
        form.addRow('Additional cost', self._extra)
        form.addRow('Paid now', pay_host)
        details = QWidget()
        details_lay = QVBoxLayout(details)
        details_lay.setContentsMargins(0, 0, 0, 0)
        details_lay.addLayout(form)
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(8)
        self._splitter.addWidget(details)
        lines_host = QWidget()
        lines_lay = QVBoxLayout(lines_host)
        lines_lay.setContentsMargins(0, 0, 0, 0)
        lines_lay.setSpacing(8)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        product_items = []
        for p in self.products:
            sku = p.get('sku') or '—'
            unit = p.get('unit') or 'pcs'
            product_items.append((
                f"{p.get('name')}  ·  {sku}  ·  {unit}  ·  stock {_qty(p.get('stock'))}",
                p.get('id'),
            ))
        self._prod = SearchableSelect(placeholder='Search products', items=product_items)
        self._prod.setMinimumHeight(40)
        self._prod.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._prod.currentIndexChanged.connect(self._fill_cost)
        self._qty = QDoubleSpinBox()
        self._qty.setRange(0.0001, 999999)
        self._qty.setDecimals(4)
        self._qty.setValue(1)
        self._qty.setMinimumHeight(40)
        self._qty.setMinimumWidth(120)
        self._qty.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._cost = QDoubleSpinBox()
        self._cost.setRange(0, 9999999)
        self._cost.setDecimals(2)
        self._cost.setMinimumHeight(40)
        self._cost.setMinimumWidth(130)
        self._cost.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self._cost.setPrefix('KES ')
        add_btn = SecondaryBtn('Add product', 40)
        add_btn.clicked.connect(self._add_line)
        add_row.addWidget(self._prod, 1)
        add_row.addWidget(self._qty)
        add_row.addWidget(self._cost)
        add_row.addWidget(add_btn)
        lines_lay.addLayout(add_row)

        self._tbl = QTableWidget(0, 8)
        self._tbl.setHorizontalHeaderLabels([
            '#', 'Product', 'SKU', 'Unit', 'Qty received', 'Unit cost', 'Line total', '',
        ])
        header = self._tbl.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        for col, width in ((0, 44), (2, 110), (3, 80), (4, 130), (5, 140), (6, 120), (7, 120)):
            self._tbl.setColumnWidth(col, width)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.verticalHeader().setDefaultSectionSize(48)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setShowGrid(False)
        self._tbl.setMinimumHeight(140)
        lines_lay.addWidget(self._tbl, 1)
        self._splitter.addWidget(lines_host)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([240, 320])
        self._splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{C['border']}; margin:2px 0; }}"
        )
        lay.addWidget(self._splitter, 1)

        self._total = QLabel('Delivery total  0.00')
        self._total.setStyleSheet(f"color:{C['text']}; font-size:16px; font-weight:800;")
        lay.addWidget(self._total)

        row = QHBoxLayout()
        manage = SecondaryBtn('Suppliers', 40)
        manage.clicked.connect(self._manage_suppliers)
        recent = SecondaryBtn('Recent deliveries', 40)
        recent.clicked.connect(self._show_recent)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        go = PrimaryBtn('Save delivery', 44)
        go.clicked.connect(self._submit)
        row.addWidget(manage)
        row.addWidget(recent)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        from desktop.utils.dialog_keys import wire_dialog_keys
        wire_dialog_keys(self, primary=go, cancel=cancel)
        apply_themed_dialog(self)
        self._fill_cost()

    def _supplier_items(self):
        return [
            (s.get('name') or f"Supplier {s.get('id')}", s.get('id'))
            for s in (self.api.get_suppliers() or [])
        ]

    def _reload_suppliers(self, select_id=None):
        self._sup.set_items(self._supplier_items())
        if select_id is not None:
            self._sup.set_value(select_id)

    def _new_supplier(self):
        dlg = _NewSupplierDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        name = dlg.supplier_name()
        if not name:
            return
        for label, sid in self._supplier_items():
            if label.strip().lower() == name.lower():
                self._reload_suppliers(sid)
                return
        res = self.api.create_supplier({'name': name})
        if not (res and res.get('success')):
            QMessageBox.warning(self, 'Supplier', (res or {}).get('error', 'Could not add the supplier.'))
            return
        self._reload_suppliers(res.get('id'))

    def _manage_suppliers(self):
        current = self._sup.current_value()
        SuppliersDialog(self.api, self).exec_()
        self._reload_suppliers(current)

    def _product(self, pid):
        try:
            return self._by_id.get(int(pid))
        except (TypeError, ValueError):
            return None

    def _fill_cost(self):
        product = self._product(self._prod.current_value())
        if product is None:
            return
        from desktop.utils.security import client_actor, sees_product_cost
        if sees_product_cost(client_actor(self.api)):
            self._cost.setValue(float(product.get('cost_price') or 0))
        else:
            self._cost.setValue(0)

    def _add_line(self):
        pid = self._prod.current_value()
        if not pid:
            QMessageBox.warning(self, 'Required', 'Search and select a product.')
            return
        if any(line['product_id'] == int(pid) for line in self._lines):
            QMessageBox.warning(self, 'Already added', 'That product is already on this delivery. Edit its quantity in the list.')
            return
        product = self._product(pid) or {}
        qty = round(float(self._qty.value()), 4)
        cost = round(float(self._cost.value()), 4)
        if qty <= 0:
            QMessageBox.warning(self, 'Required', 'Enter a quantity greater than zero.')
            return
        self._lines.append({
            'product_id': int(pid),
            'name': product.get('name') or 'Product',
            'sku': product.get('sku') or '',
            'unit': product.get('unit') or '',
            'quantity': qty,
            'unit_cost': cost,
            'line_total': round(qty * cost, 2),
        })
        self._refresh_table()

    def _remove_line(self, idx):
        if 0 <= idx < len(self._lines):
            self._lines.pop(idx)
            self._refresh_table()

    def _set_qty(self, idx, value):
        if 0 <= idx < len(self._lines):
            self._lines[idx]['quantity'] = round(float(value), 4)
            self._recalc(idx)

    def _set_cost(self, idx, value):
        if 0 <= idx < len(self._lines):
            self._lines[idx]['unit_cost'] = round(float(value), 4)
            self._recalc(idx)

    def _recalc(self, idx):
        line = self._lines[idx]
        line['line_total'] = round(line['quantity'] * line['unit_cost'], 2)
        item = self._tbl.item(idx, 6)
        if item is not None:
            item.setText(_money(line['line_total']))
        self._paint_total()

    def _paint_total(self):
        goods = sum(line['line_total'] for line in self._lines)
        extra = round(float(self._extra.value()), 2) if hasattr(self, '_extra') else 0
        self._total.setText(
            f"Goods  {_money(goods)}    Additional  {_money(extra)}    Delivery total  {_money(round(goods + extra, 2))}"
        )

    def _refresh_table(self):
        self._tbl.setRowCount(0)
        for i, line in enumerate(self._lines):
            self._tbl.insertRow(i)
            number = QTableWidgetItem(str(i + 1))
            number.setTextAlignment(Qt.AlignCenter)
            self._tbl.setItem(i, 0, number)
            self._tbl.setItem(i, 1, QTableWidgetItem(line['name']))
            self._tbl.setItem(i, 2, QTableWidgetItem(line.get('sku') or '—'))
            self._tbl.setItem(i, 3, QTableWidgetItem(line.get('unit') or '—'))
            qty = QDoubleSpinBox()
            qty.setRange(0.0001, 999999)
            qty.setDecimals(4)
            qty.setValue(float(line['quantity']))
            qty.setButtonSymbols(QDoubleSpinBox.NoButtons)
            qty.setMinimumHeight(36)
            qty.valueChanged.connect(lambda value, idx=i: self._set_qty(idx, value))
            self._tbl.setCellWidget(i, 4, qty)
            cost = QDoubleSpinBox()
            cost.setRange(0, 9999999)
            cost.setDecimals(2)
            cost.setValue(float(line['unit_cost']))
            cost.setPrefix('KES ')
            cost.setButtonSymbols(QDoubleSpinBox.NoButtons)
            cost.setMinimumHeight(36)
            cost.valueChanged.connect(lambda value, idx=i: self._set_cost(idx, value))
            self._tbl.setCellWidget(i, 5, cost)
            total = QTableWidgetItem(_money(line['line_total']))
            total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._tbl.setItem(i, 6, total)
            remove = DangerBtn('Remove', 32)
            remove.setFixedSize(104, 34)
            remove.setStyleSheet(
                f"QPushButton{{background:{C['err']};color:#ffffff;border:none;"
                f"min-width:104px;max-width:104px;min-height:34px;max-height:34px;"
                f"padding:0;font-size:13px;font-weight:700;border-radius:8px;}}"
            )
            remove.clicked.connect(lambda _=False, idx=i: self._remove_line(idx))
            self._tbl.setCellWidget(i, 7, remove)
        self._paint_total()

    def _show_recent(self):
        rows = []
        if hasattr(self.api, 'list_stock_receipts'):
            rows = self.api.list_stock_receipts(20) or []
        dlg = QDialog(self)
        dlg.setWindowTitle('Recent deliveries')
        dlg.setMinimumSize(1080, 520)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(['Receipt', 'Supplier', 'Total', 'Paid', 'Outstanding', 'Status'])
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        for i, row in enumerate(rows):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(str(row.get('receipt_number') or '')))
            table.setItem(i, 1, QTableWidgetItem(str(row.get('supplier_name') or '')))
            table.setItem(i, 2, QTableWidgetItem(_money(row.get('grand_total'))))
            table.setItem(i, 3, QTableWidgetItem(_money(row.get('amount_paid'))))
            table.setItem(i, 4, QTableWidgetItem(_money(row.get('outstanding'))))
            status = row.get('payment_status') or row.get('status') or 'posted'
            table.setItem(i, 5, QTableWidgetItem(str(status)))
            table.item(i, 0).setData(Qt.UserRole, row.get('id'))
        table.cellDoubleClicked.connect(lambda *_: open_selected())
        lay.addWidget(table, 1)

        def open_selected():
            current = table.currentRow()
            if current < 0:
                return
            receipt_id = table.item(current, 0).data(Qt.UserRole)
            full = self.api.get_stock_receipt(receipt_id) if hasattr(self.api, 'get_stock_receipt') else None
            if not full or full.get('error'):
                QMessageBox.warning(dlg, 'Delivery', (full or {}).get('error', 'Could not open that delivery.'))
                return
            DeliveryReceiptDialog(self.api, full, dlg).exec_()

        buttons = QHBoxLayout()
        open_btn = PrimaryBtn('Open', 40)
        open_btn.clicked.connect(open_selected)
        close = SecondaryBtn('Close', 40)
        close.clicked.connect(dlg.accept)
        buttons.addStretch(1)
        buttons.addWidget(open_btn)
        buttons.addWidget(close)
        lay.addLayout(buttons)
        apply_themed_dialog(dlg)
        dlg.exec_()

    def _submit(self):
        supplier_id = self._sup.current_value()
        if not supplier_id:
            QMessageBox.warning(self, 'Required', 'Select a supplier.')
            return
        if not self._lines:
            QMessageBox.warning(self, 'Required', 'Add at least one product.')
            return
        if not self._token:
            import uuid
            self._token = uuid.uuid4().hex
        res = self.api.receive_delivery(
            supplier_id,
            self._lines,
            reference=self._ref.text().strip(),
            notes=self._notes.text().strip(),
            client_token=self._token,
            payment_amount=float(self._paid.value()),
            payment_method=self._pay_method.text().strip() or 'cash',
            payment_reference=self._pay_ref.text().strip(),
            due_date=self._due.text().strip(),
            delivery_extra=float(self._extra.value()),
        )
        if not res or not res.get('success'):
            QMessageBox.critical(self, 'Error', (res or {}).get('error', 'Receive failed.'))
            return
        if res.get('duplicate'):
            info_toast(self, f"{res.get('receipt_number')} was already saved. Stock was not added again.")
            full = self.api.get_stock_receipt(res.get('receipt_id')) if res.get('receipt_id') else res
        else:
            info_toast(
                self,
                f"{res.get('receipt_number')} · {len(res.get('lines') or self._lines)} products · {_money(res.get('grand_total'))}",
            )
            full = res
        if full and not full.get('error'):
            DeliveryReceiptDialog(self.api, full, self).exec_()
        self.accept()


class DeliveryReceiptDialog(QDialog):
    def __init__(self, api, receipt: dict, parent=None):
        super().__init__(parent)
        self.api = api
        self.receipt = receipt or {}
        number = self.receipt.get('receipt_number') or 'Delivery'
        self.setWindowTitle(number)
        self.setMinimumSize(980, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        status = (self.receipt.get('status') or 'posted').replace('_', ' ')
        lay.addWidget(H2(number))
        supplier = self.receipt.get('supplier_name') or 'Supplier'
        reference = self.receipt.get('reference') or self.receipt.get('reference_note') or ''
        notes = self.receipt.get('notes') or ''
        lay.addWidget(Body(
            ' · '.join(bit for bit in (supplier, reference, status) if bit),
            muted=True,
        ))
        if notes:
            lay.addWidget(Body(notes, muted=True))

        lines = self.receipt.get('lines') or []
        table = QTableWidget(len(lines), 7)
        table.setHorizontalHeaderLabels([
            '#', 'Product', 'Qty', 'Unit cost', 'Line total', 'Before', 'After',
        ])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        table.setMinimumHeight(180)
        for i, line in enumerate(lines):
            table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            table.setItem(i, 1, QTableWidgetItem(str(line.get('product_name') or line.get('name') or '')))
            qty_text = _qty(line.get('quantity'))
            returned = float(line.get('returned_qty') or 0)
            if returned:
                qty_text = f"{qty_text} · returned {_qty(returned)}"
            table.setItem(i, 2, QTableWidgetItem(qty_text))
            table.setItem(i, 3, QTableWidgetItem(_money(line.get('unit_cost'))))
            table.setItem(i, 4, QTableWidgetItem(_money(line.get('line_total'))))
            before = line.get('old_stock')
            after = line.get('new_stock')
            table.setItem(i, 5, QTableWidgetItem('—' if before is None else _qty(before)))
            table.setItem(i, 6, QTableWidgetItem('—' if after is None else _qty(after)))
        paid = _money(self.receipt.get('amount_paid'))
        outstanding = _money(self.receipt.get('outstanding'))
        pay_status = self.receipt.get('payment_status') or 'UNPAID'
        total = QLabel(
            f"Invoice {_money(self.receipt.get('grand_total'))}    "
            f"Paid {paid}    Outstanding {outstanding}    {pay_status}"
        )
        total.setStyleSheet(f"color:{C['text']}; font-size:16px; font-weight:800;")
        total.setWordWrap(True)
        lay.addWidget(total)
        payments = self.receipt.get('payments') or []
        if payments:
            bits = []
            for payment in payments:
                bits.append(
                    f"{payment.get('payment_number') or 'Payment'}  "
                    f"{_money(payment.get('allocated') or payment.get('amount'))}  "
                    f"{payment.get('method') or ''}  {payment.get('reference') or ''}"
                )
            lay.addWidget(Body('Payments: ' + ' · '.join(bits), muted=True))
        role = (getattr(self.api, '_role', '') or '').lower()
        admin = role in ('admin', 'superadmin')
        can_pay = role in ('cashier', 'manager', 'admin', 'superadmin')
        can_request = role in ('cashier', 'manager')
        open_receipt = self.receipt.get('status') != 'reversed'
        row = QHBoxLayout()
        if can_pay and pay_status not in ('PAID', 'VOIDED') and open_receipt:
            pay = PrimaryBtn('Record payment', 40)
            pay.clicked.connect(self._pay)
            row.addWidget(pay)
        if admin and open_receipt:
            edit = SecondaryBtn('Edit details', 40)
            edit.clicked.connect(self._edit)
            back = SecondaryBtn('Backdate', 40)
            back.clicked.connect(self._backdate)
            send_back = SecondaryBtn('Return', 40)
            send_back.clicked.connect(self._return_line)
            void = DangerBtn('Void', 40)
            void.clicked.connect(self._void)
            row.addWidget(edit)
            row.addWidget(back)
            row.addWidget(send_back)
            row.addWidget(void)
        elif can_request and open_receipt:
            ask_date = SecondaryBtn('Request backdate', 40)
            ask_date.clicked.connect(self._ask_backdate)
            ask_void = SecondaryBtn('Request void', 40)
            ask_void.clicked.connect(self._ask_void)
            row.addWidget(ask_date)
            row.addWidget(ask_void)
        row.addStretch(1)
        close = SecondaryBtn('Close', 40)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        lay.addWidget(table, 1)
        apply_themed_dialog(self)

    def _reload(self):
        fresh = self.api.get_stock_receipt(self.receipt.get('id'))
        if fresh and not fresh.get('error'):
            self.receipt = fresh
            QMessageBox.information(self, 'Delivery', 'Saved. Open the delivery again to see the updated receipt.')
            self.accept()

    def _pay(self):
        from PyQt5.QtWidgets import QInputDialog
        amount, ok = QInputDialog.getDouble(
            self, 'Supplier payment', 'Amount to pay on this invoice',
            float(self.receipt.get('outstanding') or 0), 0, 99999999, 2,
        )
        if not ok or amount <= 0:
            return
        res = self.api.record_supplier_payment(
            self.receipt.get('supplier_id'), amount, method='cash', mode='manual',
            allocations=[{'receipt_id': self.receipt.get('id'), 'amount': amount}],
        )
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Payment', (res or {}).get('error', 'Could not record the payment.'))
            return
        self._reload()

    def _edit(self):
        from PyQt5.QtWidgets import QInputDialog
        reference, ok = QInputDialog.getText(
            self, 'Edit delivery', 'Supplier invoice reference',
            text=str(self.receipt.get('reference_note') or self.receipt.get('reference') or ''),
        )
        if not ok:
            return
        res = self.api.update_stock_receipt_header(self.receipt.get('id'), reference=reference)
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Edit', (res or {}).get('error', 'Could not edit the delivery.'))
            return
        self._reload()

    def _backdate(self):
        from PyQt5.QtWidgets import QInputDialog
        day, ok = QInputDialog.getText(self, 'Backdate', 'Effective delivery date (YYYY-MM-DD)')
        if not ok or not day.strip():
            return
        reason, ok = QInputDialog.getText(self, 'Backdate', 'Reason')
        if not ok or not reason.strip():
            return
        res = self.api.backdate_stock_receipt(self.receipt.get('id'), day.strip(), reason.strip())
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Backdate', (res or {}).get('error', 'Could not backdate the delivery.'))
            return
        self._reload()

    def _void(self):
        from PyQt5.QtWidgets import QInputDialog, QLineEdit
        reason, ok = QInputDialog.getText(self, 'Void delivery', 'Reason')
        if not ok or not reason.strip():
            return
        pin = ''
        if (getattr(self.api, '_role', '') or '').lower() != 'superadmin':
            pin, ok = QInputDialog.getText(self, 'Void delivery', 'Super-Admin PIN', QLineEdit.Password)
            if not ok:
                return
        res = self.api.reverse_stock_receipt(self.receipt.get('id'), reason=reason.strip(), pin=pin)
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Void', (res or {}).get('error', 'Could not void the delivery.'))
            return
        self._reload()

    def _ask_backdate(self):
        from PyQt5.QtWidgets import QInputDialog
        day, ok = QInputDialog.getText(self, 'Request backdate', 'Requested date (YYYY-MM-DD)')
        if not ok or not day.strip():
            return
        reason, ok = QInputDialog.getText(self, 'Request backdate', 'Reason')
        if not ok or not reason.strip():
            return
        res = self.api.request_delivery_action(self.receipt.get('id'), 'backdate', reason.strip(), day.strip())
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Request', (res or {}).get('error', 'Could not send the request.'))
            return
        QMessageBox.information(self, 'Request', 'Backdate request sent. The date stays until an admin approves it.')

    def _ask_void(self):
        from PyQt5.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, 'Request void', 'Reason')
        if not ok or not reason.strip():
            return
        res = self.api.request_delivery_action(self.receipt.get('id'), 'void', reason.strip())
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Request', (res or {}).get('error', 'Could not send the request.'))
            return
        QMessageBox.information(self, 'Request', 'Void request sent. Nothing is reversed until an admin approves it.')

    def _return_line(self):
        from PyQt5.QtWidgets import QInputDialog
        choices = []
        lines = []
        for line in self.receipt.get('lines') or []:
            left = float(line.get('quantity') or 0) - float(line.get('returned_qty') or 0)
            if left <= 0.0001:
                continue
            lines.append(line)
            choices.append(f"{line.get('product_name') or 'Product'}  ·  {left:g} still here")
        if not choices:
            QMessageBox.information(self, 'Return', 'Nothing on this delivery is left to return.')
            return
        choice, ok = QInputDialog.getItem(self, 'Return to supplier', 'Product', choices, 0, False)
        if not ok:
            return
        line = lines[choices.index(choice)]
        left = float(line.get('quantity') or 0) - float(line.get('returned_qty') or 0)
        qty, ok = QInputDialog.getDouble(
            self, 'Return to supplier', 'Quantity to return', left, 0.0001, left, 4,
        )
        if not ok or qty <= 0:
            return
        reason, ok = QInputDialog.getText(self, 'Return to supplier', 'Reason')
        if not ok:
            return
        pin = ''
        if (getattr(self.api, '_role', '') or '').lower() != 'superadmin':
            pin, ok = QInputDialog.getText(self, 'Return to supplier', 'Super-Admin PIN', QLineEdit.Password)
            if not ok:
                return
        res = self.api.return_receipt_line(
            self.receipt.get('id'), line.get('product_id'), qty,
            reason=(reason or '').strip() or 'Returned to supplier', pin=pin,
        )
        if not res or not res.get('success'):
            QMessageBox.warning(self, 'Return', (res or {}).get('error', 'Could not return that stock.'))
            return
        self._reload()
