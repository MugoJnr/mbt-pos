"""Shop request list. Opening a row shows the receipt and the decision buttons."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout,
)

from desktop.utils.theme import C, apply_themed_dialog


def kes(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "KES 0.00"
    return f"KES {number:,.2f}"


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
        self._current_item = None
        self._current_detail = None
        self._decision_blocks = []
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
            "Backdated sales, sale voids, supplier delivery voids and backdates, refunds, expenses, "
            "price changes, credit, discounts, and stock requests are in this list. Use the type filter. "
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
            ("supplier_void", "Supplier delivery void"),
            ("supplier_backdate", "Supplier delivery backdate"),
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
        view = QPushButton("View receipt")
        view.clicked.connect(lambda: self._open_row(self.table.currentRow()))
        tools.addWidget(self.search, 1)
        tools.addWidget(self.queue)
        tools.addWidget(self.kind)
        tools.addWidget(view)
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
        self.table.cellClicked.connect(self._open_row)
        self.table.activated.connect(lambda index: self._open_row(index.row()))
        self.table.setCursor(Qt.PointingHandCursor)
        self.table.setToolTip("Click a request, or press Enter, to open the receipt")
        body.addWidget(self.table, 3)
        right = QVBoxLayout()
        right.setSpacing(8)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.side_kicker = QLabel("REQUEST")
        self.side_kicker.setStyleSheet(f"color:{C['muted']}; font-size:11px; font-weight:700; letter-spacing:0.6px;")
        self.side_title = QLabel("Select a request")
        self.side_title.setStyleSheet("font-size:16px; font-weight:800;")
        self.side_title.setWordWrap(True)
        titles.addWidget(self.side_kicker)
        titles.addWidget(self.side_title)
        head.addLayout(titles, 1)
        self.side_amount = QLabel("")
        self.side_amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.side_amount.setStyleSheet(f"color:{C['gold']}; font-size:20px; font-weight:800;")
        head.addWidget(self.side_amount)
        right.addLayout(head)
        self.receipt = QTextEdit()
        self.receipt.setReadOnly(True)
        self.receipt.setLineWrapMode(QTextEdit.WidgetWidth)
        self.receipt.setPlainText("The amount sits with the request. Approve and Reject are in the Decision section below.")
        right.addWidget(self.receipt, 1)
        right.addWidget(self._make_decision_block())
        body.addLayout(right, 2)
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
            self._current_item = None
            self._current_detail = None
            self.receipt.setPlainText("No requests in this list.")
            self._paint_side(None, None)
            self._paint_decisions()

    def _role(self):
        return str(self.user.get("role") or "").lower()

    def _user_id(self):
        try:
            return int(self.user.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    def _make_decision_block(self, close_dialog=None):
        note = QLabel("Select a request. Approve and Reject are in this section.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        approve = QPushButton("Approve")
        reject = QPushButton("Reject")
        send_back = QPushButton("Return")
        withdraw = QPushButton("Withdraw")
        for button in (approve, reject, send_back, withdraw):
            button.setMinimumHeight(40)
            button.setCursor(Qt.PointingHandCursor)
        approve.setStyleSheet(
            f"QPushButton {{ background:{C['gold']}; color:{C['gold_fg']}; font-weight:700; "
            f"border:none; border-radius:8px; padding:8px 18px; }}"
            f"QPushButton:disabled {{ background:{C['disabled']}; color:{C['muted']}; }}"
        )
        reject.setStyleSheet(
            f"QPushButton {{ background:{C['err_dim']}; color:{C['err']}; font-weight:700; "
            f"border:1px solid {C['err']}; border-radius:8px; padding:8px 18px; }}"
            f"QPushButton:disabled {{ background:transparent; color:{C['muted']}; border-color:{C['border']}; }}"
        )
        quiet = (
            f"QPushButton {{ background:transparent; color:{C['text2']}; font-weight:600; "
            f"border:1px solid {C['border']}; border-radius:8px; padding:8px 14px; }}"
            f"QPushButton:disabled {{ color:{C['muted']}; }}"
        )
        send_back.setStyleSheet(quiet)
        withdraw.setStyleSheet(quiet)
        approve.clicked.connect(lambda: self._approve(close_dialog))
        reject.clicked.connect(lambda: self._reject(close_dialog))
        send_back.clicked.connect(lambda: self._return_request(close_dialog))
        withdraw.clicked.connect(lambda: self._withdraw(close_dialog))
        block = {
            "note": note,
            "approve": approve,
            "reject": reject,
            "return": send_back,
            "withdraw": withdraw,
            "dialog": close_dialog,
        }
        self._decision_blocks.append(block)
        frame = QFrame()
        frame.setObjectName("decisionBar")
        frame.setStyleSheet(
            f"QFrame#decisionBar {{ background:{C['card2']}; border:1px solid {C['border']}; border-radius:12px; }}"
        )
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(8)
        heading = QLabel("DECISION")
        heading.setStyleSheet(f"color:{C['muted']}; font-size:11px; font-weight:700; letter-spacing:0.6px;")
        box.addWidget(heading)
        box.addWidget(note)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(approve)
        row.addWidget(reject)
        row.addStretch(1)
        row.addWidget(send_back)
        row.addWidget(withdraw)
        box.addLayout(row)
        self._paint_decisions()
        return frame

    def _drop_decision_block(self, dialog):
        self._decision_blocks = [
            block for block in self._decision_blocks if block.get("dialog") is not dialog
        ]

    def _decision_state(self):
        item = self._current_item or {}
        detail = self._current_detail or {}
        if not item:
            return {
                "approve": False, "reject": False, "return": False, "withdraw": False,
                "note": "Select a request. Approve and Reject are in this section.",
            }
        status = str(detail.get("status") or item.get("status") or "").lower()
        source = str(item.get("source") or detail.get("source") or "")
        kind = str(detail.get("type") or item.get("type") or "")
        role = self._role()
        reviewer = role in ("manager", "admin", "superadmin")
        try:
            requester_id = int(item.get("requester_id") or 0)
        except (TypeError, ValueError):
            requester_id = 0
        own = bool(requester_id) and requester_id == self._user_id()
        awaiting = status in ("pending", "submitted", "escalated")
        can_approve = False
        can_reject = False
        can_return = False
        can_withdraw = False
        if source == "backdate":
            can_review = reviewer and status == "submitted" and not own
            can_approve = can_reject = can_return = can_review
            can_withdraw = own and status in ("draft", "submitted", "returned")
            if own and status == "submitted":
                note = "You cannot approve your own backdated sale. Another manager can."
            elif can_review:
                note = "Approve posts this sale once. Reject and Return do not post it."
            elif status not in ("submitted", "draft", "returned"):
                note = f"This request is {status or 'closed'}. The buttons stay visible and do nothing further."
            elif not reviewer:
                note = "A manager uses Approve, Reject, or Return. A cashier can withdraw their own request."
            else:
                note = "This backdated sale is not waiting for a decision."
        elif source == "delivery":
            can_approve = can_reject = role in ("admin", "superadmin") and awaiting and not own
            if own and awaiting:
                note = "You cannot approve your own supplier delivery request. Another admin can."
            elif can_approve and kind == "supplier_void" and role != "superadmin":
                note = "Approve asks for the Super-Admin PIN, then voids the delivery once. Reject leaves the stock and the invoice."
            elif can_approve:
                note = "Approve applies this supplier request once. Reject leaves the delivery unchanged."
            elif awaiting:
                note = "An admin uses Approve or Reject. A manager cannot change a supplier delivery."
            else:
                note = f"This request is {status or 'closed'}. The buttons stay visible and do nothing further."
        elif source == "stock":
            can_approve = can_reject = role == "superadmin" and status == "pending"
            if can_approve:
                note = "Only Super Admin can decide a stock adjustment. Reducing stock asks for the Super-Admin PIN."
            elif status != "pending":
                note = f"This request is {status or 'closed'}. The buttons stay visible and do nothing further."
            else:
                note = "Only Super Admin can approve or reject a stock adjustment."
        elif kind == "consumption_void":
            can_approve = role in ("admin", "superadmin") and awaiting and not own
            can_reject = reviewer and awaiting and not own
            if own and awaiting:
                note = "You cannot approve your own consumption void. Another admin can."
            elif can_approve:
                note = "Approve restores the stock once. A consumption void does not ask for the Super-Admin PIN."
            elif awaiting and reviewer:
                note = "Only an admin can approve a consumption void."
            elif not reviewer:
                note = "An admin uses Approve or Reject. The consumption stays recorded until then."
            else:
                note = f"This request is {status or 'closed'}. The buttons stay visible and do nothing further."
        elif kind in ("void", "stock_adjust"):
            can_approve = (role == "superadmin" if kind == "stock_adjust" else reviewer) and awaiting
            can_reject = (role == "superadmin" if kind == "stock_adjust" else reviewer) and awaiting
            if can_approve and role != "superadmin":
                note = "Approve asks for the Super-Admin PIN, then runs once. Reject leaves the sale and stock unchanged."
            elif can_approve:
                note = "You are signed in as Super Admin, so Approve runs once without asking for the PIN again. Reject leaves the sale and stock unchanged."
            elif awaiting and kind == "stock_adjust":
                note = "Only Super Admin can apply or reject this stock adjustment."
            elif not reviewer:
                note = "A manager uses Approve or Reject. The sale stays completed until it is approved."
            else:
                note = f"This request is {status or 'closed'}. The buttons stay visible and do nothing further."
        else:
            can_approve = can_reject = reviewer and awaiting
            if can_approve:
                note = "Approve records the decision. It does not post a sale or change stock."
            elif not reviewer:
                note = "A manager uses Approve or Reject."
            else:
                note = f"This request is {status or 'closed'}. The buttons stay visible and do nothing further."
        return {
            "approve": can_approve,
            "reject": can_reject,
            "return": can_return,
            "withdraw": can_withdraw,
            "note": note,
        }

    def _paint_decisions(self):
        state = self._decision_state()
        live = []
        for block in self._decision_blocks:
            try:
                block["note"].setText(state["note"])
                block["approve"].setEnabled(state["approve"])
                block["reject"].setEnabled(state["reject"])
                block["return"].setVisible(state["return"])
                block["withdraw"].setVisible(state["withdraw"])
                live.append(block)
            except RuntimeError:
                continue
        self._decision_blocks = live

    def _request_label(self):
        item = self._current_item or {}
        return str(item.get("reference") or "this request")

    def _needs_pin(self):
        item = self._current_item or {}
        detail = self._current_detail or {}
        kind = str(detail.get("type") or item.get("type") or "")
        source = str(item.get("source") or "")
        return self._role() != "superadmin" and (
            source == "stock" or kind in ("void", "stock_adjust")
            or (source == "delivery" and kind == "supplier_void")
        )

    def _parent_for(self, dialog):
        return dialog or self

    def _ask_pin(self, dialog=None):
        pin, ok = QInputDialog.getText(
            self._parent_for(dialog), "Super-Admin PIN",
            "Enter the Super-Admin PIN. Nothing changes until it is accepted.",
            QLineEdit.Password,
        )
        if not ok:
            return None
        pin = (pin or "").strip()
        if not pin:
            QMessageBox.warning(self._parent_for(dialog), "Decision", "Enter the Super-Admin PIN.")
            return None
        return pin

    def _ask_reason(self, title, prompt, dialog=None):
        reason, ok = QInputDialog.getText(self._parent_for(dialog), title, prompt)
        reason = (reason or "").strip()
        if not ok:
            return None
        if len(reason) < 3:
            QMessageBox.warning(self._parent_for(dialog), "Decision", "Enter a reason of at least 3 characters.")
            return None
        return reason

    def _source_id(self):
        item = self._current_item or {}
        detail = self._current_detail or {}
        try:
            return int(detail.get("id") or item.get("source_id") or 0)
        except (TypeError, ValueError):
            return 0

    def _finish_decision(self, result, message, dialog):
        parent = self._parent_for(dialog)
        if not result or result.get("error"):
            QMessageBox.warning(parent, "Decision", (result or {}).get("error") or "The request was not changed.")
            return
        QMessageBox.information(parent, "Decision", message)
        if dialog is not None:
            dialog.accept()
        self._current_item = None
        self._current_detail = None
        self._reload()
        self._paint_decisions()

    def _approve(self, dialog=None):
        item = self._current_item
        if not item or not self._decision_state()["approve"]:
            return
        label = self._request_label()
        if QMessageBox.question(
            self._parent_for(dialog), "Approve",
            f"Approve {label}? This runs once. Opening the receipt does not approve it.",
        ) != QMessageBox.Yes:
            return
        pin = ""
        if self._needs_pin():
            pin = self._ask_pin(dialog)
            if pin is None:
                return
        source = str(item.get("source") or "")
        source_id = self._source_id()
        detail = self._current_detail or {}
        if source == "backdate":
            result = self.api.approve_backdate_request(source_id, detail.get("version"))
            message = "Approved. The sale was posted once."
        elif source == "stock":
            result = self.api.review_stock_adjustment(source_id, "approved", "", pin)
            message = "Approved. The stock change was posted once."
        elif source == "delivery":
            result = self.api.review_delivery_request(source_id, "approve", "", pin)
            message = "Approved. The supplier delivery was updated once."
        else:
            result = self.api.execute_approval(source_id, "approve", pin=pin)
            message = "Approved."
        self._finish_decision(result, message, dialog)

    def _reject(self, dialog=None):
        item = self._current_item
        if not item or not self._decision_state()["reject"]:
            return
        reason = self._ask_reason("Reject", "Why is this request being rejected?", dialog)
        if reason is None:
            return
        source = str(item.get("source") or "")
        source_id = self._source_id()
        detail = self._current_detail or {}
        if source == "backdate":
            result = self.api.reject_backdate_request(source_id, reason, detail.get("version"))
            message = "Rejected. No sale was posted."
        elif source == "stock":
            result = self.api.review_stock_adjustment(source_id, "rejected", reason)
            message = "Rejected. Stock was not changed."
        elif source == "delivery":
            result = self.api.review_delivery_request(source_id, "reject", reason)
            message = "Rejected. The supplier delivery was left unchanged."
        else:
            result = self.api.execute_approval(source_id, "reject", note=reason)
            message = "Rejected. The sale and stock were left unchanged."
        self._finish_decision(result, message, dialog)

    def _return_request(self, dialog=None):
        item = self._current_item
        if not item or not self._decision_state()["return"]:
            return
        reason = self._ask_reason("Return for correction", "What should the cashier correct?", dialog)
        if reason is None:
            return
        detail = self._current_detail or {}
        result = self.api.return_backdate_request(self._source_id(), reason, detail.get("version"))
        self._finish_decision(result, "Returned for correction. Nothing was posted.", dialog)

    def _withdraw(self, dialog=None):
        item = self._current_item
        if not item or not self._decision_state()["withdraw"]:
            return
        reason = self._ask_reason("Withdraw", "Why are you withdrawing this request?", dialog)
        if reason is None:
            return
        detail = self._current_detail or {}
        result = self.api.withdraw_backdate_request(self._source_id(), reason, detail.get("version"))
        self._finish_decision(result, "Withdrawn. Nothing was posted.", dialog)

    def _open_row(self, index):
        if getattr(self, "_showing_receipt", False):
            return
        if index < 0 or index >= len(self._rows):
            self.receipt.setPlainText("Select a request, then press Enter or View receipt. Opening a receipt does not approve or void it.")
            return
        item = self._rows[index]
        detail = self.api.get_requests_centre_item(item.get("source"), item.get("source_id")) or {}
        self._current_item = item
        self._current_detail = detail
        self.receipt.setPlainText(detail_text(detail))
        self._paint_side(item, detail)
        self._paint_decisions()
        self._showing_receipt = True
        try:
            self._show_receipt(item, detail)
        finally:
            self._showing_receipt = False

    def _paint_side(self, item, detail):
        if not item:
            self.side_kicker.setText("REQUEST")
            self.side_title.setText("Select a request")
            self.side_amount.setText("")
            return
        self.side_kicker.setText(str(item.get("type_label") or "REQUEST").upper())
        self.side_title.setText(str(item.get("reference") or "Request"))
        self.side_amount.setText(self._amount_text(item, detail))

    def _amount_text(self, item, detail):
        impact = str((item or {}).get("impact") or "")
        if impact.upper().startswith("KES"):
            return impact
        receipt = (detail or {}).get("receipt") or {}
        if receipt.get("total") not in (None, ""):
            return kes(receipt.get("total"))
        lines = list((detail or {}).get("lines") or [])
        if lines and any(line.get("total_cost") not in (None, "") for line in lines):
            total = 0.0
            for line in lines:
                try:
                    total += float(line.get("total_cost") or 0)
                except (TypeError, ValueError):
                    pass
            return kes(total)
        if lines and any(line.get("total") not in (None, "") for line in lines):
            total = 0.0
            for line in lines:
                try:
                    total += float(line.get("total") or 0)
                except (TypeError, ValueError):
                    pass
            return kes(total)
        return impact

    def _money_table(self, headers, rows):
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setShowGrid(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for column in range(1, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        try:
            if len(headers) > 1:
                header.model().setHeaderData(
                    len(headers) - 1, Qt.Horizontal, Qt.AlignRight, Qt.TextAlignmentRole,
                )
        except Exception:
            pass
        for index, values in enumerate(rows):
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column > 0:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(index, column, cell)
        table.setFixedHeight(max(72, 34 + 28 * max(1, len(rows))))
        return table

    def _total_bar(self, label, amount):
        frame = QFrame()
        frame.setObjectName("requestTotal")
        frame.setStyleSheet(
            f"QFrame#requestTotal {{ background:{C['card2']}; border:1px solid {C['border']}; border-radius:10px; }}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 14, 10)
        name = QLabel(label)
        name.setStyleSheet(f"color:{C['text2']}; font-size:13px; font-weight:600;")
        value = QLabel(str(amount))
        value.setStyleSheet(f"color:{C['gold']}; font-size:20px; font-weight:800;")
        row.addWidget(name)
        row.addStretch(1)
        row.addWidget(value)
        return frame

    def _show_receipt(self, item, detail):
        from PyQt5.QtWidgets import QDialog
        dlg = QDialog(self)
        reference = (
            (detail.get("receipt") or {}).get("receipt_number")
            or item.get("reference")
            or "Receipt"
        )
        dlg.setWindowTitle(str(reference))
        dlg.resize(720, 640)
        dlg.setMinimumWidth(560)
        apply_themed_dialog(dlg)
        lay = QVBoxLayout(dlg)
        title = QLabel(str(reference))
        title.setStyleSheet("font-size:18px;font-weight:800;")
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(title)
        receipt = detail.get("receipt") or {}
        if detail.get("kind") == "consumption" or detail.get("type") == "consumption_void":
            consumption = detail.get("consumption") or {}
            reference = consumption.get("reference_no") or reference
            dlg.setWindowTitle(str(reference))
            title.setText(str(reference))
            voided = int(consumption.get("voided") or 0) == 1
            meta = QLabel(
                "INTERNAL CONSUMPTION\n"
                "This is not a customer sale and has no payment.\n"
                f"{'Voided' if voided else 'Recorded'}   ·   {consumption.get('created_at') or '—'}\n"
                f"{consumption.get('created_by_name') or item.get('requester') or '—'}"
                f"   ·   {consumption.get('department_name') or '—'}\n"
                f"Request {detail.get('status') or item.get('status_label') or '—'}"
            )
            meta.setWordWrap(True)
            lay.addWidget(meta)
            lines = list(detail.get("lines") or [])
            cost_total = 0.0
            rows = []
            for line in lines:
                try:
                    cost_total += float(line.get("total_cost") or 0)
                except (TypeError, ValueError):
                    pass
                qty = f"{line.get('quantity') or ''} {line.get('unit') or ''}".strip()
                rows.append([
                    line.get("product_name") or "Product",
                    qty,
                    kes(line.get("unit_cost")),
                    kes(line.get("total_cost")),
                ])
            lay.addWidget(self._money_table(["Item", "Qty", "Unit cost", "Line cost"], rows))
            lay.addWidget(self._total_bar("Stock cost", kes(cost_total)))
            reason = detail.get("reason") or detail.get("details") or item.get("reason") or "—"
            foot = QLabel(
                f"Taken by {consumption.get('taken_by') or '—'}\n"
                f"Use reason: {consumption.get('reason') or '—'}\n"
                f"Request reason: {reason}"
            )
            foot.setWordWrap(True)
            lay.addWidget(foot)
            lay.addWidget(self._make_decision_block(dlg))
            close = QPushButton("Close")
            close.clicked.connect(dlg.accept)
            lay.addWidget(close)
            dlg.finished.connect(lambda: self._drop_decision_block(dlg))
            dlg.exec_()
            return
        sale_status = receipt.get("status") or "—"
        request_status = detail.get("status") or detail.get("status_label") or item.get("status_label") or "—"
        who = receipt.get("cashier_name") or item.get("requester") or "—"
        when = str(receipt.get("created_at") or item.get("submitted_at") or "—").replace("T", " ")[:19]
        customer = receipt.get("customer_name") or "Walk-in"
        meta = QLabel(
            f"Sale {sale_status}   ·   {when}\n{who}   ·   {customer}\nRequest {request_status}"
        )
        meta.setWordWrap(True)
        lay.addWidget(meta)
        lines = list(detail.get("lines") or [])
        for sale in detail.get("sales") or []:
            lines.extend(sale.get("lines") or [])
        rows = []
        line_total = 0.0
        for line in lines:
            try:
                line_total += float(line.get("total") or 0)
            except (TypeError, ValueError):
                pass
            rows.append([
                line.get("product_name") or "Product",
                line.get("quantity") or "",
                kes(line.get("unit_price")),
                kes(line.get("total")),
            ])
        if rows:
            lay.addWidget(self._money_table(["Item", "Qty", "Unit price", "Amount"], rows))
        else:
            empty = QLabel(detail.get("receipt_note") or detail.get("error") or "No product lines are stored on this receipt.")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        amount = self._amount_text(item, detail) or kes(receipt.get("total") if receipt.get("total") not in (None, "") else line_total)
        lay.addWidget(self._total_bar("Receipt total", amount))
        from desktop.utils.payment_tenders import payment_slip_text
        slip = detail.get("payments") or (receipt.get("payments") if isinstance(receipt, dict) else None) or {}
        pay = QLabel(payment_slip_text(slip) if slip else "")
        pay.setWordWrap(True)
        pay.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if slip:
            lay.addWidget(pay)
        reason = detail.get("reason") or detail.get("current_reason") or detail.get("details") or item.get("reason") or "—"
        foot = QLabel(f"Request reason: {reason}")
        foot.setWordWrap(True)
        foot.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(foot)
        lay.addWidget(self._make_decision_block(dlg))
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.finished.connect(lambda: self._drop_decision_block(dlg))
        dlg.exec_()

    def _new_backdated_sale(self):
        parent = self.parent()
        self.accept()
        begin = getattr(parent, "begin_backdated_sale", None)
        if begin:
            begin()
