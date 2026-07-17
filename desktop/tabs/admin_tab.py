"""MBT POS - Admin | MugoByte Technologies"""
import json
from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *
from desktop.utils.theme   import C
from desktop.utils.widgets import (Card, H2, Caption, PrimaryBtn, SecondaryBtn,
                                    DangerBtn, GhostBtn, SearchBar, make_table, tbl_item,
                                    tbl_center, page_layout, page_intro, wrap_table_card,
                                    Badge)
from desktop.utils.security import (
    ALL_DESKTOP_TABS, default_tab_permissions, can_assign_role,
    is_superadmin_role, is_shop_admin_role, role_display_name,
)
from desktop.utils.option_lists import USER_ROLES, USER_ROLE_LABELS
from desktop.utils.select_controls import Select

ALL_TABS = ALL_DESKTOP_TABS
TAB_LABELS = {'dashboard':'⊞ Dashboard','sales':'🛒 Point of Sale','inventory':'📦 Inventory',
              'consumption':'▣ Internal Consumption',
              'debt':'💰 Debt','reports':'📊 Reports','notes':'📝 Notes','settings':'⚙ Settings',
              'admin':'👥 Users','license':'🔑 License','diagnostics':'🔧 Diagnostics',
              'security':'🔐 Security'}

class AdminTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api=api; self.user=user; self.db_path=db_path; self.config_getter=config_getter
        self.users=[]; self._uid=None; self._build()

    def _build(self):
        if self.user.get('user',{}).get('role','') not in ('admin', 'superadmin'):
            lay=QVBoxLayout(self); lay.setAlignment(Qt.AlignCenter)
            lbl=QLabel('Administrator access required.'); lbl.setStyleSheet(f"color:{C['text2']}; font-size:16px;")
            lay.addWidget(lbl); return
        lay, _ = page_layout(self, margins=(24,24,24,24), spacing=16)

        add=PrimaryBtn('+ New User', 40); add.setFixedWidth(130); add.clicked.connect(self._add)
        intro, _ = page_intro(
            'Users & Access',
            'Manage staff accounts, roles, and per-tab access.',
            add)
        lay.addLayout(intro)

        tb=QHBoxLayout(); tb.setSpacing(8)
        self._search=SearchBar('Search users…')
        self._search.textChanged.connect(self._filter); tb.addWidget(self._search, 1)
        ref=GhostBtn('↺ Refresh', 40); ref.clicked.connect(self.refresh)
        tb.addWidget(ref); lay.addLayout(tb)

        split=QSplitter(Qt.Horizontal)
        lw=QWidget(); ll=QVBoxLayout(lw); ll.setContentsMargins(0,0,0,0); ll.setSpacing(10)
        self._tbl=make_table(['Username','Full Name','Role','Status','Last Login'], stretch_col=1, row_height=44)
        self._tbl.horizontalHeader().setSectionResizeMode(0,QHeaderView.Fixed); self._tbl.setColumnWidth(0,110)
        self._tbl.horizontalHeader().setSectionResizeMode(2,QHeaderView.Fixed); self._tbl.setColumnWidth(2,100)
        self._tbl.horizontalHeader().setSectionResizeMode(3,QHeaderView.Fixed); self._tbl.setColumnWidth(3,90)
        self._tbl.horizontalHeader().setSectionResizeMode(4,QHeaderView.Fixed); self._tbl.setColumnWidth(4,130)
        self._tbl.clicked.connect(self._on_sel)
        ll.addWidget(wrap_table_card(self._tbl, 'All Users')); split.addWidget(lw)

        rw=QWidget(); rw.setMinimumWidth(280); rw.setMaximumWidth(340)
        rl=QVBoxLayout(rw); rl.setContentsMargins(12,0,0,0); rl.setSpacing(12)
        rl.addWidget(H2('Permissions'))
        pc=Card(); pl=pc.layout_v()
        self._sel_lbl=Caption('Select a user')
        self._role_cb=Select()
        roles = list(USER_ROLES)
        if not is_superadmin_role(self.user.get('user',{}).get('role','')):
            roles = [r for r in roles if r != 'superadmin']
        self._role_cb.set_items([(USER_ROLE_LABELS.get(r, r), r) for r in roles])
        self._role_cb.setMinimumHeight(40); self._role_cb.setEnabled(False)
        self._role_cb.currentIndexChanged.connect(lambda *_: self._on_role_preset())
        pl.addWidget(self._sel_lbl); pl.addWidget(QLabel('Role:')); pl.addWidget(self._role_cb)
        pl.addWidget(QLabel('Tab Access:'))
        self._chks={}
        for tid in ALL_TABS:
            cb=QCheckBox(TAB_LABELS.get(tid,tid)); cb.setEnabled(False)
            self._chks[tid]=cb; pl.addWidget(cb)
        rl.addWidget(pc)
        self._save_btn=PrimaryBtn('Save Permissions', 40); self._save_btn.setEnabled(False); self._save_btn.clicked.connect(self._save_perms)
        self._pw_btn=SecondaryBtn('Reset Password', 40); self._pw_btn.setEnabled(False); self._pw_btn.clicked.connect(self._reset_pw)
        self._tog_btn=DangerBtn('Deactivate', 40); self._tog_btn.setEnabled(False); self._tog_btn.clicked.connect(self._toggle)
        rl.addWidget(self._save_btn); rl.addWidget(self._pw_btn); rl.addWidget(self._tog_btn); rl.addStretch()
        split.addWidget(rw); lay.addWidget(split, 1)
        lay.addWidget(H2('Audit Log'))
        self._audit=make_table(['Time','User','Action','Module','Detail'], stretch_col=4, row_height=32)
        self._audit.setMaximumHeight(160)
        lay.addWidget(wrap_table_card(self._audit))

    def on_show(self): self.refresh()
    def refresh(self):
        if self.user.get('user',{}).get('role','') not in ('admin', 'superadmin'): return
        self.users=self.api.get_users() or []; self._populate(self.users); self._load_audit()
    def _filter(self):
        q=self._search.text().lower()
        self._populate([u for u in self.users if q in u.get('username','').lower() or q in (u.get('full_name') or '').lower()])
    def _populate(self, users):
        self._tbl.setRowCount(0)
        for i,u in enumerate(users):
            self._tbl.insertRow(i); active=u.get('is_active',1)
            self._tbl.setItem(i,0,tbl_item(u.get('username','')))
            self._tbl.setItem(i,1,tbl_item(u.get('full_name','') or ''))
            self._tbl.setItem(i,2,tbl_center(role_display_name(u.get('role','')),C['gold']))
            self._tbl.setItem(i,3,tbl_center('Active' if active else 'Inactive', C['ok'] if active else C['err']))
            self._tbl.setItem(i,4,tbl_item((u.get('last_login') or 'Never')[:16]))
    def _on_sel(self, idx):
        uname=self._tbl.item(idx.row(),0)
        if not uname: return
        u=next((x for x in self.users if x['username']==uname.text()), None)
        if not u: return
        self._uid=u['id']; self._sel_lbl.setText(f"Editing: {u.get('full_name') or u['username']}")
        self._role_cb.set_value(u.get('role','cashier')); self._role_cb.setEnabled(True)
        perms=json.loads(u.get('tab_permissions') or '[]')
        sel_role = u.get('role', 'cashier')
        for tid,cb in self._chks.items():
            cb.setChecked(tid in perms)
            if tid in ('security', 'license'):
                cb.setEnabled(is_superadmin_role(sel_role))
            else:
                cb.setEnabled(True)
        for b in (self._save_btn,self._pw_btn,self._tog_btn): b.setEnabled(True)
        self._tog_btn.setText('Deactivate' if u.get('is_active',1) else 'Activate')
    def _on_role_preset(self, role: str = None):
        """When role changes, apply the standard tab set for that role."""
        if not self._uid:
            return
        role = role or self._role_cb.current_value() or 'cashier'
        preset = set(default_tab_permissions(role))
        for tid, cb in self._chks.items():
            if tid in ('security', 'license'):
                cb.setEnabled(is_superadmin_role(role))
            cb.setChecked(tid in preset)

    def _save_perms(self):
        if not self._uid: return
        actor_role = self.user.get('user', {}).get('role', '')
        new_role = self._role_cb.current_value() or self._role_cb.currentText()
        if not can_assign_role(actor_role, new_role):
            QMessageBox.warning(self, 'Not Allowed',
                'Only the shop owner (Super Admin) can assign the Super Admin role.')
            return
        perms=[tid for tid,cb in self._chks.items() if cb.isChecked()]
        if new_role == 'admin' and 'security' in perms:
            perms = [t for t in perms if t not in ('security', 'license')]
        res=self.api.update_user(self._uid,{'role':new_role,'tab_permissions':perms})
        if res and res.get('success'):
            QMessageBox.information(self,'Saved','Permissions updated.'); self.refresh()
    def _reset_pw(self):
        if not self._uid: return
        pw,ok=QInputDialog.getText(self,'Reset Password','New password:',QLineEdit.Password)
        if ok and len(pw)>=6:
            res=self.api.update_user(self._uid,{'password':pw})
            if res and res.get('success'): QMessageBox.information(self,'Done','Password reset.')
    def _toggle(self):
        if not self._uid: return
        u=next((x for x in self.users if x['id']==self._uid),None)
        if not u: return
        self.api.update_user(self._uid,{'is_active':0 if u.get('is_active',1) else 1}); self.refresh()
    def _add(self):
        dlg=_NewUserDlg(self)
        if dlg.exec_()==QDialog.Accepted:
            res=self.api.create_user(dlg.data())
            if res and res.get('success'):
                self.refresh()
            else:
                err = (res or {}).get('error') or 'Failed. Username may already exist.'
                QMessageBox.critical(self, 'Error', err)
    def _load_audit(self):
        try:
            logs=self.api.get_audit_log() or []; self._audit.setRowCount(0)
            for i,l in enumerate(logs[:50]):
                self._audit.insertRow(i)
                for j,v in enumerate([(l.get('created_at') or '')[:19],l.get('username',''),
                        l.get('action',''),l.get('module',''),l.get('details','')]):
                    self._audit.setItem(i,j,tbl_item(str(v)))
        except Exception: pass

