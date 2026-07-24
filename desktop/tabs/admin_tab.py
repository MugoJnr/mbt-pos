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
TAB_LABELS = {
    'dashboard': 'Dashboard',
    'sales': 'Point of Sale',
    'inventory': 'Inventory',
    'consumption': 'Internal Consumption',
    'debt': 'Debt',
    'accounting': 'Finance',
    'reports': 'Reports',
    'notes': 'Notes',
    'settings': 'Settings',
    'admin': 'Users',
    'license': 'License',
    'diagnostics': 'Diagnostics',
    'security': 'Security',
    'ai_ops': 'AI Operations',
}


def _fmt_last_login(raw):
    if not raw:
        return 'Never'
    s = str(raw).strip()
    if not s or s.lower() == 'never':
        return 'Never'
    # ISO / sqlite → readable date
    s = s.replace('T', ' ')[:16]
    return s


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
        lay, _ = page_layout(self)

        add=PrimaryBtn('+ New User', 40); add.setFixedWidth(130); add.clicked.connect(self._add)
        intro, _ = page_intro(
            'Users & Access',
            'Manage staff accounts, roles, and per-tab access.',
            add)
        lay.addLayout(intro)

        tb=QHBoxLayout(); tb.setSpacing(8)
        self._search=SearchBar('Search users…')
        self._search.textChanged.connect(self._filter); tb.addWidget(self._search, 1)
        ref=GhostBtn('Refresh', 40); ref.clicked.connect(self.refresh)
        tb.addWidget(ref); lay.addLayout(tb)

        split=QSplitter(Qt.Horizontal)
        lw=QWidget(); ll=QVBoxLayout(lw); ll.setContentsMargins(0,0,0,0); ll.setSpacing(10)
        self._tbl=make_table(['Username','Full Name','Role','Status','Last Login'], stretch_col=1, row_height=44)
        self._tbl.horizontalHeader().setSectionResizeMode(0,QHeaderView.Fixed); self._tbl.setColumnWidth(0,110)
        self._tbl.horizontalHeader().setSectionResizeMode(2,QHeaderView.Fixed); self._tbl.setColumnWidth(2,168)
        self._tbl.horizontalHeader().setSectionResizeMode(3,QHeaderView.Fixed); self._tbl.setColumnWidth(3,90)
        self._tbl.horizontalHeader().setSectionResizeMode(4,QHeaderView.Fixed); self._tbl.setColumnWidth(4,130)
        self._tbl.clicked.connect(self._on_sel)
        self._users_card = wrap_table_card(self._tbl, 'All Users')
        ll.addWidget(self._users_card, 1)
        self._users_sparse = Caption('')
        self._users_sparse.setAlignment(Qt.AlignCenter)
        self._users_sparse.setWordWrap(True)
        self._users_sparse.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; font-weight:600; "
            f"background:transparent; padding:12px 16px;")
        self._users_sparse.hide()
        ll.addWidget(self._users_sparse, 0)
        split.addWidget(lw)

        rw=QWidget(); rw.setMinimumWidth(280); rw.setMaximumWidth(340)
        rl=QVBoxLayout(rw); rl.setContentsMargins(12,0,0,0); rl.setSpacing(12)
        rl.addWidget(H2('Permissions'))
        pc=Card(); pl=pc.layout_v()
        self._perms_card = pc
        self._sel_lbl=Caption('Select a user')
        roles = list(USER_ROLES)
        if not is_superadmin_role(self.user.get('user',{}).get('role','')):
            roles = [r for r in roles if r != 'superadmin']
        self._role_cb = Select(
            placeholder='Select a user first',
            items=[(USER_ROLE_LABELS.get(r, r), r) for r in roles],
        )
        self._role_cb.setMinimumHeight(40)
        self._role_cb.setEnabled(False)
        self._role_cb.currentIndexChanged.connect(lambda *_: self._on_role_preset())
        pl.addWidget(self._sel_lbl); pl.addWidget(QLabel('Role:')); pl.addWidget(self._role_cb)
        self._chks={}
        chk_host = QWidget()
        chk_host.setObjectName('adminChkHost')
        self._chk_host = chk_host
        chk_lay = QVBoxLayout(chk_host)
        chk_lay.setContentsMargins(0, 0, 0, 0)
        chk_lay.setSpacing(2)
        ops = [
            'dashboard', 'sales', 'inventory', 'consumption', 'debt',
            'accounting', 'reports', 'notes', 'ai_ops', 'admin', 'settings',
        ]
        system = ['license', 'diagnostics', 'security']
        def _sec(title):
            lbl = QLabel(title)
            lbl.setStyleSheet(
                f"color:{C['muted']}; font-size:10px; font-weight:800; letter-spacing:1px; "
                f"background:transparent; padding:8px 0 4px 0;")
            chk_lay.addWidget(lbl)
        _sec('TAB ACCESS')
        for tid in ops:
            if tid not in ALL_TABS:
                continue
            cb=QCheckBox(TAB_LABELS.get(tid,tid)); cb.setEnabled(False)
            self._chks[tid]=cb; chk_lay.addWidget(cb)
        _sec('SYSTEM')
        for tid in system:
            if tid not in ALL_TABS:
                continue
            cb=QCheckBox(TAB_LABELS.get(tid,tid)); cb.setEnabled(False)
            self._chks[tid]=cb; chk_lay.addWidget(cb)
        # Any leftover tabs not in the groups above
        for tid in ALL_TABS:
            if tid in self._chks:
                continue
            cb=QCheckBox(TAB_LABELS.get(tid,tid)); cb.setEnabled(False)
            self._chks[tid]=cb; chk_lay.addWidget(cb)
        chk_scroll = QScrollArea()
        chk_scroll.setWidgetResizable(True)
        chk_scroll.setFrameShape(QFrame.NoFrame)
        chk_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        chk_scroll.setMinimumHeight(180)
        chk_scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
        chk_scroll.setWidget(chk_host)
        pl.addWidget(chk_scroll, 1)
        self._set_perms_dimmed(True)
        rl.addWidget(pc, 1)
        self._save_btn=PrimaryBtn('Save Permissions', 40); self._save_btn.setEnabled(False); self._save_btn.clicked.connect(self._save_perms)
        self._pw_btn=SecondaryBtn('Reset Password', 40); self._pw_btn.setEnabled(False); self._pw_btn.clicked.connect(self._reset_pw)
        self._tog_btn=DangerBtn('Deactivate', 40); self._tog_btn.setEnabled(False); self._tog_btn.clicked.connect(self._toggle)
        self._perms_hint=Caption('Select a user in the table to edit role and tab access.')
        self._perms_hint.setWordWrap(True)
        self._perms_hint.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; padding:4px 2px;")
        rl.addWidget(self._save_btn); rl.addWidget(self._pw_btn); rl.addWidget(self._tog_btn)
        rl.addWidget(self._perms_hint)
        rl.addSpacing(8)
        split.addWidget(rw); lay.addWidget(split, 1)
        lay.addWidget(H2('Audit Log'))
        self._audit=make_table(['Time','User','Action','Module','Detail'], stretch_col=4, row_height=32)
        self._audit.setMaximumHeight(160)
        lay.addWidget(wrap_table_card(self._audit))
        # Clearance so Copilot FAB never covers Deactivate / audit footer
        lay.addSpacing(72)

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
            role_lbl = role_display_name(u.get('role',''))
            # Table uses short label; full title in tooltip
            short = role_lbl.split('(')[0].strip() if '(' in role_lbl else role_lbl
            role_it = tbl_center(short, C['gold'])
            role_it.setToolTip(role_lbl)
            self._tbl.setItem(i,2,role_it)
            self._tbl.setItem(i,3,tbl_center('Active' if active else 'Inactive', C['ok'] if active else C['err']))
            self._tbl.setItem(i,4,tbl_item(_fmt_last_login(u.get('last_login'))))
        # Size table to fill the card when staffed; only hug when truly sparse
        try:
            n = max(1, self._tbl.rowCount())
            if n < 3:
                hdr = self._tbl.horizontalHeader().height() if self._tbl.horizontalHeader() else 28
                h = hdr + n * 44 + 8
                self._tbl.setFixedHeight(min(420, max(96, h)))
            else:
                self._tbl.setMinimumHeight(200)
                self._tbl.setMaximumHeight(16777215)
                self._tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        except Exception:
            pass
        sparse = len(users) < 3
        if hasattr(self, '_users_sparse'):
            if sparse and users:
                self._users_sparse.setText(
                    f'{len(users)} staff account{"s" if len(users) != 1 else ""} · '
                    'Select a row to edit roles and tab access, or add another user.')
                self._users_sparse.show()
            elif not users:
                self._users_sparse.setText(
                    'No users yet — click + New User to invite your first staff account.')
                self._users_sparse.show()
            else:
                self._users_sparse.hide()
        # Auto-select first row when none chosen so permissions panel isn't blank
        if users and not self._uid and self._tbl.rowCount() > 0:
            self._tbl.selectRow(0)
            try:
                self._on_sel(self._tbl.currentIndex())
            except Exception:
                pass
        # Keep Save Permissions disabled until a row is chosen
        elif not self._uid and hasattr(self, '_save_btn'):
            self._save_btn.setEnabled(False)
            self._sel_lbl.setText('Select a user')
            self._role_cb.setEnabled(False)
            for cb in self._chks.values():
                cb.setEnabled(False); cb.setChecked(False)
            self._set_perms_dimmed(True)
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
        self._set_perms_dimmed(False)
        if hasattr(self, '_perms_hint'):
            self._perms_hint.setText(
                f'Editing access for {u.get("full_name") or u.get("username")}. '
                'Save to apply role and tab changes.')
            self._perms_hint.show()

    def _set_perms_dimmed(self, dimmed: bool):
        """Visually mute the whole permissions panel until a user is selected."""
        try:
            host = getattr(self, '_chk_host', None)
            if host is not None:
                host.setEnabled(not dimmed)
                host.setStyleSheet(
                    f"QWidget#adminChkHost {{ background:transparent; }}"
                    if not dimmed else
                    f"QWidget#adminChkHost {{ background:transparent; }}"
                    f"QWidget#adminChkHost QCheckBox {{ color:{C['muted']}; }}")
            if hasattr(self, '_role_cb'):
                self._role_cb.setEnabled(not dimmed and bool(self._uid))
            if hasattr(self, '_sel_lbl'):
                self._sel_lbl.setStyleSheet(
                    f"color:{C['text2'] if dimmed else C['text']}; font-size:13px; "
                    f"background:transparent;")
        except Exception:
            pass

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
