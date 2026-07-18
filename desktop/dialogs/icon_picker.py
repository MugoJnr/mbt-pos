"""
MBT POS — Product / Category Icon Picker
MugoByte Technologies | mugobyte.com

Coloured emoji tiles (Claude icon pack look) across 18 sections.
Keeps original emoji colour on tinted category backgrounds.
Returns icon id via selected_icon_id() for persistence.
"""
from __future__ import annotations

from collections import OrderedDict

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C
from desktop.utils.category_visuals import (
    all_icons, search_icons, find_icon, favorite_ids, recent_ids,
    toggle_favorite, push_recent, emoji_tile_pixmap, section_tile_bg,
    SECTION_TILE_COLOURS, icon_to_pixmap,
)


def _icons_by_section() -> OrderedDict:
    """Group index icons by Claude section name, preserving index order."""
    groups = OrderedDict()
    for ic in all_icons():
        sec = ic.get('section') or 'General / Default'
        groups.setdefault(sec, []).append(ic)
    # Prefer Claude section order when present
    ordered = OrderedDict()
    for sec in SECTION_TILE_COLOURS:
        if sec in groups:
            ordered[sec] = groups.pop(sec)
    for sec, items in groups.items():
        ordered[sec] = items
    return ordered


class _EmojiTile(QPushButton):
    picked = pyqtSignal(dict)

    def __init__(self, icon: dict, selected_id: str = '', parent=None):
        super().__init__(parent)
        self._icon = icon
        self._id = icon.get('id') or ''
        self.setFixedSize(80, 80)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(icon.get('name') or '')
        self.set_selected(self._id == selected_id)
        self.clicked.connect(lambda: self.picked.emit(self._icon))

    def set_selected(self, on: bool):
        from desktop.utils.category_visuals import icon_to_pixmap
        pm = icon_to_pixmap(icon=self._icon, size=72)
        if on:
            # redraw with gold ring
            ic = self._icon
            bg = ic.get('bg') or section_tile_bg(ic.get('section') or '')
            pm = emoji_tile_pixmap(
                ic.get('emoji') or '📦',
                bg=bg,
                size=72,
                selected=True,
                selected_border=C.get('gold', '#D4A017'),
                emoji_png=ic.get('emoji_png'),
            )
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(72, 72))
        self.setText('')
        self.setStyleSheet(
            'QPushButton { background:transparent; border:none; padding:0; }'
            'QPushButton:hover { background:transparent; }'
        )


