"""Read-only list of every request this shop already stores."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
)

from desktop.utils.theme import apply_themed_dialog


def detail_text(detail: dict) -> str:
    if not detail or detail.get("error"):
        return (detail or {}).get("error") or "Select a request to see what was asked."
    if detail.get("source") == "backdate" or detail.get("sales"):
        from desktop.tabs.backdate_dialog import receipt_text
        return receipt_text(detail)
    lines = [
        f"{detail.get('type_label') or detail.get('type') or 'Request'}",
        f"Reference: {detail.get('reference') or detail.get('title') or detail.get('request_number') or '—'}",
        f"Status: {detail.get('status_label') or detail.get('status') or '—'}",
        f"Requester: {detail.get('requester') or detail.get('requested_by') or detail.get('username') or '—'}",
        f"Submitted: {detail.get('submitted_at') or detail.get('created_at') or '—'}",
    ]
    if detail.get("receipt"):
        receipt = detail["receipt"]
        lines.append(f"Receipt: {receipt.get('receipt_number') or '—'}  ·  {receipt.get('status') or ''}")
        lines.append(f"Receipt total: {receipt.get('total') or 0}")
    for line in detail.get("lines") or []:
        lines.append(
            f"  {line.get('product_name') or 'Product'}  "
            f"{line.get('quantity')} × {line.get('unit_price') or 0}"
        )
    reason = detail.get("reason") or detail.get("current_reason") or detail.get("details") or detail.get("original_reason")
    if reason:
        lines.append(f"Reason: {reason}")
    if detail.get("review_note"):
        lines.append(f"Review note: {detail.get('review_note')}")
    if detail.get("product_name"):
        lines.append(
            f"Product: {detail.get('product_name')}  "
            f"from {detail.get('current_stock')} to {detail.get('requested_qty')}"
        )
    lines.append("")
    lines.append("Opening this list does not create or approve a request.")
    return "\n".join(lines)


class RequestsCentreDialog(QDialog):
    def __init__(self, api, user, parent=None, initial_type=""):
        super().__init__(parent)
        self.api = api
        self.user = (user or {}).get("user") or user or {}
        self._initial_type = initial_type or ""
        self.setWindowTitle("Requests Centre")
        self.resize(1180, 720)
        self.setMinimumSize(860, 520)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        apply_themed_dialog(self)
        self._rows = []
        self._build()
        if self._initial_type:
            index = self.kind.findData(self._initial_type)
            if index >= 0:
                self.kind.blockSignals(True)
                self.kind.setCurrentIndex(index)
                self.kind.blockSignals(False)
        self._reload()

    def closeEvent(self, event):
        from desktop.utils.date_controls import release_window_topmost
        release_window_topmost(self)
        release_window_topmost(self.parent())
        super().closeEvent(event)

    def _build(self):
        root = QVBoxLayout(self)
        title = QLabel("Requests Centre")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)
        explain = QLabel(
            "Backdated sales, sale voids, refunds, expenses, price changes, credit, discounts, "
            "and stock requests are in this list. Use the type filter. "
            "Debt is not a request — it is on Debt Management. "
            "Nothing here posts a sale, voids a receipt, or collects a debt."
        )
        explain.setWordWrap(True)
        root.addWidget(explain)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search reference, person, or reason")
        self.search.textChanged.connect(self._reload)
        self.queue = QComboBox()
        for value, label in (
            ("all", "All requests"),
            ("action", "Awaiting my action"),
            ("mine", "My requests"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("returned", "Returned for correction"),
        ):
            self.queue.addItem(label, value)
        self.queue.currentIndexChanged.connect(self._reload)
        self.kind = QComboBox()
        self.kind.addItem("All types", "")
        for value, label in (
            ("backdated_sale", "Backdated sale"),
            ("void", "Sale void"),
            ("consumption_void", "Consumption void"),
            ("stock_adjustment", "Stock adjustment"),
            ("refund", "Refund"),
            ("expense", "Expense"),
            ("price_override", "Price change"),
            ("credit", "Credit"),
            ("large_discount", "Large discount"),
        ):
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(self._reload)
        new_btn = QPushButton("New Backdated Sale")
        new_btn.clicked.connect(self._new_backdated_sale)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._reload)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.queue)
        tools.addWidget(self.kind)
        tools.addWidget(refresh)
        tools.addWidget(new_btn)
        root.addLayout(tools)

        body = QHBoxLayout()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Reference", "Type", "Requester", "Submitted", "Amount", "Status", "Next"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column in range(1, 7):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        header.setMinimumSectionSize(90)
        self.table.currentCellChanged.connect(lambda row, *_: self._open_row(row))
        body.addWidget(self.table, 3)
        self.receipt = QTextEdit()
        self.receipt.setReadOnly(True)
        self.receipt.setLineWrapMode(QTextEdit.WidgetWidth)
        self.receipt.setPlainText("Select a request. This does not start a new one.")
        body.addWidget(self.receipt, 2)
        root.addLayout(body, 1)
        close = QPushButton("Back to till")
        close.clicked.connect(self.accept)
        root.addWidget(close)

    def _reload(self):
        result = self.api.list_requests_centre({
            "queue": self.queue.currentData() or "all",
            "type": self.kind.currentData() or "",
            "q": self.search.text().strip(),
        }) or {}
        if result.get("error") and not result.get("requests"):
            self.receipt.setPlainText(result["error"])
        self._rows = result.get("requests") or []
        self.table.setRowCount(len(self._rows))
        for index, item in enumerate(self._rows):
            values = [
                item.get("reference") or "",
                item.get("type_label") or "",
                item.get("requester") or "",
                item.get("submitted_at") or "",
                item.get("impact") or "",
                item.get("status_label") or "",
                item.get("next_action") or "",
            ]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        if not self._rows:
            self.receipt.setPlainText("No requests in this list.")

    def _open_row(self, index):
        if index < 0 or index >= len(self._rows):
            return
        item = self._rows[index]
        detail = self.api.get_requests_centre_item(item.get("source"), item.get("source_id")) or {}
        self.receipt.setPlainText(detail_text(detail))

    def _new_backdated_sale(self):
        parent = self.parent()
        self.accept()
        begin = getattr(parent, "begin_backdated_sale", None)
        if begin:
            begin()
