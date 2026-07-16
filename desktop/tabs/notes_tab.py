"""MBT POS - Notes | MugoByte Technologies (Lovable two-pane layout)"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C, RADIUS
from desktop.utils.widgets import H2, Caption, PrimaryBtn, DangerBtn, GhostBtn, SearchBar, Card


class NotesTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api=api; self.user=user; self.db_path=db_path; self.config_getter=config_getter
        self.notes=[]; self._nid=None; self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        # ── Left list card (Lovable) ──────────────────────────────────────────
        left = Card()
        left.setFixedWidth(300)
        ll = left.layout_v(margins=(0, 0, 0, 0), spacing=0)

        toolbar = QWidget()
        toolbar.setStyleSheet(f"border-bottom:1px solid {C['border']};")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 10, 12, 10); tl.setSpacing(8)
        self._search = SearchBar('Search notes…')
        self._search.textChanged.connect(self._filter)
        tl.addWidget(self._search, 1)
        add = PrimaryBtn('+', 34); add.setFixedWidth(34)
        add.clicked.connect(self._new)
        tl.addWidget(add)
        ll.addWidget(toolbar)

        self._list = QListWidget()
        r = RADIUS['md']
        self._list.setStyleSheet(
            f"QListWidget {{ background:transparent; border:none; outline:none; }}"
            f"QListWidget::item {{ background:transparent; border:none; "
            f"border-bottom:1px solid {C['border']}; border-radius:0; "
            f"padding:12px 14px; margin:0; color:{C['text']}; }}"
            f"QListWidget::item:selected {{ background:{C['hover']}; "
            f"color:{C['text']}; border-left:3px solid {C['gold']}; }}"
            f"QListWidget::item:hover:!selected {{ background:{C['hover']}88; }}")
        self._list.currentRowChanged.connect(self._select)
        ll.addWidget(self._list, 1)
        root.addWidget(left)

        # ── Right editor card ─────────────────────────────────────────────────
        right = Card()
        rl = right.layout_v(margins=(0, 0, 0, 0), spacing=0)

        hdr = QWidget()
        hdr.setStyleSheet(f"border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16, 12, 12, 12); hl.setSpacing(8)
        self._tin = QLineEdit(); self._tin.setPlaceholderText('Note title...')
        self._tin.setMinimumHeight(40)
        self._tin.setStyleSheet(
            f"QLineEdit {{ font-size:17px; font-weight:600; background:transparent; "
            f"border:none; padding:4px 0; color:{C['text']}; }}"
            f"QLineEdit:focus {{ border:none; }}")
        hl.addWidget(self._tin, 1)
        sv = PrimaryBtn('Save', 36); sv.setFixedWidth(84); sv.clicked.connect(self._save)
        dl = GhostBtn('🗑', 36); dl.setFixedWidth(40); dl.clicked.connect(self._delete)
        hl.addWidget(sv); hl.addWidget(dl)
        rl.addWidget(hdr)

        body = QWidget()
        bl = QVBoxLayout(body); bl.setContentsMargins(20, 16, 20, 16); bl.setSpacing(8)
        self._body = QTextEdit(); self._body.setPlaceholderText('Start writing…')
        self._body.setStyleSheet(
            f"font-size:15px; background:transparent; border:none; "
            f"color:{C['text']}; line-height:1.6; padding:0;")
        bl.addWidget(self._body, 1)
        self._meta = Caption('')
        bl.addWidget(self._meta)
        rl.addWidget(body, 1)
        root.addWidget(right, 1)

    def on_show(self): self.refresh()
    def refresh(self): self.notes=self.api.get_notes() or []; self._populate(self.notes)
    def _filter(self):
        q=self._search.text().lower()
        self._populate([n for n in self.notes if q in (n.get('title') or '').lower() or q in (n.get('content') or '').lower()])
    def _populate(self, notes):
        self._list.clear()
        for n in notes:
            title = n.get('title') or 'Untitled'
            preview = ((n.get('content') or '').split('\n')[0] or 'Empty note')[:60]
            item = QListWidgetItem(f"{title}\n{preview}")
            item.setData(Qt.UserRole, n['id'])
            self._list.addItem(item)
    def _select(self, row):
        if row<0: return
        item=self._list.item(row)
        if not item: return
        n=next((x for x in self.notes if x['id']==item.data(Qt.UserRole)), None)
        if n:
            self._nid=n['id']; self._tin.setText(n.get('title') or '')
            self._body.setPlainText(n.get('content') or '')
            self._meta.setText(f"Updated: {(n.get('updated_at') or '')[:16]}")
    def _new(self):
        self._nid=None; self._tin.clear(); self._body.clear()
        self._meta.setText(''); self._list.clearSelection(); self._tin.setFocus()
    def _save(self):
        title=self._tin.text().strip() or 'Untitled'
        content=self._body.toPlainText().strip()
        if self._nid: res=self.api.update_note(self._nid,{'title':title,'content':content})
        else:          res=self.api.create_note({'title':title,'content':content})
        if res and res.get('success'): self.refresh()
    def _delete(self):
        if not self._nid: return
        if QMessageBox.question(self,'Delete','Delete this note?',QMessageBox.Yes|QMessageBox.No)==QMessageBox.Yes:
            if self.api.delete_note(self._nid): self._new(); self.refresh()
