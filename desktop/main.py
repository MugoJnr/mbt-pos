"""
MBT POS â€” Main Application Entry Point
MugoByte Technologies | mugobyte.com

All services run as internal threads â€” no terminal or CMD windows.
"""
import sys
import os
import threading
import time
import tempfile
import logging
from datetime import datetime

# â”€â”€ Path setup (single source: mbt_paths) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
APP_BUILD_TAG = "PROD-2026-07-16-v2.3.36"
APP_VERSION   = "2.3.36"   # must match GitHub release tag vX.Y.Z


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
                    None, 'MBT POS - Unexpected Error',
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
from desktop.utils.theme            import (
    MBT_STYLESHEET, C, ThemeManager, is_light_mode, ensure_fonts,
)
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
_main_window = None   # global ref â€” prevents GC
_web_svc     = None   # embedded Flask dashboard (app lifetime)


# â”€â”€ Icon / logo loaders â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _load_icon() -> QIcon:
    # Prefer multi-size ICO, then transparent PNG icons (no black/white plate)
    for name in ('mbt_icon.ico', 'mbt_icon.png', 'mbt_icon_256.png', 'mbt_icon_64.png'):
        p = os.path.join(ASSETS_DIR, name)
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()


def _load_logo_pixmap(max_w: int = 280, max_h: int = 140) -> QPixmap:
    """HD monitor logo with transparent background (exact brand mark)."""
    for name in ('mbt_logo_hd.png', 'mbt_icon_256.png', 'mbt_icon.png'):
        p = os.path.join(ASSETS_DIR, name)
        if not os.path.exists(p):
            continue
        pm = QPixmap(p)
        if pm.isNull():
            continue
        return pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QPixmap()


def _make_logo_label(max_w: int = 280, max_h: int = 140) -> QLabel:
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet("background:transparent; border:none;")
    pm = _load_logo_pixmap(max_w, max_h)
    if not pm.isNull():
        lbl.setPixmap(pm)
    else:
        lbl.setText("MBT")
        lbl.setObjectName("logoText")
    return lbl


# â”€â”€ Signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class AppSignals(QObject):
    connection_changed = pyqtSignal(bool)
    sync_status        = pyqtSignal(str)
    update_available   = pyqtSignal(str, str)   # version, notes
    update_ready       = pyqtSignal(str, str)   # installer_path, version
    force_update       = pyqtSignal(str, str)   # version, reason


