"""Supplier payment. The payee, method, and reference are on the form."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QDoubleSpinBox, QMessageBox,
)
from PyQt5.QtCore import Qt

from desktop.utils.theme import C
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn


def prompt_supplier_payment(parent, *, supplier_name: str, outstanding: float,
                            suggested: float = None) -> dict | None:
    """Ask who is paid, how, and the reference. An overpayment must be confirmed."""
    name = (supplier_name or "Supplier").strip() or "Supplier"
    owed = round(float(outstanding or 0), 2)
    start = owed if suggested is None else round(float(suggested or 0), 2)
    dialog = QDialog(parent)
    dialog.setWindowTitle("Supplier payment")
    dialog.setMinimumWidth(420)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    layout = QVBoxLayout(dialog)
    payee = QLabel(f"Payee: {name}")
    payee.setStyleSheet(f"color:{C['text']}; font-size:15px; font-weight:700;")
    payee.setWordWrap(True)
    layout.addWidget(payee)
    layout.addWidget(QLabel(f"Outstanding on open invoices: {owed:,.2f}"))
    method = QComboBox()
    method.addItems(["Cash", "M-Pesa", "Card", "Bank Transfer"])
    method.setMinimumHeight(36)
    layout.addWidget(QLabel("Method"))
    layout.addWidget(method)
    reference = QLineEdit()
    reference.setPlaceholderText("Reference (receipt, M-Pesa code, or cheque)")
    reference.setMinimumHeight(36)
    layout.addWidget(QLabel("Reference"))
    layout.addWidget(reference)
    amount = QDoubleSpinBox()
    amount.setRange(0.01, 99999999)
    amount.setDecimals(2)
    amount.setValue(max(0.01, start) if start > 0 else 0.01)
    amount.setMinimumHeight(36)
    layout.addWidget(QLabel("Amount"))
    layout.addWidget(amount)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = SecondaryBtn("Cancel", 36)
    cancel.clicked.connect(dialog.reject)
    save = PrimaryBtn("Record payment", 36)
    buttons.addWidget(cancel)
    buttons.addWidget(save)
    layout.addLayout(buttons)

    chosen = {}

    def accept():
        paid = round(float(amount.value()), 2)
        if paid <= 0:
            QMessageBox.warning(dialog, "Amount", "Enter a payment amount greater than zero.")
            return
        allow = False
        if paid - owed > 0.009:
            answer = QMessageBox.question(
                dialog,
                "More than is owed",
                f"{paid:,.2f} is more than {name} is owed ({owed:,.2f}). "
                "Leave the extra as supplier credit?",
            )
            if answer != QMessageBox.Yes:
                return
            allow = True
        chosen.update({
            "amount": paid,
            "method": method.currentText(),
            "reference": reference.text().strip(),
            "allow_overpay": allow,
            "supplier_name": name,
        })
        dialog.accept()

    save.clicked.connect(accept)
    if dialog.exec_() != QDialog.Accepted:
        return None
    return chosen or None
