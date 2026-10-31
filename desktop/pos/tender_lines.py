"""A sale can take any number of payment lines. Cash is not required."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from desktop.utils.option_lists import SPLIT_LINE_METHODS
from desktop.utils.payment_tenders import is_credit_method
from desktop.utils.select_controls import Select
from desktop.utils.theme import C

METHODS = SPLIT_LINE_METHODS


def _r2(value) -> float:
    return round(float(value or 0), 2)


class TenderLines(QWidget):
    """Dynamic payment allocations. Each line is a method and an amount.

    Credit is the amount still owed. It is not money received.
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._due = 0.0
        self._currency = "KES"
        self._rows: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self._line_host = QWidget()
        self._lines = QVBoxLayout(self._line_host)
        self._lines.setContentsMargins(0, 0, 0, 0)
        self._lines.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(108)
        scroll.setMaximumHeight(220)
        scroll.setWidget(self._line_host)
        root.addWidget(scroll)
        actions = QVBoxLayout()
        actions.setSpacing(4)
        add = QPushButton("Add payment")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(lambda: self.add_line())
        self._credit = QPushButton("On account")
        self._credit.setToolTip(
            "Put the unpaid remainder on the customer account. "
            "You can also choose Credit on a payment line.")
        self._credit.setCheckable(True)
        self._credit.setCursor(Qt.PointingHandCursor)
        self._credit.toggled.connect(lambda *_: self._refresh())
        actions.addWidget(add)
        actions.addWidget(self._credit)
        root.addLayout(actions)
        self._remaining = QLabel("Remaining")
        self._remaining.setWordWrap(True)
        root.addWidget(self._remaining)
        self._customer_hint = QLabel("")
        self._customer_hint.setWordWrap(True)
        root.addWidget(self._customer_hint)
        self.add_line("M-Pesa", 0)
        self._apply_style()

    def _apply_style(self):
        text = C.get("text", "#fff")
        self._remaining.setStyleSheet(
            f"color:{text};font-size:13px;font-weight:800;background:transparent;")
        self._customer_hint.setStyleSheet(
            "color:#c9842a;font-size:12px;font-weight:700;background:transparent;")
        self._paint_credit_button()

    def _paint_credit_button(self):
        if self._credit.isChecked():
            self._credit.setStyleSheet(
                "color:#1a1206;font-size:12px;font-weight:800;"
                "background:#e0b15a;border:1px solid #e0b15a;border-radius:6px;padding:6px;")
        else:
            mute = C.get("text", "#fff")
            self._credit.setStyleSheet(
                f"color:{mute};font-size:12px;font-weight:700;"
                "background:transparent;border:1px solid #8a7344;border-radius:6px;padding:6px;")

    def set_due(self, due: float, currency: str = ""):
        self._due = _r2(due)
        if currency:
            self._currency = currency
        self._paint_remaining()

    def remainder_on_credit(self) -> bool:
        return bool(self._credit.isChecked())

    def reset(self):
        self._credit.setChecked(False)
        while self._rows:
            self._remove(0)
        self.add_line("M-Pesa", 0)

    def add_line(self, method: str = "", amount: float = 0):
        used = {row["method"].currentText() for row in self._rows}
        pick = method or next((name for name in METHODS if name not in used), METHODS[0])
        method_box = Select()
        method_box.set_items(list(METHODS))
        method_box.setCurrentText(pick if pick in METHODS else METHODS[0])
        method_box.setMinimumHeight(32)
        amount_box = QDoubleSpinBox()
        amount_box.setRange(0, 99999999)
        amount_box.setDecimals(2)
        amount_box.setValue(_r2(amount))
        amount_box.setMinimumHeight(32)
        amount_box.setPrefix("")
        amount_box.setButtonSymbols(QDoubleSpinBox.NoButtons)
        reference = QLineEdit()
        reference.setPlaceholderText("Reference")
        reference.setMinimumHeight(32)
        remove = QPushButton("Remove")
        remove.setCursor(Qt.PointingHandCursor)
        row = {
            "method": method_box,
            "amount": amount_box,
            "reference": reference,
            "remove": remove,
            "wrap": QWidget(),
        }
        lay = QVBoxLayout(row["wrap"])
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(method_box)
        money = QHBoxLayout()
        money.setSpacing(6)
        money.addWidget(amount_box, 1)
        money.addWidget(remove)
        lay.addLayout(money)
        lay.addWidget(reference)

        def _show_reference(*_):
            name = method_box.currentText() or ""
            reference.setVisible(name != "Cash" and not is_credit_method(name))

        _show_reference()
        remove.clicked.connect(lambda _=False, item=row: self._remove_row(item))
        method_box.currentTextChanged.connect(_show_reference)
        method_box.currentTextChanged.connect(lambda *_: self._refresh())
        amount_box.valueChanged.connect(lambda *_: self._refresh())
        reference.textChanged.connect(lambda *_: self._refresh())
        self._rows.append(row)
        self._lines.addWidget(row["wrap"])
        self._refresh()
        return len(self._rows) - 1

    def _remove_row(self, item: dict):
        if item not in self._rows:
            return
        self._rows.remove(item)
        item["wrap"].setParent(None)
        item["wrap"].deleteLater()
        if not self._rows:
            self.add_line()
            return
        self._refresh()

    def _remove(self, index: int):
        if 0 <= index < len(self._rows):
            self._remove_row(self._rows[index])

    def rows(self) -> list[dict]:
        out = []
        for row in self._rows:
            amount = _r2(row["amount"].value())
            method = (row["method"].currentText() or "").strip()
            if amount <= 0.009 or not method:
                continue
            if is_credit_method(method):
                out.append({"method": "Credit", "amount": amount, "status": "outstanding"})
                continue
            item = {"method": method, "amount": amount, "status": "confirmed"}
            reference = (row["reference"].text() or "").strip()
            if reference and method.lower() != "cash":
                item["reference"] = reference
            out.append(item)
        return out

    def money_paid(self) -> float:
        return _r2(sum(
            row["amount"] for row in self.rows() if not is_credit_method(row["method"])
        ))

    def credit_amount(self) -> float:
        explicit = _r2(sum(
            row["amount"] for row in self.rows() if is_credit_method(row["method"])
        ))
        gap = _r2(self._due - self.money_paid() - explicit)
        if self.remainder_on_credit() and gap > 0.009:
            return _r2(explicit + gap)
        return explicit

    def rows_for_sale(self, due: float) -> list[dict]:
        self._due = _r2(due)
        lines = self.rows()
        paid = self.money_paid()
        explicit = _r2(sum(
            row["amount"] for row in lines if is_credit_method(row["method"])
        ))
        left = _r2(self._due - paid - explicit)
        if self.remainder_on_credit() and left > 0.009:
            lines.append({"method": "Credit", "amount": left, "status": "outstanding"})
        return lines

    def remaining(self) -> float:
        """Amount not yet covered by money or an explicit credit line."""
        explicit = _r2(sum(
            row["amount"] for row in self.rows() if is_credit_method(row["method"])
        ))
        return _r2(self._due - self.money_paid() - explicit)

    def summary(self, currency: str = "KES") -> str:
        paid = self.money_paid()
        credit = self.credit_amount()
        left = self.remaining()
        parts = [
            f"Sale {currency} {self._due:,.2f}",
            f"Paid {currency} {paid:,.2f}",
            f"Customer credit {currency} {credit:,.2f}",
        ]
        if left > 0.009 and not self.remainder_on_credit():
            parts.append(f"Still due {currency} {left:,.2f}")
        elif left < -0.009:
            parts.append(f"Over by {currency} {abs(left):,.2f}")
        return " · ".join(parts)

    def _refresh(self):
        self._paint_credit_button()
        self._paint_remaining()
        self.changed.emit()

    def _paint_remaining(self):
        cur = self._currency or "KES"
        self._remaining.setText(self.summary(cur))
        if self.credit_amount() > 0.009:
            self._customer_hint.setText(
                "Select a customer. Customer credit is the amount still owed. "
                "It is not money received.")
        else:
            self._customer_hint.setText("")