# â”€â”€ Login Dialog â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class LoginDialog(QDialog):
    def __init__(self, api: APIClient, icon: QIcon):
        super().__init__()
        self.api       = api
        self.user_data = None
        self.setWindowTitle("MBT POS")
        self.setWindowIcon(icon)
        self.setFixedSize(440, 540)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # Always use live ThemeManager stylesheet (Manrope + current palette)
        from desktop.utils.theme import MBT_STYLESHEET as _ss
        self.setStyleSheet(_ss)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Banner â€” exact HD logo (transparent, no black/white plate)
        banner = QWidget()
        banner.setObjectName("loginBrand")
        banner.setFixedHeight(210)
        banner.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {C['app']}, stop:1 {C['card']});"
            f"border-bottom: 2px solid {C['gold']};"
        )
        bl = QVBoxLayout(banner)
        bl.setAlignment(Qt.AlignCenter)
        bl.setSpacing(6)

        logo  = _make_logo_label(300, 150)
        brand = QLabel("MugoByte Technologies")
        brand.setObjectName("loginSubtitle")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet(
            f"color:{C['gold']}; font-size:12px; font-weight:600; "
            f"letter-spacing:1px; background:transparent;")
        bl.addWidget(logo)
        bl.addWidget(brand)
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
        self._msg.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent;")

        self._u = QLineEdit(); self._u.setObjectName("loginInput")
        self._u.setPlaceholderText("Username")
        self._u.setMinimumHeight(48)

        self._p = QLineEdit(); self._p.setObjectName("loginInput")
        self._p.setPlaceholderText("Password")
        self._p.setEchoMode(QLineEdit.Password)
        self._p.setMinimumHeight(48)
        self._p.returnPressed.connect(self._login)
        self._u.returnPressed.connect(self._p.setFocus)

        # Password visibility toggle (eye)
        self._eye = QPushButton("Show")
        self._eye.setObjectName("loginEyeBtn")
        self._eye.setFixedSize(56, 48)
        self._eye.setCursor(Qt.PointingHandCursor)
        self._eye.setToolTip("Show / hide password")
        self._eye.setCheckable(True)
        self._eye.toggled.connect(self._toggle_password)
        self._eye.setStyleSheet(
            f"QPushButton#loginEyeBtn {{ background:{C['card2']}; color:{C['text2']};"
            f" border:1px solid {C['border2']}; border-radius:8px; font-size:16px; }}"
            f"QPushButton#loginEyeBtn:hover {{ color:{C['gold']}; border-color:{C['gold']}; }}"
            f"QPushButton#loginEyeBtn:checked {{ color:{C['gold']}; border-color:{C['gold']}; }}")

        pw_row = QHBoxLayout(); pw_row.setSpacing(8); pw_row.setContentsMargins(0, 0, 0, 0)
        pw_row.addWidget(self._p, 1)
        pw_row.addWidget(self._eye)

        self._btn = QPushButton("SIGN IN")
        self._btn.setObjectName("loginBtn")
        self._btn.setFixedHeight(52)
        self._btn.setMinimumWidth(200)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._login)
        # Force visible gold button (QSS alone can fail under Fusion + transparent parents)
        gold_fg = C.get('gold_fg', '#0A0F1A')
        self._btn.setStyleSheet(
            f"QPushButton#loginBtn {{ background:{C['gold']}; color:{gold_fg};"
            f" border:none; border-radius:8px; font-size:15px; font-weight:800;"
            f" letter-spacing:2px; padding:12px; min-height:48px; }}"
            f"QPushButton#loginBtn:hover {{ background:{C['gold_lt']}; color:{gold_fg}; }}"
            f"QPushButton#loginBtn:pressed {{ background:{C['gold_dk']}; color:{gold_fg}; }}"
            f"QPushButton#loginBtn:disabled {{ background:{C['border2']}; color:{C['muted']}; }}")

        foot = QLabel("Powered by MugoByte Technologies  \u00b7  mugobyte.com")
        foot.setObjectName("loginFooter")
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet(
            f"color:{C['text2']}; font-size:11px; background:transparent;")

        fl.addWidget(self._msg)
        fl.addWidget(self._u)
        fl.addLayout(pw_row)
        fl.addWidget(self._btn)
        fl.addStretch()
        fl.addWidget(foot)
        root.addWidget(form)

    def _toggle_password(self, show: bool):
        self._p.setEchoMode(QLineEdit.Normal if show else QLineEdit.Password)
        self._eye.setText("Hide" if show else "Show")
    def _login(self):
        # Username is case-insensitive (normalized in API / backend)
        u, p = self._u.text().strip(), self._p.text()
        if not u or not p:
            self._set_msg("Enter username and password", err=True); return

        self._btn.setText("Signing in\u2026"); self._btn.setEnabled(False)
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


