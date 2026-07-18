"""
MBT POS — Standardized select / smart input controls.
MugoByte Technologies | mugobyte.com

Theme-aware via live C palette + ThemeManager.
Keyboard: open (Alt+Down / F4), arrows, Enter, Esc, type-to-search.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple, Union

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QStringListModel
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QComboBox, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QAbstractItemView, QFrame, QPushButton,
    QDialog, QDialogButtonBox, QSizePolicy, QMessageBox, QApplication,
    QStyledItemDelegate,
)

from desktop.utils.theme import apply_themed_dialog,  C, RADIUS, TOUCH_MIN, qss_alpha

CONTROL_HEIGHT = max(40, TOUCH_MIN - 4)
OTHER_TOKEN = 'Other'


def _popup_view_qss() -> str:
    """Popup list QSS — no border-radius (Qt paints black corner artifacts)."""
    bg = C['card']
    fg = C['text']
    return (
        f"QAbstractItemView{{"
        f"background:{bg};color:{fg};"
        f"border:1px solid {C['border']};"
        f"selection-background-color:{qss_alpha(C['gold'], 0.18)};"
        f"selection-color:{fg};outline:0;padding:4px;}}"
        f"QAbstractItemView::item{{"
        f"min-height:32px;padding:6px 10px;color:{fg};background:{bg};}}"
        f"QAbstractItemView::item:selected{{"
        f"background:{C.get('selected', C['hover'])};color:{fg};}}"
        f"QAbstractItemView::item:hover{{"
        f"background:{C['hover']};color:{fg};}}"
    )


def _style_combo_popup(combo: QComboBox) -> None:
    """Force popup palette + QSS so dark mode never shows empty white sheets."""
    view = combo.view()
    if view is None:
        return
    bg = C['card']
    fg = C['text']
    sel = C.get('selected', C['hover'])
    view.setAttribute(Qt.WA_StyledBackground, True)
    view.setAutoFillBackground(True)
    from PyQt5.QtGui import QColor, QPalette
    pal = view.palette()
    pal.setColor(QPalette.Base, QColor(bg))
    pal.setColor(QPalette.Text, QColor(fg))
    pal.setColor(QPalette.Window, QColor(bg))
    pal.setColor(QPalette.WindowText, QColor(fg))
    pal.setColor(QPalette.ButtonText, QColor(fg))
    pal.setColor(QPalette.Highlight, QColor(sel))
    pal.setColor(QPalette.HighlightedText, QColor(fg))
    view.setPalette(pal)
    view.setStyleSheet(_popup_view_qss())
    # Completer popup (SearchableSelect) — same treatment
    try:
        comp = combo.completer()
        if comp is not None and comp.popup() is not None:
            pop = comp.popup()
            pop.setAttribute(Qt.WA_StyledBackground, True)
            pop.setAutoFillBackground(True)
            pop.setPalette(pal)
            pop.setStyleSheet(_popup_view_qss())
    except Exception:
        pass


def _select_qss(object_name: str = 'mbtSelect') -> str:
    r = RADIUS['md']
    bg = C['card']
    fg = C['text']
    return (
        f"QComboBox#{object_name}{{"
        f"background:{C['input']};color:{fg};"
        f"border:1px solid {C['border']};border-radius:{r}px;"
        f"padding:4px 12px;font-size:13px;font-weight:600;"
        f"min-height:{CONTROL_HEIGHT - 8}px;}}"
        f"QComboBox#{object_name}:hover{{border-color:{C['border2']};"
        f"background:{C['hover']};}}"
        f"QComboBox#{object_name}:focus{{border-color:{C['gold']};}}"
        f"QComboBox#{object_name}:disabled{{background:{C['disabled']};"
        f"color:{C['muted']};}}"
        f"QComboBox#{object_name}::drop-down{{border:none;width:28px;}}"
        f"QComboBox#{object_name}::down-arrow{{"
        f"image:none;border-left:5px solid transparent;"
        f"border-right:5px solid transparent;"
        f"border-top:6px solid {C['muted']};width:0;height:0;"
        f"margin-right:10px;}}"
        # No border-radius on popup — avoids black corner triangles / empty white sheet
        f"QComboBox#{object_name} QAbstractItemView{{"
        f"background:{bg};color:{fg};"
        f"border:1px solid {C['border']};"
        f"selection-background-color:{qss_alpha(C['gold'], 0.18)};"
        f"selection-color:{fg};outline:0;padding:4px;}}"
        f"QComboBox#{object_name} QAbstractItemView::item{{"
        f"min-height:32px;padding:6px 10px;color:{fg};background:{bg};}}"
        f"QComboBox#{object_name} QAbstractItemView::item:selected{{"
        f"background:{C.get('selected', C['hover'])};color:{fg};}}"
        f"QComboBox#{object_name} QAbstractItemView::item:hover{{"
        f"background:{C['hover']};color:{fg};}}"
    )


def _line_qss(object_name: str = 'mbtSelectSpecify') -> str:
    r = RADIUS['md']
    return (
        f"QLineEdit#{object_name}{{"
        f"background:{C['input']};color:{C['text']};"
        f"border:1px solid {C['border']};border-radius:{r}px;"
        f"padding:0 12px;font-size:13px;min-height:{CONTROL_HEIGHT - 8}px;}}"
        f"QLineEdit#{object_name}:focus{{border-color:{C['gold']};}}"
        f"QLineEdit#{object_name}:disabled{{background:{C['disabled']};"
        f"color:{C['muted']};}}"
    )


class Select(QComboBox):
    """
    Standard single-select dropdown.
    Supports clear button, empty/loading placeholders, and data roles.
    """
    cleared = pyqtSignal()

    def __init__(self, parent=None, *,
                 items: Optional[Iterable] = None,
                 placeholder: str = '',
                 clearable: bool = False,
                 searchable: bool = False,
                 height: int = CONTROL_HEIGHT,
                 object_name: str = 'mbtSelect'):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMaxVisibleItems(14)
        self._placeholder = placeholder or ''
        self._clearable = clearable
        self._loading = False
        self._empty_label = 'No options'
        self._searchable = searchable
        if searchable:
            self.setEditable(True)
            self.setInsertPolicy(QComboBox.NoInsert)
            comp = self.completer()
            if comp is not None:
                from PyQt5.QtWidgets import QCompleter
                comp.setCompletionMode(QCompleter.PopupCompletion)
                comp.setFilterMode(Qt.MatchContains)
                comp.setCaseSensitivity(Qt.CaseInsensitive)
            if self.lineEdit():
                self.lineEdit().setPlaceholderText(self._placeholder or 'Search…')
        elif self._placeholder:
            # Non-editable: show placeholder as disabled first item with None data
            self._ensure_placeholder()
        if items is not None:
            self.set_items(items)
        self.refresh_theme()

    def _ensure_placeholder(self):
        if not self._placeholder or self._searchable:
            return
        if self.count() == 0 or self.itemData(0) is not None:
            self.insertItem(0, self._placeholder, None)
            self.setItemData(0, C.get('muted', '#64748B'), Qt.ForegroundRole)
            self.setCurrentIndex(0)

    def set_items(self, items: Iterable,
                  *, data_from_item: bool = False,
                  keep_selection: bool = False):
        prev = self.current_value() if keep_selection else None
        self.blockSignals(True)
        self.clear()
        if self._placeholder and not self._searchable:
            self.addItem(self._placeholder, None)
            self.setItemData(0, C.get('muted', '#64748B'), Qt.ForegroundRole)
        for it in (items or []):
            if isinstance(it, (tuple, list)) and len(it) >= 2:
                self.addItem(str(it[0]), it[1])
            elif data_from_item:
                self.addItem(str(it), it)
            else:
                self.addItem(str(it), str(it))
        if self._loading:
            self.addItem('Loading…', None)
            self.setEnabled(False)
        elif self.count() == (1 if self._placeholder and not self._searchable else 0):
            if not self._placeholder:
                self.addItem(self._empty_label, None)
        self.blockSignals(False)
        if keep_selection and prev is not None:
            self.set_value(prev)
        elif self._placeholder and not self._searchable:
            self.setCurrentIndex(0)

    def set_loading(self, loading: bool, label: str = 'Loading…'):
        self._loading = bool(loading)
        self.setEnabled(not self._loading)
        if self._loading:
            self.blockSignals(True)
            self.clear()
            self.addItem(label, None)
            self.blockSignals(False)

    def set_empty_label(self, text: str):
        self._empty_label = text or 'No options'

    def current_value(self):
        idx = self.currentIndex()
        if idx < 0:
            return None
        data = self.itemData(idx)
        if data is None and self._placeholder and idx == 0 and not self._searchable:
            return None
        if data is not None:
            return data
        text = self.currentText().strip()
        if self._placeholder and text == self._placeholder:
            return None
        return text or None

    def current_label(self) -> str:
        return (self.currentText() or '').strip()

    def set_value(self, value) -> bool:
        if value is None or value == '':
            if self._placeholder and not self._searchable:
                self.setCurrentIndex(0)
                return True
            self.setCurrentIndex(-1)
            return False
        idx = self.findData(value)
        if idx < 0:
            idx = self.findText(str(value), Qt.MatchFixedString)
        if idx >= 0:
            self.setCurrentIndex(idx)
            return True
        return False

    def clear_selection(self):
        if self._placeholder and not self._searchable:
            self.setCurrentIndex(0)
        else:
            self.setCurrentIndex(-1)
            if self._searchable and self.lineEdit():
                self.lineEdit().clear()
        self.cleared.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape and self.view().isVisible():
            self.hidePopup()
            event.accept()
            return
        if key in (Qt.Key_F4,) or (
                key == Qt.Key_Down and event.modifiers() & Qt.AltModifier):
            self.showPopup()
            event.accept()
            return
        if self._clearable and key in (Qt.Key_Delete, Qt.Key_Backspace) \
                and not self._searchable and not self.view().isVisible():
            self.clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def showPopup(self):
        self.refresh_theme()
        _style_combo_popup(self)
        super().showPopup()
        # Fit outer QComboBoxPrivateContainer — kills tall white sheet
        try:
            from desktop.utils.pos_light_theme import _fit_combo_popup
            bg, fg, bd = C['card'], C['text'], C['border']
            _fit_combo_popup(self, bg=bg, fg=fg, border=bd, max_items=14)
            QTimer.singleShot(
                0, lambda: _fit_combo_popup(
                    self, bg=C['card'], fg=C['text'], border=C['border'],
                    max_items=14))
        except Exception:
            pass

    def refresh_theme(self):
        self.setStyleSheet(_select_qss(self.objectName() or 'mbtSelect'))
        _style_combo_popup(self)
        if self._searchable and self.lineEdit():
            self.lineEdit().setStyleSheet(
                f"QLineEdit{{background:transparent;color:{C['text']};"
                f"border:none;padding:0;font-size:13px;font-weight:600;}}")


class SearchableSelect(Select):
    """Editable combobox with contains-match filtering for large lists."""

    def __init__(self, parent=None, *, items=None, placeholder='Search…',
                 clearable=True, height=CONTROL_HEIGHT):
        super().__init__(
            parent, items=items, placeholder=placeholder,
            clearable=clearable, searchable=True, height=height,
            object_name='mbtSearchSelect')
        self._all_items: List[Tuple[str, object]] = []
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(80)
        self._filter_timer.timeout.connect(self._apply_filter)
        if self.lineEdit():
            self.lineEdit().textEdited.connect(self._on_edit)
        if items is not None:
            self.set_items(items)

    def set_items(self, items: Iterable, *, data_from_item: bool = False,
                  keep_selection: bool = False):
        self._all_items = []
        for it in (items or []):
            if isinstance(it, (tuple, list)) and len(it) >= 2:
                self._all_items.append((str(it[0]), it[1]))
            elif data_from_item:
                self._all_items.append((str(it), it))
            else:
                self._all_items.append((str(it), str(it)))
        super().set_items(self._all_items, keep_selection=keep_selection)
        if self.count() == 0:
            self.addItem(self._empty_label, None)

    def _on_edit(self, _text: str):
        self._filter_timer.start()

    def _apply_filter(self):
        q = (self.lineEdit().text() if self.lineEdit() else '').strip().lower()
        prev = self.current_value()
        self.blockSignals(True)
        self.clear()
        matched = 0
        for label, data in self._all_items:
            if not q or q in label.lower():
                self.addItem(label, data)
                matched += 1
        if matched == 0:
            self.addItem('No matches', None)
        self.blockSignals(False)
        if prev is not None:
            self.set_value(prev)
        if q and matched > 0 and not self.view().isVisible():
            self.showPopup()

    def set_loading(self, loading: bool, label: str = 'Loading…'):
        super().set_loading(loading, label)
        if loading:
            self._all_items = []


class MultiSelect(QFrame):
    """
    Multi-select list with optional filter box.
    Emits selectionChanged with list of selected data values.
    """
    selectionChanged = pyqtSignal(list)

    def __init__(self, parent=None, *, items=None, height=160,
                 searchable: bool = True):
        super().__init__(parent)
        self.setObjectName('mbtMultiSelect')
        self._items: List[Tuple[str, object]] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._search = None
        if searchable:
            self._search = QLineEdit()
            self._search.setObjectName('mbtSelectSpecify')
            self._search.setPlaceholderText('Filter…')
            self._search.setMinimumHeight(CONTROL_HEIGHT - 4)
            self._search.textChanged.connect(self._filter)
            lay.addWidget(self._search)
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._list.setMinimumHeight(height)
        self._list.itemSelectionChanged.connect(self._emit)
        lay.addWidget(self._list)
        if items:
            self.set_items(items)
        self.refresh_theme()

    def set_items(self, items: Iterable):
        self._items = []
        for it in (items or []):
            if isinstance(it, (tuple, list)) and len(it) >= 2:
                self._items.append((str(it[0]), it[1]))
            else:
                self._items.append((str(it), str(it)))
        self._rebuild()

    def _rebuild(self, query: str = ''):
        q = (query or '').strip().lower()
        selected = set(self.selected_values())
        self._list.blockSignals(True)
        self._list.clear()
        for label, data in self._items:
            if q and q not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, data)
            self._list.addItem(item)
            if data in selected or label in selected:
                item.setSelected(True)
        self._list.blockSignals(False)

    def _filter(self, text: str):
        self._rebuild(text)

    def _emit(self):
        self.selectionChanged.emit(self.selected_values())

    def selected_values(self) -> list:
        out = []
        for item in self._list.selectedItems():
            data = item.data(Qt.UserRole)
            out.append(data if data is not None else item.text())
        return out

    def selected_labels(self) -> List[str]:
        return [i.text() for i in self._list.selectedItems()]

    def set_selected(self, values: Sequence):
        want = set(values or [])
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.UserRole)
            item.setSelected(data in want or item.text() in want)
        self._list.blockSignals(False)
        self._emit()

    def clear_selection(self):
        self._list.clearSelection()
        self._emit()

    def refresh_theme(self):
        r = RADIUS['md']
        self.setStyleSheet(
            f"QFrame#mbtMultiSelect{{background:transparent;border:none;}}"
            f"QListWidget{{background:{C['input']};color:{C['text']};"
            f"border:1px solid {C['border']};border-radius:{r}px;"
            f"padding:4px;outline:0;}}"
            f"QListWidget::item{{min-height:30px;padding:4px 8px;"
            f"border-radius:6px;}}"
            f"QListWidget::item:selected{{background:{qss_alpha(C['gold'], 0.18)};"
            f"color:{C['text']};}}"
            f"QListWidget::item:hover{{background:{C['hover']};}}")
        if self._search:
            self._search.setStyleSheet(_line_qss())


class ReasonSelect(QWidget):
    """
    Reason dropdown with required 'Please specify' when Other is chosen.
    value() returns the catalog label, or 'Other: <detail>' when Other.
    """
    changed = pyqtSignal()

    def __init__(self, parent=None, *, reasons: Optional[Iterable[str]] = None,
                 other_label: str = OTHER_TOKEN,
                 specify_placeholder: str = 'Please specify…',
                 height: int = CONTROL_HEIGHT):
        super().__init__(parent)
        self.setObjectName('mbtReasonSelect')
        self._other = other_label or OTHER_TOKEN
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._select = Select(self, items=list(reasons or ()), height=height)
        self._select.currentIndexChanged.connect(self._on_change)
        lay.addWidget(self._select)
        self._specify = QLineEdit()
        self._specify.setObjectName('mbtSelectSpecify')
        self._specify.setPlaceholderText(specify_placeholder)
        self._specify.setMinimumHeight(height)
        self._specify.hide()
        self._specify.textChanged.connect(lambda _: self.changed.emit())
        lay.addWidget(self._specify)
        self._hint = QLabel('Required when Other is selected')
        self._hint.setStyleSheet(
            f"color:{C['muted']};font-size:11px;background:transparent;border:none;")
        self._hint.hide()
        lay.addWidget(self._hint)
        self.refresh_theme()
        self._on_change()

    def set_reasons(self, reasons: Iterable[str]):
        self._select.set_items(list(reasons or ()))
        self._on_change()

    def _on_change(self, *_):
        is_other = self._select.current_label() == self._other
        self._specify.setVisible(is_other)
        self._hint.setVisible(is_other)
        if not is_other:
            self._specify.clear()
        self.changed.emit()

    def is_other(self) -> bool:
        return self._select.current_label() == self._other

    def value(self) -> str:
        label = self._select.current_label()
        if label == self._other:
            detail = self._specify.text().strip()
            return f'{self._other}: {detail}' if detail else self._other
        return label

    def catalog_value(self) -> str:
        return self._select.current_label()

    def specify_text(self) -> str:
        return self._specify.text().strip()

    def is_valid(self) -> bool:
        label = self._select.current_label()
        if not label:
            return False
        if label == self._other:
            return bool(self._specify.text().strip())
        return True

    def validation_error(self) -> str:
        if not self._select.current_label():
            return 'Please select a reason.'
        if self.is_other() and not self._specify.text().strip():
            return 'Please specify a reason when Other is selected.'
        return ''

    def set_value(self, text: str):
        raw = (text or '').strip()
        if raw.startswith(f'{self._other}:'):
            self._select.set_value(self._other)
            self._specify.setText(raw.split(':', 1)[1].strip())
        elif raw == self._other:
            self._select.set_value(self._other)
        else:
            if not self._select.set_value(raw) and raw:
                # Unknown legacy value — select Other and put text in specify
                self._select.set_value(self._other)
                self._specify.setText(raw)
        self._on_change()

    def clear_selection(self):
        self._select.clear_selection()
        self._specify.clear()
        self._on_change()

    def refresh_theme(self):
        self._select.refresh_theme()
        self._specify.setStyleSheet(_line_qss())
        self._hint.setStyleSheet(
            f"color:{C['muted']};font-size:11px;background:transparent;border:none;")


class ReasonDialog(QDialog):
    """Modal: title + ReasonSelect + optional notes. Returns reason string."""

    def __init__(self, parent=None, *, title: str = 'Reason',
                 prompt: str = '', reasons: Sequence[str] = (),
                 require_reason: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self._require = require_reason
        apply_themed_dialog(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        if prompt:
            lbl = QLabel(prompt)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color:{C['text2']};font-size:13px;background:transparent;")
            lay.addWidget(lbl)
        self._reason = ReasonSelect(self, reasons=reasons)
        lay.addWidget(self._reason)
        notes_lbl = QLabel('Notes (optional)')
        notes_lbl.setStyleSheet(
            f"color:{C['muted']};font-size:12px;background:transparent;")
        lay.addWidget(notes_lbl)
        self._notes = QLineEdit()
        self._notes.setObjectName('mbtSelectSpecify')
        self._notes.setPlaceholderText('Optional notes…')
        self._notes.setMinimumHeight(CONTROL_HEIGHT)
        self._notes.setStyleSheet(_line_qss())
        lay.addWidget(self._notes)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._reason.refresh_theme()

    def _accept(self):
        if self._require and not self._reason.is_valid():
            QMessageBox.warning(self, 'Required', self._reason.validation_error())
            return
        self.accept()

    def reason(self) -> str:
        return self._reason.value()

    def notes(self) -> str:
        return self._notes.text().strip()


def prompt_reason(parent, *, title: str, prompt: str,
                  reasons: Sequence[str]) -> Optional[str]:
    """Show ReasonDialog; return reason string or None if cancelled."""
    dlg = ReasonDialog(parent, title=title, prompt=prompt, reasons=reasons)
    if dlg.exec_() != QDialog.Accepted:
        return None
    reason = dlg.reason().strip()
    notes = dlg.notes()
    if notes:
        reason = f'{reason} — {notes}' if reason else notes
    return reason or None


def refresh_select_controls(root: QWidget):
    """Retheme Select / SearchableSelect / MultiSelect / ReasonSelect under root."""
    try:
        for w in root.findChildren(Select):
            w.refresh_theme()
        for w in root.findChildren(MultiSelect):
            w.refresh_theme()
        for w in root.findChildren(ReasonSelect):
            w.refresh_theme()
    except Exception:
        pass


# Date preset convenience widget
class DatePresetSelect(Select):
    """Dashboard / report date preset dropdown."""
    presetChanged = pyqtSignal(str)  # key: today, yesterday, week, …

    def __init__(self, parent=None, *, include_last_month: bool = True):
        from desktop.utils.option_lists import DATE_PRESETS
        items = list(DATE_PRESETS)
        if not include_last_month:
            items = [(l, k) for l, k in items if k != 'last_month']
        super().__init__(parent, items=items, height=CONTROL_HEIGHT,
                         object_name='mbtDatePreset')
        self.currentIndexChanged.connect(self._emit)

    def _emit(self, *_):
        key = self.current_value()
        if key:
            self.presetChanged.emit(str(key))

    def current_key(self) -> str:
        v = self.current_value()
        return str(v) if v else 'today'
