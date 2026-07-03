"""
MBT POS — Main Application Entry Point
MugoByte Technologies | mugobyte.com

All services run as internal threads — no terminal or CMD windows.
"""
import sys
import os
import threading
import time
import logging
from datetime import datetime

# ── Path setup (single source: mbt_paths) ─────────────────────────────────────
from mbt_paths import get_project_root, get_db_path, ensure_data_dirs

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    BASE_DIR   = os.path.join(BUNDLE_DIR, 'desktop')
else:
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = os.path.dirname(BASE_DIR)

PROJECT_ROOT = ensure_data_dirs(get_project_root())
ASSETS_DIR   = os.path.join(BUNDLE_DIR, 'assets')
LOGS_DIR     = os.path.join(PROJECT_ROOT, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

for p in (BUNDLE_DIR, PROJECT_ROOT):
    if p and p not in sys.path:
        sys.path.insert(0, p)

logging.basicConfig(
    filename=os.path.join(LOGS_DIR, 'app.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
log = logging.getLogger('main')
log.info('MBT POS data root: %s', PROJECT_ROOT)
log.info('MBT POS database: %s', get_db_path())

# Update this tag whenever shipping visual/runtime patches.
APP_BUILD_TAG = "PROD-2026-07-03-v2.3.3"
APP_VERSION   = "2.3.3"   # must match GitHub release tag vX.Y.Z


def install_crash_handler():
    """Log unhandled errors and show a dialog instead of silent exit."""
    import traceback

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        msg = ''.join(traceback.format_exception(exc_type, exc, tb))
        log.error('Unhandled exception:\n%s', msg)
        try:
            app = QApplication.instance()
            if app:
                QMessageBox.critical(
                    None, 'MBT POS — Unexpected Error',
                    'Something went wrong.\n\n'
                    f'{exc}\n\n'
                    'The app will keep running. Details were written to the log file.')
        except Exception:
            pass

    sys.excepthook = _hook


from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

from desktop.utils.api_client       import APIClient
from desktop.utils.theme            import MBT_STYLESHEET, C
from desktop.utils.splash           import SplashScreen
from desktop.wizard.setup_wizard    import SetupWizard, needs_wizard, reset_wizard
from desktop.tabs.dashboard_tab     import DashboardTab
from desktop.tabs.sales_tab         import SalesTab
from desktop.tabs.inventory_tab     import InventoryTab
from desktop.tabs.debt_tab          import DebtTab
from desktop.tabs.reports_tab       import ReportsTab
from desktop.tabs.notes_tab         import NotesTab
from desktop.tabs.admin_tab         import AdminTab
from desktop.tabs.settings_tab      import SettingsTab
from desktop.tabs.diagnostics_tab   import DiagnosticsTab
from desktop.tabs.license_tab       import LicenseTab
from desktop.tabs.security_tab      import SecurityTab

BACKEND_URL  = "http://127.0.0.1:5050"
_main_window = None   # global ref — prevents GC
_web_svc     = None   # embedded Flask dashboard (app lifetime)


# ── Icon loader ────────────────────────────────────────────────────────────────
def _load_icon() -> QIcon:
    for name in ('mbt_icon.png', 'mbt_icon_256.png', 'mbt_icon_64.png'):
        p = os.path.join(ASSETS_DIR, name)
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()


# ── Signals ────────────────────────────────────────────────────────────────────
class AppSignals(QObject):
    connection_changed = pyqtSignal(bool)
    sync_status        = pyqtSignal(str)


# ── Login Dialog ───────────────────────────────────────────────────────────────
class LoginDialog(QDialog):
    def __init__(self, api: APIClient, icon: QIcon):
        super().__init__()
        self.api       = api
        self.user_data = None
        self.setWindowTitle("MBT POS")
        self.setWindowIcon(icon)
        self.setFixedSize(440, 540)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setStyleSheet(MBT_STYLESHEET)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Banner
        banner = QWidget()
        banner.setObjectName("loginBrand")
        banner.setFixedHeight(200)
        banner.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {C['app']}, stop:1 {C['card']});"
            f"border-bottom: 2px solid {C['gold']};"
        )
        bl = QVBoxLayout(banner)
        bl.setAlignment(Qt.AlignCenter)
        bl.setSpacing(6)

        logo  = QLabel("MBT");        logo.setObjectName("logoText");     logo.setAlignment(Qt.AlignCenter)
        prod  = QLabel("POINT OF SALE"); prod.setObjectName("loginTitle"); prod.setAlignment(Qt.AlignCenter)
        brand = QLabel("MugoByte Technologies"); brand.setObjectName("loginSubtitle"); brand.setAlignment(Qt.AlignCenter)
        bl.addWidget(logo); bl.addWidget(prod); bl.addWidget(brand)
        root.addWidget(banner)

        # Form
        form = QWidget()
        form.setObjectName("loginForm")
        form.setStyleSheet(f"background:{C['surface']};")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(44, 30, 44, 30)
        fl.setSpacing(16)

        self._msg = QLabel("Sign in to continue")
        self._msg.setObjectName("loginStatus")
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)

        self._u = QLineEdit(); self._u.setObjectName("loginInput"); self._u.setPlaceholderText("Username")
        self._p = QLineEdit(); self._p.setObjectName("loginInput"); self._p.setPlaceholderText("Password")
        self._p.setEchoMode(QLineEdit.Password)
        self._p.returnPressed.connect(self._login)

        self._btn = QPushButton("SIGN IN")
        self._btn.setObjectName("loginBtn")
        self._btn.setFixedHeight(48)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._login)

        foot = QLabel("Powered by MugoByte Technologies  ·  mugobyte.com")
        foot.setObjectName("loginFooter")
        foot.setAlignment(Qt.AlignCenter)

        fl.addWidget(self._msg); fl.addWidget(self._u); fl.addWidget(self._p)
        fl.addWidget(self._btn); fl.addStretch(); fl.addWidget(foot)
        root.addWidget(form)

    def _login(self):
        u, p = self._u.text().strip(), self._p.text()
        if not u or not p:
            self._set_msg("Enter username and password", err=True); return

        self._btn.setText("Signing in…"); self._btn.setEnabled(False)
        QApplication.processEvents()

        try:
            res = self.api.login(u, p)
            if res and 'token' in res:
                self.user_data = res
                self._btn.setText("SIGN IN"); self._btn.setEnabled(True)
                self.accept()
                return
            self._set_msg("Invalid username or password", err=True)
        except Exception as e:
            self._set_msg(f"Could not open database.\n{e}", err=True)
        self._btn.setText("SIGN IN"); self._btn.setEnabled(True)

    def _set_msg(self, txt, err=False):
        self._msg.setText(txt)
        self._msg.setStyleSheet(
            f"color:{C['err'] if err else C['ok']}; font-size:13px;")

    # Allow dragging the frameless window
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(e.globalPos() - self._drag_pos)


