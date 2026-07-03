"""MBT POS - Notes | MugoByte Technologies"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C
from desktop.utils.widgets import H2, Caption, PrimaryBtn, DangerBtn, SecondaryBtn, SearchBar

class NotesTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api=api; self.user=user; self.db_path=db_path; self.config_getter=config_getter
        self.notes=[]; self._nid=None; self._build()

    def _build(self):
        root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        left=QWidget(); left.setFixedWidth(280)
        left.setStyleSheet(f"background:{C['panel']}; border-right:1px solid {C['border']};")
        ll=QVBoxLayout(left); ll.setContentsMargins(16,18,16,16); ll.setSpacing(12)
        hdr=QHBoxLayout(); hdr.addWidget(H2('Notes')); hdr.addStretch()
        add=PrimaryBtn('+', 34); add.setFixedWidth(34); add.clicked.connect(self._new); hdr.addWidget(add)
        ll.addLayout(hdr)
        self._search=SearchBar('Search...'); self._search.textChanged.connect(self._filter); ll.addWidget(self._search)
        self._list=QListWidget()
        self._list.setStyleSheet(
            f"QListWidget {{ background:transparent; border:none; outline:none; }}"
            f"QListWidget::item {{ background:{C['card']}; border-radius:8px; "
            f"padding:12px 14px; margin-bottom:4px; color:{C['text']}; font-size:13px; border:1px solid {C['border']}; }}"
            f"QListWidget::item:selected {{ background:{C['selected']}; color:{C['gold']}; border-color:{C['selected']}; }}"
            f"QListWidget::item:hover:!selected {{ background:{C['hover']}; }}")
        self._list.currentRowChanged.connect(self._select); ll.addWidget(self._list)
        root.addWidget(left)
        right=QWidget(); right.setStyleSheet(f"background:{C['surface']};")
        rl=QVBoxLayout(right); rl.setContentsMargins(28,22,28,22); rl.setSpacing(14)
        hdr2=QHBoxLayout()
        self._tin=QLineEdit(); self._tin.setPlaceholderText('Note title...')
        self._tin.setMinimumHeight(44)
        self._tin.setStyleSheet(
            f"QLineEdit {{ font-size:18px; font-weight:700; background:transparent; "
            f"border:none; border-bottom:2px solid {C['border2']}; border-radius:0; padding:4px 0; color:{C['text']}; }}"
            f"QLineEdit:focus {{ border-bottom-color:{C['gold']}; }}")
        hdr2.addWidget(self._tin, 1)
        sv=PrimaryBtn('Save', 40); sv.setFixedWidth(90); sv.clicked.connect(self._save)
        dl=DangerBtn('🗑', 40); dl.setFixedWidth(42); dl.clicked.connect(self._delete)
        hdr2.addWidget(sv); hdr2.addWidget(dl); rl.addLayout(hdr2)
        self._body=QTextEdit(); self._body.setPlaceholderText('Write your note here...')
        self._body.setStyleSheet(f"font-size:14px; background:transparent; border:none; color:{C['text']}; line-height:1.6;")
        rl.addWidget(self._body)
        self._meta=Caption(''); rl.addWidget(self._meta)
        root.addWidget(right, 1)

    def on_show(self): self.refresh()
    def refresh(self): self.notes=self.api.get_notes() or []; self._populate(self.notes)
    def _filter(self):
        q=self._search.text().lower()
        self._populate([n for n in self.notes if q in (n.get('title') or '').lower() or q in (n.get('content') or '').lower()])
    def _populate(self, notes):
        self._list.clear()
        for n in notes:
            item=QListWidgetItem(n.get('title') or 'Untitled')
            item.setData(Qt.UserRole, n['id']); self._list.addItem(item)
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
