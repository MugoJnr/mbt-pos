"""MBT POS - Notes | Theme-aware two-pane notes (Light + Dark)."""
from __future__ import annotations

import logging
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QTextEdit, QLabel, QMessageBox, QAbstractItemView,
    QShortcut,
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QKeySequence, QFont

from desktop.utils.theme import C, RADIUS, qss_alpha, apply_themed_dialog
from desktop.utils.widgets import (
    PrimaryBtn, GhostBtn, SearchBar, Card, Caption, refresh_themed_widgets,
)

_log = logging.getLogger('mbt.notes')


def _fmt_edited(ts):
    """Human-friendly last-edited label."""
    if not ts:
        return ''
    raw = str(ts).strip()
    try:
        # Accept ISO with/without seconds / Z
        cleaned = raw.replace('Z', '')
        if 'T' in cleaned:
            dt = datetime.fromisoformat(cleaned[:19])
        else:
            dt = datetime.strptime(cleaned[:19], '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        if dt.date() == now.date():
            return f'Today {dt.strftime("%H:%M")}'
        if (now.date() - dt.date()).days == 1:
            return f'Yesterday {dt.strftime("%H:%M")}'
        if dt.year == now.year:
            return dt.strftime('%d %b %H:%M')
        return dt.strftime('%d %b %Y')
    except Exception:
        return raw[:16]


def _snippet(content, limit=72):
    text = (content or '').strip().replace('\r\n', '\n').replace('\r', '\n')
    if not text:
        return 'Empty note'
    first = next((ln.strip() for ln in text.split('\n') if ln.strip()), 'Empty note')
    if len(first) > limit:
        return first[: limit - 1].rstrip() + '…'
    return first


class _NoteRow(QWidget):
    """Custom list row: title, snippet, date (+ pin glyph)."""

    def __init__(self, note: dict, parent=None):
        super().__init__(parent)
        self._nid = note.get('id')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        self._title = QLabel()
        self._title.setObjectName('noteRowTitle')
        f = QFont(self._title.font())
        f.setWeight(QFont.DemiBold)
        f.setPointSize(12)
        self._title.setFont(f)
        top.addWidget(self._title, 1)

        self._pin = QLabel('📌')
        self._pin.setObjectName('noteRowPin')
        self._pin.setFixedWidth(16)
        self._pin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self._pin)
        lay.addLayout(top)

        self._snip = QLabel()
        self._snip.setObjectName('noteRowSnippet')
        self._snip.setWordWrap(False)
        lay.addWidget(self._snip)

        self._date = QLabel()
        self._date.setObjectName('noteRowDate')
        lay.addWidget(self._date)

        self.set_note(note)
        self.apply_theme()

    def set_note(self, note: dict):
        title = (note.get('title') or '').strip() or 'Untitled'
        pinned = bool(int(note.get('pinned') or 0))
        self._title.setText(title)
        self._snip.setText(_snippet(note.get('content')))
        self._date.setText(_fmt_edited(note.get('updated_at') or note.get('created_at')))
        self._pin.setVisible(pinned)

    def apply_theme(self):
        self._title.setStyleSheet(
            f"color:{C['text']}; background:transparent; border:none;")
        self._snip.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; border:none;")
        self._date.setStyleSheet(
            f"color:{C['muted']}; font-size:11px; background:transparent; border:none;")
        self._pin.setStyleSheet(
            f"color:{C['gold']}; font-size:11px; background:transparent; border:none;")


class NotesTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api
        self.user = user
        self.db_path = db_path
        self.config_getter = config_getter
        self.notes: list = []
        self._nid = None
        self._dirty = False
        self._loading = False
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(900)
        self._autosave.timeout.connect(self._save)
        self._feedback_clear = QTimer(self)
        self._feedback_clear.setSingleShot(True)
        self._feedback_clear.setInterval(2200)
        self._feedback_clear.timeout.connect(self._reset_save_label)
        self._build()
        self._wire_shortcuts()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        # Left list
        self._left = Card()
        self._left.setFixedWidth(320)
        ll = self._left.layout_v(margins=(0, 0, 0, 0), spacing=0)

        self._toolbar = QWidget()
        self._toolbar.setObjectName('notesToolbar')
        tl = QHBoxLayout(self._toolbar)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.setSpacing(8)
        self._search = SearchBar('Search notes…')
        self._search.textChanged.connect(self._filter)
        tl.addWidget(self._search, 1)
        self._add_btn = PrimaryBtn('+', 34)
        self._add_btn.setFixedWidth(34)
        self._add_btn.setToolTip('New note (Ctrl+N)')
        self._add_btn.clicked.connect(self._new)
        tl.addWidget(self._add_btn)
        ll.addWidget(self._toolbar)

        self._list = QListWidget()
        self._list.setObjectName('notesList')
        self._list.setUniformItemSizes(False)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.currentRowChanged.connect(self._select)
        ll.addWidget(self._list, 1)

        self._empty = QWidget()
        self._empty.setObjectName('notesEmpty')
        el = QVBoxLayout(self._empty)
        el.setContentsMargins(24, 40, 24, 40)
        el.setSpacing(8)
        self._empty_title = QLabel('No notes yet')
        self._empty_title.setAlignment(Qt.AlignCenter)
        self._empty_title.setObjectName('sectionTitle')
        self._empty_title.setProperty('mbtTitleSize', 15)
        self._empty_hint = QLabel('Click + to create your first note')
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setObjectName('sectionSubtitle')
        self._empty_hint.setWordWrap(True)
        el.addStretch(1)
        el.addWidget(self._empty_title)
        el.addWidget(self._empty_hint)
        el.addStretch(2)
        ll.addWidget(self._empty)
        self._empty.hide()

        root.addWidget(self._left)

        # Right editor
        self._right = Card()
        rl = self._right.layout_v(margins=(0, 0, 0, 0), spacing=0)

        self._hdr = QWidget()
        self._hdr.setObjectName('notesHdr')
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(16, 12, 12, 12)
        hl.setSpacing(8)

        self._tin = QLineEdit()
        self._tin.setObjectName('notesTitle')
        self._tin.setPlaceholderText('Note title…')
        self._tin.setMinimumHeight(40)
        self._tin.textChanged.connect(self._on_edit)
        hl.addWidget(self._tin, 1)

        self._pin_btn = GhostBtn('📌', 36)
        self._pin_btn.setFixedWidth(40)
        self._pin_btn.setToolTip('Pin / unpin note')
        self._pin_btn.clicked.connect(self._toggle_pin)
        hl.addWidget(self._pin_btn)

        self._sv = PrimaryBtn('Save', 36)
        self._sv.setFixedWidth(88)
        self._sv.setToolTip('Save (Ctrl+S)')
        self._sv.clicked.connect(self._save)
        hl.addWidget(self._sv)

        self._dl = GhostBtn('🗑', 36)
        self._dl.setFixedWidth(40)
        self._dl.setToolTip('Delete note')
        self._dl.clicked.connect(self._delete)
        hl.addWidget(self._dl)
        rl.addWidget(self._hdr)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 14, 20, 14)
        bl.setSpacing(10)

        self._body = QTextEdit()
        self._body.setObjectName('notesBody')
        self._body.setPlaceholderText('Start writing…')
        self._body.setAcceptRichText(False)
        self._body.textChanged.connect(self._on_edit)
        bl.addWidget(self._body, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(8)
        self._meta = Caption('')
        self._meta.setObjectName('notesMeta')
        foot.addWidget(self._meta, 1)
        self._status = Caption('')
        self._status.setObjectName('notesStatus')
        self._status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        foot.addWidget(self._status)
        bl.addLayout(foot)

        self._editor_empty = QWidget()
        self._editor_empty.setObjectName('notesEditorEmpty')
        eel = QVBoxLayout(self._editor_empty)
        eel.setContentsMargins(32, 48, 32, 48)
        eel.setSpacing(8)
        self._ed_empty_title = QLabel('Select a note')
        self._ed_empty_title.setAlignment(Qt.AlignCenter)
        self._ed_empty_title.setObjectName('sectionTitle')
        self._ed_empty_title.setProperty('mbtTitleSize', 16)
        self._ed_empty_hint = QLabel(
            'Choose a note from the list, or press Ctrl+N to create one.')
        self._ed_empty_hint.setAlignment(Qt.AlignCenter)
        self._ed_empty_hint.setObjectName('sectionSubtitle')
        self._ed_empty_hint.setWordWrap(True)
        eel.addStretch(1)
        eel.addWidget(self._ed_empty_title)
        eel.addWidget(self._ed_empty_hint)
        eel.addStretch(2)

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(body, 1)
        stack.addWidget(self._editor_empty, 1)
        wrap = QWidget()
        wrap.setLayout(stack)
        rl.addWidget(wrap, 1)

        self._editor_body = body
        root.addWidget(self._right, 1)

        self._set_editor_enabled(False)
        self.apply_theme()

    def _wire_shortcuts(self):
        QShortcut(QKeySequence.New, self, activated=self._new)
        QShortcut(QKeySequence.Save, self, activated=self._save)
        # Explicit Ctrl+N / Ctrl+S (Windows)
        QShortcut(QKeySequence('Ctrl+N'), self, activated=self._new)
        QShortcut(QKeySequence('Ctrl+S'), self, activated=self._save)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def apply_theme(self, is_light=None):
        try:
            refresh_themed_widgets(self)
            self._paint_chrome()
            for i in range(self._list.count()):
                item = self._list.item(i)
                w = self._list.itemWidget(item)
                if isinstance(w, _NoteRow):
                    w.apply_theme()
            self._empty_title.setStyleSheet(
                f"color:{C['text']}; font-size:15px; font-weight:600; "
                f"background:transparent; border:none;")
            self._empty_hint.setStyleSheet(
                f"color:{C['text2']}; font-size:13px; background:transparent; border:none;")
            self._ed_empty_title.setStyleSheet(
                f"color:{C['text']}; font-size:16px; font-weight:600; "
                f"background:transparent; border:none;")
            self._ed_empty_hint.setStyleSheet(
                f"color:{C['text2']}; font-size:13px; background:transparent; border:none;")
            self._meta.setStyleSheet(
                f"color:{C['muted']}; font-size:12px; background:transparent; border:none;")
            self._status.setStyleSheet(
                f"color:{C['muted']}; font-size:12px; background:transparent; border:none;")
        except Exception as e:
            _log.warning('Notes apply_theme: %s', e)

    def _paint_chrome(self):
        r = RADIUS['md']
        sel = C.get('selected', C['hover'])
        gold_tint = qss_alpha(C['gold'], 0.16)
        border = C['border']
        self._toolbar.setStyleSheet(
            f"QWidget#notesToolbar {{ background:transparent; "
            f"border:none; border-bottom:1px solid {border}; }}")
        self._hdr.setStyleSheet(
            f"QWidget#notesHdr {{ background:transparent; "
            f"border:none; border-bottom:1px solid {border}; }}")
        self._list.setStyleSheet(
            f"QListWidget#notesList {{ background:transparent; border:none; outline:none; }}"
            f"QListWidget#notesList::item {{ background:transparent; border:none; "
            f"border-bottom:1px solid {border}; border-radius:0; padding:0; margin:0; }}"
            f"QListWidget#notesList::item:selected {{ background:{sel}; "
            f"border-left:3px solid {C['gold']}; }}"
            f"QListWidget#notesList::item:hover:!selected {{ background:{C['hover']}; }}"
        )
        self._tin.setStyleSheet(
            f"QLineEdit#notesTitle {{ font-size:17px; font-weight:600; "
            f"background:transparent; border:none; padding:4px 0; color:{C['text']}; "
            f"selection-background-color:{gold_tint}; }}"
            f"QLineEdit#notesTitle:focus {{ border:none; }}")
        self._body.setStyleSheet(
            f"QTextEdit#notesBody {{ font-size:15px; background:transparent; border:none; "
            f"color:{C['text']}; padding:4px 0; selection-background-color:{gold_tint}; }}")
        self._empty.setStyleSheet('background:transparent;')
        self._editor_empty.setStyleSheet('background:transparent;')

    # ── Data ──────────────────────────────────────────────────────────────────

    def on_show(self):
        self.refresh()

    def refresh(self, select_id=None):
        keep = select_id if select_id is not None else self._nid
        try:
            self.notes = self.api.get_notes() or []
        except Exception as e:
            _log.warning('get_notes: %s', e)
            self.notes = []
        self._populate(self._filtered(), keep_id=keep)

    def _filtered(self):
        q = (self._search.text() or '').strip().lower()
        if not q:
            return list(self.notes)
        out = []
        for n in self.notes:
            title = (n.get('title') or '').lower()
            content = (n.get('content') or '').lower()
            if q in title or q in content:
                out.append(n)
        return out

    def _filter(self):
        self._populate(self._filtered(), keep_id=self._nid)

    def _populate(self, notes, keep_id=None):
        self._list.blockSignals(True)
        self._list.clear()
        has = bool(notes)
        self._list.setVisible(has)
        self._empty.setVisible(not has)
        if not has and (self._search.text() or '').strip():
            self._empty_title.setText('No matching notes')
            self._empty_hint.setText('Try a different search, or clear the filter.')
        elif not has:
            self._empty_title.setText('No notes yet')
            self._empty_hint.setText('Click + to create your first note')

        select_row = -1
        for i, n in enumerate(notes):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, n['id'])
            item.setSizeHint(QSize(280, 78))
            self._list.addItem(item)
            row = _NoteRow(n)
            self._list.setItemWidget(item, row)
            if keep_id is not None and n['id'] == keep_id:
                select_row = i

        self._list.blockSignals(False)
        if select_row >= 0:
            self._list.setCurrentRow(select_row)
        elif self._nid is None:
            self._show_editor_empty()
        elif keep_id is not None and select_row < 0:
            # Deleted / filtered out
            self._show_editor_empty()

    def _find_note(self, nid):
        return next((x for x in self.notes if x.get('id') == nid), None)

    def _set_editor_enabled(self, enabled: bool):
        self._editor_body.setVisible(enabled)
        self._editor_empty.setVisible(not enabled)
        self._tin.setEnabled(enabled)
        self._body.setEnabled(enabled)
        self._pin_btn.setEnabled(enabled and self._nid is not None)
        self._sv.setEnabled(enabled)
        self._dl.setEnabled(enabled and self._nid is not None)

    def _show_editor_empty(self):
        self._nid = None
        self._dirty = False
        self._loading = True
        self._tin.clear()
        self._body.clear()
        self._loading = False
        self._meta.setText('')
        self._status.setText('')
        self._set_editor_enabled(False)
        self._list.clearSelection()

    def _select(self, row):
        if row < 0:
            return
        item = self._list.item(row)
        if not item:
            return
        nid = item.data(Qt.UserRole)
        n = self._find_note(nid)
        if not n:
            return
        if self._dirty and self._nid and self._nid != nid:
            self._autosave.stop()
            self._save(silent=True)
        self._load_note(n)

    def _load_note(self, n: dict):
        self._nid = n['id']
        self._loading = True
        self._tin.setText(n.get('title') or '')
        self._body.setPlainText(n.get('content') or '')
        self._loading = False
        self._dirty = False
        pinned = bool(int(n.get('pinned') or 0))
        self._pin_btn.setText('📌' if pinned else '📍')
        self._pin_btn.setToolTip('Unpin note' if pinned else 'Pin note')
        edited = _fmt_edited(n.get('updated_at') or n.get('created_at'))
        self._meta.setText(f'Last edited · {edited}' if edited else '')
        self._status.setText('Saved')
        self._set_editor_enabled(True)

    # ── Edit / save ───────────────────────────────────────────────────────────

    def _on_edit(self):
        if self._loading:
            return
        if not self._editor_body.isVisible():
            # New draft started from empty editor path
            return
        self._dirty = True
        self._status.setText('Editing…')
        self._status.setStyleSheet(
            f"color:{C['warn']}; font-size:12px; background:transparent; border:none;")
        self._autosave.start()

    def _reset_save_label(self):
        if not self._dirty:
            self._status.setText('Saved')
            self._status.setStyleSheet(
                f"color:{C['muted']}; font-size:12px; background:transparent; border:none;")

    def _new(self):
        if self._dirty and self._nid:
            self._autosave.stop()
            self._save(silent=True)
        self._nid = None
        self._dirty = False
        self._loading = True
        self._tin.clear()
        self._body.clear()
        self._loading = False
        self._meta.setText('New note — unsaved')
        self._status.setText('')
        self._pin_btn.setText('📍')
        self._pin_btn.setToolTip('Pin note')
        self._set_editor_enabled(True)
        self._pin_btn.setEnabled(False)
        self._dl.setEnabled(False)
        self._list.clearSelection()
        self._tin.setFocus()
        self._tin.setPlaceholderText('Note title…')

    def _save(self, silent: bool = False):
        if not self._editor_body.isVisible() and self._nid is None:
            # Nothing to save from empty state
            if not (self._tin.text().strip() or self._body.toPlainText().strip()):
                return
        title = self._tin.text().strip() or 'Untitled'
        content = self._body.toPlainText()
        payload = {'title': title, 'content': content}
        try:
            if self._nid:
                n = self._find_note(self._nid)
                if n is not None:
                    payload['pinned'] = int(n.get('pinned') or 0)
                res = self.api.update_note(self._nid, payload)
                new_id = self._nid
            else:
                if not title.strip() and not content.strip():
                    return
                payload['pinned'] = 0
                res = self.api.create_note(payload)
                new_id = None
                if isinstance(res, dict):
                    new_id = res.get('id') or (res.get('note') or {}).get('id')
                if new_id is None:
                    # Fallback: reload and pick newest matching title
                    self.refresh()
                    for n in self.notes:
                        if (n.get('title') or '') == title:
                            new_id = n['id']
                            break
            if res and res.get('success'):
                self._dirty = False
                self._nid = new_id or self._nid
                if not silent:
                    self._status.setText('Saved ✓')
                    self._status.setStyleSheet(
                        f"color:{C['ok']}; font-size:12px; background:transparent; border:none;")
                    self._feedback_clear.start()
                self.refresh(select_id=self._nid)
                n = self._find_note(self._nid) if self._nid else None
                if n:
                    edited = _fmt_edited(n.get('updated_at') or n.get('created_at'))
                    self._meta.setText(f'Last edited · {edited}' if edited else '')
                    self._pin_btn.setEnabled(True)
                    self._dl.setEnabled(True)
            elif not silent:
                self._status.setText('Save failed')
                self._status.setStyleSheet(
                    f"color:{C['err']}; font-size:12px; background:transparent; border:none;")
        except Exception as e:
            _log.warning('save note: %s', e)
            if not silent:
                self._status.setText('Save failed')
                self._status.setStyleSheet(
                    f"color:{C['err']}; font-size:12px; background:transparent; border:none;")

    def _toggle_pin(self):
        if not self._nid:
            return
        n = self._find_note(self._nid)
        if not n:
            return
        if self._dirty:
            self._autosave.stop()
            self._save(silent=True)
        pinned = 0 if int(n.get('pinned') or 0) else 1
        try:
            res = self.api.update_note(self._nid, {
                'title': self._tin.text().strip() or 'Untitled',
                'content': self._body.toPlainText(),
                'pinned': pinned,
            })
            if res and res.get('success'):
                self._dirty = False
                self.refresh(select_id=self._nid)
                n2 = self._find_note(self._nid)
                if n2:
                    self._load_note(n2)
        except Exception as e:
            _log.warning('pin note: %s', e)

    def _delete(self):
        if not self._nid:
            return
        n = self._find_note(self._nid)
        title = (n.get('title') if n else None) or self._tin.text().strip() or 'Untitled'
        dlg = QMessageBox(self)
        dlg.setIcon(QMessageBox.Warning)
        dlg.setWindowTitle('Delete note')
        dlg.setText(f'Delete “{title}”?')
        dlg.setInformativeText('This cannot be undone.')
        dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dlg.setDefaultButton(QMessageBox.No)
        apply_themed_dialog(dlg)
        if dlg.exec_() != QMessageBox.Yes:
            return
        try:
            res = self.api.delete_note(self._nid)
            if res and res.get('success'):
                self._dirty = False
                self._autosave.stop()
                self._show_editor_empty()
                self.refresh()
        except Exception as e:
            _log.warning('delete note: %s', e)
            QMessageBox.warning(self, 'Delete failed', str(e))
