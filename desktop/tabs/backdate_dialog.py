"""Cashier screen for preparing and reviewing backdating requests."""
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)


class BackdateDialog(QDialog):
    def __init__(self, api, user, parent=None):
        super().__init__(parent)
        self.api = api
        self.user = (user or {}).get('user') or user or {}
        self.setWindowTitle('Backdating Requests')
        self.resize(980, 680)
        self._current = None
        self._sale_forms = []
        self._products = []
        self._customers = []
        self._build()
        self._load_lists()
        self._reload()

    def _build(self):
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._open_selected)
        left.addWidget(QLabel('Your requests'))
        left.addWidget(self.list, 1)
        new_btn = QPushButton('New request')
        new_btn.clicked.connect(self._new)
        left.addWidget(new_btn)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.reference = QLabel('New request')
        self.status = QLabel('Draft')
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        yesterday = QDate.currentDate().addDays(-1)
        self.date.setDate(yesterday)
        self.date.setMaximumDate(yesterday)
        self.reason = QTextEdit()
        self.reason.setFixedHeight(70)
        self.review = QLabel('')
        self.review.setWordWrap(True)
        form.addRow('Reference', self.reference)
        form.addRow('Status', self.status)
        form.addRow('Business date', self.date)
        form.addRow('Reason', self.reason)
        form.addRow('Administrator', self.review)
        right.addLayout(form)

        self.sales_host = QVBoxLayout()
        scroll_body = QWidget()
        scroll_body.setLayout(self.sales_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_body)
        right.addWidget(scroll, 1)

        self.totals = QLabel('')
        self.totals.setWordWrap(True)
        right.addWidget(self.totals)
        buttons = QHBoxLayout()
        self.add_sale_btn = QPushButton('Add sale')
        self.save_btn = QPushButton('Save draft')
        self.submit_btn = QPushButton('Submit for review')
        self.withdraw_btn = QPushButton('Withdraw')
        self.add_sale_btn.clicked.connect(lambda: self._add_sale())
        self.save_btn.clicked.connect(self._save)
        self.submit_btn.clicked.connect(self._submit)
        self.withdraw_btn.clicked.connect(self._withdraw)
        for button in (self.add_sale_btn, self.save_btn, self.submit_btn, self.withdraw_btn):
            buttons.addWidget(button)
        right.addLayout(buttons)
        root.addLayout(right, 2)
        self._add_sale()

    def _load_lists(self):
        try:
            self._products = self.api.get_products() or []
        except Exception:
            self._products = []
        try:
            self._customers = self.api.get_customers() or []
        except Exception:
            self._customers = []

    def _reload(self):
        result = self.api.list_backdate_requests() or {}
        if result.get('error'):
            QMessageBox.warning(self, 'Backdating', result['error'])
            return
        self.list.clear()
        self._rows = result.get('requests') or []
        for item in self._rows:
            summary = item.get('summary') or {}
            self.list.addItem(
                f"{item.get('reference')}  {item.get('business_date')}  "
                f"{item.get('status')}  {summary.get('total_sales', 0):.2f}"
            )

    def _new(self):
        self._current = None
        self.reference.setText('New request')
        self.status.setText('Draft')
        self.reason.setPlainText('')
        self.review.setText('')
        self._clear_sales()
        self._add_sale()
        self._set_locked(False)

    def _open_selected(self, index):
        if index < 0 or index >= len(getattr(self, '_rows', [])):
            return
        item = self._rows[index]
        detail = self.api.get_backdate_request(item['id'])
        if not detail or detail.get('error'):
            QMessageBox.warning(self, 'Backdating', (detail or {}).get('error') or 'Could not open the request.')
            return
        self._show(detail)

    def _show(self, detail):
        self._current = detail
        self.reference.setText(detail.get('reference') or '')
        self.status.setText(str(detail.get('status') or ''))
        parts = str(detail.get('business_date') or '').split('-')
        if len(parts) == 3:
            self.date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
        self.reason.setPlainText(detail.get('reason') or '')
        note = detail.get('review_note') or ''
        self.review.setText(note)
        self._clear_sales()
        for sale in detail.get('sales') or []:
            self._add_sale(sale)
        if not detail.get('sales'):
            self._add_sale()
        summary = detail.get('summary') or {}
        warnings = detail.get('warnings') or []
        self.totals.setText(
            f"Sales {summary.get('total_sales', 0):.2f}  "
            f"Cash {summary.get('cash_sales', 0):.2f}  "
            f"M-Pesa {summary.get('mpesa_sales', 0):.2f}  "
            f"Credit {summary.get('credit_sales', 0):.2f}  "
            f"Debt {summary.get('outstanding_debt', 0):.2f}"
            + (('  Warning: ' + warnings[0]) if warnings else '')
        )
        self._set_locked(detail.get('status') not in ('draft', 'returned', None))

    def _set_locked(self, locked):
        self.date.setEnabled(not locked)
        self.reason.setReadOnly(locked)
        self.add_sale_btn.setEnabled(not locked)
        self.save_btn.setEnabled(not locked)
        self.submit_btn.setEnabled(not locked and bool(self._current))
        self.withdraw_btn.setEnabled(bool(self._current) and self._current.get('status') in ('draft', 'submitted', 'returned'))
        for form in self._sale_forms:
            form['box'].setEnabled(not locked)

    def _clear_sales(self):
        while self.sales_host.count():
            item = self.sales_host.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._sale_forms = []

    def _add_sale(self, sale=None):
        sale = sale or {}
        box = QWidget()
        lay = QFormLayout(box)
        product = QComboBox()
        for item in self._products:
            product.addItem(item.get('name') or f"Product {item.get('id')}", item.get('id'))
        qty = QDoubleSpinBox()
        qty.setRange(0.01, 100000)
        qty.setValue(float((sale.get('lines') or [{}])[0].get('quantity') or 1))
        price = QDoubleSpinBox()
        price.setRange(0, 10000000)
        price.setDecimals(2)
        first = (sale.get('lines') or [{}])[0]
        price.setValue(float(first.get('unit_price') or 0))
        discount = QDoubleSpinBox()
        discount.setRange(0, 10000000)
        discount.setDecimals(2)
        discount.setValue(float(first.get('discount') or 0))
        method = QComboBox()
        for name in ('Cash', 'M-Pesa', 'Bank Transfer', 'Credit Sale', 'Part Payment', 'Mixed'):
            method.addItem(name)
        if sale.get('payment_method'):
            index = method.findText(sale['payment_method'])
            if index >= 0:
                method.setCurrentIndex(index)
        paid = QDoubleSpinBox()
        paid.setRange(0, 10000000)
        paid.setDecimals(2)
        paid.setValue(float(sale.get('amount_paid') or 0))
        customer = QComboBox()
        customer.addItem('No customer', None)
        for item in self._customers:
            customer.addItem(item.get('name') or '', item.get('id'))
        if sale.get('customer_id'):
            index = customer.findData(sale['customer_id'])
            if index >= 0:
                customer.setCurrentIndex(index)
        mpesa = QLineEdit(sale.get('mpesa_ref') or '')
        notes = QLineEdit(sale.get('notes') or '')
        if first.get('product_id'):
            index = product.findData(first['product_id'])
            if index >= 0:
                product.setCurrentIndex(index)
        lay.addRow('Product', product)
        lay.addRow('Quantity', qty)
        lay.addRow('Price', price)
        lay.addRow('Discount', discount)
        lay.addRow('Payment', method)
        lay.addRow('Amount received', paid)
        lay.addRow('Customer', customer)
        lay.addRow('M-Pesa reference', mpesa)
        lay.addRow('Note', notes)
        lines_label = QLabel(self._line_text(sale.get('lines') or []))
        lines_label.setWordWrap(True)
        add_line = QPushButton('Add another product to this sale')
        remove = QPushButton('Remove this sale')
        lay.addRow('Products', lines_label)
        lay.addRow(add_line)
        lay.addRow(remove)
        self.sales_host.addWidget(box)
        form = {
            'box': box, 'product': product, 'qty': qty, 'price': price,
            'discount': discount, 'method': method, 'paid': paid,
            'customer': customer, 'mpesa': mpesa, 'notes': notes,
            'lines_label': lines_label,
            'extra_lines': list((sale.get('lines') or [])[1:]),
        }
        self._sale_forms.append(form)
        add_line.clicked.connect(lambda: self._keep_line(form))
        remove.clicked.connect(lambda: self._remove_sale(form))

    def _line_text(self, lines):
        if not lines:
            return 'No extra products yet.'
        return '\n'.join(
            f"{item.get('product_name') or 'Product'} x {item.get('quantity')} @ {item.get('unit_price')}"
            for item in lines
        )

    def _keep_line(self, form):
        form['extra_lines'].append({
            'product_id': form['product'].currentData(),
            'product_name': form['product'].currentText(),
            'quantity': form['qty'].value(),
            'unit_price': form['price'].value(),
            'discount': form['discount'].value(),
        })
        form['lines_label'].setText(self._line_text(
            [{'product_name': 'Current row', 'quantity': form['qty'].value(), 'unit_price': form['price'].value()}]
            + form['extra_lines']
        ))

    def _remove_sale(self, form):
        if form in self._sale_forms:
            self._sale_forms.remove(form)
            form['box'].setParent(None)

    def _payload(self):
        sales = []
        for form in self._sale_forms:
            product_id = form['product'].currentData()
            lines = [{
                'product_id': product_id,
                'product_name': form['product'].currentText(),
                'quantity': form['qty'].value(),
                'unit_price': form['price'].value(),
                'discount': form['discount'].value(),
            }]
            lines.extend(form['extra_lines'])
            sales.append({
                'payment_method': form['method'].currentText(),
                'amount_paid': form['paid'].value(),
                'customer_id': form['customer'].currentData(),
                'mpesa_ref': form['mpesa'].text().strip(),
                'notes': form['notes'].text().strip(),
                'lines': lines,
            })
        return {
            'business_date': self.date.date().toString('yyyy-MM-dd'),
            'reason': self.reason.toPlainText().strip(),
            'version': (self._current or {}).get('version'),
            'sales': sales,
        }

    def _save(self):
        payload = self._payload()
        if self._current:
            result = self.api.update_backdate_request(self._current['id'], payload)
        else:
            result = self.api.create_backdate_request(payload)
        self._after(result, 'The draft was saved.')

    def _submit(self):
        if not self._current:
            self._save()
        if not self._current:
            return
        saved = self.api.update_backdate_request(self._current['id'], self._payload())
        if saved.get('error'):
            QMessageBox.warning(self, 'Backdating', saved['error'])
            return
        result = self.api.submit_backdate_request(saved['id'], saved.get('version'))
        self._after(result, 'The request was submitted. It does not change sales or stock until it is approved.')

    def _withdraw(self):
        if not self._current:
            return
        reason, ok = _ask(self, 'Why are you withdrawing this request?')
        if not ok:
            return
        result = self.api.withdraw_backdate_request(
            self._current['id'], reason, self._current.get('version')
        )
        self._after(result, 'The request was withdrawn.')

    def _after(self, result, message):
        if not result or result.get('error'):
            QMessageBox.warning(self, 'Backdating', (result or {}).get('error') or 'The request was not saved.')
            return
        self._show(result)
        self._reload()
        QMessageBox.information(self, 'Backdating', message)


def _ask(parent, title):
    text, ok = QInputDialog.getText(parent, 'Backdating', title)
    return text.strip(), bool(ok and text.strip())
