"""
MBT POS — License & Subscription Tab
MugoByte Technologies | mugobyte.com

Admin-only panel showing license status, subscription details,
activation controls, and device binding information.
"""
import os
import sys
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from desktop.utils.theme import C, RADIUS, qss_alpha
from desktop.utils.widgets import (PrimaryBtn, SecondaryBtn, SuccessBtn, DangerBtn,
                                    page_layout, Card, H2, Badge, GhostBtn)


# ── State styling map (Lovable semantic tokens — read C at render time) ────────
def _state_style(state: str):
    styles = {
        'active':       (C['ok'],    '✓  ACTIVE',       'License is valid and active.'),
        'expiring':     (C['warn'],  '⚠  EXPIRING SOON', 'Subscription expires in less than 14 days.'),
        'warning':      (C['warn'],  '⚠  WARNING',       'Subscription expires in 7 days or less.'),
        'critical':     (C['err'],   '⚠  CRITICAL',      'Subscription expires in 3 days or less!'),
        'expired':      (C['err'],   '✗  EXPIRED',        'Your subscription has expired. Renew to continue.'),
        'inactive':     (C['muted'], '○  INACTIVE',       'License has been deactivated.'),
        'tampered':     (C['err'],   '✗  TAMPERED',       'License integrity check failed. Contact support.'),
        'unactivated':  (C['muted'], '○  NOT ACTIVATED',  'Activate your license to use MBT POS.'),
    }
    return styles.get(state, (C['muted'], state.upper(), ''))


class _LicCard(QFrame):
    """Compact info card for the license dashboard (Lovable Info tile)."""
    def __init__(self, icon, label, value='—', accent=None):
        super().__init__()
        self._accent = accent or C['gold']
        self._icon = icon
        self._label = label
        self.setMinimumHeight(72)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        self._lbl = QLabel(f"{icon}  {label.upper()}")
        self._val = QLabel(str(value))
        self._val.setWordWrap(True)
        lay.addWidget(self._lbl)
        lay.addWidget(self._val)
        self.refresh_theme()
        self.set_value(value)

    def set_value(self, v, color=None):
        self._val.setText(str(v))
        col = color or C['text']
        self._val.setStyleSheet(
            f"color:{col}; font-size:14px; font-weight:700; background:transparent;")

    def refresh_theme(self):
        r = RADIUS['md']
        self.setStyleSheet(
            f"QFrame {{ background:{C['card2']}; border:1px solid {C['border']};"
            f"border-radius:{r}px; }}"
        )
        self._lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:10px; letter-spacing:1.4px; "
            f"font-weight:700; background:transparent;")