# ── Main Window ────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, user_data: dict, api: APIClient, icon: QIcon):
        super().__init__()
        self.user_data = user_data
        self.api       = api
        self.signals   = AppSignals()
        self._svc_net  = None
        self._svc_lic  = None
        self._svc_diag = None

        self.setWindowTitle("MBT POS — MugoByte Technologies")
        self.setWindowIcon(icon)
        self.setMinimumSize(1200, 720)
        self.setStyleSheet(MBT_STYLESHEET)
        self.showMaximized()

        self._db_path = get_db_path()

        # UI first — services second (never block render)
        self._build_ui()
        self._build_tabs()

        self.signals.connection_changed.connect(self._on_conn)
        self.signals.sync_status.connect(self._on_sync)

        first = next(iter(self._nav), 'dashboard')
        self._goto(first)

        # Wire dashboard quick-action navigation
        if 'dashboard' in self._tabs:
            dash = self._tabs['dashboard']
            if hasattr(dash, 'navigate'):
                dash.navigate.connect(self._goto)

        # Wire sale_completed → refresh dashboard + reports immediately
        if 'sales' in self._tabs:
            sales_tab = self._tabs['sales']
            if hasattr(sales_tab, 'sale_completed'):
                if 'dashboard' in self._tabs and hasattr(self._tabs['dashboard'], '_load'):
                    sales_tab.sale_completed.connect(self._tabs['dashboard']._load)
                if 'reports' in self._tabs and hasattr(self._tabs['reports'], 'refresh'):
                    sales_tab.sale_completed.connect(self._tabs['reports'].refresh)

        # Start services after a short delay so UI paints immediately
        QTimer.singleShot(500, self._start_services)
        QTimer.singleShot(1500, self._initial_conn_check)

    # ── Config ─────────────────────────────────────────────────────────────────
    def _cfg(self) -> dict:
        try:
            return self.api.get('/api/settings') or {}
        except Exception:
            return {}

    # ── Background services ────────────────────────────────────────────────────
    def _start_services(self):
        try:
            from backend.internet_monitor import InternetMonitor
            self._svc_net = InternetMonitor(
                db_path=self._db_path, config_getter=self._cfg,
                status_callback=lambda c: self.signals.connection_changed.emit(c))
            self._svc_net.start()
        except Exception as e:
            log.warning(f"Internet monitor: {e}")

        try:
            from licensing.license_service import LicenseService
            self._svc_lic = LicenseService(
                project_root=PROJECT_ROOT, config_getter=self._cfg,
                on_state_change=self._on_license_state)
            self._svc_lic.start()
        except Exception as e:
            log.warning(f"License service: {e}")

        try:
            from diagnostics.diagnostic_engine import DiagnosticEngine
            self._svc_diag = DiagnosticEngine(self._db_path, self._cfg)
            self._svc_diag.start()
        except Exception as e:
            log.warning(f"Diagnostics: {e}")

        try:
            from backend.telegram_reporter import ReportScheduler
            self._svc_sched = ReportScheduler(
                self.api, self._cfg,
                is_online_getter=lambda: getattr(self._svc_net, 'is_connected', False),
            )
            self._svc_sched.start()
        except Exception as e:
            log.warning(f"Report scheduler: {e}")

        self._updater = None
        self._pending_update_version = ''
        self._pending_installer_path = ''
        self._pending_update_notes = ''
        try:
            from backend.updater import UpdateChecker
            self._updater = UpdateChecker(APP_VERSION)
            self._updater.on_update_available = self._on_update_available
            self._updater.on_download_ready   = self._on_update_ready
            self._updater.on_force_required   = self._on_force_update
            self._updater.start()
        except Exception as e:
            log.warning(f"UpdateChecker: {e}")

        # Pass license service to license tab if it exists
        if 'license' in self._tabs and self._svc_lic:
            try:
                self._tabs['license'].license_service = self._svc_lic
            except Exception:
                pass

    def _on_license_state(self, state: str, data: dict):
        """
        Called immediately when LicenseService detects a state change —
        including from remote commands (revoke, extend, activate).
        Runs on the license service thread → must use QTimer to touch UI.
        """
        from licensing.license_engine import (
            STATE_TAMPERED, STATE_EXPIRED, STATE_INACTIVE, STATE_UNACTIVATED
        )

        def _ui_update():
            # 1. Always refresh the license tab so it shows new state instantly
            if 'license' in self._tabs:
                try:
                    self._tabs['license'].refresh()
                except Exception:
                    pass

            # 2. Lock the app if revoked / tampered / expired
            if state in (STATE_TAMPERED, STATE_INACTIVE, STATE_EXPIRED):
                reason = {
                    STATE_TAMPERED:  "⚠  License Tampered\n\nThis license has been flagged. The application will now close.",
                    STATE_INACTIVE:  "🔒  License Revoked\n\nYour license has been revoked by MugoByte Technologies.\nPlease contact support to renew.",
                    STATE_EXPIRED:   "⏰  License Expired\n\nYour subscription has expired.\nPlease contact MugoByte Technologies to renew.",
                }.get(state, "License invalid.")

                QMessageBox.critical(self, 'MBT POS — License', reason)

                if state in (STATE_TAMPERED, STATE_INACTIVE):
                    # Hard close — no way to continue
                    QApplication.quit()

            # 3. Warn on tamper
            if state == STATE_TAMPERED and self._svc_lic:
                try:
                    self._svc_lic.send_tamper_alert()
                except Exception:
                    pass

        QTimer.singleShot(0, _ui_update)

    def _on_update_available(self, version, notes, asset_url):
        self._pending_update_version = version
        self._pending_update_notes = notes or ''
        log.info(f"Update available: v{version}")

        def _show():
            btn = getattr(self, '_update_btn', None)
            if btn:
                btn.setText(f"  Downloading v{version}…  ")
                btn.show()
        QTimer.singleShot(0, _show)

    def _on_update_ready(self, installer_path, version):
        self._pending_installer_path = installer_path
        self._pending_update_version = version
        log.info(f"Update downloaded: v{version}")

        def _show():
            btn = getattr(self, '_update_btn', None)
            if btn:
                btn.setText(f"  Update v{version}  ")
                btn.show()
        QTimer.singleShot(0, _show)

    def _on_force_update(self, version, reason):
        self._pending_update_version = version
        log.warning(f"Force update required: v{version}")

        def _warn():
            QMessageBox.warning(
                self, 'Update Required',
                reason or f'Please update to v{version} to continue using MBT POS.')
        QTimer.singleShot(0, _warn)

    def _on_update_btn_clicked(self):
        version = self._pending_update_version or '?'
        path    = self._pending_installer_path or ''
        notes   = self._pending_update_notes or ''
        if not path or not os.path.isfile(path):
            QMessageBox.warning(
                self, 'Update',
                'The update file is not ready yet. Try again in a few minutes.')
            return
        dlg = QMessageBox(self)
        dlg.setWindowTitle(f'Update v{version} Ready')
        dlg.setText(
            f'<b>Version {version} is ready to install.</b><br><br>'
            'Your shop data will not be affected.')
        if notes:
            dlg.setDetailedText(notes[:600])
        dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dlg.button(QMessageBox.Ok).setText('Install Now')
        dlg.button(QMessageBox.Cancel).setText('Later')
        if dlg.exec_() != QMessageBox.Ok:
            return
        try:
            if self._updater and self._updater.install_and_restart(path):
                self._stop_services()
                QApplication.instance().quit()
        except Exception as e:
            log.error(f'Install update: {e}')
            QMessageBox.critical(self, 'Update Failed', str(e))

    def _stop_services(self):
        updater = getattr(self, '_updater', None)
        if updater:
            try:
                updater.stop()
            except Exception:
                pass
        for svc in (self._svc_net, self._svc_lic, self._svc_diag,
                    getattr(self, '_svc_sched', None)):
            if svc:
                try: svc.stop()
                except Exception: pass

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        right = QWidget(); right.setObjectName("content")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        rl.addWidget(self._build_topbar())
        self._stack = QStackedWidget(); self._stack.setObjectName("pageStack")
        rl.addWidget(self._stack)
        rl.addWidget(self._build_statusbar())
        root.addWidget(right, 1)

    def _build_sidebar(self):
        sb = QWidget(); sb.setObjectName("sidebar"); sb.setFixedWidth(220)
        sl = QVBoxLayout(sb); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)

        # Logo block
        lw = QWidget(); lw.setObjectName("sidebarLogo"); lw.setFixedHeight(72)
        ll = QVBoxLayout(lw); ll.setAlignment(Qt.AlignCenter); ll.setSpacing(1)
        lt = QLabel("MBT"); lt.setObjectName("sidebarLogoText"); lt.setAlignment(Qt.AlignCenter)
        ls = QLabel("POS SYSTEM"); ls.setObjectName("sidebarLogoSub"); ls.setAlignment(Qt.AlignCenter)
        ll.addWidget(lt); ll.addWidget(ls)
        sl.addWidget(lw)

        sl.addSpacing(10)

        # Navigation — scrollable when many tabs / short displays
        self._nav = {}
        perms = self.user_data.get('user', {}).get('tab_permissions', [])
        role  = self.user_data.get('user', {}).get('role', '')
        tabs  = [
            ('dashboard',   '⊞',  'Dashboard'),
            ('sales',       '⊕',  'Point of Sale'),
            ('inventory',   '▤',  'Inventory'),
            ('debt',        '💰', 'Debt Management'),
            ('reports',     '▦',  'Reports'),
            ('notes',       '≡',  'Notes'),
            ('admin',       '⊛',  'Users & Access'),
            ('settings',    '⚙',  'Settings'),
            ('security',    '🔐', 'Security'),
            ('license',     '◈',  'License'),
            ('diagnostics', '⚒',  'Diagnostics'),
        ]
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        nav_body = QWidget()
        nav_body.setStyleSheet("background:transparent;")
        nv = QVBoxLayout(nav_body)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(2)
        for tid, icon, lbl in tabs:
            if tid in ('security', 'license') and role != 'superadmin':
                continue
            if role != 'admin' and role != 'superadmin' and tid not in perms:
                continue
            btn = QPushButton(f"  {icon}   {lbl}")
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, t=tid: self._goto(t))
            nv.addWidget(btn)
            self._nav[tid] = btn
        nv.addStretch()
        nav_scroll.setWidget(nav_body)
        sl.addWidget(nav_scroll, 1)

        # User panel
        uw = QWidget(); uw.setObjectName("sidebarUser")
        ul = QVBoxLayout(uw); ul.setContentsMargins(16, 12, 16, 12); ul.setSpacing(2)
        u  = self.user_data.get('user', {})
        un = QLabel(u.get('full_name') or u.get('username', ''))
        un.setObjectName("sidebarUserName")
        ur = QLabel(u.get('role', '').upper())
        ur.setObjectName("sidebarUserRole")
        lo = QPushButton("Sign Out"); lo.setObjectName("logoutBtn")
        lo.setCursor(Qt.PointingHandCursor); lo.clicked.connect(self._logout)
        ul.addWidget(un); ul.addWidget(ur); ul.addWidget(lo)
        sl.addWidget(uw)
        return sb

    def _build_topbar(self):
        bar = QWidget(); bar.setObjectName("topbar"); bar.setFixedHeight(52)
        lay = QHBoxLayout(bar); lay.setContentsMargins(26, 0, 20, 0); lay.setSpacing(12)

        self._page_title = QLabel("Dashboard"); self._page_title.setObjectName("pageTitle")
        lay.addWidget(self._page_title); lay.addStretch()

        # Connection badge
        self._conn_lbl = QLabel("● Online")
        self._conn_lbl.setObjectName("connBadge")
        self._conn_lbl.setStyleSheet(
            f"color:{C['ok']}; font-size:12px; font-weight:600; background:transparent;")
        lay.addWidget(self._conn_lbl)

        self._sync_lbl = QLabel(""); self._sync_lbl.setObjectName("syncLbl")
        lay.addWidget(self._sync_lbl)

        self._update_btn = QPushButton("  Update  ")
        self._update_btn.setObjectName("refreshBtn")
        self._update_btn.setCursor(Qt.PointingHandCursor)
        self._update_btn.clicked.connect(self._on_update_btn_clicked)
        self._update_btn.hide()
        lay.addWidget(self._update_btn)

        ref_btn = QPushButton("↺  Refresh"); ref_btn.setObjectName("refreshBtn")
        ref_btn.setCursor(Qt.PointingHandCursor); ref_btn.clicked.connect(self._manual_refresh)
        lay.addWidget(ref_btn)

        self._clk = QLabel(); self._clk.setObjectName("clockLbl")
        lay.addWidget(self._clk)

        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000); self._tick()
        return bar

    def _build_statusbar(self):
        bar = QWidget(); bar.setObjectName("statusBar"); bar.setFixedHeight(24)
        lay = QHBoxLayout(bar); lay.setContentsMargins(20, 0, 20, 0)
        l = QLabel("MBT POS  ·  MugoByte Technologies"); l.setObjectName("statusLeft")
        runtime = "EXE" if getattr(sys, 'frozen', False) else "DEV"
        exe_name = os.path.basename(sys.executable) if getattr(sys, 'frozen', False) else "python"
        r = QLabel(f"v{APP_VERSION}  ·  {APP_BUILD_TAG}  ·  {runtime}:{exe_name}")
        r.setObjectName("statusRight")
        r.setToolTip(
            f"Version: {APP_VERSION}\n"
            f"Build: {APP_BUILD_TAG}\n"
            f"Runtime: {runtime}\n"
            f"Executable: {sys.executable}\n"
            f"Database: {get_db_path()}"
        )
        lay.addWidget(l); lay.addStretch(); lay.addWidget(r)
        return bar

    def _build_tabs(self):
        self._tabs = {}
        kw = dict(api=self.api, user=self.user_data,
                  db_path=self._db_path, config_getter=self._cfg)
        cls_map = {
            'dashboard':   DashboardTab,
            'sales':       SalesTab,
            'inventory':   InventoryTab,
            'debt':        DebtTab,
            'reports':     ReportsTab,
            'notes':       NotesTab,
            'admin':       AdminTab,
            'settings':    SettingsTab,
            'security':    SecurityTab,
            'diagnostics': DiagnosticsTab,
            'license':     LicenseTab,
        }
        for tid, cls in cls_map.items():
            if tid not in self._nav:
                continue
            try:
                if tid == 'license':
                    w = cls(**kw, license_service=None)
                else:
                    w = cls(**kw)
            except Exception as e:
                w = QLabel(f"Error loading {tid}:\n{e}")
                w.setStyleSheet(f"color:{C['err']}; padding:32px; font-size:14px;")
            self._tabs[tid] = w
            self._stack.addWidget(w)

    # ── Navigation ──────────────────────────────────────────────────────────────
    _TAB_LABELS = {
        'dashboard':'Dashboard', 'sales':'Point of Sale', 'inventory':'Inventory',
        'debt':'Debt Management',
        'reports':'Reports', 'notes':'Notes', 'admin':'Users & Access',
        'settings':'Settings', 'security':'Security & Super-Admin',
        'license':'License & Subscription', 'diagnostics':'Diagnostics',
    }

    def _goto(self, tid: str):
        for bid, btn in self._nav.items():
            btn.setChecked(bid == tid)
        self._page_title.setText(self._TAB_LABELS.get(tid, tid.title()))
        if tid in self._tabs:
            self._stack.setCurrentWidget(self._tabs[tid])
            tab = self._tabs[tid]
            if hasattr(tab, 'on_show'):
                try: tab.on_show()
                except Exception as e: log.warning(f"on_show {tid}: {e}")

    # ── Status slots ────────────────────────────────────────────────────────────
    def _on_conn(self, ok: bool):
        self._conn_lbl.setText("● Online" if ok else "● Offline")
        self._conn_lbl.setStyleSheet(
            f"color:{C['ok'] if ok else C['err']}; font-size:13px; font-weight:700;")

    def _on_sync(self, s: str):
        self._sync_lbl.setText(
            {'syncing':'⟳ Syncing', 'synced':'✓ Synced', 'failed':'⚠ Failed', 'idle':''}.get(s, s))

    def _tick(self):
        self._clk.setText(datetime.now().strftime('%a %d %b  %H:%M:%S'))

    def _manual_refresh(self):
        self._sync_lbl.setText("⟳ Checking…")
        QTimer.singleShot(80, self._do_refresh)

    def _do_refresh(self):
        ok = False
        if self._svc_net:
            ok = self._svc_net.force_sync()
        else:
            import socket
            try:
                s = socket.create_connection(("8.8.8.8", 53), timeout=3); s.close(); ok = True
            except Exception: pass
        self._on_conn(ok)
        cur = self._stack.currentWidget()
        if cur and hasattr(cur, 'refresh'):
            try: cur.refresh()
            except Exception: pass

    def _initial_conn_check(self):
        ok = self._svc_net.is_connected if self._svc_net else False
        self._on_conn(ok)

    # ── Auth ────────────────────────────────────────────────────────────────────
    def _logout(self):
        if QMessageBox.question(self, "Sign Out", "Sign out of MBT POS?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._stop_services()
            self.hide()
            _show_login(self.api)

    def closeEvent(self, event):
        self._stop_services(); event.accept()


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def _start_web_dashboard():
    """Start embedded web dashboard (runs for entire app session)."""
    global _web_svc
    if _web_svc and _web_svc.running:
        return True
    try:
        try:
            from backend.cloudflare_setup import bootstrap_cloudflared, refresh_remote_setup_status
            bootstrap_cloudflared()
            refresh_remote_setup_status()
        except Exception:
            pass
        from backend.web_service import WebDashboardService
        _web_svc = WebDashboardService()
        ok = _web_svc.start()
        if ok:
            log.info(f"Web dashboard: {_web_svc.url}")
        else:
            log.warning("Web dashboard could not start — desktop POS still works")
        return ok
    except Exception as e:
        log.warning(f"Web dashboard: {e}")
        return False


def _stop_web_dashboard():
    global _web_svc
    if _web_svc:
        try:
            _web_svc.stop()
        except Exception:
            pass
        _web_svc = None


def _show_login(api: APIClient = None):
    """Show login; store MainWindow in global to prevent GC."""
    global _main_window
    icon = _load_icon()
    if api is None:
        api = APIClient(BACKEND_URL)

    dlg = LoginDialog(api, icon)
    # Centre it
    s = QApplication.primaryScreen().geometry()
    dlg.move(s.center().x() - dlg.width()//2, s.center().y() - dlg.height()//2)

    if dlg.exec_() != QDialog.Accepted:
        QApplication.instance().quit(); return

    ud = dlg.user_data
    api.set_token(ud['token'])
    _main_window = MainWindow(ud, api, icon)
    _main_window.show()


def main():
    # Hide console on Windows (extra safety)
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except Exception:
            pass

    # Force consistent high-DPI behavior so text isn't tiny on some PCs.
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    install_crash_handler()
    app.setApplicationName("MBT POS")
    app.setOrganizationName("MugoByte Technologies")
    app.setFont(QFont('Segoe UI', 13))

    icon = _load_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Splash screen
    splash = SplashScreen()
    splash.show()
    splash.set_status("Starting MBT POS…", 5)
    QApplication.processEvents()

    splash.set_status("Initialising database…", 30)
    QApplication.processEvents()
    # Init DB directly — no HTTP server needed
    try:
        from backend.app import init_db
        init_db()
    except Exception as e:
        log.error(f"DB init: {e}")

    try:
        from backend.telegram_hub import start_hub
        start_hub(lambda: APIClient(BACKEND_URL).get_settings() or {})
    except Exception as e:
        log.warning(f"Telegram hub: {e}")

    splash.set_status("Starting web dashboard…", 55)
    QApplication.processEvents()
    _start_web_dashboard()

    splash.set_status("Loading interface…", 80)
    QApplication.processEvents()

    splash.set_status("Ready", 100)
    QApplication.processEvents()

    def _launch():
        global _main_window
        # Run setup wizard if needed
        if needs_wizard():
            api_temp = APIClient(BACKEND_URL)
            wiz = SetupWizard()
            wiz.completed.connect(lambda data: log.info(f"Wizard complete: shop={data.get('shop_name')}"))
            # Centre
            s = QApplication.primaryScreen().geometry()
            wiz.move(s.center().x() - wiz.width()//2, s.center().y() - wiz.height()//2)
            if wiz.exec_() != QDialog.Accepted:
                QApplication.instance().quit(); return

        _show_login()

    splash.finish_and_close(300)
    QTimer.singleShot(700, _launch)

    app.aboutToQuit.connect(_stop_web_dashboard)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
