"""
MBT POS — Offline Icon Picker dialog
Search, favorites, recently used, folder filters. Index-based (no folder scan).
"""
from __future__ import annotations

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, qss_alpha, RADIUS
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, GhostBtn
from desktop.utils.category_visuals import (
    all_icons, icon_folders, search_icons, svg_to_pixmap, resolve_icon_path,
    favorite_ids, recent_ids, toggle_favorite, push_recent, find_icon,
)


class _IconTile(QFrame):
    clicked = pyqtSignal(dict)
    fav_toggled = pyqtSignal(str)

    def __init__(self, icon: dict, selected_id: str = None, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._id = icon.get('id') or ''
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(88, 96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 4)
        lay.setSpacing(4)
        self._img = QLabel()
        self._img.setFixedSize(56, 56)
        self._img.setAlignment(Qt.AlignCenter)
        path = resolve_icon_path(icon.get('path') or icon.get('id'))
        if path:
            self._img.setPixmap(svg_to_pixmap(path, 56))
        lay.addWidget(self._img, 0, Qt.AlignCenter)
        name = (icon.get('name') or '')[:16]
        self._lbl = QLabel(name)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setWordWrap(True)
        self._lbl.setStyleSheet(f"color:{C['text2']}; font-size:10px; background:transparent;")
        lay.addWidget(self._lbl)
        self._fav = QToolButton()
        self._fav.setText('★' if self._id in favorite_ids() else '☆')
        self._fav.setFixedSize(22, 22)
        self._fav.setStyleSheet(
            f"QToolButton {{ border:none; color:{C['gold']}; background:transparent; font-size:14px; }}")
        self._fav.clicked.connect(self._toggle_fav)
        lay.addWidget(self._fav, 0, Qt.AlignRight)
        self.set_selected(self._id == selected_id)
        self.setToolTip(f"{icon.get('name')}\n{icon.get('section') or icon.get('category')}")

    def _toggle_fav(self):
        is_fav = toggle_favorite(self._id)
        self._fav.setText('★' if is_fav else '☆')
        self.fav_toggled.emit(self._id)

    def set_selected(self, on: bool):
        bg = qss_alpha(C['gold'], 0.18) if on else C['card']
        border = C['gold'] if on else C.get('border', C['card2'])
        self.setStyleSheet(
            f"QFrame {{ background:{bg}; border:2px solid {border}; "
            f"border-radius:{RADIUS.get('md', 10)}px; }}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._icon)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._icon)
            # Parent dialog listens via clicked; double-click accept handled there
            parent = self.window()
            if hasattr(parent, '_double'):
                parent._double(self._icon)
        super().mouseDoubleClickEvent(e)


class IconPickerDialog(QDialog):
    """Choose an offline category icon."""

    def __init__(self, parent=None, current_icon: str = None):
        super().__init__(parent)
        self.setWindowTitle('Choose Category Icon')
        self.setMinimumSize(720, 560)
        self.resize(780, 620)
        self._selected = find_icon(current_icon) if current_icon else None
        self._tiles = []
        self._build()
        self._reload()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # Search + filter
        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText('Search icons by name, keyword, category…')
        self._search.setMinimumHeight(40)
        self._search.textChanged.connect(self._reload)
        top.addWidget(self._search, 1)

        self._folder = QComboBox()
        self._folder.setMinimumHeight(40)
        self._folder.addItem('All folders', 'all')
        self._folder.addItem('★ Favorites', '__fav__')
        self._folder.addItem('🕐 Recently used', '__recent__')
        for f in icon_folders():
            self._folder.addItem(f.title(), f)
        self._folder.currentIndexChanged.connect(self._reload)
        top.addWidget(self._folder)
        root.addLayout(top)

        hint = QLabel('Offline icon library — no internet required. Double-click or Select to confirm.')
        hint.setStyleSheet(f"color:{C['muted']}; font-size:12px; background:transparent;")
        root.addWidget(hint)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)

        self._status = QLabel('')
        self._status.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        root.addWidget(self._status)

        # Preview + actions
        bot = QHBoxLayout()
        self._preview = QLabel()
        self._preview.setFixedSize(48, 48)
        self._preview.setAlignment(Qt.AlignCenter)
        bot.addWidget(self._preview)
        self._preview_name = QLabel('No icon selected')
        self._preview_name.setStyleSheet(f"color:{C['text']}; font-weight:600;")
        bot.addWidget(self._preview_name, 1)

        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        bot.addWidget(cancel)
        ok = PrimaryBtn('Select Icon', 40)
        ok.clicked.connect(self._accept)
        bot.addWidget(ok)
        root.addLayout(bot)

        self.setStyleSheet(
            f"QDialog {{ background:{C['app']}; }}"
            f"QLineEdit, QComboBox {{ background:{C['input']}; color:{C['text']}; "
            f"border:1px solid {C.get('border', C['card2'])}; border-radius:8px; padding:6px 10px; }}"
            f"QScrollArea {{ border:none; background:{C['app']}; }}")

    def _reload(self):
        # Clear grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._tiles = []

        folder = self._folder.currentData()
        q = self._search.text()
        icons = []

        if folder == '__fav__':
            favs = set(favorite_ids())
            icons = [ic for ic in all_icons() if ic.get('id') in favs]
            if q:
                icons = [ic for ic in search_icons(q) if ic.get('id') in favs]
        elif folder == '__recent__':
            order = recent_ids()
            by_id = {ic.get('id'): ic for ic in all_icons()}
            icons = [by_id[i] for i in order if i in by_id]
            if q:
                ql = q.lower()
                icons = [ic for ic in icons if ql in (ic.get('name') or '').lower()
                         or any(ql in k for k in (ic.get('keywords') or []))]
        else:
            icons = search_icons(q, folder=None if folder == 'all' else folder, limit=300)

        # Lazy: first page only — keep picker snappy offline
        sel_id = (self._selected or {}).get('id')
        cols = 7
        page = icons[:48]
        for i, ic in enumerate(page):
            tile = _IconTile(ic, selected_id=sel_id)
            tile.clicked.connect(self._on_pick)
            r, c = divmod(i, cols)
            self._grid.addWidget(tile, r, c)
            self._tiles.append(tile)

        more = len(icons) - len(page)
        self._status.setText(
            f'{len(icons)} icon(s)'
            + (f' matching “{q}”' if q else '')
            + (f' — showing first {len(page)}, refine search for more' if more > 0 else '')
        )
        self._update_preview()

    def _double(self, icon):
        self._selected = icon
        self._accept()

    def _on_pick(self, icon: dict):
        self._selected = icon
        sel_id = icon.get('id')
        for t in self._tiles:
            t.set_selected(t._id == sel_id)
        self._update_preview()

    def _update_preview(self):
        if not self._selected:
            self._preview.clear()
            self._preview_name.setText('No icon selected')
            return
        path = resolve_icon_path(self._selected.get('path') or self._selected.get('id'))
        if path:
            self._preview.setPixmap(svg_to_pixmap(path, 48))
        self._preview_name.setText(
            f"{self._selected.get('name')}  ·  {self._selected.get('category')}")

    def _accept(self):
        if not self._selected:
            QMessageBox.information(self, 'Icon', 'Please select an icon.')
            return
        push_recent(self._selected.get('id'))
        self.accept()

    def selected_icon(self) -> dict:
        return self._selected or {}

    def selected_icon_id(self) -> str:
        return (self._selected or {}).get('id') or ''