class _NewUserDlg(QDialog):
    def __init__(self, parent):
        super().__init__(parent); self.setWindowTitle('New User'); self.setFixedWidth(400)
        from desktop.utils.theme import apply_themed_dialog,  MBT_STYLESHEET
        apply_themed_dialog(self)
        lay=QFormLayout(self); lay.setContentsMargins(22,20,22,20); lay.setSpacing(14)
        self.uname=QLineEdit(); self.uname.setMinimumHeight(40)
        self.fname=QLineEdit(); self.fname.setMinimumHeight(40)
        self.pw=QLineEdit(); self.pw.setEchoMode(QLineEdit.Password); self.pw.setMinimumHeight(40)
        self.role=Select()
        roles = list(USER_ROLES)
        if not is_superadmin_role(parent.user.get('user',{}).get('role','')):
            roles = [r for r in roles if r != 'superadmin']
        self.role.set_items([(USER_ROLE_LABELS.get(r, r), r) for r in roles])
        self.role.setMinimumHeight(40)
        self.role.currentIndexChanged.connect(lambda *_: self._show_role_hint())
        self._hint = QLabel('')
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color:{C['muted']}; font-size:11px;")
        for lbl,w in [('Username *',self.uname),('Full Name',self.fname),('Password *',self.pw),('Role',self.role)]:
            l=QLabel(lbl); l.setStyleSheet(f"color:{C['text2']}; font-size:13.5px;"); lay.addRow(l,w)
        lay.addRow(self._hint)
        self._show_role_hint()
        # Explicit styled buttons — QDialogButtonBox uses OS theme (black text on grey)
        btn_row = QHBoxLayout()
        save_btn   = PrimaryBtn('Save', 42);   save_btn.clicked.connect(self._val)
        cancel_btn = SecondaryBtn('Cancel', 42); cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn)
        lay.addRow(btn_row)
    def _val(self):
        if not self.uname.text().strip(): QMessageBox.warning(self,'Required','Username required.'); return
        if len(self.pw.text())<6: QMessageBox.warning(self,'Weak','Min 6 chars.'); return
        self.accept()
    def _show_role_hint(self, role=None):
        role = role or self.role.current_value() or 'cashier'
        hints = {
            'superadmin': 'Shop owner — full access, Security tab, stock overrides, license.',
            'admin': 'Shop manager — users, settings, reports. No Security or license.',
            'manager': 'Supervises sales and stock info. Cannot change users or security.',
            'cashier': 'Point of sale only.',
            'viewer': 'Read-only reports.',
        }
        self._hint.setText(hints.get(role, ''))

    def data(self):
        r=self.role.current_value() or 'cashier'
        return {'username':self.uname.text().strip(),'full_name':self.fname.text().strip() or None,
                'password':self.pw.text(),'role':r,
                'tab_permissions': default_tab_permissions(r)}
