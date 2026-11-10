"""Non-modal sale document. Print retry never submits the sale again."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QFileDialog,
)

from desktop.utils.theme import C


class SaleDocumentDialog(QDialog):
    def __init__(self, api, sale_id: int, parent=None, notice: str = ""):
        super().__init__(parent)
        self.api = api
        self.sale_id = int(sale_id)
        self.setWindowTitle("Sale document")
        self.setWindowModality(Qt.NonModal)
        self.setMinimumSize(420, 560)
        self.setStyleSheet(
            f"QDialog {{ background:{C.get('surface', '#0B1220')}; color:{C.get('text', '#fff')}; }}"
        )
        layout = QVBoxLayout(self)
        self.notice = QLabel(notice or "")
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color:{C.get('warn', '#E6B450')}; font-weight:600;")
        layout.addWidget(self.notice)
        self.title = QLabel("Document")
        self.title.setStyleSheet("font-size:16px; font-weight:700;")
        layout.addWidget(self.title)
        self.body = QTextEdit()
        self.body.setReadOnly(True)
        self.body.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; background:#111; color:#f4f4f4;"
        )
        layout.addWidget(self.body, 1)
        row = QHBoxLayout()
        for label, slot in (
            ("View receipt", lambda: self._load("receipt")),
            ("View invoice", lambda: self._load("invoice")),
            ("Print", lambda: self._print(False)),
            ("Reprint", lambda: self._print(True)),
            ("Download PDF", self._download),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        kind_row = QHBoxLayout()
        self.use_receipt = QPushButton("Use receipt")
        self.use_invoice = QPushButton("Use invoice")
        self.use_receipt.clicked.connect(lambda: self._change("receipt"))
        self.use_invoice.clicked.connect(lambda: self._change("invoice"))
        kind_row.addWidget(self.use_receipt)
        kind_row.addWidget(self.use_invoice)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        kind_row.addWidget(close)
        layout.addLayout(kind_row)
        self._doc = {}
        self._load("")

    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _load(self, kind: str):
        doc = self.api.sale_document(self.sale_id, kind=kind, reprint=False)
        if not doc or doc.get("error"):
            self.body.setPlainText((doc or {}).get("error") or "The document could not be opened.")
            return
        self._doc = doc
        self.title.setText(f"{doc.get('title') or 'Document'}  {doc.get('number') or ''}")
        self.body.setPlainText(doc.get("text") or "")
        allowed = bool(doc.get("can_override"))
        self.use_receipt.setEnabled(allowed)
        self.use_invoice.setEnabled(allowed)

    def _print(self, reprint: bool):
        outcome = self.api.print_sale_document(self.sale_id, automatic=False, reprint=reprint)
        if outcome.get("printed"):
            self.notice.setText(outcome.get("message") or "Sent to the printer.")
            self.notice.setStyleSheet("color:#8FDBA8; font-weight:600;")
        else:
            self.notice.setText(
                outcome.get("message")
                or "Sale saved successfully. Printer unavailable. You can view, download or print the document later."
            )
            self.notice.setStyleSheet("color:#E6B450; font-weight:600;")
        self._load("" if not reprint else (self._doc.get("kind") or ""))

    def _download(self):
        from printing.sale_documents import document_pdf
        number = (self._doc or {}).get("number") or f"sale-{self.sale_id}"
        path, _selected = QFileDialog.getSaveFileName(self, "Download PDF", f"{number}.pdf", "PDF (*.pdf)")
        if not path:
            return
        doc = self._doc or self.api.sale_document(self.sale_id)
        with open(path, "wb") as handle:
            handle.write(document_pdf(doc))
        self.notice.setText(f"Saved {number}.pdf")

    def _change(self, kind: str):
        result = self.api.set_sale_document_kind(self.sale_id, kind)
        if result.get("error"):
            self.notice.setText(result["error"])
            return
        self.notice.setText(f"Document type is {result.get('kind')}. The number stays {result.get('number')}.")
        self._load(kind)