# â”€â”€ Main Window â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class MainWindow(QMainWindow):
    def __init__(self, user_data: dict, api: APIClient, icon: QIcon):
        super().__init__()
        self.user_data = user_data
        self.api       = api
        self.signals   = AppSignals()
        self._svc_net  = None
        self._svc_lic  = None
        self._svc_diag = None
        self._conn_ok  = True
        # Updater state must exist before any timer/callback reads it.
        # _start_services runs at 500ms and can take >1.5s; _restore_pending_update
        # fires at 2000ms and previously raced before these attrs were set.
        self._updater = None
        self._pending_update_version = ''
        self._pending_installer_path = None
        self._pending_update_notes = ''

        self.setWindowTitle("MBT POS - MugoByte Technologies")
        self.setWindowIcon(icon)
        self.setMinimumSize(1200, 720)
        self.setStyleSheet(MBT_STYLESHEET)
        self.showMaximized()

        self._db_path = get_db_path()

        # UI first â€” services second (never block render)
        self._build_ui()
        self._build_tabs()

        self.signals.connection_changed.connect(self._on_conn)
        self.signals.sync_status.connect(self._on_sync)
        self.signals.update_available.connect(self._ui_update_available)
        self.signals.update_ready.connect(self._ui_update_ready)
        self.signals.force_update.connect(self._ui_force_update)

        first = next(iter(self._nav), 'dashboard')
        self._goto(first)

        # Wire dashboard quick-action navigation
        if 'dashboard' in self._tabs:
            dash = self._tabs['dashboard']
            if hasattr(dash, 'navigate'):
                dash.navigate.connect(self._goto)
            if hasattr(dash, 'theme_changed'):
                dash.theme_changed.connect(self._apply_app_theme)

        # Wire sale_completed â†’ refresh dashboard + reports immediately
        if 'sales' in self._tabs:
            sales_tab = self._tabs['sales']
            if hasattr(sales_tab, 'sale_completed'):
                if 'dashboard' in self._tabs and hasattr(self._tabs['dashboard'], '_load'):
                    sales_tab.sale_completed.connect(self._tabs['dashboard']._load)
                if 'reports' in self._tabs and hasattr(self._tabs['reports'], 'refresh'):
                    sales_tab.sale_completed.connect(self._tabs['reports'].refresh)
            if hasattr(sales_tab, 'theme_changed'):
                sales_tab.theme_changed.connect(self._apply_app_theme)

        QTimer.singleShot(0, self._load_saved_theme)

        # Start services after a short delay so UI paints immediately
        QTimer.singleShot(500, self._start_services)
        QTimer.singleShot(1500, self._initial_conn_check)
        QTimer.singleShot(2000, self._restore_pending_update)

    # â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _cfg(self) -> dict:
        try:
            return self.api.get('/api/settings') or {}
        except Exception:
            return {}

    # â”€â”€ Background services â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        self._pending_installer_path = None
        self._pending_update_notes = ''
        try:
            from backend.updater import UpdateChecker
            online_fn = lambda: getattr(
                getattr(self, '_svc_net', None), 'is_connected', False)
            self._updater = UpdateChecker(APP_VERSION, is_online_getter=online_fn)
            self._updater.on_update_available = self._on_update_available
            self._updater.on_download_ready   = self._on_update_ready
            self._updater.on_force_required   = self._on_force_update
            self._updater.on_install_failed   = self._on_install_failed
            self._updater.on_download_failed  = self._on_download_failed
            self._updater.start()
        except Exception as e:
            log.warning(f"UpdateChecker: {e}")

        try:
            from backend.cloudflare_setup import start_auto_cloudflare
            start_auto_cloudflare(
                on_done=self._on_auto_cloudflare_done,
                on_failed=self._on_auto_cloudflare_failed,
            )
        except Exception as e:
            log.warning(f"Auto Cloudflare: {e}")

        # Pass license service to license tab if it exists
        if 'license' in self._tabs and self._svc_lic:
            try:
                self._tabs['license'].license_service = self._svc_lic
            except Exception:
                pass

    def _on_license_state(self, state: str, data: dict):
        """
        Called immediately when LicenseService detects a state change â€”
        including from remote commands (revoke, extend, activate).
        Runs on the license service thread â†’ must use QTimer to touch UI.
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
                    STATE_TAMPERED:  "WARNING: License Tampered\n\nThis license has been flagged. The application will now close.",
                    STATE_INACTIVE:  "License Revoked\n\nYour license has been revoked by MugoByte Technologies.\nPlease contact support to renew.",
                    STATE_EXPIRED:   "License Expired\n\nYour subscription has expired.\nPlease contact MugoByte Technologies to renew.",
                }.get(state, "License invalid.")

                QMessageBox.critical(self, 'MBT POS - License', reason)

                if state in (STATE_TAMPERED, STATE_INACTIVE):
                    # Hard close â€” no way to continue
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
        self.signals.update_available.emit(version, notes or '')

    def _on_update_ready(self, installer_path, version):
        self._pending_installer_path = installer_path
        self._pending_update_version = version
        log.info(f"Update downloaded: v{version}")
        self.signals.update_ready.emit(installer_path, version)

    def _on_force_update(self, version, reason):
        self._pending_update_version = version
        log.warning(f"Force update required: v{version}")
        self.signals.force_update.emit(version, reason or '')

    def _on_install_failed(self, version, reason):
        def _show():
            title = 'Update Could Not Install'
            msg = reason or ''
            if msg and '\n\n' in msg:
                head, body = msg.split('\n\n', 1)
                if len(head) < 60 and not head.startswith('Update v'):
                    title = head
                    msg = body
            QMessageBox.warning(
                self, title,
                f'Update v{version} could not install.\n\n{msg}')
        QTimer.singleShot(3000, _show)

    def _on_download_failed(self, version, title, reason):
        def _show():
            btn = getattr(self, '_update_btn', None)
            if btn:
                btn.setText(f"  Downloading v{version}...  ")
                btn.show()
            QMessageBox.warning(
                self, title or 'Update Download',
                reason or 'The update is still downloading in the background.')
        QTimer.singleShot(0, _show)

    def _ui_update_available(self, version, notes):
        self._pending_update_version = version
        self._pending_update_notes = notes
        btn = getattr(self, '_update_btn', None)
        if btn:
            btn.setText(f"  Downloading v{version}...  ")
            btn.show()
            btn.raise_()

    def _ui_update_ready(self, installer_path, version):
        self._pending_installer_path = installer_path
        self._pending_update_version = version
        btn = getattr(self, '_update_btn', None)
        if btn:
            btn.setText(f"  Update v{version}  ")
            btn.show()
            btn.raise_()

    def _ui_force_update(self, version, reason):
        QMessageBox.warning(
            self, 'Update Required',
            reason or f'Please update to v{version} to continue using MBT POS.')

    def _restore_pending_update(self):
        """If a update was downloaded while UI was not ready, show the button."""
        import glob
        import re
        from backend.updater import _version_gt, BLOCKED_VERSIONS

        search_roots = [tempfile.gettempdir()]
        try:
            search_roots.append(os.path.join(PROJECT_ROOT, 'updates'))
        except Exception:
            pass

        pending = getattr(self, '_pending_installer_path', None)
        if pending and os.path.isfile(pending):
            ver = getattr(self, '_pending_update_version', None) or '?'
            try:
                if ver not in BLOCKED_VERSIONS and _version_gt(ver, APP_VERSION):
                    self._ui_update_ready(pending, ver)
                else:
                    try:
                        os.remove(pending)
                    except Exception:
                        pass
            except Exception:
                pass
            return

        best = None
        best_ver = ''
        for root in search_roots:
            pattern = os.path.join(root, 'MBT_POS_Setup_v*.exe')
            for path in glob.glob(pattern):
                m = re.search(r'_v([\d.]+)\.exe$', path, re.I)
                if not m:
                    continue
                ver = m.group(1)
                try:
                    if ver in BLOCKED_VERSIONS or not _version_gt(ver, APP_VERSION):
                        try:
                            os.remove(path)
                            log.info(f'Removed stale cached installer v{ver}')
                        except Exception:
                            pass
                        continue
                    if os.path.getsize(path) > 1_000_000:
                        if not best_ver or _version_gt(ver, best_ver):
                            best, best_ver = path, ver
                except Exception:
                    pass
        if best:
            # Discard known-bad onefile installers (v2.3.5 broke silent updates)
            if best_ver in BLOCKED_VERSIONS or os.path.getsize(best) > 60_000_000:
                try:
                    os.remove(best)
                    log.warning(f"Removed bad cached installer v{best_ver}")
                except Exception:
                    pass
                return
            log.info(f"Restored pending update: v{best_ver} at {best}")
            self._ui_update_ready(best, best_ver)


    def _on_update_btn_clicked(self):
        version = getattr(self, '_pending_update_version', None) or '?'
        path    = getattr(self, '_pending_installer_path', None) or ''
        notes   = getattr(self, '_pending_update_notes', None) or ''
        if not path or not os.path.isfile(path):
            QMessageBox.warning(
                self, 'Update',
                'The update file is not ready yet. Try again in a few minutes.')
            return
        dlg = QMessageBox(self)
        dlg.setWindowTitle(f'Update v{version} Ready')
        dlg.setText(
            f'<b>Version {version} is ready to install.</b><br><br>'
            'The app will close for about 30 seconds, then reopen automatically.<br>'
            '<b>Windows will ask for permission - click Yes.</b><br>'
            'If you see "Windows protected your PC", click <b>More info</b> '
            'then <b>Run anyway</b>.<br>'
            'Do not start MBT POS manually during the update.<br><br>'
            'Your shop data will not be affected.')
        if notes:
            dlg.setDetailedText(notes[:600])
        dlg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dlg.button(QMessageBox.Ok).setText('Install Now')
        dlg.button(QMessageBox.Cancel).setText('Later')
        if dlg.exec_() != QMessageBox.Ok:
            return
        try:
            if self._updater:
                ok, err = self._updater.install_and_restart(path)
                if not ok:
                    QMessageBox.warning(self, 'Update Blocked', err)
                    return
                self._pending_installer_path = getattr(
                    self._updater, '_installer_path', path) or path
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

    # â”€â”€ UI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
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
        # Lovable AppShell sidebar â€” 228px, logo + brand, gold active rail
        sb = QWidget(); sb.setObjectName("sidebar"); sb.setFixedWidth(228)
        sl = QVBoxLayout(sb); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)

        # Logo block â€” HD mark + MBT / POS SYSTEM text (Lovable)
        lw = QWidget(); lw.setObjectName("sidebarLogo"); lw.setFixedHeight(76)
        ll = QHBoxLayout(lw)
        ll.setContentsMargins(14, 10, 14, 10); ll.setSpacing(10)
        ll.setAlignment(Qt.AlignVCenter)
        logo = _make_logo_label(44, 44)
        logo.setFixedSize(48, 48)
        brand = QVBoxLayout(); brand.setSpacing(0); brand.setContentsMargins(0, 0, 0, 0)
        t1 = QLabel("MBT"); t1.setObjectName("sidebarLogoText")
        t2 = QLabel("POS SYSTEM"); t2.setObjectName("sidebarLogoSub")
        brand.addWidget(t1); brand.addWidget(t2)
        ll.addWidget(logo); ll.addLayout(brand, 1)
        sl.addWidget(lw)

        sl.addSpacing(6)

        # Navigation â€” scrollable when many tabs / short displays
        self._nav = {}
        perms = self.user_data.get('user', {}).get('tab_permissions', [])
        role  = self.user_data.get('user', {}).get('role', '')
        tabs  = [
            ('dashboard',   '\u229e',  'Dashboard'),
            ('sales',       '\u2295',  'Point of Sale'),
            ('inventory',   '\u25a4',  'Inventory'),
            ('debt',        '\U0001f4b0', 'Debt Management'),
            ('reports',     '\u25a6',  'Reports'),
            ('notes',       '\u2261',  'Notes'),
            ('admin',       '\u229b',  'Users && Access'),
            ('settings',    '\u2699',  'Settings'),
            ('security',    '\U0001f510', 'Security'),
            ('license',     '\u25c8',  'License'),
            ('diagnostics', '\u2692',  'Diagnostics'),
        ]
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        nav_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        nav_body = QWidget()
        nav_body.setStyleSheet("background:transparent;")
        nv = QVBoxLayout(nav_body)
        nv.setContentsMargins(0, 4, 0, 4)
        nv.setSpacing(1)
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
        ul = QVBoxLayout(uw); ul.setContentsMargins(14, 12, 14, 12); ul.setSpacing(2)
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
        bar = QWidget(); bar.setObjectName("topbar"); bar.setFixedHeight(56)
        lay = QHBoxLayout(bar); lay.setContentsMargins(24, 0, 20, 0); lay.setSpacing(10)

        self._page_title = QLabel("Dashboard"); self._page_title.setObjectName("pageTitle")
        lay.addWidget(self._page_title); lay.addStretch()

        # Connection badge
        self._conn_lbl = QLabel("\u25cf Online")
        self._conn_lbl.setObjectName("connBadge")
        self._conn_lbl.setStyleSheet(
            f"color:{C['ok']}; font-size:12px; font-weight:600; background:transparent;")
        lay.addWidget(self._conn_lbl)

        self._sync_lbl = QLabel(""); self._sync_lbl.setObjectName("syncLbl")
        lay.addWidget(self._sync_lbl)

        self._update_btn = QPushButton("  Update  ")
        self._update_btn.setObjectName("updateBtn")
        self._update_btn.setCursor(Qt.PointingHandCursor)
        gold_fg = C.get('gold_fg', '#0A0F1A')
        self._update_btn.setStyleSheet(
            f"QPushButton#updateBtn {{ background:{C['gold']}; color:{gold_fg};"
            f" font-weight:700; font-size:12px; border:none; border-radius:8px;"
            f" padding:6px 12px; }}"
            f"QPushButton#updateBtn:hover {{ background:{C['gold_lt']}; }}"
        )
        self._update_btn.clicked.connect(self._on_update_btn_clicked)
        self._update_btn.hide()
        lay.addWidget(self._update_btn)

        ref_btn = QPushButton("\u21bb  Refresh"); ref_btn.setObjectName("refreshBtn")
        ref_btn.setCursor(Qt.PointingHandCursor); ref_btn.clicked.connect(self._manual_refresh)
        lay.addWidget(ref_btn)

        from desktop.utils.widgets import ThemeToggleBtn
        self._theme_btn = ThemeToggleBtn(on_toggle=self._on_theme_change)
        lay.addWidget(self._theme_btn)

        self._clk = QLabel(); self._clk.setObjectName("clockLbl")
        lay.addWidget(self._clk)

        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000); self._tick()
        return bar

    def _build_statusbar(self):
        bar = QWidget(); bar.setObjectName("statusBar"); bar.setFixedHeight(36)
        lay = QHBoxLayout(bar); lay.setContentsMargins(24, 0, 24, 0)
        l = QLabel("MBT POS \u00b7 MugoByte Technologies"); l.setObjectName("statusLeft")
        runtime = "EXE" if getattr(sys, 'frozen', False) else "DEV"
        exe_name = os.path.basename(sys.executable) if getattr(sys, 'frozen', False) else "python"
        r = QLabel(f"v{APP_VERSION} \u00b7 {APP_BUILD_TAG} \u00b7 {runtime}:{exe_name}")
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

    # â”€â”€ Navigation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Theme â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_theme_change(self, is_light: bool):
        """Called after ThemeToggleBtn already applied ThemeManager.toggle()."""
        self._sync_theme_ui(is_light, persist=True)

    def _load_saved_theme(self):
        try:
            cfg = self._cfg() or {}
            theme = str(cfg.get('theme') or cfg.get('ui_theme') or 'dark').lower()
            if theme == 'light':
                self._apply_app_theme(True, persist=False)
        except Exception as e:
            log.warning(f'Load theme: {e}')

    def _apply_app_theme(self, is_light: bool, persist: bool = True):
        """Apply theme from dashboard / sales / saved preference."""
        self._sync_theme_ui(is_light, persist=persist)

    def _theme_overlay_show(self):
        """Blocking-feel-free progress cover while theme QSS + tabs retint."""
        if getattr(self, '_theme_overlay', None) is None:
            ov = QWidget(self)
            ov.setObjectName('mbtThemeOverlay')
            ov.setStyleSheet(
                "QWidget#mbtThemeOverlay { background: rgba(8, 13, 24, 160); }"
                "QLabel#mbtThemeOverlayLbl { color: #EEF2FC; font-size: 15px; font-weight: 700;"
                " background: transparent; }"
                "QProgressBar#mbtThemeOverlayBar { background: #0F1A2E; border: 1px solid #18283E;"
                " border-radius: 6px; height: 10px; text-align: center; }"
                "QProgressBar#mbtThemeOverlayBar::chunk { background: #F2A800; border-radius: 5px; }")
            lay = QVBoxLayout(ov)
            lay.setAlignment(Qt.AlignCenter)
            box = QWidget(); box.setFixedWidth(320)
            bl = QVBoxLayout(box); bl.setSpacing(12)
            lbl = QLabel('Switching theme...'); lbl.setObjectName('mbtThemeOverlayLbl')
            lbl.setAlignment(Qt.AlignCenter)
            bar = QProgressBar(); bar.setObjectName('mbtThemeOverlayBar')
            bar.setRange(0, 0)  # indeterminate — never looks frozen
            bar.setTextVisible(False)
            bar.setFixedHeight(12)
            bl.addWidget(lbl); bl.addWidget(bar)
            lay.addWidget(box)
            self._theme_overlay = ov
            self._theme_overlay_lbl = lbl
            self._theme_overlay_bar = bar
        self._theme_overlay.setGeometry(self.rect())
        self._theme_overlay.raise_()
        self._theme_overlay.show()
        QApplication.processEvents()
        return self._theme_overlay

    def _theme_overlay_hide(self):
        ov = getattr(self, '_theme_overlay', None)
        if ov is not None:
            ov.hide()

    def resizeEvent(self, event):
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        ov = getattr(self, '_theme_overlay', None)
        if ov is not None and ov.isVisible():
            ov.setGeometry(self.rect())

    def _sync_theme_ui(self, is_light: bool, persist: bool = True):
        """
        Fast theme switch:
        - show indeterminate progress overlay (no deadlock feel)
        - apply global QSS once
        - retint visible chrome + current tab only first
        - defer other tabs; never call tab.refresh() (data reload was the lag)
        """
        if getattr(self, '_theme_switching', False):
            return
        self._theme_switching = True
        try:
            self._theme_overlay_show()
            if hasattr(self, '_theme_overlay_lbl'):
                self._theme_overlay_lbl.setText(
                    'Switching to light...' if is_light else 'Switching to dark...')
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()

            ss = ThemeManager.apply(is_light)
            self.setStyleSheet(ss)
            QApplication.processEvents()

            if hasattr(self, '_theme_btn') and hasattr(self._theme_btn, '_refresh_theme'):
                self._theme_btn._refresh_theme()
            elif hasattr(self, '_theme_btn'):
                self._theme_btn.setText('Dark' if is_light else 'Light')

            self._refresh_chrome_styles()
            try:
                from desktop.utils.widgets import refresh_themed_widgets
                refresh_themed_widgets(self)
            except Exception as e:
                log.warning(f'theme widget refresh: {e}')
            QApplication.processEvents()

            # Current tab first (what the user sees)
            cur = self._stack.currentWidget() if hasattr(self, '_stack') else None
            cur_tid = None
            for tid, tab in getattr(self, '_tabs', {}).items():
                if tab is cur:
                    cur_tid = tid
                    break
            if cur_tid == 'dashboard' and hasattr(cur, 'set_light_mode'):
                cur.set_light_mode(is_light)
            elif cur_tid == 'sales':
                self._apply_sales_theme(is_light)
            elif cur is not None:
                if hasattr(cur, 'apply_theme'):
                    try: cur.apply_theme(is_light)
                    except Exception: pass
                elif hasattr(cur, 'set_light_mode'):
                    try: cur.set_light_mode(is_light)
                    except Exception: pass
            QApplication.processEvents()

            # Defer non-visible tabs so UI unlocks quickly
            pending = [
                (tid, tab) for tid, tab in getattr(self, '_tabs', {}).items()
                if tab is not cur
            ]
            self._theme_pending = pending
            self._theme_pending_light = is_light
            self._theme_persist = persist
            QTimer.singleShot(0, self._theme_apply_pending_tabs)
        except Exception as e:
            log.warning(f'theme sync: {e}')
            self._theme_switching = False
            QApplication.restoreOverrideCursor()
            self._theme_overlay_hide()

    def _theme_apply_pending_tabs(self):
        is_light = getattr(self, '_theme_pending_light', False)
        pending = getattr(self, '_theme_pending', []) or []
        # Apply a few tabs per tick to keep UI responsive
        batch = pending[:3]
        self._theme_pending = pending[3:]
        for tid, tab in batch:
            try:
                if tid == 'dashboard' and hasattr(tab, 'set_light_mode'):
                    tab.set_light_mode(is_light)
                elif tid == 'sales':
                    self._apply_sales_theme(is_light)
                elif hasattr(tab, 'apply_theme'):
                    tab.apply_theme(is_light)
                elif hasattr(tab, 'set_light_mode'):
                    tab.set_light_mode(is_light)
            except Exception:
                pass
            QApplication.processEvents()

        if self._theme_pending:
            QTimer.singleShot(0, self._theme_apply_pending_tabs)
            return

        # Done — do NOT call tab.refresh() (was reloading DB and freezing UI)
        if getattr(self, '_theme_persist', False):
            threading.Thread(
                target=self._save_theme_pref,
                args=(is_light,),
                daemon=True,
                name='SaveTheme',
            ).start()
        QApplication.restoreOverrideCursor()
        self._theme_overlay_hide()
        self._theme_switching = False

    def _save_theme_pref(self, is_light: bool):
        try:
            self.api.update_settings({
                'theme': 'light' if is_light else 'dark',
                'ui_theme': 'light' if is_light else 'dark',
            })
        except Exception as e:
            log.warning(f'Save theme: {e}')

    def _apply_sales_theme(self, is_light: bool):
        sales = self._tabs.get('sales')
        if not sales:
            return
        try:
            from desktop.utils.pos_light_theme import apply_light, apply_dark
            if is_light:
                apply_light(sales)
            else:
                apply_dark(sales)
            if hasattr(sales, '_theme_btn'):
                sales._theme_btn.setText('Dark' if is_light else 'Light')
            if getattr(sales, 'cart', None) is not None:
                sales._refresh_cart()
        except Exception as e:
            log.warning(f'Sales theme: {e}')

    def _refresh_chrome_styles(self):
        if hasattr(self, '_conn_lbl'):
            self._conn_lbl.setStyleSheet(
                f"color:{C['ok'] if self._conn_ok else C['err']}; "
                f"font-size:13px; font-weight:700; background:transparent;")
        if hasattr(self, '_update_btn'):
            gold_fg = C.get('gold_fg', '#0A0F1A')
            self._update_btn.setStyleSheet(
                f"QPushButton#updateBtn {{ background:{C['gold']}; color:{gold_fg};"
                f" font-weight:700; font-size:13px; border:none; border-radius:6px;"
                f" padding:6px 14px; }}"
                f"QPushButton#updateBtn:hover {{ background:{C['gold_lt']}; }}")

    # â”€â”€ Status slots â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_conn(self, ok: bool):
        self._conn_ok = ok
        self._conn_lbl.setText("\u25cf Online" if ok else "\u25cf Offline")
        self._conn_lbl.setStyleSheet(
            f"color:{C['ok'] if ok else C['err']}; font-size:13px; font-weight:700;")
        if ok:
            try:
                from backend.cloudflare_setup import (
                    needs_auto_cloudflare_setup, run_auto_cloudflare_setup,
                )
                need, _ = needs_auto_cloudflare_setup()
                if need:
                    threading.Thread(
                        target=run_auto_cloudflare_setup,
                        daemon=True, name='AutoCloudflareReconnect',
                    ).start()
            except Exception:
                pass

    def _on_auto_cloudflare_done(self, result: dict):
        dom = result.get('domain', '')
        log.info('Remote dashboard ready: %s', dom or 'ok')
        def _ui():
            if 'settings' in self._tabs and hasattr(self._tabs['settings'], '_refresh_cf_status'):
                try:
                    self._tabs['settings']._refresh_cf_status()
                except Exception:
                    pass
        QTimer.singleShot(0, _ui)

    def _on_auto_cloudflare_failed(self, result: dict):
        role = self.user_data.get('user', {}).get('role', '')
        if role not in ('admin', 'superadmin'):
            return
        err = result.get('error') or ''
        if isinstance(result.get('errors'), list) and result['errors']:
            err = str(result['errors'][0])
        if not err:
            return
        def _show():
            QMessageBox.warning(
                self, 'Remote Dashboard Setup',
                'MBT POS could not set up the remote dashboard automatically.\n\n'
                f'{err}\n\n'
                'It will retry every 30 minutes. Check Settings -> Remote Web Dashboard.')
        QTimer.singleShot(0, _show)

    def _on_sync(self, s: str):
        self._sync_lbl.setText(
            {'syncing':'Syncing', 'synced':'Synced', 'failed':'Failed', 'idle':'Idle'}.get(s, s))

    def _tick(self):
        now = datetime.now()
        self._clk.setText(
            f"{now.strftime('%a %d %b')}   {now.strftime('%H:%M:%S')}")

    def _manual_refresh(self):
        self._sync_lbl.setText("Checking...")
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

    # â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _logout(self):
        if QMessageBox.question(self, "Sign Out", "Sign out of MBT POS?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._stop_services()
            self.hide()
            _show_login(self.api)

    def closeEvent(self, event):
        self._stop_services(); event.accept()


# â”€â”€ Bootstrap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            log.warning("Web dashboard could not start â€” desktop POS still works")
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
    # Single instance â€” prevent duplicate POS during update restart
    try:
        from backend.updater import acquire_single_instance
        if not acquire_single_instance():
            sys.exit(0)
    except Exception:
        pass

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
    # Fusion makes QSS colors/borders reliable on Windows (native style ignores many rules)
    try:
        app.setStyle('Fusion')
    except Exception:
        pass
    install_crash_handler()
    app.setApplicationName("MBT POS")
    app.setOrganizationName("MugoByte Technologies")
    # Manrope when bundled; Segoe UI fallback â€” never crash if missing
    fam = ensure_fonts()
    try:
        # Prefer first quoted family from font_stack
        primary = fam.split(',')[0].strip().strip("'\"") or 'Segoe UI'
        app.setFont(QFont(primary, 13))
    except Exception:
        app.setFont(QFont('Segoe UI', 13))
    # Rebuild QSS now that fonts (and QApp) are ready
    app.setStyleSheet(ThemeManager.apply(False))

    icon = _load_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Splash screen
    splash = SplashScreen()
    splash.show()
    splash.set_status("Starting MBT POS...", 5)
    QApplication.processEvents()

    splash.set_status("Initialising database...", 30)
    QApplication.processEvents()
    # Init DB directly â€” no HTTP server needed
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

    splash.set_status("Starting web dashboard...", 55)
    QApplication.processEvents()
    _start_web_dashboard()

    splash.set_status("Loading interface...", 80)
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