class LicenseTab(QWidget):
    """
    Admin-facing license management panel.
    Shows subscription status, activation control, device info.
    """

    def __init__(self, api, user, db_path, config_getter, license_service=None):
        super().__init__()
        self.api             = api
        self.user            = user
        self.db_path         = db_path
        self.config_getter   = config_getter
        self.license_service = license_service
        self._setup_ui()
        QTimer.singleShot(500, self.refresh)

    def _setup_ui(self):
        root, _ = page_layout(self, margins=(24, 20, 24, 20), spacing=16)

        # ── Header (Lovable) ──────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(2)
        eye = QLabel("CURRENT PLAN")
        eye.setStyleSheet(
            f"color:{C['text2']}; font-size:10px; letter-spacing:2px; font-weight:700;")
        ttl = QLabel("License & Subscription")
        ttl.setStyleSheet(f"color:{C['text']}; font-size:20px; font-weight:700;")
        sub = QLabel("Manage your MBT POS license, subscription, and device binding")
        sub.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        hdr_col.addWidget(eye)
        hdr_col.addWidget(ttl)
        hdr_col.addWidget(sub)
        hdr_row.addLayout(hdr_col)
        hdr_row.addStretch()

        ref_btn = GhostBtn("↺  Refresh", 36)
        ref_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(ref_btn)

        sync_btn = SecondaryBtn("⟳  Sync Now", 36)
        sync_btn.clicked.connect(self._force_sync)
        hdr_row.addWidget(sync_btn)
        root.addLayout(hdr_row)

        # ── Status banner ─────────────────────────────────────────────────────
        self.status_banner = QFrame()
        self.status_banner.setMinimumHeight(64)
        self.status_banner.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {C['border']};"
            f"border-radius:12px; }}"
        )
        bl = QHBoxLayout(self.status_banner)
        bl.setContentsMargins(20, 10, 20, 10)

        self.state_icon = QLabel("○")
        self.state_icon.setStyleSheet("font-size:26px; background:transparent;")
        bl.addWidget(self.state_icon)

        state_col = QVBoxLayout()
        state_col.setSpacing(1)
        self.state_label = QLabel("Checking license…")
        self.state_label.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:700; background:transparent;")
        self.state_sub = QLabel("Please wait…")
        self.state_sub.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        state_col.addWidget(self.state_label)
        state_col.addWidget(self.state_sub)
        bl.addLayout(state_col)
        bl.addStretch()

        self.days_badge = QLabel("")
        self.days_badge.setStyleSheet(
            f"color:{C.get('gold_fg','#0A0F1A')}; background:{C['gold']};"
            f"border-radius:8px; font-size:12px; font-weight:700; padding:4px 14px;"
        )
        bl.addWidget(self.days_badge)
        root.addWidget(self.status_banner)

        # ── Subscription warning bar (hidden by default) ──────────────────────
        self.warn_bar = QFrame()
        self.warn_bar.setFixedHeight(38)
        self.warn_bar.hide()
        wl = QHBoxLayout(self.warn_bar)
        wl.setContentsMargins(14, 0, 14, 0)
        self.warn_icon = QLabel("⚠")
        self.warn_icon.setStyleSheet("font-size:16px;")
        self.warn_text = QLabel("")
        self.warn_text.setStyleSheet(f"color:{C['warn']}; font-size:12px; font-weight:600;")
        wl.addWidget(self.warn_icon)
        wl.addWidget(self.warn_text)
        wl.addStretch()
        renew_btn = PrimaryBtn("Renew →", 38)
        renew_btn.setObjectName("primaryBtn")
        renew_btn.setFixedHeight(26)
        renew_btn.clicked.connect(self._open_renewal)
        wl.addWidget(renew_btn)
        root.addWidget(self.warn_bar)

        # ── KPI cards row ─────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.card_plan    = _LicCard('📦', 'Subscription Plan', '—',         C['gold'])
        self.card_days    = _LicCard('⏳', 'Days Remaining',    '—',         C['info'])
        self.card_expiry  = _LicCard('📅', 'Expiry Date',       '—',         C['text2'])
        self.card_sync    = _LicCard('🔄', 'Last Sync',         'Never',     C['ok'])
        for c in (self.card_plan, self.card_days, self.card_expiry, self.card_sync):
            kpi_row.addWidget(c)
        root.addLayout(kpi_row)

        # ── Main body: device info + activation ───────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(14)

        # Left: device info panel
        dev_frame = QFrame()
        dev_frame.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {C['border']};"
            f"border-radius:8px; }}"
        )
        dl = QVBoxLayout(dev_frame)
        dl.setContentsMargins(18, 14, 18, 14)
        dl.setSpacing(10)

        dev_hdr = QLabel("DEVICE BINDING")
        dev_hdr.setStyleSheet(
            f"color:{C['text']}; font-size:10px; letter-spacing:2px; font-weight:600;")
        dl.addWidget(dev_hdr)

        def _info_row(lbl_txt, val_txt='—'):
            rw = QHBoxLayout()
            l  = QLabel(lbl_txt)
            l.setStyleSheet(f"color:{C['text']}; font-size:12px;")
            l.setFixedWidth(120)
            v  = QLabel(val_txt)
            v.setStyleSheet(f"color:{C['text']}; font-size:12px; font-weight:600;")
            v.setWordWrap(True)
            rw.addWidget(l)
            rw.addWidget(v, 1)
            dl.addLayout(rw)
            return v

        self.dev_id_lbl      = _info_row("Device ID:")
        self.activation_lbl  = _info_row("Activated:")
        self.issued_by_lbl   = _info_row("Issued by:")
        self.plan_detail_lbl = _info_row("Plan details:")

        dl.addStretch()
        bind_lbl = QLabel(
            "This license is cryptographically bound to this device.\n"
            "Moving to another PC requires reactivation.")
        bind_lbl.setWordWrap(True)
        bind_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:10px; background:transparent;")
        dl.addWidget(bind_lbl)
        foot_lbl = QLabel("MUGOBYTE TECHNOLOGIES  ·  mugobyte.com")
        foot_lbl.setStyleSheet(f"color:{C['text']}; font-size:10px; letter-spacing:1px;")
        foot_lbl.setAlignment(Qt.AlignCenter)
        dl.addWidget(foot_lbl)
        body.addWidget(dev_frame, 3)

        # Right: activation panel (scrollable when window is short)
        act_frame = QFrame()
        act_frame.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {C['border']};"
            f"border-radius:8px; }}"
        )
        act_frame.setMinimumWidth(280)
        act_frame.setMaximumWidth(400)
        act_outer = QVBoxLayout(act_frame)
        act_outer.setContentsMargins(0, 0, 0, 0)
        act_scroll = QScrollArea()
        act_scroll.setWidgetResizable(True)
        act_scroll.setFrameShape(QFrame.NoFrame)
        act_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        act_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        act_inner = QWidget()
        act_inner.setStyleSheet("background: transparent;")
        al = QVBoxLayout(act_inner)
        al.setContentsMargins(18, 14, 18, 14)
        al.setSpacing(12)

        act_hdr = QLabel("ACTIVATE LICENSE")
        act_hdr.setStyleSheet(
            f"color:{C['text']}; font-size:10px; letter-spacing:2px; font-weight:600;")
        al.addWidget(act_hdr)

        act_info = QLabel(
            "Enter the license key provided by\n"
            "MugoByte Technologies to activate\n"
            "or renew your subscription."
        )
        act_info.setStyleSheet(f"color:{C['text']}; font-size:12px; line-height:1.5;")
        al.addWidget(act_info)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        self.key_input.setFont(QFont('Consolas', 11))
        self.key_input.returnPressed.connect(self._activate)
        al.addWidget(self.key_input)

        self.activate_btn = PrimaryBtn("ACTIVATE LICENSE", 46)
        self.activate_btn.setObjectName("primaryBtn")
        self.activate_btn.setMinimumHeight(44)
        self.activate_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.activate_btn.setCursor(Qt.PointingHandCursor)
        self.activate_btn.clicked.connect(self._activate)
        al.addWidget(self.activate_btn)

        self.act_result = QLabel("")
        self.act_result.setWordWrap(True)
        self.act_result.setStyleSheet(f"font-size:12px; color:{C['text']};")
        al.addWidget(self.act_result)

        al.addSpacing(8)
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{C['border']};")
        al.addWidget(sep)

        # Copy device ID button (for sending to MugoByte to get a key)
        dev_id_lbl = QLabel("Your Device ID (share with MugoByte to get a key):")
        dev_id_lbl.setStyleSheet(f"color:{C['text']}; font-size:10px;")
        al.addWidget(dev_id_lbl)

        copy_row = QHBoxLayout()
        self.short_dev_id = QLabel("Loading…")
        self.short_dev_id.setStyleSheet(
            f"color:{C['gold']}; font-size:11px; font-family:Consolas;")
        copy_row.addWidget(self.short_dev_id, 1)
        copy_btn = SecondaryBtn("Copy", 36)
        copy_btn.setMinimumWidth(64)
        copy_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        copy_btn.clicked.connect(self._copy_device_id)
        copy_row.addWidget(copy_btn)
        al.addLayout(copy_row)

        al.addSpacing(6)

        # ── Telegram key-push status ──────────────────────────────────────────
        tg_hdr = QLabel("ACTIVATION VIA TELEGRAM")
        tg_hdr.setStyleSheet(
            f"color:{C['text']}; font-size:10px; letter-spacing:2px; font-weight:600;")
        al.addWidget(tg_hdr)

        self.tg_status_lbl = QLabel("Waiting for key from MugoByte Technologies…")
        self.tg_status_lbl.setStyleSheet(
            f"color:{C['text']}; font-size:11px;")
        self.tg_status_lbl.setWordWrap(True)
        al.addWidget(self.tg_status_lbl)

        tg_btn_row = QHBoxLayout()
        self.tg_listen_btn = SuccessBtn("Wait for Key via Telegram", 44)
        self.tg_listen_btn.setObjectName("successBtn")
        self.tg_listen_btn.setMinimumHeight(44)
        self.tg_listen_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tg_listen_btn.setCursor(Qt.PointingHandCursor)
        self.tg_listen_btn.clicked.connect(self._start_tg_listen)
        tg_btn_row.addWidget(self.tg_listen_btn, 1)
        al.addLayout(tg_btn_row)

        al.addStretch()
        act_scroll.setWidget(act_inner)
        act_outer.addWidget(act_scroll)

        body.addWidget(act_frame, 2)
        root.addLayout(body)

        # ── Event log ─────────────────────────────────────────────────────────
        log_hdr = QLabel("LICENSE EVENT LOG")
        log_hdr.setStyleSheet(
            f"color:{C['text']}; font-size:10px; letter-spacing:2px; font-weight:600;")
        root.addWidget(log_hdr)

        self.log_table = QTableWidget(0, 3)
        self.log_table.setHorizontalHeaderLabels(['Time', 'Event', 'Detail'])
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.log_table.setColumnWidth(0, 140)
        self.log_table.setColumnWidth(1, 160)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setMaximumHeight(140)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.log_table.setShowGrid(False)
        root.addWidget(self.log_table)

    # ── Data ───────────────────────────────────────────────────────────────────

    def refresh(self):
        if not self.license_service:
            self._show_no_service()
            return

        s = self.license_service.get_status()
        self._render_status(s)
        self._render_logs()

    def on_show(self):
        self.refresh()

    def apply_theme(self, is_light=None):
        from desktop.utils.widgets import refresh_themed_widgets
        refresh_themed_widgets(self)
        for card in (
            getattr(self, 'card_plan', None),
            getattr(self, 'card_days', None),
            getattr(self, 'card_expiry', None),
            getattr(self, 'card_sync', None),
        ):
            if card and hasattr(card, 'refresh_theme'):
                card.refresh_theme()
        if self.license_service:
            try:
                self._render_status(self.license_service.get_status())
            except Exception:
                pass

    def _render_status(self, s: dict):
        state      = s.get('state', 'unactivated')
        color, label_txt, sub_txt = _state_style(state)

        # Banner
        self.state_icon.setText('✓' if state == 'active' else ('✗' if state in ('expired','tampered') else '⚠'))
        self.state_icon.setStyleSheet(f"font-size:26px; color:{color};")
        self.state_label.setText(label_txt)
        self.state_label.setStyleSheet(f"color:{color}; font-size:15px; font-weight:700;")
        self.state_sub.setText(sub_txt)
        self.status_banner.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {qss_alpha(color, 0.25)};"
            f"border-left:4px solid {color}; border-radius:8px; }}"
        )

        days = s.get('days_remaining', 0)
        if state in ('active', 'expiring', 'warning', 'critical'):
            self.days_badge.setText(f"{days} days left")
            self.days_badge.setStyleSheet(
                f"color:{C.get('gold_fg','#0A0F1A')}; background:{color};"
                f"border-radius:14px; font-size:13px; font-weight:800; padding:4px 16px;"
            )
            self.days_badge.show()
        else:
            self.days_badge.hide()

        # Warning bar
        if state in ('expiring', 'warning', 'critical'):
            urgency = {
                'expiring': f"Your subscription expires in {days} days. Renew to avoid interruption.",
                'warning':  f"⚠  Only {days} days remaining. Please renew your subscription soon.",
                'critical': f"🚨  URGENT: License expires in {days} days!",
            }
            self.warn_text.setText(urgency.get(state, ''))
            self.warn_bar.show()
        elif state == 'expired':
            self.warn_text.setText("Your subscription has expired. Read-only mode active.")
            self.warn_text.setStyleSheet(f"color:{C['err']}; font-size:12px; font-weight:600;")
            self.warn_bar.show()
        else:
            self.warn_bar.hide()

        # KPI cards
        self.card_plan.set_value(s.get('plan_name', '—'), C['gold'])
        self.card_days.set_value(
            str(days) if days > 0 else 'Expired',
            color if state != 'active' else C['info']
        )
        self.card_expiry.set_value(s.get('expiry_date') or '—')

        last_sync = s.get('last_sync', 0)
        if last_sync:
            sync_str = datetime.fromtimestamp(last_sync).strftime('%d %b %H:%M')
        else:
            sync_str = 'Never'
        self.card_sync.set_value(sync_str)

        # Device info
        self.dev_id_lbl.setText(s.get('device_id', '—'))
        self.activation_lbl.setText(s.get('activation_date') or 'Not yet activated')
        self.issued_by_lbl.setText('MugoByte Technologies')

        from licensing.license_engine import PLANS
        plan_key = s.get('plan', '')
        plan_info = PLANS.get(plan_key, {})
        max_p = plan_info.get('max_products', '—')
        max_u = plan_info.get('max_users', '—')
        self.plan_detail_lbl.setText(
            f"Max products: {'Unlimited' if max_p == -1 else max_p}  |  "
            f"Max users: {'Unlimited' if max_u == -1 else max_u}"
        )

        # Short device ID for copy
        if self.license_service:
            self.short_dev_id.setText(self.license_service.masked_device_id)

    def _render_logs(self):
        if not self.license_service:
            return
        logs = self.license_service.engine.store.get_logs(20)
        self.log_table.setRowCount(0)
        for i, log in enumerate(logs):
            self.log_table.insertRow(i)
            ts_str = datetime.fromtimestamp(log['ts']).strftime('%Y-%m-%d %H:%M:%S')
            for j, val in enumerate([ts_str, log['event'], log.get('detail', '')]):
                item = QTableWidgetItem(val)
                if j == 1:
                    # Color-code events
                    color = C['err'] if 'TAMPER' in val or 'FAIL' in val or 'REVOKE' in val \
                            else C['ok'] if 'ACTIVATE' in val \
                            else C['text']
                    item.setForeground(QColor(color))
                self.log_table.setItem(i, j, item)

    def _show_no_service(self):
        self.state_label.setText("License service unavailable")
        self.state_sub.setText("Restart the application to initialise the license system.")

    # ── Actions ────────────────────────────────────────────────────────────────

    def _activate(self):
        key = self.key_input.text().strip()
        if not key:
            self._set_result("Please enter a license key.", error=True)
            return
        if not self.license_service:
            self._set_result("License service not running.", error=True)
            return

        self.activate_btn.setEnabled(False)
        self.activate_btn.setText("Activating…")
        QApplication.processEvents()
        try:
            ok, msg = self.license_service.activate_key(key)
            self._set_result(msg, error=not ok)
            if ok:
                self.key_input.clear()
                self.refresh()
        finally:
            self.activate_btn.setEnabled(True)
            self.activate_btn.setText("ACTIVATE LICENSE")

    def _set_result(self, msg: str, error: bool = False):
        color = C['err'] if error else C['ok']
        self.act_result.setText(msg)
        self.act_result.setStyleSheet(f"font-size:12px; color:{color}; font-weight:600;")

    def _copy_device_id(self):
        if self.license_service:
            QApplication.clipboard().setText(self.license_service.engine.device_id)
            self._set_result("Device ID copied to clipboard.", error=False)

    def _force_sync(self):
        if self.license_service:
            self.license_service.force_sync()
            self.refresh()
            self._set_result("Sync complete.", error=False)

    def _open_renewal(self):
        import webbrowser
        webbrowser.open("https://mugobyte.com/renew")

    # ── Telegram key-push listener ─────────────────────────────────────────────

    def _start_tg_listen(self):
        """Poll the Telegram bot for 5 minutes waiting for a key from the developer."""
        import threading, requests, time
        cfg   = self.config_getter() or {}
        token = cfg.get('telegram_bot_token', '').strip()
        if not token:
            QMessageBox.warning(self, 'Not Configured',
                'Telegram Bot Token is not set.\nAsk MugoByte Technologies to confirm setup.')
            return

        self.tg_listen_btn.setEnabled(False)
        self.tg_listen_btn.setText('Listening for key…')
        self.tg_status_lbl.setText('⏳  Listening — developer will send key within 5 minutes…')
        self.tg_status_lbl.setStyleSheet(f"color:{C['warn']}; font-size:11px;")

        def _poll():
            deadline = time.time() + 300   # 5 minutes
            offset   = 0
            api_base = f'https://api.telegram.org/bot{token}'
            try:
                # get current offset so we only see NEW messages
                r = requests.get(f'{api_base}/getUpdates',
                                  params={'timeout': 1, 'limit': 1}, timeout=5)
                if r.ok:
                    updates = r.json().get('result', [])
                    if updates:
                        offset = updates[-1]['update_id'] + 1
            except Exception:
                pass

            while time.time() < deadline:
                try:
                    r = requests.get(
                        f'{api_base}/getUpdates',
                        params={'timeout': 20, 'offset': offset,
                                'allowed_updates': ['message']},
                        timeout=25,
                    )
                    if not r.ok:
                        time.sleep(5); continue
                    for upd in r.json().get('result', []):
                        offset = upd['update_id'] + 1
                        text   = upd.get('message', {}).get('text', '')
                        # Developer pushes:  /send_key <key>
                        # or just pastes a key that looks like XXXX-XXXX-XXXX-XXXX
                        key = None
                        if text.startswith('/send_key '):
                            key = text[len('/send_key '):].strip()
                        elif len(text) >= 20 and ' ' not in text and '-' in text:
                            key = text.strip()
                        if key:
                            QTimer.singleShot(0, lambda k=key: self._tg_key_received(k))
                            return
                except requests.exceptions.Timeout:
                    continue
                except Exception as e:
                    time.sleep(5)

            # Timed out
            QTimer.singleShot(0, self._tg_listen_timeout)

        threading.Thread(target=_poll, daemon=True).start()

    def _tg_key_received(self, key: str):
        """Called on main thread when a key arrives via Telegram."""
        self.tg_listen_btn.setEnabled(True)
        self.tg_listen_btn.setText('Wait for Key via Telegram')
        self.tg_status_lbl.setText(f'✓  Key received via Telegram — activating…')
        self.tg_status_lbl.setStyleSheet(f"color:{C['ok']}; font-size:11px;")
        self.key_input.setText(key)
        # Auto-trigger activation
        self._activate()

    def _tg_listen_timeout(self):
        self.tg_listen_btn.setEnabled(True)
        self.tg_listen_btn.setText('Wait for Key via Telegram')
        self.tg_status_lbl.setText('⏰  Timed out. Ask MugoByte to send the key and try again.')
        self.tg_status_lbl.setStyleSheet(f"color:{C['err']}; font-size:11px;")

