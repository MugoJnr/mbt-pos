"""
MBT POS — Credit-sale customer dialogs (stay on POS).
Select existing (searchable) | Create new | Cancel.
"""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFormLayout,
    QMessageBox, QTextEdit,
)

from desktop.utils.theme import C, MBT_STYLESHEET, qss_alpha
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, H2, Caption


def ensure_credit_customer(parent, api) -> Optional[int]:
    """
    When Credit/Part Payment needs a customer: choice → pick or create.
    Returns customer_id or None if cancelled. Never navigates away from POS.
    """
    choice = CreditCustomerChoiceDialog(parent)
    if choice.exec_() != QDialog.Accepted:
        return None
    action = choice.choice
    if action == 'existing':
        picker = CustomerPickerDialog(parent, api)
        if picker.exec_() != QDialog.Accepted:
            return None
        return picker.selected_id
    if action == 'create':
        dlg = QuickCustomerDialog(parent, api)
        if dlg.exec_() != QDialog.Accepted:
            return None
        return dlg.customer_id
    return None


class CreditCustomerChoiceDialog(QDialog):
    """Select Existing Customer | Create New Customer | Cancel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle('Customer Required for Credit')
        self.setMinimumWidth(420)
        self.setStyleSheet(MBT_STYLESHEET)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(H2('Credit Sale needs a customer'))
        tip = Caption(
            'Link this sale to a customer before checkout. '
            'Your cart stays intact — you will not leave the POS.')
        tip.setWordWrap(True)
        lay.addWidget(tip)

        existing = PrimaryBtn('Select Existing Customer', 48)
        existing.clicked.connect(lambda: self._pick('existing'))
        lay.addWidget(existing)

        create = PrimaryBtn('Create New Customer', 48)
        create.setStyleSheet(
            f"QPushButton{{background:{C['card2']};color:{C['gold']};"
            f"border:2px solid {C['gold']};border-radius:10px;"
            f"font-size:15px;font-weight:800;}}"
            f"QPushButton:hover{{background:{qss_alpha(C['gold'], 0.12)};}}")
        create.clicked.connect(lambda: self._pick('create'))
        lay.addWidget(create)

        cancel = SecondaryBtn('Cancel', 42)
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)

        from desktop.utils.state_reset import StateResetManager
        StateResetManager.clear_modal_on_close(self)

    def _pick(self, action: str):
        self.choice = action
        self.accept()


class QuickCustomerDialog(QDialog):
    """Modal create: Name*, Phone*, Email, Address, National ID, Notes."""

    def __init__(self, parent, api):
        super().__init__(parent)
        self.api = api
        self.customer_id = None
        self.setWindowTitle('Create New Customer')
        self.setMinimumWidth(480)
        self.setStyleSheet(MBT_STYLESHEET)
        lay = QFormLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)

        def lbl(t):
            w = QLabel(t)
            w.setStyleSheet(
                f"color:{C['text']};font-size:13px;font-weight:600;background:transparent;")
            return w

        def fld(ph=''):
            f = QLineEdit()
            f.setMinimumHeight(40)
            f.setPlaceholderText(ph)
            return f

        self.name = fld('Full name *')
        self.phone = fld('Phone *  e.g. 0712345678')
        self.email = fld('Email (optional)')
        self.addr = fld('Address (optional)')
        self.nid = fld('National ID (optional)')
        self.notes = QTextEdit()
        self.notes.setPlaceholderText('Notes (optional)')
        self.notes.setMaximumHeight(72)

        lay.addRow(lbl('Name *'), self.name)
        lay.addRow(lbl('Phone *'), self.phone)
        lay.addRow(lbl('Email'), self.email)
        lay.addRow(lbl('Address'), self.addr)
        lay.addRow(lbl('National ID'), self.nid)
        lay.addRow(lbl('Notes'), self.notes)

        br = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 42)
        cancel.clicked.connect(self.reject)
        save = PrimaryBtn('Save & Continue', 42)
        save.clicked.connect(self._save)
        br.addWidget(cancel, 1)
        br.addWidget(save, 1)
        lay.addRow(br)

        from desktop.utils.state_reset import StateResetManager
        StateResetManager.clear_modal_on_close(
            self, wipe=lambda: StateResetManager.reset_customer_form(self))

    def _save(self):
        name = self.name.text().strip()
        phone = self.phone.text().strip()
        if not name:
            QMessageBox.warning(self, 'Required', 'Name is required.')
            return
        if not phone:
            QMessageBox.warning(self, 'Required', 'Phone is required.')
            return
        data = {
            'name': name,
            'phone': phone,
            'email': self.email.text().strip(),
            'address': self.addr.text().strip(),
            'national_id': self.nid.text().strip(),
            'notes': self.notes.toPlainText().strip(),
        }
        try:
            from desktop.utils.auto_fill import AutoFillService
            existing = AutoFillService.prompt_use_existing_customer(
                self, self.api, phone)
            if existing == -1:
                return
            if existing is not None:
                self.customer_id = int(existing)
                self.accept()
                return
            res = self.api.create_customer(data)
            if res and res.get('success'):
                self.customer_id = int(res['customer_id'])
                self.accept()
            else:
                QMessageBox.critical(
                    self, 'Error', (res or {}).get('error', 'Failed to create customer.'))
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))


class CustomerPickerDialog(QDialog):
    """Searchable customer picker (type to filter)."""

    def __init__(self, parent, api):
        super().__init__(parent)
        self.api = api
        self.selected_id = None
        self._customers = []
        self.setWindowTitle('Select Customer')
        self.setMinimumSize(520, 480)
        self.setStyleSheet(MBT_STYLESHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(H2('Select Existing Customer'))

        self.search = QLineEdit()
        self.search.setMinimumHeight(42)
        self.search.setPlaceholderText('Type to search — e.g. Joh…')
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        try:
            from desktop.utils.select_controls import SearchableSelect
            self._use_select = True
            self.picker = SearchableSelect(placeholder='Search customers…')
            lay.addWidget(self.picker)
            self._list = None
        except Exception:
            self._use_select = False
            from PyQt5.QtWidgets import QListWidget, QListWidgetItem
            self.picker = None
            self._list = QListWidget()
            self._list.setMinimumHeight(280)
            self._list.itemDoubleClicked.connect(lambda *_: self._accept())
            lay.addWidget(self._list)

        br = QHBoxLayout()
        cancel = SecondaryBtn('Cancel', 42)
        cancel.clicked.connect(self.reject)
        ok = PrimaryBtn('Select & Continue', 42)
        ok.clicked.connect(self._accept)
        br.addWidget(cancel, 1)
        br.addWidget(ok, 1)
        lay.addLayout(br)

        self._load()
        self.search.setFocus()
        from desktop.utils.state_reset import StateResetManager
        StateResetManager.clear_modal_on_close(
            self, wipe=lambda: StateResetManager.clear_search(self.search))

    def _load(self):
        try:
            self._customers = self.api.get_customers() or []
        except Exception:
            self._customers = []
        self._filter()

    def _label(self, c: dict) -> str:
        name = (c.get('name') or '').strip()
        phone = (c.get('phone') or '').strip()
        out = f'{name}  ·  {phone}' if phone else name
        bal = float(c.get('total_outstanding') or 0)
        if bal > 0.009:
            out += f'  ·  Owing {bal:,.2f}'
        return out

    def _filter(self, *_args):
        q = self.search.text().strip().lower()
        items = []
        for c in self._customers:
            label = self._label(c)
            hay = f"{c.get('name','')} {c.get('phone','')} {c.get('email','')}".lower()
            if not q or q in hay:
                items.append((label, c.get('id')))
        if self._use_select and self.picker is not None:
            self.picker.set_items(items)
        elif self._list is not None:
            from PyQt5.QtWidgets import QListWidgetItem
            self._list.clear()
            for label, cid in items:
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, cid)
                self._list.addItem(it)

    def _accept(self):
        cid = None
        if self._use_select and self.picker is not None:
            cid = self.picker.current_value()
        elif self._list is not None:
            it = self._list.currentItem()
            if it:
                cid = it.data(Qt.UserRole)
        if not cid:
            QMessageBox.warning(self, 'Required', 'Select a customer from the list.')
            return
        self.selected_id = int(cid)
        self.accept()
