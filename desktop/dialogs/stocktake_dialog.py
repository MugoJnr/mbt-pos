"""Inventory stocktake. Counts save as they are entered and do not change stock."""
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from desktop.utils.security import has_permission
from desktop.utils.stocktake import REASONS


def _ask(parent, text) -> bool:
    return QMessageBox.question(parent, 'MBT POS', text) == QMessageBox.Yes


class StocktakeDialog(QDialog):
    def __init__(self, api, user, parent=None):
        super().__init__(parent)
        self.api = api
        self.user = user
        self.setWindowTitle('Stocktake & Reconciliation')
        self.resize(980, 640)
        self._session_id = None
        self._loading = False
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._new_tab(), 'New Stocktake')
        self.tabs.addTab(self._active_tab(), 'Active Stocktakes')
        self.tabs.addTab(self._review_tab(), 'Reconciliation')
        self.tabs.addTab(self._history_tab(), 'History')
        root.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._refresh_lists)

    def _new_tab(self):
        page = QWidget()
        form = QFormLayout(page)
        self.name = QLineEdit()
        self.name.setPlaceholderText('September full stocktake')
        self.scope = QComboBox()
        self.scope.addItem('All products', 'all')
        self.scope.addItem('Categories', 'categories')
        self.scope.addItem('Selected products', 'products')
        self.scope.addItem('Cycle count', 'cycle')
        self.scope_ids = QLineEdit()
        self.scope_ids.setPlaceholderText('Category names or product ids, separated by commas')
        self.mode = QComboBox()
        self.mode.addItem('Normal count', 'normal')
        self.mode.addItem('Blind count', 'blind')
        self.reason = QComboBox()
        for reason in REASONS:
            self.reason.addItem(reason)
        self.reason_other = QLineEdit()
        self.reason_other.setPlaceholderText('Custom reason when you choose Other')
        self.allow_sales = QCheckBox('Allow sales while counting')
        self.allow_sales.setChecked(True)
        start = QPushButton('Start stocktake')
        start.clicked.connect(self._start)
        form.addRow('Name', self.name)
        form.addRow('Scope', self.scope)
        form.addRow('Included items', self.scope_ids)
        form.addRow('Counting mode', self.mode)
        form.addRow('Reason', self.reason)
        form.addRow('Other reason', self.reason_other)
        form.addRow('', self.allow_sales)
        form.addRow('', start)
        note = QLabel(
            'Counting does not change stock. A manager reviews the difference, '
            'then an authorized person can adjust inventory.'
        )
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def _active_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.active_list = QComboBox()
        self.active_list.currentIndexChanged.connect(self._load_active)
        self.progress = QLabel('No stocktake selected')
        self.count_table = QTableWidget(0, 4)
        self.count_table.setHorizontalHeaderLabels(['Product', 'Unit', 'Counted', 'Status'])
        self.count_table.itemChanged.connect(self._save_count)
        buttons = QHBoxLayout()
        submit = QPushButton('Submit')
        submit.clicked.connect(self._submit)
        cancel = QPushButton('Cancel stocktake')
        cancel.clicked.connect(self._cancel)
        buttons.addWidget(submit)
        buttons.addWidget(cancel)
        lay.addWidget(self.active_list)
        lay.addWidget(self.progress)
        lay.addWidget(self.count_table)
        lay.addLayout(buttons)
        return page

    def _review_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.review_summary = QLabel('Open a submitted stocktake to review it.')
        self.review_summary.setWordWrap(True)
        self.review_table = QTableWidget(0, 7)
        self.review_table.setHorizontalHeaderLabels(
            ['Product', 'Expected', 'Physical', 'Variance', 'Cost impact', 'Status', 'Reason']
        )
        self.line_reason = QLineEdit()
        self.line_reason.setPlaceholderText('Reason for the selected difference')
        buttons = QHBoxLayout()
        for label, slot in (
            ('Save reason', self._save_reason),
            ('Request recount', self._recount),
            ('Accept and adjust stock', self._apply),
            ('Request admin approval', self._request_adjust),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        lay.addWidget(self.review_summary)
        lay.addWidget(self.review_table)
        lay.addWidget(self.line_reason)
        lay.addLayout(buttons)
        return page

    def _history_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ['Reference', 'Name', 'Status', 'Counted', 'Started']
        )
        row = QHBoxLayout()
        self.compare_left = QLineEdit()
        self.compare_left.setPlaceholderText('First reference')
        self.compare_right = QLineEdit()
        self.compare_right.setPlaceholderText('Second reference')
        compare = QPushButton('Compare')
        compare.clicked.connect(self._compare)
        export = QPushButton('Export spreadsheet')
        export.clicked.connect(self._export)
        row.addWidget(self.compare_left)
        row.addWidget(self.compare_right)
        row.addWidget(compare)
        row.addWidget(export)
        self.compare_result = QLabel('')
        self.compare_result.setWordWrap(True)
        lay.addWidget(self.history_table)
        lay.addLayout(row)
        lay.addWidget(self.compare_result)
        return page

    def _refresh_lists(self):
        listed = self.api.list_stocktakes()
        rows = listed.get('stocktakes') or []
        self.active_list.blockSignals(True)
        self.active_list.clear()
        self.history_table.setRowCount(0)
        for row in rows:
            label = f"{row['reference']} · {row['name']} · {row['status']}"
            if row['status'] in ('IN_PROGRESS', 'RECOUNT_REQUIRED', 'SUBMITTED', 'UNDER_REVIEW'):
                self.active_list.addItem(label, row['id'])
            pos = self.history_table.rowCount()
            self.history_table.insertRow(pos)
            for col, value in enumerate((
                row['reference'], row['name'], row['status'],
                f"{row.get('counted') or 0}/{row.get('products') or 0}",
                row.get('started_at') or '',
            )):
                self.history_table.setItem(pos, col, QTableWidgetItem(str(value)))
        self.active_list.blockSignals(False)
        if self.active_list.count():
            self._load_active()

    def _selected_id(self):
        return self.active_list.currentData()

    def _start(self):
        if not has_permission(self.user, 'stocktake.create'):
            QMessageBox.warning(self, 'MBT POS', 'You cannot start a stocktake.')
            return
        reason = self.reason.currentText()
        if reason == 'Other':
            reason = self.reason_other.text().strip()
        ids = [part.strip() for part in self.scope_ids.text().split(',') if part.strip()]
        result = self.api.start_stocktake({
            'name': self.name.text().strip(),
            'scope_type': self.scope.currentData(),
            'scope_ids': ids,
            'counting_mode': self.mode.currentData(),
            'reason': reason,
            'allow_sales': self.allow_sales.isChecked(),
        })
        if result.get('error'):
            QMessageBox.warning(self, 'MBT POS', result['error'])
            return
        QMessageBox.information(
            self, 'MBT POS',
            f"Started {result.get('reference')} with {result.get('products')} products.",
        )
        self.tabs.setCurrentIndex(1)
        self._refresh_lists()

    def _load_active(self):
        stocktake_id = self._selected_id()
        self._session_id = stocktake_id
        self.count_table.setRowCount(0)
        self.review_table.setRowCount(0)
        if not stocktake_id:
            return
        data = self.api.stocktake_reconcile(int(stocktake_id))
        if data.get('error'):
            self.progress.setText(data['error'])
            return
        summary = data['summary']
        session = data['stocktake']
        self.progress.setText(
            f"{session['reference']} · {summary['counted']} / {summary['products']} counted"
        )
        review = (
            f"{session['name']} · {session['status']}\n"
            f"Matched {summary.get('matched')} · Shortages {summary.get('shortages')} · "
            f"Excess {summary.get('excess')}\n"
            f"Shortage at cost {summary.get('shortage_cost')} · "
            f"Excess at cost {summary.get('excess_cost')} · "
            f"Net {summary.get('net_cost')}"
        )
        self.review_summary.setText(review)
        self._loading = True
        for line in data['lines']:
            row = self.count_table.rowCount()
            self.count_table.insertRow(row)
            product = QTableWidgetItem(line['product_name'])
            product.setData(32, line['line_id'])
            self.count_table.setItem(row, 0, product)
            self.count_table.setItem(row, 1, QTableWidgetItem(str(line.get('unit') or '')))
            counted = QTableWidgetItem(
                '' if line.get('physical_qty') is None else str(line['physical_qty'])
            )
            self.count_table.setItem(row, 2, counted)
            self.count_table.setItem(row, 3, QTableWidgetItem(line['status']))
            review_row = self.review_table.rowCount()
            self.review_table.insertRow(review_row)
            values = [
                line['product_name'],
                '' if line.get('expected_qty') is None else str(line.get('expected_qty')),
                '' if line.get('physical_qty') is None else str(line.get('physical_qty')),
                '' if line.get('variance_qty') is None else str(line.get('variance_qty')),
                '' if line.get('cost_impact') is None else str(line.get('cost_impact')),
                line['status'],
                line.get('variance_reason') or '',
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(32, line['line_id'])
                self.review_table.setItem(review_row, col, item)
        self._loading = False

    def _save_count(self, item):
        if self._loading or item.column() != 2:
            return
        product = self.count_table.item(item.row(), 0)
        if not product or not item.text().strip():
            return
        result = self.api.record_stocktake_count(int(product.data(32)), item.text().strip())
        if result.get('error'):
            QMessageBox.warning(self, 'MBT POS', result['error'])

    def _submit(self):
        stocktake_id = self._selected_id()
        if not stocktake_id:
            return
        if not _ask(self, 'Submit this stocktake? Submitted counts cannot be silently edited.'):
            return
        result = self.api.stocktake_set_status(int(stocktake_id), 'SUBMITTED')
        self._show(result)

    def _cancel(self):
        stocktake_id = self._selected_id()
        if not stocktake_id:
            return
        if not _ask(self, 'Cancel this stocktake?'):
            return
        self._show(self.api.stocktake_set_status(int(stocktake_id), 'CANCELLED'))

    def _selected_line(self):
        row = self.review_table.currentRow()
        if row < 0:
            return None
        item = self.review_table.item(row, 0)
        return int(item.data(32)) if item else None

    def _save_reason(self):
        if not has_permission(self.user, 'stocktake.review'):
            QMessageBox.warning(self, 'MBT POS', 'You cannot review differences.')
            return
        line_id = self._selected_line()
        if not line_id:
            return
        db_result = self.api.list_stocktakes()
        if db_result.get('error'):
            return
        from desktop.utils.api_client import _db
        from desktop.utils.stocktake import set_variance_reason
        db = _db()
        try:
            result = set_variance_reason(db, line_id, self.line_reason.text())
        finally:
            db.close()
        self._show(result)

    def _recount(self):
        if not has_permission(self.user, 'stocktake.review'):
            QMessageBox.warning(self, 'MBT POS', 'You cannot request a recount.')
            return
        stocktake_id = self._selected_id()
        if not stocktake_id:
            return
        from desktop.utils.api_client import _db
        from desktop.utils.stocktake import request_recount
        db = _db()
        try:
            result = request_recount(db, int(stocktake_id), self._selected_line())
        finally:
            db.close()
        self._show(result)

    def _apply(self):
        stocktake_id = self._selected_id()
        if not stocktake_id:
            return
        if not _ask(self, 'Approve these inventory adjustments? Stock will change to the physical counts.'):
            return
        self._show(self.api.apply_stocktake(int(stocktake_id)))

    def _request_adjust(self):
        stocktake_id = self._selected_id()
        if not stocktake_id:
            return
        self._show(self.api.request_stocktake_adjust(
            int(stocktake_id), self.line_reason.text() or 'Physical count should update stock',
        ))

    def _compare(self):
        listed = self.api.list_stocktakes().get('stocktakes') or []
        by_ref = {row['reference']: row['id'] for row in listed}
        left = by_ref.get(self.compare_left.text().strip())
        right = by_ref.get(self.compare_right.text().strip())
        if not left or not right:
            self.compare_result.setText('Enter two stocktake references from the history list.')
            return
        from desktop.utils.api_client import _db
        from desktop.utils.stocktake import compare_stocktakes
        db = _db()
        try:
            result = compare_stocktakes(db, left, right)
        finally:
            db.close()
        if result.get('error'):
            self.compare_result.setText(result['error'])
            return
        self.compare_result.setText(
            f"Repeated shortages {result['repeated_shortages']}. "
            f"Repeated excess {result['repeated_excess']}. "
            f"{len(result['lines'])} products compared."
        )

    def _export(self):
        if not has_permission(self.user, 'stocktake.export'):
            QMessageBox.warning(self, 'MBT POS', 'You cannot export stocktakes.')
            return
        row = self.history_table.currentRow()
        if row < 0:
            return
        reference = self.history_table.item(row, 0).text()
        listed = self.api.list_stocktakes().get('stocktakes') or []
        match = next((item for item in listed if item['reference'] == reference), None)
        if not match:
            return
        from desktop.utils.api_client import _db
        from desktop.utils.stocktake import export_workbook
        db = _db()
        try:
            payload = export_workbook(db, match['id'])
        finally:
            db.close()
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save stocktake', f'{reference}.xlsx', 'Excel (*.xlsx)'
        )
        if not path:
            return
        with open(path, 'wb') as handle:
            handle.write(payload)
        QMessageBox.information(self, 'MBT POS', 'Spreadsheet saved.')

    def _show(self, result):
        if result.get('error'):
            QMessageBox.warning(self, 'MBT POS', str(result['error']))
        else:
            QMessageBox.information(self, 'MBT POS', 'Saved.')
        self._refresh_lists()
