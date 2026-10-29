"""Receipts on the till: find a saved record, open it, copy the reference."""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QTextDocument
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTextEdit, QVBoxLayout, QWidget,
)

from desktop.utils.shop_time import shop_today
from desktop.utils.theme import C
from desktop.utils.widgets import H2, PrimaryBtn, SecondaryBtn, page_layout


_TYPES = [
    ("", "All types"),
    ("sale", "Sales"),
    ("consumption", "Internal consumption"),
    ("supplier", "Supplier deliveries"),
    ("debt_payment", "Debt repayments"),
    ("expense", "Expenses"),
    ("stock_adjustment", "Stock adjustments"),
    ("approval", "Approval requests"),
]


def _payment_names(tenders) -> str:
    names = []
    for tender in tenders or []:
        name = str((tender or {}).get("method") or "").strip()
        status = str((tender or {}).get("status") or "confirmed").lower()
        if not name or status != "confirmed" or name.lower() in ("credit", "account"):
            continue
        if name not in names:
            names.append(name)
    return " + ".join(names)


def _money(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"KES {float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


class _ReceiptTable(QTableWidget):
    def __init__(self, rows, cols, opener):
        super().__init__(rows, cols)
        self._opener = opener

    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        super().mousePressEvent(event)
        if event.button() != Qt.LeftButton or not index.isValid() or index.column() == 7:
            return
        row = index.row()
        # Open after this click finishes. A modal dialog opened inside the
        # press handler would receive the mouse release as a click.
        QTimer.singleShot(0, lambda: self._opener(row, 0))


class ReceiptsTab(QWidget):
    def __init__(self, api, user, db_path=None, config_getter=None):
        super().__init__()
        self.api = api
        self.user = user or {}
        self._rows: list[dict] = []
        self._filters = {}
        root, _scroll = page_layout(self)
        root.addWidget(H2("Receipts"))
        note = QLabel(
            "Sales, internal consumption, deliveries, repayments, and other saved records. "
            "Opening one does not create a new sale."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
        root.addWidget(note)

        bar = QHBoxLayout()
        today = shop_today().isoformat()
        self._start = QLineEdit(today)
        self._end = QLineEdit(today)
        self._type = QLineEdit()
        self._type.setPlaceholderText("Type: sale, consumption, …")
        self._status = QLineEdit()
        self._status.setPlaceholderText("Status")
        self._query = QLineEdit()
        self._query.setPlaceholderText("Receipt, customer, or product")
        for box in (self._start, self._end, self._type, self._status, self._query):
            box.setMinimumHeight(34)
        self._start.setAccessibleName("From")
        self._end.setAccessibleName("To")
        bar.addWidget(self._start)
        bar.addWidget(self._end)
        bar.addWidget(self._type, 1)
        bar.addWidget(self._status)
        bar.addWidget(self._query, 2)
        find = PrimaryBtn("Find")
        find.clicked.connect(self.reload)
        bar.addWidget(find)
        root.addLayout(bar)

        self._status_line = QLabel("")
        self._status_line.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
        root.addWidget(self._status_line)

        self._table = _ReceiptTable(0, 8, self._open_row)
        self._table.setHorizontalHeaderLabels(
            ["When", "Type", "Reference", "Who", "Amount", "Payment", "Status", ""])
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.cellClicked.connect(self._open_row)
        self._table.itemClicked.connect(lambda item: self._open_row(item.row(), item.column()))
        self._table.setMinimumHeight(360)
        root.addWidget(self._table, 1)
        self.reload()

    def refresh(self, force: bool = False):
        self.reload()

    def reload(self):
        self._filters = {
            "start": self._start.text().strip(),
            "end": self._end.text().strip(),
            "kind": self._type.text().strip().lower().replace(" ", "_"),
            "status": self._status.text().strip(),
            "query": self._query.text().strip(),
        }
        data = self.api.list_centre_receipts(**self._filters)
        if data.get("error"):
            self._status_line.setText(data["error"])
            self._rows = []
        else:
            self._rows = list(data.get("receipts") or [])
            self._status_line.setText(f"{data.get('total', len(self._rows))} receipts")
        self._table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            values = [
                str(row.get("at") or "").replace("T", " ")[:19],
                str(row.get("kind") or "").replace("_", " "),
                str(row.get("reference") or ""),
                str(row.get("user") or ""),
                _money(row.get("amount")),
                str(row.get("payment") or "—"),
                str(row.get("display_status") or row.get("status") or ""),
            ]
            from PyQt5.QtWidgets import QTableWidgetItem
            for col, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._table.setItem(index, col, cell)
            open_btn = QPushButton("Open")
            open_btn.setCursor(Qt.PointingHandCursor)
            open_btn.clicked.connect(lambda _=False, row_index=index: self._open_row(row_index, 0))
            self._table.setCellWidget(index, 7, open_btn)
            self._table.setRowHeight(index, 36)
        self._table.resizeColumnsToContents()

    def _open_row(self, index: int, _column: int = 0):
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        detail = self.api.centre_receipt(row.get("kind"), row.get("id"))
        if not detail or detail.get("error"):
            QMessageBox.warning(self, "Receipt", (detail or {}).get("error") or "That receipt could not be opened.")
            return
        dlg = ReceiptDetailDialog(self, self.api, self.user, row, detail)
        dlg.exec_()
        self.reload()


class ReceiptDetailDialog(QDialog):
    def __init__(self, parent, api, user, row: dict, detail: dict):
        super().__init__(parent)
        self.api = api
        self.user = user or {}
        self.row = row
        self.detail = detail
        self.setWindowTitle("Receipt")
        self.resize(640, 520)
        header = detail.get("header") or {}
        reference = str(detail.get("reference") or row.get("reference") or "").strip()
        lay = QVBoxLayout(self)
        title = QLabel(reference or "Receipt")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title.setStyleSheet(f"color:{C['text']};font-size:18px;font-weight:800;background:transparent;")
        lay.addWidget(title)
        actions = QHBoxLayout()
        copy = PrimaryBtn("Copy reference")
        copy.clicked.connect(lambda: self._copy(reference))
        actions.addWidget(copy)
        print_btn = SecondaryBtn("Print")
        print_btn.clicked.connect(lambda: self._print(reference))
        actions.addWidget(print_btn)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        lay.addLayout(actions)
        self._copy_state = QLabel("")
        self._copy_state.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
        lay.addWidget(self._copy_state)
        kind = str(row.get("kind") or "")
        status = str(header.get("status") or row.get("status") or "")
        who = header.get("cashier_name") or header.get("username") or header.get("created_by_name") or row.get("user") or "—"
        paid_with = _payment_names(detail.get("tenders") or []) or header.get("payment_method") or row.get("payment") or "—"
        lines = [
            f"Type: {kind.replace('_', ' ')}",
            f"Status: {status}",
            f"When: {header.get('created_at') or row.get('at') or '—'}",
            f"Business date: {header.get('sale_date') or header.get('date') or '—'}",
            f"Who: {who}",
            f"Payment: {paid_with}",
            f"Total: {_money(header.get('total') if header.get('total') is not None else row.get('amount'))}",
        ]
        customer = detail.get("customer") or {}
        if customer.get("name"):
            phone = f" · {customer['phone']}" if customer.get("phone") else ""
            lines.append(f"Customer: {customer['name']}{phone}")
        body = QTextEdit()
        body.setReadOnly(True)
        chunks = ["\n".join(lines), ""]
        if kind == "consumption":
            chunks.append("Internal consumption. This is not a customer sale.")
        tenders = detail.get("tenders") or []
        if tenders:
            chunks.append("Payments")
            for tender in tenders:
                ref = f" · {tender.get('reference')}" if tender.get("reference") else ""
                state = f" · {tender.get('status')}" if tender.get("status") else ""
                chunks.append(f"  {tender.get('method')} {_money(tender.get('amount'))}{state}{ref}")
        debt = detail.get("debt") or {}
        if debt:
            chunks.append(
                f"Debt {debt.get('invoice_number') or ''} · balance {_money(debt.get('balance'))} · {debt.get('status') or ''}"
            )
        item_rows = detail.get("lines") or []
        if item_rows:
            chunks.append("Lines")
            for item in item_rows:
                name = item.get("product_name") or item.get("name") or "Item"
                chunks.append(
                    f"  {name}  × {item.get('quantity')}  @ {_money(item.get('unit_price'))}  = {_money(item.get('total'))}"
                )
        history = detail.get("history") or []
        if history:
            chunks.append("History")
            for item in history:
                chunks.append(
                    f"  {item.get('edit_type') or item.get('action') or 'event'}"
                    f" · {item.get('edited_by_name') or item.get('username') or '—'}"
                    f" · {item.get('reason') or item.get('details') or ''}"
                )
        approvals = detail.get("approvals") or []
        if approvals:
            chunks.append("Requests")
            for item in approvals:
                chunks.append(
                    f"  {item.get('type') or 'request'} #{item.get('id')}"
                    f" · {item.get('status') or ''}"
                    f" · {item.get('current_reason') or item.get('details') or ''}"
                )
        body.setPlainText("\n".join(chunks))
        lay.addWidget(body, 1)
        role = str(((user.get("user") or user) if isinstance(user, dict) else {}).get("role") or "").lower()
        stored = str(header.get("status") or "").lower()
        if kind == "sale" and stored == "completed" and role == "superadmin":
            void = QPushButton("Void receipt")
            void.clicked.connect(self._void_now)
            lay.addWidget(void)
        elif kind == "sale" and stored == "completed" and role in ("cashier", "manager", "admin"):
            ask = QPushButton("Request void")
            ask.clicked.connect(self._request_void)
            lay.addWidget(ask)
        self._reference = reference

    def _copy(self, reference: str):
        reference = (reference or "").strip()
        if not reference:
            self._copy_state.setText("There is no reference to copy.")
            return
        clip = QApplication.clipboard()
        clip.setText(reference)
        copied = clip.text()
        if copied == reference:
            self._copy_state.setText("Copied")
        else:
            self._copy_state.setText("Could not copy")

    def _print(self, reference: str):
        try:
            from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
        except Exception:
            self._copy_state.setText("Printing is not available on this till.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        doc = QTextDocument()
        doc.setPlainText(f"{reference}\nReprint of the saved receipt. This does not create a new sale.\n")
        doc.print_(printer)
        self._copy_state.setText("Reprint sent. No new sale was created.")

    def _sale_id(self):
        header = self.detail.get("header") or {}
        return int(header.get("id") or self.row.get("id") or 0)

    def _request_void(self):
        from PyQt5.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "Request void", "Why should this receipt be voided?")
        if not ok:
            return
        if len((reason or "").strip()) < 3:
            self._copy_state.setText("Enter a reason before requesting a void.")
            return
        result = self.api.request_sale_void(self._sale_id(), reason.strip())
        if result.get("error"):
            self._copy_state.setText(result["error"])
            return
        self._copy_state.setText(
            "This request is already open." if result.get("duplicate")
            else "Request saved. The receipt is still completed."
        )

    def _void_now(self):
        from PyQt5.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "Void receipt", "Reason for voiding this receipt")
        if not ok or len((reason or "").strip()) < 3:
            self._copy_state.setText("Enter a reason before voiding.")
            return
        result = self.api.void_sale(self._sale_id(), reason.strip())
        if result.get("error"):
            self._copy_state.setText(result["error"])
            return
        self._copy_state.setText("Receipt voided.")
