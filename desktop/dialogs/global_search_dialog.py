"""Ctrl+K global lookup — products, receipts, customers, open debts."""
from __future__ import annotations

from datetime import date, timedelta

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QAbstractItemView,
)

from desktop.utils.theme import C, ThemeManager
from desktop.utils.dialog_keys import wire_dialog_keys


class GlobalSearchDialog(QDialog):
    """Lightweight omnisearch. Emits navigate(module_id, payload)."""

    navigate = pyqtSignal(str, object)

    def __init__(self, api, parent=None, allowed_modules=None):
        super().__init__(parent)
        self.api = api
        self.allowed_modules = set(
            allowed_modules or ('sales', 'inventory', 'debt'))
        self.setWindowTitle('Search')
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self._hint = QLabel(self._hint_text())
        self._hint.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        lay.addWidget(self._hint)

        self._q = QLineEdit()
        self._q.setPlaceholderText('Type at least 2 characters…')
        self._q.setMinimumHeight(40)
        self._q.textChanged.connect(self._run)
        self._q.returnPressed.connect(self._activate_current)
        lay.addWidget(self._q)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.itemActivated.connect(self._on_item)
        self._list.itemDoubleClicked.connect(self._on_item)
        lay.addWidget(self._list, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.reject)
        row.addWidget(close_btn)
        lay.addLayout(row)

        # Enter belongs to the query field / result list, never to Close.
        wire_dialog_keys(self, primary=None, cancel=close_btn)
        self._apply_theme()
        self._q.setFocus()

    def _hint_text(self) -> str:
        """Advertise only what this user can actually open."""
        kinds = []
        if 'inventory' in self.allowed_modules:
            kinds.append('products')
        if 'sales' in self.allowed_modules:
            kinds.append('receipts')
        if 'debt' in self.allowed_modules:
            kinds.extend(('customers', 'open debts'))
        if not kinds:
            return 'No searchable modules are available for your role'
        return 'Search ' + ', '.join(kinds)

    def _apply_theme(self):
        light = ThemeManager.is_light()
        bg = C.get('card', '#fff' if light else '#1a2332')
        fg = C.get('text', '#111' if light else '#eee')
        border = C.get('border', '#ccc')
        self.setStyleSheet(
            f"QDialog {{ background:{bg}; color:{fg}; }}"
            f"QLineEdit {{ background:{C.get('input','#fff')}; color:{fg}; "
            f"border:1px solid {border}; border-radius:8px; padding:8px 12px; }}"
            f"QListWidget {{ background:{bg}; color:{fg}; border:1px solid {border}; "
            f"border-radius:8px; }}"
            f"QPushButton {{ min-height:34px; padding:6px 14px; }}"
        )

    def _run(self, text: str = ''):
        q = (text or self._q.text() or '').strip()
        self._list.clear()
        if len(q) < 2:
            return
        ql = q.lower()
        results = []

        # Only query what this role can open — previously every source was
        # fetched and the disallowed hits were discarded afterwards.
        if not self.allowed_modules:
            item = QListWidgetItem('No searchable modules are available for your role')
            item.setFlags(Qt.NoItemFlags)
            self._list.addItem(item)
            return

        if 'inventory' in self.allowed_modules:
            results.extend(self._search_products(q, ql))
        if 'debt' in self.allowed_modules:
            results.extend(self._search_customers(q, ql))
        if 'sales' in self.allowed_modules:
            results.extend(self._search_receipts(ql))
        if 'debt' in self.allowed_modules:
            results.extend(self._search_debts(q, ql))

        if not results:
            item = QListWidgetItem('No matches')
            item.setFlags(Qt.NoItemFlags)
            self._list.addItem(item)
            return

        for label, module, payload in results[:40]:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, (module, payload))
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    # Products
    def _search_products(self, q: str, ql: str) -> list:
        out = []
        try:
            for p in (self.api.get_products() or [])[:800]:
                if not p.get('is_active', 1):
                    continue
                blob = ' '.join([
                    str(p.get('name') or ''),
                    str(p.get('sku') or ''),
                    str(p.get('barcode') or ''),
                ]).lower()
                if ql in blob:
                    out.append((
                        f"Product  ·  {p.get('name')}  ·  "
                        f"{p.get('sku') or '—'}  ·  stock {p.get('stock')}",
                        'inventory',
                        {'product_id': p.get('id'), 'query': q},
                    ))
                    if len(out) >= 8:
                        break
        except Exception:
            pass
        return out

    # Customers
    def _search_customers(self, q: str, ql: str) -> list:
        out = []
        try:
            customers = []
            if hasattr(self.api, 'search_customers'):
                customers = self.api.search_customers(q) or []
            if not customers:
                customers = [
                    c for c in (self.api.get_customers() or [])
                    if ql in (c.get('name') or '').lower()
                    or ql in (c.get('phone') or '').lower()
                ]
            for c in customers[:8]:
                out.append((
                    f"Customer  ·  {c.get('name')}  ·  {c.get('phone') or '—'}",
                    'debt',
                    {'customer_id': c.get('id'), 'query': q},
                ))
        except Exception:
            pass
        return out

    # Receipts (last 90 days)
    def _search_receipts(self, ql: str) -> list:
        out = []
        try:
            end = date.today()
            start = end - timedelta(days=90)
            for s in (self.api.get_sales(str(start), str(end)) or []):
                rn = (s.get('receipt_number') or '').lower()
                if ql in rn or ql in str(s.get('id') or ''):
                    out.append((
                        f"Receipt  ·  {s.get('receipt_number')}  ·  "
                        f"{s.get('payment_method')}  ·  {s.get('total')}  ·  "
                        f"{s.get('status')}",
                        'sales',
                        {'sale_id': s.get('id'),
                         'receipt_number': s.get('receipt_number')},
                    ))
                    if len(out) >= 8:
                        break
        except Exception:
            pass
        return out

    # Open debts
    def _search_debts(self, q: str, ql: str) -> list:
        out = []
        try:
            for d in (self.api.get_debt_invoices() or []):
                status = (d.get('status') or '').lower()
                if status in ('paid', 'cancelled', 'written_off'):
                    continue
                blob = ' '.join([
                    str(d.get('invoice_number') or ''),
                    str(d.get('receipt_number') or ''),
                    str(d.get('customer_name') or ''),
                ]).lower()
                if ql in blob:
                    out.append((
                        f"Debt  ·  {d.get('invoice_number')}  ·  "
                        f"{d.get('customer_name')}  ·  bal {d.get('balance')}",
                        'debt',
                        {'invoice_id': d.get('id'), 'query': q},
                    ))
                    if len(out) >= 8:
                        break
        except Exception:
            pass
        return out

    def _activate_current(self):
        item = self._list.currentItem()
        if item:
            self._on_item(item)

    def _on_item(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) if item else None
        if not data:
            return
        module, payload = data
        self.accept()
        # Let QDialog.exec_ unwind before the receiver replaces the current tab.
        QTimer.singleShot(0, lambda: self.navigate.emit(module, payload))
