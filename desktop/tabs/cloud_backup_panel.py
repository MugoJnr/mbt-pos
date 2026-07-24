"""
MBT POS — Settings → Cloud Backup panel
Theme-aware (Light/Dark via C tokens). Local-first; internet only for sync.
"""
from __future__ import annotations

import threading

from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QProgressBar, QFrame, QInputDialog,
)

from desktop.utils.theme import C
from desktop.utils.widgets import section_card, SecondaryBtn, PrimaryBtn, GhostBtn, DangerBtn


class _Bridge(QObject):
    done = pyqtSignal(object)
    err = pyqtSignal(str)
    progress = pyqtSignal(str, float)


class CloudBackupPanel(QWidget):
    """Embeddable Cloud Backup section for SettingsTab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_worker_done)
        self._bridge.err.connect(self._on_worker_err)
        self._bridge.progress.connect(self._on_progress)
        self._busy = False
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        grp, body = section_card(
            '☁', 'Cloud Backup',
            'Encrypted offline-first backups to Supabase · disaster recovery')
        form = QVBoxLayout()
        form.setSpacing(12)

        # Status card
        self._status_frame = QFrame()
        self._status_frame.setStyleSheet(
            f"QFrame{{background:{C['card2']};border:1px solid {C['border2']};"
            f"border-radius:10px;}}")
        sf = QVBoxLayout(self._status_frame)
        sf.setContentsMargins(16, 12, 16, 12)
        sf.setSpacing(4)
        self._status_title = QLabel('Cloud Backup')
        self._status_title.setStyleSheet(
            f"color:{C['text']}; font-size:14px; font-weight:700; background:transparent;")
        self._status_sub = QLabel('Loading…')
        self._status_sub.setWordWrap(True)
        self._status_sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        sf.addWidget(self._status_title)
        sf.addWidget(self._status_sub)
        form.addWidget(self._status_frame)

        # Meta row
        meta = QHBoxLayout()
        self._lbl_device = QLabel('Device: —')
        self._lbl_size = QLabel('Last size: —')
        self._lbl_last = QLabel('Last backup: —')
        for w in (self._lbl_device, self._lbl_size, self._lbl_last):
            w.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
            meta.addWidget(w)
        meta.addStretch(1)
        form.addLayout(meta)

        # Auth / config fields
        auth = QHBoxLayout()
        self.email = QLineEdit()
        self.email.setPlaceholderText('Business email')
        self.email.setMinimumHeight(40)
        self.password = QLineEdit()
        self.password.setPlaceholderText('Password')
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setMinimumHeight(40)
        self.biz_name = QLineEdit()
        self.biz_name.setPlaceholderText('Business name (new)')
        self.biz_name.setMinimumHeight(40)
        auth.addWidget(self.email, 2)
        auth.addWidget(self.password, 2)
        auth.addWidget(self.biz_name, 2)
        form.addLayout(auth)

        # Frequency
        freq = QHBoxLayout()
        fl = QLabel('Backup every')
        fl.setStyleSheet(f"color:{C['text']}; font-size:13px; background:transparent;")
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setValue(5)
        self.interval.setSuffix(' min')
        self.interval.setMinimumHeight(36)
        self.interval.setMinimumWidth(110)
        save_freq = SecondaryBtn('Save frequency', 36)
        save_freq.clicked.connect(self._save_frequency)
        freq.addWidget(fl)
        freq.addWidget(self.interval)
        freq.addWidget(save_freq)
        freq.addStretch(1)
        form.addLayout(freq)

        # Actions
        row = QHBoxLayout()
        self.btn_create = PrimaryBtn('Create New Business', 40)
        self.btn_login = SecondaryBtn('Login Existing', 40)
        self.btn_backup = PrimaryBtn('Backup Now', 40)
        self.btn_restore = SecondaryBtn('Restore Latest', 40)
        self.btn_devices = GhostBtn('Manage Devices', 40)
        self.btn_skip = GhostBtn('Continue Offline', 40)
        self.btn_logout = DangerBtn('Disconnect', 40)
        for b, slot in (
            (self.btn_create, self._create_business),
            (self.btn_login, self._login),
            (self.btn_backup, self._backup_now),
            (self.btn_restore, self._restore_latest),
            (self.btn_devices, self._manage_devices),
            (self.btn_skip, self._skip),
            (self.btn_logout, self._logout),
        ):
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        form.addLayout(row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{border:1px solid {C['border2']}; border-radius:6px; "
            f"background:{C['surface']}; text-align:center; color:{C['text']};}}"
            f"QProgressBar::chunk{{background:{C['gold']}; border-radius:5px;}}")
        form.addWidget(self._progress)

        self._msg = QLabel('')
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        form.addWidget(self._msg)

        # History table
        hl = QLabel('Backup history')
        hl.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:600; background:transparent;")
        form.addWidget(hl)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ['When', 'Device', 'Size', 'Version', 'Reason'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(160)
        self.table.setStyleSheet(
            f"QTableWidget{{background:{C['surface']}; color:{C['text']}; "
            f"gridline-color:{C['border2']}; border:1px solid {C['border2']}; "
            f"border-radius:8px;}}"
            f"QHeaderView::section{{background:{C['card2']}; color:{C['text2']}; "
            f"padding:6px; border:none;}}")
        form.addWidget(self.table)

        hist_row = QHBoxLayout()
        refresh_btn = SecondaryBtn('Refresh history', 36)
        refresh_btn.clicked.connect(self.refresh)
        restore_sel = SecondaryBtn('Restore selected', 36)
        restore_sel.clicked.connect(self._restore_selected)
        hist_row.addWidget(refresh_btn)
        hist_row.addWidget(restore_sel)
        hist_row.addStretch(1)
        form.addLayout(hist_row)

        hint = QLabel(
            'Sign in with your <b>portal.mugobyte.com</b> email to enable encrypted backups. '
            'Offline POS sales continue if cloud is skipped.')
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['muted']}; font-size:11px; background:transparent;")
        form.addWidget(hint)

        body.addLayout(form)
        root.addWidget(grp)
        self._backups = []

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        try:
            from backend.cloud_backup.sync_manager import SyncManager
            from backend.cloud_backup.paths import load_identity, load_cloud_config
            st = SyncManager.instance().status()
            cfg = load_cloud_config()
            ident = load_identity()
            self.interval.setValue(int(cfg.get('backup_interval_minutes') or 5))
            if ident.get('email') and not self.email.text():
                self.email.setText(ident.get('email') or '')
            if ident.get('business_name') and not self.biz_name.text():
                self.biz_name.setText(ident.get('business_name') or '')

            if st.get('logged_in'):
                title = f"Connected · {st.get('business_name') or 'Business'}"
                sub = (
                    f"{st.get('email') or ''} · "
                    f"{'Auto-backup ON' if st.get('enabled') else 'Auto-backup OFF'} · "
                    f"every {st.get('interval_minutes')} min"
                )
            elif not st.get('configured'):
                title = 'Cloud unavailable'
                sub = (
                    'Could not load MugoByte Cloud endpoints. Check internet, '
                    'restart POS, or contact support.'
                )
            elif st.get('cloud_skipped'):
                title = 'Offline mode'
                sub = 'Cloud skipped — POS works fully offline. Connect anytime.'
            else:
                title = 'Ready to connect'
                sub = 'Create a business or login to enable encrypted cloud backups.'

            if st.get('last_error'):
                sub += f"\nLast error: {st['last_error']}"

            self._status_title.setText(title)
            self._status_sub.setText(sub)
            self._lbl_device.setText(f"Device: {st.get('device_id') or '—'}")
            size = int(st.get('last_backup_size') or 0)
            if size:
                self._lbl_size.setText(f"Last size: {size / (1024 * 1024):.2f} MB")
            else:
                self._lbl_size.setText('Last size: —')
            self._lbl_last.setText(f"Last backup: {st.get('last_backup_at') or '—'}")

            logged = bool(st.get('logged_in'))
            self.btn_backup.setEnabled(logged and not self._busy)
            self.btn_restore.setEnabled(logged and not self._busy)
            self.btn_devices.setEnabled(logged)
            self.btn_logout.setEnabled(logged)

            if logged:
                self._load_history_async()
        except Exception as e:
            self._status_title.setText('Cloud Backup')
            self._status_sub.setText(str(e))

    def _load_history_async(self):
        def work():
            try:
                from backend.cloud_backup.restore_manager import RestoreManager
                rows = RestoreManager().list_available_backups(limit=25)
                self._bridge.done.emit({'op': 'history', 'rows': rows})
            except Exception as e:
                self._bridge.err.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def _fill_history(self, rows: list):
        self._backups = rows or []
        self.table.setRowCount(0)
        for r in self._backups:
            i = self.table.rowCount()
            self.table.insertRow(i)
            size = int(r.get('size_bytes') or 0)
            size_s = f"{size / (1024 * 1024):.2f} MB" if size else '—'
            vals = [
                str(r.get('created_at') or '')[:19].replace('T', ' '),
                str(r.get('device_id') or ''),
                size_s,
                f"v{r.get('mbt_version') or '?'} / s{r.get('schema_version') or '?'}",
                str(r.get('reason') or ''),
            ]
            for c, v in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(v))

    # ── Workers ───────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, msg: str = ''):
        self._busy = busy
        self._progress.setVisible(busy)
        if not busy:
            self._progress.setValue(0)
        if msg:
            self._msg.setText(msg)
        self.refresh()

    def _on_progress(self, msg: str, pct: float):
        self._msg.setText(msg)
        if pct >= 0:
            self._progress.setValue(int(min(100, max(0, pct))))

    def _on_worker_done(self, payload):
        op = (payload or {}).get('op')
        if op == 'history':
            self._fill_history(payload.get('rows') or [])
            return
        self._set_busy(False)
        if payload.get('ok'):
            self._msg.setText(payload.get('message') or 'Done')
            if op == 'restore':
                QMessageBox.information(
                    self, 'Restore complete',
                    'Database restored. Please restart MBT POS.')
            else:
                QMessageBox.information(self, 'MugoByte Platform', payload.get('message') or 'Success')
        else:
            err = payload.get('error') or 'Failed'
            if payload.get('queued'):
                self._msg.setText(f'Queued offline: {err}')
            else:
                QMessageBox.warning(self, 'MugoByte Platform', err)
        self.refresh()

    def _on_worker_err(self, err: str):
        self._set_busy(False)
        self._msg.setText(err)
        QMessageBox.warning(self, 'MugoByte Platform', err)
        self.refresh()

    def _run(self, op: str, fn):
        if self._busy:
            return
        self._set_busy(True, 'Working…')

        def work():
            try:
                result = fn()
                if isinstance(result, dict):
                    result = {**result, 'op': op}
                else:
                    result = {'ok': True, 'op': op, 'message': str(result)}
                self._bridge.done.emit(result)
            except Exception as e:
                self._bridge.err.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _save_frequency(self):
        from backend.cloud_backup.paths import load_cloud_config, save_cloud_config
        cfg = load_cloud_config()
        cfg['backup_interval_minutes'] = int(self.interval.value())
        save_cloud_config(cfg)
        self._msg.setText(f'Frequency saved: every {self.interval.value()} min')
        self.refresh()

    def _create_business(self):
        email, pw, name = self.email.text().strip(), self.password.text(), self.biz_name.text().strip()
        if not email or not pw:
            QMessageBox.warning(self, 'MugoByte Platform', 'Email and password required.')
            return

        def fn():
            from backend.cloud_backup.auth_service import create_business
            r = create_business(email, pw, name or 'My Business')
            return {'ok': True, 'message': f"Business created: {r.get('business_name')}", **r}

        self._run('auth', fn)

    def _login(self):
        email, pw = self.email.text().strip(), self.password.text()
        if not email or not pw:
            QMessageBox.warning(self, 'MugoByte Platform', 'Email and password required.')
            return

        def fn():
            from backend.cloud_backup.auth_service import login_existing
            r = login_existing(email, pw)
            msg = f"Logged in: {r.get('business_name')}"
            if r.get('has_backups'):
                msg += f" — {len(r.get('backups') or [])} backup(s) found. You can restore below."
            return {'ok': True, 'message': msg, **r}

        self._run('auth', fn)

    def _backup_now(self):
        def fn():
            from backend.cloud_backup.sync_manager import SyncManager
            sm = SyncManager.instance()
            sm.set_progress_callback(
                lambda m, p: self._bridge.progress.emit(m, p))
            r = sm.run_backup(reason='manual')
            if r.get('ok'):
                r['message'] = f"Backup uploaded ({(r.get('size') or 0) / 1024:.0f} KB)"
            return r

        self._run('backup', fn)

    def _restore_latest(self):
        reply = QMessageBox.question(
            self, 'Restore latest backup',
            'Replace the local database with the latest cloud backup?\n'
            'A pre-restore copy will be saved. Restart required after.',
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        def fn():
            from backend.cloud_backup.restore_manager import RestoreManager
            rm = RestoreManager()
            rm.set_progress_callback(
                lambda m, p: self._bridge.progress.emit(m, p))
            r = rm.restore_latest(password=self.password.text())
            r['message'] = 'Restore complete'
            return r

        self._run('restore', fn)

    def _restore_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._backups):
            QMessageBox.information(self, 'MugoByte Platform', 'Select a backup row first.')
            return
        bak = self._backups[row]
        reply = QMessageBox.question(
            self, 'Restore backup',
            f"Restore backup from {bak.get('created_at')}?\n"
            f"Device {bak.get('device_id')} · v{bak.get('mbt_version')}",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        def fn():
            from backend.cloud_backup.restore_manager import RestoreManager
            rm = RestoreManager()
            rm.set_progress_callback(
                lambda m, p: self._bridge.progress.emit(m, p))
            r = rm.restore_from_meta(bak, password=self.password.text())
            r['message'] = 'Restore complete'
            return r

        self._run('restore', fn)

    def _manage_devices(self):
        def fn():
            from backend.cloud_backup.supabase_client import SupabaseClient
            from backend.cloud_backup.paths import load_identity
            biz = load_identity().get('business_id') or ''
            rows = SupabaseClient().list_devices(biz) if biz else []
            lines = []
            for d in rows:
                active = 'active' if d.get('is_active', True) else 'inactive'
                lines.append(
                    f"{d.get('device_id')} · {d.get('hostname') or '?'} · "
                    f"{d.get('mbt_version') or '?'} · {active} · "
                    f"seen {str(d.get('last_seen_at') or '')[:19]}"
                )
            return {
                'ok': True,
                'message': 'Devices:\n' + ('\n'.join(lines) if lines else '(none)'),
            }

        self._run('devices', fn)

    def _skip(self):
        from backend.cloud_backup.auth_service import skip_cloud
        skip_cloud()
        self._msg.setText('Cloud skipped — continuing offline.')
        self.refresh()

    def _logout(self):
        from backend.cloud_backup.auth_service import logout
        logout()
        self._msg.setText('Disconnected from MugoByte Platform.')
        self.refresh()