class IconPickerDialog(QDialog):
    """
    Scrollable coloured emoji grid (242 icons).
    Accept → selected_icon_id() for category editor / POS.
    """

    def __init__(self, parent=None, current_icon: str = None, current_emoji: str = ''):
        super().__init__(parent)
        self.setWindowTitle('Choose Product Icon')
        self.setMinimumSize(780, 580)
        self.setModal(True)
        self._selected = find_icon(current_icon) if current_icon else None
        if not self._selected and current_emoji:
            for ic in all_icons():
                if ic.get('emoji') == current_emoji:
                    self._selected = ic
                    break
        self._by_section = _icons_by_section()
        self._tiles = []
        self._build()
        self._render_all()
        self._update_preview()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(58)
        hdr.setStyleSheet(
            f"background:{C['card2']}; border-bottom:1px solid {C['border2']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(14)

        title = QLabel('Choose Product Icon')
        title.setStyleSheet(
            f"color:{C['text']}; font-size:16px; font-weight:800; "
            f"background:transparent; border:none;")
        hl.addWidget(title)
        hl.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText('  Search icons…')
        self._search.setFixedWidth(240)
        self._search.setFixedHeight(38)
        self._search.setStyleSheet(
            f"QLineEdit {{ background:{C['input']}; color:{C['text']}; "
            f"border:1.5px solid {C['border2']}; border-radius:19px; "
            f"padding:0 14px; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{C['gold']}; }}")
        self._search.textChanged.connect(self._on_search)
        hl.addWidget(self._search)

        close_btn = QPushButton('✕')
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{C['card2']}; color:{C['text2']}; "
            f"border:1px solid {C['border2']}; border-radius:8px; font-size:14px; }}"
            f"QPushButton:hover {{ color:{C['err']}; border-color:{C['err']}; }}")
        close_btn.clicked.connect(self.reject)
        hl.addWidget(close_btn)
        root.addWidget(hdr)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        total = sum(len(v) for v in self._by_section.values())
        self._cat_list = QListWidget()
        self._cat_list.setFixedWidth(210)
        self._cat_list.setStyleSheet(
            f"QListWidget {{ background:{C['panel']}; border:none; "
            f"border-right:1px solid {C['border2']}; outline:none; padding:8px 4px; }}"
            f"QListWidget::item {{ color:{C['text2']}; font-size:12px; font-weight:600; "
            f"padding:9px 12px; border-radius:8px; margin:1px 4px; border:none; }}"
            f"QListWidget::item:selected {{ background:{C['selected']}; color:{C['gold']}; }}"
            f"QListWidget::item:hover:!selected {{ background:{C['hover']}; color:{C['text']}; }}")
        self._cat_list.addItem(QListWidgetItem(f'  All Icons ({total})'))
        self._cat_list.addItem(QListWidgetItem('  ★ Favorites'))
        self._cat_list.addItem(QListWidgetItem('  Recently used'))
        for sec, items in self._by_section.items():
            sample = (items[0].get('emoji') or '📦') if items else '📦'
            self._cat_list.addItem(QListWidgetItem(f'  {sample}  {sec}'))
        self._cat_list.setCurrentRow(0)
        self._cat_list.currentRowChanged.connect(self._on_cat_change)
        body.addWidget(self._cat_list)

        right = QWidget()
        right.setStyleSheet(f"background:{C['surface']};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 16, 16, 16)
        rl.setSpacing(12)

        self._cat_label = QLabel('ALL ICONS')
        self._cat_label.setStyleSheet(
            f"color:{C['muted']}; font-size:10px; font-weight:800; "
            f"letter-spacing:1.5px; background:transparent; border:none;")
        rl.addWidget(self._cat_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea { border:none; background:transparent; }')

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet('background:transparent;')
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(8)
        self._grid.setContentsMargins(0, 0, 8, 0)
        scroll.setWidget(self._grid_widget)
        rl.addWidget(scroll, 1)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        # Footer
        ftr = QWidget()
        ftr.setFixedHeight(58)
        ftr.setStyleSheet(
            f"background:{C['card2']}; border-top:1px solid {C['border2']};")
        fl = QHBoxLayout(ftr)
        fl.setContentsMargins(20, 0, 20, 0)
        fl.setSpacing(12)

        self._preview_img = QLabel()
        self._preview_img.setFixedSize(40, 40)
        fl.addWidget(self._preview_img)

        self._preview = QLabel('No icon selected')
        self._preview.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent; border:none;")
        fl.addWidget(self._preview, 1)

        fav_btn = QPushButton('★ Fav')
        fav_btn.setFixedHeight(38)
        fav_btn.setFixedWidth(72)
        fav_btn.setCursor(Qt.PointingHandCursor)
        fav_btn.setStyleSheet(
            f"QPushButton {{ background:{C['card2']}; color:{C['gold']}; "
            f"border:1px solid {C['border2']}; border-radius:9px; font-size:13px; }}"
            f"QPushButton:hover {{ border-color:{C['gold']}; }}")
        fav_btn.clicked.connect(self._toggle_fav)
        fl.addWidget(fav_btn)

        clear_btn = QPushButton('Clear Icon')
        clear_btn.setFixedHeight(38)
        clear_btn.setFixedWidth(110)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(
            f"QPushButton {{ background:{C['card2']}; color:{C['text2']}; "
            f"border:1px solid {C['border2']}; border-radius:9px; font-size:13px; }}"
            f"QPushButton:hover {{ color:{C['err']}; border-color:{C['err']}; }}")
        clear_btn.clicked.connect(self._clear)
        fl.addWidget(clear_btn)

        self._ok_btn = QPushButton('Use This Icon')
        self._ok_btn.setFixedHeight(38)
        self._ok_btn.setFixedWidth(140)
        self._ok_btn.setCursor(Qt.PointingHandCursor)
        self._ok_btn.setEnabled(bool(self._selected))
        self._ok_btn.setStyleSheet(
            f"QPushButton {{ background:{C['gold']}; color:#080810; "
            f"border:none; border-radius:9px; font-size:13px; font-weight:700; }}"
            f"QPushButton:hover {{ background:{C.get('gold_lt', C['gold'])}; }}"
            f"QPushButton:disabled {{ background:{C['panel']}; color:{C['muted']}; }}")
        self._ok_btn.clicked.connect(self._accept)
        fl.addWidget(self._ok_btn)
        root.addWidget(ftr)

        self.setStyleSheet(f"QDialog {{ background:{C['app']}; }}")

    def _clear_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._tiles = []

    def _render_icons(self, icons: list, label: str):
        self._clear_grid()
        sel_id = (self._selected or {}).get('id') or ''
        cols = 7
        for idx, ic in enumerate(icons):
            btn = _EmojiTile(ic, selected_id=sel_id)
            btn.picked.connect(self._select)
            self._grid.addWidget(btn, idx // cols, idx % cols)
            self._tiles.append(btn)
        self._cat_label.setText(f'{label}  ({len(icons)})')

    def _render_all(self):
        icons = []
        for items in self._by_section.values():
            icons.extend(items)
        self._render_icons(icons, 'ALL ICONS')

    def _on_cat_change(self, row: int):
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        if row <= 0:
            self._render_all()
            return
        if row == 1:
            favs = set(favorite_ids())
            icons = [ic for ic in all_icons() if ic.get('id') in favs]
            self._render_icons(icons, 'FAVORITES')
            return
        if row == 2:
            order = recent_ids()
            by_id = {ic.get('id'): ic for ic in all_icons()}
            icons = [by_id[i] for i in order if i in by_id]
            self._render_icons(icons, 'RECENTLY USED')
            return
        secs = list(self._by_section.keys())
        sec = secs[row - 3]
        self._render_icons(self._by_section[sec], sec.upper())

    def _on_search(self, text: str):
        q = (text or '').strip()
        if not q:
            self._on_cat_change(self._cat_list.currentRow())
            return
        results = search_icons(q, limit=300)
        self._render_icons(results, f'SEARCH RESULTS')

    def _select(self, icon: dict):
        self._selected = icon
        sel_id = icon.get('id')
        for t in self._tiles:
            t.set_selected(t._id == sel_id)
        self._update_preview()

    def _update_preview(self):
        if not self._selected:
            self._preview_img.clear()
            self._preview.setText('No icon selected')
            self._ok_btn.setEnabled(False)
            return
        ic = self._selected
        bg = ic.get('bg') or section_tile_bg(ic.get('section') or '')
        self._preview_img.setPixmap(
            emoji_tile_pixmap(
                ic.get('emoji') or '📦',
                bg=bg,
                size=40,
                emoji_png=ic.get('emoji_png'),
            ))
        self._preview.setText(
            f"Selected:  {ic.get('emoji') or ''}  {ic.get('name') or ''}")
        self._preview.setStyleSheet(
            f"color:{C['text']}; font-size:15px; background:transparent; border:none;")
        self._ok_btn.setEnabled(True)

    def _toggle_fav(self):
        if not self._selected:
            return
        toggle_favorite(self._selected.get('id'))

    def _clear(self):
        self._selected = None
        self._update_preview()
        self._on_cat_change(self._cat_list.currentRow())

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

    def selected_emoji(self) -> str:
        return (self._selected or {}).get('emoji') or ''

    def selected_category(self) -> str:
        return (self._selected or {}).get('section') or ''

    @classmethod
    def pick(cls, parent=None, current_emoji='', current_icon=''):
        """Returns (emoji, section) or ('', '') if cancelled — Claude API."""
        dlg = cls(parent, current_icon=current_icon, current_emoji=current_emoji)
        if dlg.exec_() == QDialog.Accepted and dlg.selected_emoji():
            return dlg.selected_emoji(), dlg.selected_category()
        return '', ''
