"""Restock lists for the desktop till. This window does not touch the sale cart."""
from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import (
    QAbstractScrollArea, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from desktop.utils.theme import C, apply_themed_dialog
from desktop.utils.security import has_permission


def _actor(user: dict) -> dict:
    inner = (user or {}).get("user") or user or {}
    return {
        "id": inner.get("id"),
        "username": inner.get("full_name") or inner.get("username") or "",
        "role": inner.get("role") or "",
        "shop_id": "local",
    }


def _run(actor, fn, *args):
    from desktop.utils.api_client import _db
    db = _db()
    try:
        result = fn(db, actor, *args)
        if result.get("success"):
            db.commit()
        else:
            db.rollback()
        return result
    finally:
        db.close()


def can_open_restock(user: dict) -> bool:
    actor = _actor(user)
    return any(has_permission(actor, action) for action in (
        "restock.view", "restock.create", "restock.manage", "restock.purchase",
    ))


class RestockDialog(QDialog):
    """Independent restock workspace. It never reads or writes the open sale."""

    def __init__(self, api, user, parent=None, product_id=None):
        super().__init__(parent)
        self.api = api
        self.user = user
        self.actor = _actor(user)
        self.current = None
        self.setWindowTitle("Restock Lists")
        self.resize(1100, 720)
        self.setMinimumSize(920, 600)
        apply_themed_dialog(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        intro = QLabel(
            "Create lists of products the shop needs to buy. A list does not change stock. "
            "The till and the dashboard on this shop read the same saved lists."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        self.list = QListWidget()
        self.list.setMinimumWidth(200)
        self.list.setMaximumWidth(260)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.ElideNone)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self._open_selected)
        split.addWidget(self.list)
        right = QWidget()
        form = QVBoxLayout(right)
        form.setContentsMargins(8, 0, 0, 0)
        form.setSpacing(8)
        self.name = QLineEdit()
        self.name.setPlaceholderText("List name")
        self.priority = QComboBox()
        self.priority.addItem("Normal", "normal")
        self.priority.addItem("Urgent", "urgent")
        self.priority.setFixedWidth(150)
        self.instructions = QTextEdit()
        self.instructions.setPlaceholderText("Instructions for the buyer")
        self.instructions.setFixedHeight(52)
        self.status = QLabel("No list open")
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_label = QLabel("Title")
        title_label.setFixedWidth(96)
        priority_label = QLabel("Priority")
        title_row.addWidget(title_label)
        title_row.addWidget(self.name, 1)
        title_row.addWidget(priority_label)
        title_row.addWidget(self.priority)
        form.addLayout(title_row)
        note_row = QHBoxLayout()
        note_row.setSpacing(8)
        note_label = QLabel("Instructions")
        note_label.setFixedWidth(96)
        note_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        note_row.addWidget(note_label)
        note_row.addWidget(self.instructions, 1)
        form.addLayout(note_row)
        form.addWidget(self.status)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Requested", "Unit", "Purchased", "Received", "Notes"]
        )
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setMinimumHeight(280)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(64)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 108), (2, 72), (3, 112), (4, 104)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setStyleSheet(
            f"QTableWidget {{ background:{C['card']}; color:{C['text']};"
            f"border:1px solid {C['border']}; border-radius:0px; }}"
            f"QTableWidget::item {{ padding:4px 8px; border:none;"
            f"border-bottom:1px solid {C['border']}; }}"
            f"QHeaderView::section {{ background:{C['panel']}; color:{C['text2']};"
            f"padding:6px 8px; border:none; border-bottom:1px solid {C['border']};"
            f"font-size:11px; font-weight:700; }}"
        )
        viewport = self.table.viewport()
        viewport.setAutoFillBackground(True)
        viewport.setStyleSheet(f"background:{C['card']};")
        self._empty = QLabel("No products have been added yet.", viewport)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(f"color:{C['text2']}; background:transparent; font-size:13px;")
        viewport.installEventFilter(self)
        form.addWidget(self.table, 1)
        actions = QWidget()
        actions.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        actions.setStyleSheet(
            "QPushButton { min-height: 32px; max-height: 36px; padding: 4px 12px; }"
        )
        actions_lay = QVBoxLayout(actions)
        actions_lay.setContentsMargins(0, 4, 0, 0)
        actions_lay.setSpacing(6)
        actions_lay.addLayout(self._action_row("List", (
            ("New list", self._new),
            ("Save", self._save),
            ("Mark ready", self._submit),
            ("Return to draft", self._return_draft),
            ("Duplicate", self._duplicate),
            ("Archive", self._archive),
        )))
        actions_lay.addLayout(self._action_row("Lines", (
            ("Add product", self._add_product),
            ("Change qty", self._change_qty),
            ("Remove", self._remove),
            ("Low stock", self._low_stock),
        )))
        actions_lay.addLayout(self._action_row("Buying", (
            ("Record purchase", self._purchase),
            ("Receive", self._receive),
            ("Assign", self._assign),
            ("Cancel", self._cancel),
        )))
        actions_lay.addLayout(self._action_row("Output", (
            ("Print", self._print),
            ("Save PDF", self._save_pdf),
            ("Close", self.accept),
        )))
        form.addWidget(actions, 0)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 840])
        root.addWidget(split, 1)
        self._reload()
        self._sync_empty()
        if product_id:
            self._quick_product = int(product_id)
        else:
            self._quick_product = None

    def _add_button(self, layout, label, handler):
        button = QPushButton(label)
        button.clicked.connect(handler)
        layout.addWidget(button)

    def _action_row(self, title, actions):
        row = QHBoxLayout()
        row.setSpacing(6)
        label = QLabel(title)
        label.setFixedWidth(72)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(label)
        for text, handler in actions:
            button = QPushButton(text)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        return row

    def eventFilter(self, obj, event):
        table = getattr(self, "table", None)
        if table is not None and obj is table.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            self._position_empty()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_empty()

    def _position_empty(self):
        label = getattr(self, "_empty", None)
        table = getattr(self, "table", None)
        if label is None or table is None:
            return
        label.setGeometry(table.viewport().rect())

    def _sync_empty(self):
        label = getattr(self, "_empty", None)
        table = getattr(self, "table", None)
        if label is None or table is None:
            return
        label.setVisible(table.rowCount() == 0)
        self._position_empty()

    def _reload(self):
        from backend import restock_requests as restock
        result = _run(self.actor, restock.list_requests, {})
        self.list.clear()
        self._rows = result.get("requests") or []
        if result.get("error"):
            self.status.setText(result["error"])
            return
        for row in self._rows:
            item = f"{row['reference']}\n{row['name']}\n{row['status_label']}"
            self.list.addItem(item)
            self.list.item(self.list.count() - 1).setToolTip(item.replace("\n", " · "))

    def _open_selected(self, index):
        if index < 0 or index >= len(getattr(self, "_rows", [])):
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.get_request, self._rows[index]["id"])
        if result.get("error"):
            self.status.setText(result["error"])
            return
        self._show(result["request"])

    def _show(self, request):
        self.current = request
        self.name.setText(request.get("name") or "")
        self.priority.setCurrentIndex(1 if request.get("priority") == "urgent" else 0)
        self.instructions.setPlainText(request.get("instructions") or "")
        lines = request.get("lines") or []
        self.table.setRowCount(len(lines))
        for row, line in enumerate(lines):
            self.table.setItem(row, 0, QTableWidgetItem(line.get("product_name") or ""))
            self.table.setItem(row, 1, QTableWidgetItem(str(line.get("quantity_text") or line.get("quantity"))))
            self.table.setItem(row, 2, QTableWidgetItem(line.get("unit") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(str(line.get("purchased_qty") or 0)))
            self.table.setItem(row, 4, QTableWidgetItem(str(line.get("received_qty") or 0)))
            self.table.setItem(row, 5, QTableWidgetItem(line.get("notes") or line.get("purchase_notes") or ""))
            self.table.item(row, 0).setData(Qt.UserRole, line.get("line_id") or line.get("id"))
            self.table.item(row, 0).setData(Qt.UserRole + 1, line.get("id"))
        self.table.setColumnHidden(2, not any(str(line.get("unit") or "").strip() for line in lines))
        self.table.setColumnHidden(5, not any(str(line.get("notes") or line.get("purchase_notes") or "").strip() for line in lines))
        self.status.setText(
            f"Saved · {request.get('reference')} · {request.get('status_label')} · version {request.get('version')}"
        )
        self._sync_empty()

    def _new(self):
        from backend import restock_requests as restock
        name = self.name.text().strip() or "New restock list"
        result = _run(self.actor, restock.create_request, {
            "name": name,
            "priority": self.priority.currentData(),
            "instructions": self.instructions.toPlainText(),
        })
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._reload()
        self._show(result["request"])

    def _save(self):
        if not self.current:
            self._new()
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.update_request, self.current["id"], {
            "version": self.current["version"],
            "name": self.name.text().strip(),
            "priority": self.priority.currentData(),
            "instructions": self.instructions.toPlainText(),
        })
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            if result.get("conflict"):
                self._open_id(self.current["id"])
            return
        self._show(result["request"])
        self._reload()

    def _open_id(self, request_id):
        from backend import restock_requests as restock
        result = _run(self.actor, restock.get_request, request_id)
        if result.get("success"):
            self._show(result["request"])

    def _add_product(self):
        if not self.current:
            self._new()
        if not self.current:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Add product")
        layout = QFormLayout(dialog)
        search = QLineEdit()
        choices = QComboBox()
        quantity = QDoubleSpinBox()
        quantity.setDecimals(4)
        quantity.setMaximum(999999)
        quantity.setValue(1)
        layout.addRow("Search", search)
        layout.addRow("Product", choices)
        layout.addRow("Quantity", quantity)

        def refresh():
            from backend import restock_requests as restock
            found = _run(self.actor, restock.search_products, search.text().strip())
            choices.clear()
            for product in found.get("products") or []:
                choices.addItem(f"{product['name']} ({product.get('unit') or ''})", product["id"])

        search.textChanged.connect(lambda _text: refresh())
        refresh()
        buttons = QHBoxLayout()
        ok = QPushButton("Add")
        cancel = QPushButton("Cancel")
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addRow(buttons)
        cancel.clicked.connect(dialog.reject)

        def add():
            from backend import restock_requests as restock
            result = _run(self.actor, restock.add_line, self.current["id"], {
                "version": self.current["version"],
                "product_id": choices.currentData(),
                "quantity": quantity.value(),
            })
            if result.get("status") == 409 and result.get("existing_line_id"):
                answer = QMessageBox.question(
                    self, "Already on the list",
                    "That product is already on this list. Add to its quantity?",
                )
                if answer != QMessageBox.Yes:
                    return
                result = _run(self.actor, restock.add_line, self.current["id"], {
                    "version": self.current["version"],
                    "product_id": choices.currentData(),
                    "quantity": quantity.value(),
                    "merge": True,
                })
            if result.get("error"):
                QMessageBox.warning(self, "Restock list", result["error"])
                return
            self._show(result["request"])
            dialog.accept()

        ok.clicked.connect(add)
        dialog.exec_()

    def _selected_line(self):
        row = self.table.currentRow()
        if row < 0 or not self.current:
            return None, None
        item = self.table.item(row, 0)
        if item is None:
            return None, None
        return item.data(Qt.UserRole), item.data(Qt.UserRole + 1)

    def _submit(self):
        if not self.current:
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.submit_request, self.current["id"], self.current["version"])
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._show(result["request"])
        self._reload()

    def _purchase(self):
        if not self.current:
            return
        _line_id, revision_line = self._selected_line()
        if not revision_line:
            QMessageBox.information(self, "Restock list", "Select a product row first.")
            return
        quantity, ok = _ask_quantity(self, "Purchased quantity")
        if not ok:
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.record_purchase, self.current["id"], {
            "version": self.current["version"],
            "lines": [{"id": revision_line, "purchased_qty": quantity}],
        })
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._show(result["request"])
        self._reload()

    def _archive(self):
        if not self.current:
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.archive_request, self.current["id"], self.current["version"])
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self.current = None
        self._reload()
        self.status.setText("Archived. The list stays searchable.")

    def _remove(self):
        if not self.current:
            return
        line_id, _revision_line = self._selected_line()
        if not line_id:
            QMessageBox.information(self, "Restock list", "Select a product row first.")
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.remove_line, self.current["id"], line_id, self.current["version"])
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._show(result["request"])
        self._reload()

    def _change_qty(self):
        if not self.current:
            return
        line_id, _revision_line = self._selected_line()
        if not line_id:
            QMessageBox.information(self, "Restock list", "Select a product row first.")
            return
        quantity, ok = _ask_quantity(self, "Requested quantity")
        if not ok:
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.update_line, self.current["id"], line_id, {
            "version": self.current["version"],
            "quantity": quantity,
        })
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._show(result["request"])

    def _duplicate(self):
        if not self.current:
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.duplicate_request, self.current["id"])
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._reload()
        self._show(result["request"])

    def _return_draft(self):
        if not self.current:
            return
        from backend import restock_requests as restock
        result = _run(self.actor, restock.return_to_draft, self.current["id"], self.current["version"])
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        self._show(result["request"])
        self._reload()

    def _assign(self):
        if not self.current:
            return
        from backend import restock_requests as restock
        found = _run(self.actor, restock.buyers)
        dialog = QDialog(self)
        dialog.setWindowTitle("Assign buyer")
        layout = QFormLayout(dialog)
        choices = QComboBox()
        choices.addItem("External buyer", None)
        for buyer in found.get("buyers") or []:
            choices.addItem(buyer["name"], buyer["id"])
        external = QLineEdit()
        external.setPlaceholderText("Name if the buyer has no login")
        layout.addRow("Staff buyer", choices)
        layout.addRow("External name", external)
        buttons = QHBoxLayout()
        ok = QPushButton("Assign")
        cancel = QPushButton("Cancel")
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addRow(buttons)
        cancel.clicked.connect(dialog.reject)

        def save():
            result = _run(self.actor, restock.assign_request, self.current["id"], {
                "version": self.current["version"],
                "buyer_user_id": choices.currentData(),
                "external_buyer": external.text().strip(),
            })
            if result.get("error"):
                QMessageBox.warning(self, "Restock list", result["error"])
                return
            self._show(result["request"])
            self._reload()
            dialog.accept()

        ok.clicked.connect(save)
        dialog.exec_()

    def _receive(self):
        if not self.current:
            return
        line_id, _revision_line = self._selected_line()
        if not line_id:
            QMessageBox.information(self, "Restock list", "Select a product row first.")
            return
        line = next(
            (item for item in (self.current.get("lines") or [])
             if int(item.get("line_id") or item.get("id") or 0) == int(line_id)),
            None,
        )
        if not line:
            QMessageBox.warning(self, "Restock list", "That product is not on this list.")
            return
        from desktop.utils.api_client import _db
        db = _db()
        try:
            suppliers = db.execute("SELECT id, name FROM suppliers ORDER BY name").fetchall()
        finally:
            db.close()
        dialog = QDialog(self)
        dialog.setWindowTitle("Receive goods")
        layout = QFormLayout(dialog)
        supplier = QComboBox()
        for row in suppliers:
            supplier.addItem(row["name"], row["id"])
        quantity = QDoubleSpinBox()
        quantity.setDecimals(4)
        quantity.setMaximum(999999)
        quantity.setValue(1)
        rejected = QDoubleSpinBox()
        rejected.setDecimals(4)
        rejected.setMaximum(999999)
        rejected.setValue(0)
        layout.addRow("Supplier", supplier)
        layout.addRow("Accepted quantity", quantity)
        layout.addRow("Rejected or damaged", rejected)
        note = QLabel("This uses the normal supplier delivery. It is the only step that changes stock.")
        note.setWordWrap(True)
        layout.addRow(note)
        buttons = QHBoxLayout()
        ok = QPushButton("Receive")
        cancel = QPushButton("Cancel")
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addRow(buttons)
        cancel.clicked.connect(dialog.reject)

        def save():
            import uuid
            received = self.api.receive_stock(
                int(line["product_id"]),
                quantity.value(),
                supplier_id=supplier.currentData(),
                notes=f"Restock list {self.current.get('reference') or ''}",
                client_token=f"restock-till-{self.current['id']}-{line_id}-{uuid.uuid4().hex[:8]}",
            )
            if received.get("error"):
                QMessageBox.warning(self, "Restock list", received["error"])
                return
            from backend import restock_requests as restock
            result = _run(self.actor, restock.link_receipt, self.current["id"], {
                "line_id": line_id,
                "receipt_id": received.get("receipt_id"),
                "qty_accepted": quantity.value(),
                "qty_rejected": rejected.value(),
            })
            if result.get("error"):
                QMessageBox.warning(self, "Restock list", result["error"])
                return
            self._show(result["request"])
            self._reload()
            dialog.accept()

        ok.clicked.connect(save)
        dialog.exec_()

    def _cancel(self):
        if not self.current:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Cancel list")
        layout = QFormLayout(dialog)
        reason = QLineEdit()
        reason.setPlaceholderText("Why is this list being cancelled?")
        layout.addRow("Reason", reason)
        buttons = QHBoxLayout()
        ok = QPushButton("Cancel list")
        cancel = QPushButton("Keep list")
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addRow(buttons)
        cancel.clicked.connect(dialog.reject)

        def save():
            from backend import restock_requests as restock
            result = _run(self.actor, restock.cancel_request, self.current["id"], {
                "version": self.current["version"],
                "reason": reason.text().strip(),
            })
            if result.get("error"):
                QMessageBox.warning(self, "Restock list", result["error"])
                return
            self._show(result["request"])
            self._reload()
            dialog.accept()

        ok.clicked.connect(save)
        dialog.exec_()

    def _low_stock(self):
        if not self.current:
            self._new()
        if not self.current or self.current.get("status") != "draft":
            QMessageBox.information(self, "Restock list", "Open a draft before adding low-stock products.")
            return
        from backend import restock_requests as restock
        found = _run(self.actor, restock.suggestions)
        items = found.get("suggestions") or []
        if not items:
            QMessageBox.information(self, "Restock list", found.get("note") or "No products are at or below the reorder level.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Low and out of stock")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Tick the products to add. Nothing is ordered until you confirm."))
        picker = QListWidget()
        for item in items:
            label = f"{item['product_name']} · suggest {item['suggested_qty']} {item.get('unit') or ''}"
            row = QListWidgetItem(label)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Unchecked)
            row.setData(Qt.UserRole, item)
            picker.addItem(row)
        layout.addWidget(picker)
        buttons = QHBoxLayout()
        ok = QPushButton("Add selected")
        cancel = QPushButton("Cancel")
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        cancel.clicked.connect(dialog.reject)

        def save():
            added = 0
            for index in range(picker.count()):
                row = picker.item(index)
                if row.checkState() != Qt.Checked:
                    continue
                item = row.data(Qt.UserRole)
                result = _run(self.actor, restock.add_line, self.current["id"], {
                    "version": self.current["version"],
                    "product_id": item["product_id"],
                    "quantity": item["suggested_qty"],
                    "merge": True,
                })
                if result.get("error"):
                    QMessageBox.warning(self, "Restock list", result["error"])
                    return
                self._show(result["request"])
                added += 1
            if added:
                self._reload()
            dialog.accept()

        ok.clicked.connect(save)
        dialog.exec_()

    def _print(self):
        if not self.current:
            return
        outcome = self.api.print_saved_document("restock", self.current["id"], reprint=True) or {}
        if outcome.get("printed"):
            self.status.setText("Sent to the receipt printer.")
            return
        from backend import restock_requests as restock
        preview = _run(self.actor, restock.document_text, self.current["id"], "80")
        text = preview.get("text") or outcome.get("message") or outcome.get("error") or "The request could not be printed."
        dialog = QDialog(self)
        dialog.setWindowTitle("Restocking request")
        layout = QVBoxLayout(dialog)
        note = QLabel(outcome.get("message") or "No receipt printer is connected. The request is shown here and can be saved as a PDF.")
        note.setWordWrap(True)
        layout.addWidget(note)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        layout.addWidget(view)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.resize(420, 640)
        dialog.exec_()

    def _save_pdf(self):
        if not self.current:
            return
        from PyQt5.QtWidgets import QFileDialog
        from backend import restock_requests as restock
        path, _selected = QFileDialog.getSaveFileName(
            self, "Save restocking request PDF", f"{self.current.get('reference') or 'restock'}.pdf", "PDF (*.pdf)",
        )
        if not path:
            self.status.setText("PDF save was cancelled.")
            return
        result = _run(self.actor, restock.document_pdf, self.current["id"], "a4")
        if result.get("error"):
            QMessageBox.warning(self, "Restock list", result["error"])
            return
        with open(path, "wb") as handle:
            handle.write(result["pdf"])
        self.status.setText("PDF saved. This is not a supplier invoice or goods received note.")


def _ask_quantity(parent, title):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QFormLayout(dialog)
    quantity = QDoubleSpinBox()
    quantity.setDecimals(4)
    quantity.setMaximum(999999)
    quantity.setValue(1)
    layout.addRow("Quantity", quantity)
    buttons = QHBoxLayout()
    ok = QPushButton("Save")
    cancel = QPushButton("Cancel")
    buttons.addWidget(ok)
    buttons.addWidget(cancel)
    layout.addRow(buttons)
    chosen = {"ok": False}

    def accept():
        chosen["ok"] = True
        dialog.accept()

    ok.clicked.connect(accept)
    cancel.clicked.connect(dialog.reject)
    dialog.exec_()
    return quantity.value(), chosen["ok"]


def open_restock_dialog(parent, api, user, product_id=None):
    if not can_open_restock(user):
        QMessageBox.warning(parent, "Restock lists", "You cannot open restock lists.")
        return None
    dialog = RestockDialog(api, user, parent, product_id=product_id)
    dialog.exec_()
    return dialog
