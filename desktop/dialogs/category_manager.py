"""
MBT POS — Category management dialog (list + edit visuals).
"""
from __future__ import annotations

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, qss_alpha
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, GhostBtn, DangerBtn
from desktop.utils.category_visuals import CategoryVisual
from desktop.dialogs.category_editor import CategoryEditorDialog


class CategoryManagerDialog(QDialog):
    """Admin: manage category names + offline icons/images."""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle('Shop categories')
        self.setMinimumSize(640, 480)
        self.resize(720, 540)
        self._build()
        self.refresh()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel('Product Categories')
        title.setStyleSheet(f"color:{C['text']}; font-size:18px; font-weight:700;")
        top.addWidget(title, 1)
        add = PrimaryBtn('+ New Category', 36)
        add.clicked.connect(self._add)
        top.addWidget(add)
        ref = GhostBtn('Refresh', 36)
        ref.clicked.connect(self.refresh)
        top.addWidget(ref)
        lay.addLayout(top)

        hint = QLabel(
            'Categories belong to this shop. An empty category is allowed. '
            'Removing one never deletes its products.')
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['muted']}; font-size:12px;")
        lay.addWidget(hint)

        self._search = QLineEdit()
        self._search.setPlaceholderText('Search categories')
        self._search.setAccessibleName('Search categories')
        self._search.setMinimumHeight(36)
        self._search.textChanged.connect(self.refresh)
        lay.addWidget(self._search)

        self._list = QListWidget()
        self._list.setSpacing(4)
        self._list.setStyleSheet(
            f"QListWidget {{ background:{C['card']}; border:1px solid {C.get('border', C['card2'])}; "
            f"border-radius:10px; color:{C['text']}; }}"
            f"QListWidget::item {{ padding:6px; border-radius:8px; }}"
            f"QListWidget::item:selected {{ background:{qss_alpha(C['gold'], 0.2)}; }}")
        self._list.itemDoubleClicked.connect(self._edit_item)
        lay.addWidget(self._list, 1)

        bot = QHBoxLayout()
        edit = SecondaryBtn('Edit Visual…', 36)
        edit.clicked.connect(self._edit_selected)
        bot.addWidget(edit)
        dele = DangerBtn('Delete category', 36)
        dele.clicked.connect(self._deactivate)
        bot.addWidget(dele)
        bot.addStretch(1)
        close = SecondaryBtn('Close', 36)
        close.clicked.connect(self.accept)
        bot.addWidget(close)
        lay.addLayout(bot)

        self.setStyleSheet(f"QDialog {{ background:{C['app']}; }}")

    def refresh(self):
        self._list.clear()
        try:
            cats = self.api.get_categories(active_only=True) or []
        except Exception:
            cats = []
        query = ''
        try:
            query = (self._search.text() or '').strip().casefold()
        except Exception:
            query = ''
        if query:
            cats = [
                c for c in cats
                if query in (c.get('name') or '').casefold()
                or query in (c.get('description') or '').casefold()
            ]
        for c in cats:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c)
            # Prefer text row for speed; visual loaded on selection / edit
            accent = c.get('accent_color') or '#3B82F6'
            count = int(c.get('product_count') or 0)
            label = (
                f"{c.get('name') or ''}\n"
                f"{count} product{'s' if count != 1 else ''}"
                + (f" · {c.get('description')}" if c.get('description') else '')
            )
            item.setText(label)
            item.setSizeHint(QSize(200, 52))
            # Small decoration via CategoryVisual only for first 24
            self._list.addItem(item)
        # Attach visuals for first rows only (lazy)
        for i in range(min(24, self._list.count())):
            item = self._list.item(i)
            c = item.data(Qt.UserRole) or {}
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(8, 4, 8, 4)
            hl.setSpacing(12)
            vis = CategoryVisual(c, size=40, show_label=False)
            hl.addWidget(vis)
            col = QVBoxLayout()
            name = QLabel(c.get('name') or '')
            name.setStyleSheet(
                f"color:{C['text']}; font-weight:700; font-size:14px; background:transparent;")
            col.addWidget(name)
            count = int(c.get('product_count') or 0)
            meta = QLabel(
                f"{count} product{'s' if count != 1 else ''}"
                + (f" · {c.get('description')}" if c.get('description') else ' · No description')
            )
            meta.setStyleSheet(
                f"color:{C['text2']}; font-size:11px; background:transparent;")
            col.addWidget(meta)
            hl.addLayout(col, 1)
            item.setSizeHint(QSize(200, 64))
            item.setText('')  # widget replaces text
            self._list.setItemWidget(item, w)

    def _selected(self):
        it = self._list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _add(self):
        dlg = CategoryEditorDialog(self, category=None, api=self.api)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()

    def _edit_item(self, _item):
        self._edit_selected()

    def _edit_selected(self):
        cat = self._selected()
        if not cat:
            return
        dlg = CategoryEditorDialog(self, category=cat, api=self.api)
        if dlg.exec_() == QDialog.Accepted:
            self.refresh()

    def _deactivate(self):
        cat = self._selected()
        if not cat:
            return
        count = int(cat.get('product_count') or 0)
        if count:
            answer = QMessageBox.question(
                self, 'Delete category',
                f"Remove “{cat.get('name')}” and leave {count} product"
                f"{'s' if count != 1 else ''} uncategorised?\n\n"
                "The products stay in the shop. Only the category is removed.",
            )
            if answer != QMessageBox.Yes:
                return
            result = self.api.delete_category(cat['id'], leave_uncategorised=True)
        else:
            if QMessageBox.question(
                self, 'Delete category',
                f"Remove the empty category “{cat.get('name')}”?",
            ) != QMessageBox.Yes:
                return
            result = self.api.delete_category(cat['id'])
        if result.get('error'):
            QMessageBox.warning(self, 'Delete category', result['error'])
            return
        self.refresh()
