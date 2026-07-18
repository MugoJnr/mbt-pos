"""
MBT POS — Category editor dialog (name, visual type, icon/image, accent).
"""
from __future__ import annotations

import os

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, qss_alpha
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, Field
from desktop.utils.category_visuals import (
    CategoryVisual, suggest_icons_for_name, save_category_image,
    resolve_icon_path, svg_to_pixmap, accessible_fg, find_icon,
)
from desktop.dialogs.icon_picker import IconPickerDialog


class CategoryEditorDialog(QDialog):
    def __init__(self, parent=None, category: dict = None, api=None):
        super().__init__(parent)
        self.api = api
        self._cat = dict(category or {})
        self._icon_id = self._cat.get('icon_name') or ''
        self._image_path = self._cat.get('image_path') or ''
        self.setWindowTitle('Edit Category' if self._cat.get('id') else 'New Category')
        self.setMinimumWidth(480)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.name = Field('e.g. Grocery, Pharmacy…')
        self.name.setMinimumHeight(40)
        self.name.textChanged.connect(self._on_name_changed)
        form.addRow('Name *', self.name)

        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText('Optional description')
        self.desc.setMaximumHeight(72)
        form.addRow('Description', self.desc)
        lay.addLayout(form)

        # Visual type
        vbox = QVBoxLayout()
        vbox.setSpacing(6)
        vlab = QLabel('Visual type')
        vlab.setStyleSheet(f"color:{C['text2']}; font-weight:600;")
        vbox.addWidget(vlab)
        row = QHBoxLayout()
        self._type_icon = QRadioButton('Icon')
        self._type_image = QRadioButton('Custom Image')
        self._type_icon.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self._type_icon)
        self._type_group.addButton(self._type_image)
        self._type_icon.toggled.connect(self._on_type)
        row.addWidget(self._type_icon)
        row.addWidget(self._type_image)
        row.addStretch(1)
        vbox.addLayout(row)
        lay.addLayout(vbox)

        # Preview + controls
        prev_row = QHBoxLayout()
        self._preview = CategoryVisual(size=72, show_label=False)
        prev_row.addWidget(self._preview)

        ctrl = QVBoxLayout()
        self._icon_btn = SecondaryBtn('Choose Icon…', 36)
        self._icon_btn.clicked.connect(self._pick_icon)
        ctrl.addWidget(self._icon_btn)
        self._img_btn = SecondaryBtn('Upload Image…', 36)
        self._img_btn.clicked.connect(self._pick_image)
        ctrl.addWidget(self._img_btn)
        self._icon_hint = QLabel('')
        self._icon_hint.setStyleSheet(f"color:{C['muted']}; font-size:11px;")
        self._icon_hint.setWordWrap(True)
        ctrl.addWidget(self._icon_hint)
        prev_row.addLayout(ctrl, 1)
        lay.addLayout(prev_row)

        # Accent color
        crow = QHBoxLayout()
        crow.addWidget(QLabel('Accent color'))
        self._color = QLineEdit('#3B82F6')
        self._color.setMaximumWidth(110)
        self._color.setMinimumHeight(36)
        self._color.textChanged.connect(self._refresh_preview)
        crow.addWidget(self._color)
        self._color_btn = QPushButton('Pick')
        self._color_btn.setMinimumHeight(36)
        self._color_btn.clicked.connect(self._pick_color)
        crow.addWidget(self._color_btn)
        self._fg_swatch = QLabel(' Aa ')
        self._fg_swatch.setAlignment(Qt.AlignCenter)
        self._fg_swatch.setFixedHeight(36)
        self._fg_swatch.setMinimumWidth(48)
        crow.addWidget(self._fg_swatch)
        crow.addStretch(1)
        lay.addLayout(crow)

        # Suggestions
        self._sug_label = QLabel('Suggestions')
        self._sug_label.setStyleSheet(f"color:{C['text2']}; font-weight:600;")
        lay.addWidget(self._sug_label)
        self._sug_row = QHBoxLayout()
        self._sug_row.setSpacing(6)
        lay.addLayout(self._sug_row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = SecondaryBtn('Cancel', 40)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        save = PrimaryBtn('Save Category', 40)
        save.clicked.connect(self._save)
        btns.addWidget(save)
        lay.addLayout(btns)

        self.setStyleSheet(
            f"QDialog {{ background:{C['app']}; color:{C['text']}; }}"
            f"QLineEdit, QPlainTextEdit {{ background:{C['input']}; color:{C['text']}; "
            f"border:1px solid {C.get('border', C['card2'])}; border-radius:8px; padding:6px; }}"
            f"QRadioButton {{ color:{C['text']}; }}")
        self._on_type()

    def _load(self):
        c = self._cat
        self.name.setText(c.get('name') or '')
        self.desc.setPlainText(c.get('description') or '')
        vt = (c.get('visual_type') or 'icon').lower()
        if vt == 'image':
            self._type_image.setChecked(True)
        else:
            self._type_icon.setChecked(True)
        self._icon_id = c.get('icon_name') or ''
        self._image_path = c.get('image_path') or ''
        self._color.setText(c.get('accent_color') or '#3B82F6')
        self._refresh_preview()
        self._update_suggestions(self.name.text())

    def _on_type(self):
        is_icon = self._type_icon.isChecked()
        self._icon_btn.setEnabled(is_icon)
        self._img_btn.setEnabled(not is_icon)
        self._refresh_preview()

    def _on_name_changed(self, text):
        self._update_suggestions(text)
        # Auto-suggest icon if empty
        if not self._icon_id and text.strip():
            sug = suggest_icons_for_name(text, limit=1)
            if sug:
                self._icon_id = sug[0].get('id') or ''
                bg = sug[0].get('bg')
                if bg and self._color.text() in ('', '#3B82F6'):
                    # keep brand-ish accents; only fill if default
                    pass
        self._refresh_preview()

    def _clear_sug(self):
        while self._sug_row.count():
            item = self._sug_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _update_suggestions(self, text):
        self._clear_sug()
        for ic in suggest_icons_for_name(text, limit=6):
            btn = QToolButton()
            btn.setFixedSize(44, 44)
            path = resolve_icon_path(ic.get('path') or ic.get('id'))
            if path:
                btn.setIcon(QIcon(svg_to_pixmap(path, 40)))
                btn.setIconSize(QSize(40, 40))
            btn.setToolTip(ic.get('name'))
            iid = ic.get('id')
            btn.clicked.connect(lambda _=False, i=iid: self._apply_suggestion(i))
            self._sug_row.addWidget(btn)
        self._sug_row.addStretch(1)

    def _apply_suggestion(self, icon_id: str):
        self._icon_id = icon_id
        self._type_icon.setChecked(True)
        ic = find_icon(icon_id)
        if ic and ic.get('bg'):
            # optional: don't override custom accent unless default
            pass
        self._refresh_preview()

    def _pick_icon(self):
        dlg = IconPickerDialog(self, current_icon=self._icon_id)
        if dlg.exec_() == QDialog.Accepted:
            self._icon_id = dlg.selected_icon_id()
            self._type_icon.setChecked(True)
            self._refresh_preview()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Category Image',
            '', 'Images (*.png *.jpg *.jpeg *.webp *.svg)')
        if not path:
            return
        try:
            saved = save_category_image(path)
            self._image_path = saved
            self._type_image.setChecked(True)
            self._refresh_preview()
        except Exception as e:
            QMessageBox.warning(self, 'Upload', f'Could not save image:\n{e}')

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self._color.text() or '#3B82F6'), self)
        if col.isValid():
            self._color.setText(col.name())

    def _refresh_preview(self):
        accent = self._color.text().strip() or '#3B82F6'
        vt = 'image' if self._type_image.isChecked() else 'icon'
        self._preview.set_visual(
            visual_type=vt,
            icon_name=self._icon_id,
            image_path=self._image_path,
            accent_color=accent,
            name=self.name.text().strip() or 'Category',
        )
        fg = accessible_fg(accent)
        self._fg_swatch.setStyleSheet(
            f"background:{accent}; color:{fg}; border-radius:6px; font-weight:700;")
        self._icon_hint.setText(
            f"Icon: {self._icon_id or '—'}"
            + (f"\nImage: {os.path.basename(self._image_path)}" if self._image_path else ''))

    def _save(self):
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, 'Category', 'Name is required.')
            return
        vt = 'image' if self._type_image.isChecked() else 'icon'
        if vt == 'icon' and not self._icon_id:
            sug = suggest_icons_for_name(name, limit=1)
            self._icon_id = (sug[0].get('id') if sug else 'generic/general-product')
        if vt == 'image' and not self._image_path:
            QMessageBox.warning(self, 'Category', 'Upload an image or switch to Icon.')
            return
        payload = {
            'name': name,
            'description': self.desc.toPlainText().strip(),
            'visual_type': vt,
            'icon_name': self._icon_id or None,
            'image_path': self._image_path or None,
            'accent_color': self._color.text().strip() or '#3B82F6',
        }
        if self._cat.get('id'):
            payload['id'] = self._cat['id']
        self._result = payload
        if self.api:
            try:
                if payload.get('id'):
                    self.api.update_category(payload['id'], payload)
                else:
                    created = self.api.create_category(payload)
                    self._result = created if isinstance(created, dict) else payload
            except Exception as e:
                QMessageBox.warning(self, 'Save', str(e))
                return
        self.accept()

    def result_data(self) -> dict:
        return getattr(self, '_result', {})
