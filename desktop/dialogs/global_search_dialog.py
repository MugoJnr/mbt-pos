"""Ctrl+K global lookup — products, receipts, customers, open debts."""
from __future__ import annotations

from datetime import date, timedelta

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QAbstractItemView,
)

from desktop.utils.theme import C, ThemeManager


class GlobalSearchDialog(QDialog):
    """Lightweight omnisearch. Emits navigate(module_id, payload)."""

    navigate = pyqtSignal(str, object)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle('Search')
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self._hint = QLabel('Search products, receipts, customers, open debts')
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

        self._apply_theme()
        self._q.setFocus()

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

        # Products
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
                    results.append((
                        f"Product  ·  {p.get('name')}  ·  "
                        f"{p.get('sku') or '—'}  ·  stock {p.get('stock')}",
                        'inventory',
                        {'product_id': p.get('id'), 'query': q},
                    ))
                    if sum(1 for r in results if r[1] == 'inventory') >= 8:
                        break
        except Exception:
            pass

        # Customers
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
                results.append((
                    f"Customer  ·  {c.get('name')}  ·  {c.get('phone') or '—'}",
                    'debt',
                    {'customer_id': c.get('id'), 'query': q},
                ))
        except Exception:
            pass

        # Receipts (last 90 days)
        try:
            end = date.today()
            start = end - timedelta(days=90)
            sales = self.api.get_sales(str(start), str(end)) or []
            for s in sales:
                rn = (s.get('receipt_number') or '').lower()
                if ql in rn or ql in str(s.get('id') or ''):
                    results.append((
                        f"Receipt  ·  {s.get('receipt_number')}  ·  "
                        f"{s.get('payment_method')}  ·  {s.get('total')}  ·  "
                        f"{s.get('status')}",
                        'sales',
                        {'sale_id': s.get('id'), 'receipt_number': s.get('receipt_number')},
                    ))
                    if sum(1 for r in results if r[1] == 'sales') >= 8:
                        break
        except Exception:
            pass

        # Open debts
        try:
            debts = self.api.get_debt_invoices() or []
            for d in debts:
                status = (d.get('status') or '').lower()
                if status in ('paid', 'cancelled', 'written_off'):
                    continue
                blob = ' '.join([
                    str(d.get('invoice_number') or ''),
                    str(d.get('receipt_number') or ''),
                    str(d.get('customer_name') or ''),
                ]).lower()
                if ql in blob:
                    results.append((
                        f"Debt  ·  {d.get('invoice_number')}  ·  "
                        f"{d.get('customer_name')}  ·  bal {d.get('balance')}",
                        'debt',
                        {'invoice_id': d.get('id'), 'query': q},
                    ))
                    if sum(1 for r in results if r[0].startswith('Debt')) >= 8:
                        break
        except Exception:
            pass

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

    def _activate_current(self):
        item = self._list.currentItem()
        if item:
            self._on_item(item)

    def _on_item(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) if item else None
        if not data:
            return
        module, payload = data
        self.navigate.emit(module, payload)
        self.accept()
