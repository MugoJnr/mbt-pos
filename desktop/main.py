"""
MBT POS ? Main Application Entry Point
MugoByte Technologies | mugobyte.com

All services run as internal threads ? no terminal or CMD windows.
"""
import sys
import os
import threading
import time
import tempfile
import logging
from datetime import datetime

# ?? Path setup (single source: mbt_paths) ?????????????????????????????????????
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
APP_BUILD_TAG = "PROD-2026-07-17-v2.3.50"
APP_VERSION   = "2.3.50"   # must match GitHub release tag vX.Y.Z


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
    MBT_STYLESHEET, C, ThemeManager, is_light_mode, ensure_fonts, qss_alpha,
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
_main_window = None   # global ref ? prevents GC
_web_svc     = None   # embedded Flask dashboard (app lifetime)


# ?? Icon / logo loaders ????????????????????????????????????????????????????????
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


# ?? Signals ????????????????????????????????????????????????????????????????????
class AppSignals(QObject):
    connection_changed = pyqtSignal(bool)
    sync_status        = pyqtSignal(str)
    update_available   = pyqtSignal(str, str)   # version, notes
    update_ready       = pyqtSignal(str, str)   # installer_path, version
    force_update       = pyqtSignal(str, str)   # version, reason


# ?? Login Dialog ???????????????????????????????????????????????????????????????
class LoginDialog(QDialog):
    def __init__(self, api: APIClient, icon: QIcon):
        super().__init__()
        self.api       = api
        self.user_data = None
        self.setWindowTitle("MBT POS")
        self.setWindowIcon(icon)
        self.setFixedSize(460, 580)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # Inherit live QApplication ThemeManager sheet — do NOT freeze a copy
        # (stale DARK QSS on the dialog caused light-mode hybrid on login).
        self.setStyleSheet('')
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Brand banner ? gradient wash + crisp logo
        banner = QWidget()
        banner.setObjectName("loginBrand")
        banner.setFixedHeight(200)
        banner.setStyleSheet(
            f"QWidget#loginBrand {{"
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {C['app']}, stop:0.45 {C['card']}, stop:1 {C['surface']});"
            f"border-bottom: 2px solid {C['gold']};"
            f"}}"
        )
        bl = QVBoxLayout(banner)
        bl.setAlignment(Qt.AlignCenter)
        bl.setContentsMargins(24, 18, 24, 14)
        bl.setSpacing(4)

        logo = _make_logo_label(280, 130)
        brand = QLabel("MugoByte Technologies")
        brand.setObjectName("loginSubtitle")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet(
            f"color:{C['gold']}; font-size:13px; font-weight:700; "
            f"letter-spacing:1.5px; background:transparent;")
        tag = QLabel("Modern retail checkout")
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet(
            f"color:{C['text2']}; font-size:11px; font-weight:500; "
            f"background:transparent;")
        bl.addWidget(logo)
        bl.addWidget(brand)
        bl.addWidget(tag)
        root.addWidget(banner)

        # Form card
        form = QWidget()
        form.setObjectName("loginForm")
        form.setStyleSheet(f"QWidget#loginForm {{ background:{C['surface']}; }}")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(40, 28, 40, 28)
        fl.setSpacing(14)

        self._msg = QLabel("Sign in to continue")
        self._msg.setObjectName("loginStatus")
        self._msg.setAlignment(Qt.AlignCenter)
        self._msg.setWordWrap(True)
        self._msg.setStyleSheet(
            f"color:{C['text2']}; font-size:14px; font-weight:600; background:transparent;")

        field_ss = (
            f"QLineEdit#loginInput {{"
            f" background:{C['input']}; color:{C['text']};"
            f" border:1.5px solid {C['border2']}; border-radius:12px;"
            f" padding:10px 14px; font-size:15px; font-weight:600; }}"
            f"QLineEdit#loginInput:focus {{"
            f" border-color:{C['gold']}; background:{C['card']}; }}"
        )

        self._u = QLineEdit(); self._u.setObjectName("loginInput")
        self._u.setPlaceholderText("Username")
        self._u.setMinimumHeight(50)
        self._u.setStyleSheet(field_ss)

        self._p = QLineEdit(); self._p.setObjectName("loginInput")
        self._p.setPlaceholderText("Password")
        self._p.setEchoMode(QLineEdit.Password)
        self._p.setMinimumHeight(50)
        self._p.setStyleSheet(field_ss)
        self._p.returnPressed.connect(self._login)
        self._u.returnPressed.connect(self._p.setFocus)

        self._eye = QPushButton("Show")
        self._eye.setObjectName("loginEyeBtn")
        self._eye.setFixedSize(64, 50)
        self._eye.setCursor(Qt.PointingHandCursor)
        self._eye.setToolTip("Show / hide password")
        self._eye.setCheckable(True)
        self._eye.toggled.connect(self._toggle_password)
        self._eye.setStyleSheet(
            f"QPushButton#loginEyeBtn {{ background:{C['card2']}; color:{C['text2']};"
            f" border:1.5px solid {C['border2']}; border-radius:12px;"
            f" font-size:13px; font-weight:700; }}"
            f"QPushButton#loginEyeBtn:hover {{ color:{C['gold']}; border-color:{C['gold']}; }}"
            f"QPushButton#loginEyeBtn:checked {{ color:{C['gold']}; border-color:{C['gold']}; }}")

        pw_row = QHBoxLayout(); pw_row.setSpacing(10); pw_row.setContentsMargins(0, 0, 0, 0)
        pw_row.addWidget(self._p, 1)
        pw_row.addWidget(self._eye)

        self._btn = QPushButton("SIGN IN")
        self._btn.setObjectName("loginBtn")
        self._btn.setFixedHeight(54)
        self._btn.setMinimumWidth(200)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._login)
        gold_fg = C.get('gold_fg', '#0A0F1A')
        self._btn.setStyleSheet(
            f"QPushButton#loginBtn {{ background:{C['gold']}; color:{gold_fg};"
            f" border:none; border-radius:14px; font-size:16px; font-weight:800;"
            f" letter-spacing:1.5px; padding:12px; min-height:50px; }}"
            f"QPushButton#loginBtn:hover {{ background:{C['gold_lt']}; color:{gold_fg}; }}"
            f"QPushButton#loginBtn:pressed {{ background:{C['gold_dk']}; color:{gold_fg}; }}"
            f"QPushButton#loginBtn:disabled {{ background:{C['border2']}; color:{C['muted']}; }}")

        foot = QLabel(f"Powered by MugoByte  \u00b7  mugobyte.com  \u00b7  v{APP_VERSION}")
        foot.setObjectName("loginFooter")
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet(
            f"color:{C['muted']}; font-size:11px; background:transparent;")

        fl.addWidget(self._msg)
        fl.addSpacing(4)
        fl.addWidget(self._u)
        fl.addLayout(pw_row)
        fl.addSpacing(6)
        fl.addWidget(self._btn)
        fl.addStretch()
        fl.addWidget(foot)
        root.addWidget(form)
        self._login_banner = banner
        self._login_brand = brand
        self._login_tag = tag
        self._login_form = form
        self._login_foot = foot
        self.refresh_theme()

    def refresh_theme(self):
        """Re-apply live ThemeManager colors to login chrome (no frozen dark copy)."""
        banner = getattr(self, '_login_banner', None)
        if banner is not None:
            banner.setAttribute(Qt.WA_StyledBackground, True)
            banner.setStyleSheet(
                f"QWidget#loginBrand {{"
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f"stop:0 {C['app']}, stop:0.45 {C['card']}, stop:1 {C['surface']});"
                f"border-bottom: 2px solid {C['gold']};"
                f"}}"
            )
        brand = getattr(self, '_login_brand', None)
        if brand is not None:
            brand.setStyleSheet(
                f"color:{C['gold']}; font-size:13px; font-weight:700; "
                f"letter-spacing:1.5px; background:transparent;")
        tag = getattr(self, '_login_tag', None)
        if tag is not None:
            tag.setStyleSheet(
                f"color:{C['text2']}; font-size:11px; font-weight:500; "
                f"background:transparent;")
        form = getattr(self, '_login_form', None)
        if form is not None:
            form.setAttribute(Qt.WA_StyledBackground, True)
            form.setStyleSheet(f"QWidget#loginForm {{ background:{C['surface']}; }}")
        field_ss = (
            f"QLineEdit#loginInput {{"
            f" background:{C['input']}; color:{C['text']};"
            f" border:1.5px solid {C['border2']}; border-radius:12px;"
            f" padding:10px 14px; font-size:15px; font-weight:600; }}"
            f"QLineEdit#loginInput:focus {{"
            f" border-color:{C['gold']}; background:{C['card']}; }}"
        )
        for w in (getattr(self, '_u', None), getattr(self, '_p', None)):
            if w is not None:
                w.setStyleSheet(field_ss)
        eye = getattr(self, '_eye', None)
        if eye is not None:
            eye.setStyleSheet(
                f"QPushButton#loginEyeBtn {{ background:{C['card2']}; color:{C['text2']};"
                f" border:1.5px solid {C['border2']}; border-radius:12px;"
                f" font-size:13px; font-weight:700; }}"
                f"QPushButton#loginEyeBtn:hover {{ color:{C['gold']}; border-color:{C['gold']}; }}"
                f"QPushButton#loginEyeBtn:checked {{ color:{C['gold']}; border-color:{C['gold']}; }}")
        btn = getattr(self, '_btn', None)
        if btn is not None:
            gold_fg = C.get('gold_fg', '#0A0F1A')
            btn.setStyleSheet(
                f"QPushButton#loginBtn {{ background:{C['gold']}; color:{gold_fg};"
                f" border:none; border-radius:14px; font-size:16px; font-weight:800;"
                f" letter-spacing:1.5px; padding:12px; min-height:50px; }}"
                f"QPushButton#loginBtn:hover {{ background:{C['gold_lt']}; color:{gold_fg}; }}"
                f"QPushButton#loginBtn:pressed {{ background:{C['gold_dk']}; color:{gold_fg}; }}"
                f"QPushButton#loginBtn:disabled {{ background:{C['border2']}; color:{C['muted']}; }}")
        foot = getattr(self, '_login_foot', None)
        if foot is not None:
            foot.setStyleSheet(
                f"color:{C['muted']}; font-size:11px; background:transparent;")
        msg = getattr(self, '_msg', None)
        if msg is not None and not msg.text().startswith('Invalid') and 'Could not' not in msg.text():
            msg.setStyleSheet(
                f"color:{C['text2']}; font-size:14px; font-weight:600; background:transparent;")

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


# ?? Main Window ????????????????????????????????????????????????????????????????
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
        # Do NOT freeze a copy of MBT_STYLESHEET on the window — it blocks ThemeManager
        # light/dark updates (QApp sheet never reaches #sidebar / #topbar). Inherit QApp.
        self.setStyleSheet('')

        self._db_path = get_db_path()

        # Apply saved theme BEFORE building widgets. Re-applying light QSS after
        # 11 tabs exist re-polishes the whole tree and freezes Windows 25–80s
        # (Responding=False). Build once under the correct palette instead.
        self._boot_is_light = self._read_theme_pref()
        try:
            if bool(self._boot_is_light) != bool(ThemeManager.is_light()):
                ThemeManager.apply(self._boot_is_light, force=True)
            self.setStyleSheet('')
        except Exception as e:
            log.warning(f'boot theme: {e}')
            self._boot_is_light = bool(ThemeManager.is_light())

        # UI first — services second (never block render)
        self._build_ui()
        # Lazy tabs: only build the first page before paint. Eagerly constructing
        # all 11 tabs under light QSS freezes Windows (Not Responding) for 40–80s
        # and blocks QA/theme evidence dumps.
        self._tabs = {}
        self._tab_kw = dict(
            api=self.api, user=self.user_data,
            db_path=self._db_path, config_getter=self._cfg)
        self._tab_cls = {
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
        # Prefetch dashboard only so first paint has content
        self._ensure_tab('dashboard')
        # Paint shell chrome from live C (sidebar/topbar need WA_StyledBackground tint)
        self._refresh_chrome_styles()

        self.signals.connection_changed.connect(self._on_conn)
        self.signals.sync_status.connect(self._on_sync)
        self.signals.update_available.connect(self._ui_update_available)
        self.signals.update_ready.connect(self._ui_update_ready)
        self.signals.force_update.connect(self._ui_force_update)

        # Wire dashboard quick-action navigation (tab exists)
        if 'dashboard' in self._tabs:
            dash = self._tabs['dashboard']
            if hasattr(dash, 'navigate'):
                dash.navigate.connect(self._goto)
            if hasattr(dash, 'theme_changed'):
                dash.theme_changed.connect(self._apply_app_theme)

        # Paint chrome first — defer first-tab show so the maximized frame paints
        self.showMaximized()
        # Optional evidence dumps: set MBT_QA_THEME=1 before RUN_DEV
        if os.environ.get('MBT_QA_THEME', '').strip() in ('1', 'true', 'yes'):
            try:
                QApplication.processEvents()
                self._qa_dump_theme_evidence()
            except Exception as e:
                log.warning('QA sync dump: %s', e)
        QTimer.singleShot(120, self._open_first_tab)
        QTimer.singleShot(200, self._load_saved_theme)
        QTimer.singleShot(600, self._start_services)
        QTimer.singleShot(1600, self._initial_conn_check)
        QTimer.singleShot(2200, self._restore_pending_update)
        # Warm remaining tabs slowly after first paint + services settle
        QTimer.singleShot(8000, self._warm_remaining_tabs)

    def _open_first_tab(self):
        first = next(iter(self._nav), 'dashboard')
        self._goto(first)

    def _ensure_tab(self, tid: str):
        if tid in self._tabs:
            return self._tabs[tid]
        if tid not in getattr(self, '_nav', {}):
            return None
        cls = self._tab_cls.get(tid)
        if not cls:
            return None
        try:
            if tid == 'license':
                w = cls(**self._tab_kw, license_service=getattr(self, '_svc_lic', None))
            else:
                w = cls(**self._tab_kw)
        except Exception as e:
            w = QLabel(f"Error loading {tid}:\n{e}")
            w.setStyleSheet(f"color:{C['err']}; padding:32px; font-size:14px;")
        self._tabs[tid] = w
        self._stack.addWidget(w)
        # Wire sales hooks when first created
        if tid == 'sales':
            if hasattr(w, 'sale_completed'):
                if 'dashboard' in self._tabs and hasattr(self._tabs['dashboard'], '_load'):
                    w.sale_completed.connect(self._tabs['dashboard']._load)
                # reports may not exist yet — reconnect in _ensure_tab('reports') if needed
            if hasattr(w, 'theme_changed'):
                w.theme_changed.connect(self._apply_app_theme)
        if tid == 'reports' and 'sales' in self._tabs:
            sales = self._tabs['sales']
            if hasattr(sales, 'sale_completed') and hasattr(w, 'refresh'):
                try:
                    sales.sale_completed.connect(w.refresh)
                except Exception:
                    pass
        return w

    def _warm_remaining_tabs(self):
        """Create non-dashboard tabs one-per-tick so UI stays responsive."""
        pending = [t for t in self._nav.keys() if t not in self._tabs]
        if not pending:
            return
        tid = pending[0]
        try:
            self._ensure_tab(tid)
        except Exception as e:
            log.warning('warm tab %s: %s', tid, e)
        if len(pending) > 1:
            QTimer.singleShot(80, self._warm_remaining_tabs)

    def _qa_dump_theme_evidence(self):
        """Write light/dark hybrid evidence screenshots (Desktop folder)."""
        try:
            out = os.path.join(
                os.path.expanduser('~'), 'OneDrive', 'Desktop',
                'QA_EVIDENCE_LIGHT_THEME')
            os.makedirs(out, exist_ok=True)
            QApplication.processEvents()
            pm = self.grab()
            full = os.path.join(out, '01_full_light_hybrid.png')
            pm.save(full, 'PNG')
            w, h = pm.width(), pm.height()
            if w > 10 and h > 10:
                pm.copy(0, 0, min(260, w), h).save(
                    os.path.join(out, '02_sidebar.png'), 'PNG')
                pm.copy(0, 0, w, min(90, h)).save(
                    os.path.join(out, '03_topbar.png'), 'PNG')
                pm.copy(min(228, w // 4), min(56, h // 10),
                        max(1, w - min(228, w // 4)),
                        max(1, h - min(56, h // 10) - 36)).save(
                    os.path.join(out, '04_content.png'), 'PNG')
                pm.copy(w // 3, h // 5, max(1, w // 3), max(1, h // 5)).save(
                    os.path.join(out, '05_content_center.png'), 'PNG')
            mode = 'light' if ThemeManager.is_light() else 'dark'
            log.info('QA theme evidence dump (%s) -> %s (%dx%d)', mode, out, w, h)
            # Late dump after dashboard paints (no auto POS nav — that raced warm-tabs)
            QTimer.singleShot(1200, self._qa_dump_theme_evidence_late)
        except Exception as e:
            log.warning('QA evidence dump: %s', e)

    def _qa_dump_theme_evidence_late(self):
        try:
            out = os.path.join(
                os.path.expanduser('~'), 'OneDrive', 'Desktop',
                'QA_EVIDENCE_LIGHT_THEME')
            QApplication.processEvents()
            pm = self.grab()
            pm.save(os.path.join(out, '01b_after_dashboard_load.png'), 'PNG')
            log.info('QA late dashboard dump done')
        except Exception as e:
            log.warning('QA late dump: %s', e)

    def _qa_dump_sales_evidence(self):
        """Optional — call manually / from tests; not auto-chained (avoids hang)."""
        try:
            out = os.path.join(
                os.path.expanduser('~'), 'OneDrive', 'Desktop',
                'QA_EVIDENCE_LIGHT_THEME')
            QApplication.processEvents()
            pm = self.grab()
            pm.save(os.path.join(out, '06_pos_full.png'), 'PNG')
            w, h = pm.width(), pm.height()
            if w > 400 and h > 200:
                left = min(228, w // 5)
                mid = left + (w - left) // 2
                pm.copy(left, 56, max(1, mid - left), max(1, h - 100)).save(
                    os.path.join(out, '07_pos_products.png'), 'PNG')
                pm.copy(mid, 56, max(1, w - mid - 8), max(1, h - 100)).save(
                    os.path.join(out, '08_pos_cart.png'), 'PNG')
            log.info('QA POS evidence dump -> %s', out)
        except Exception as e:
            log.warning('QA POS dump: %s', e)

    # ?? Config ?????????????????????????????????????????????????????????????????
    def _cfg(self) -> dict:
        try:
            return self.api.get('/api/settings') or {}
        except Exception:
            return {}

    # ?? Background services ????????????????????????????????????????????????????
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
        Called immediately when LicenseService detects a state change ?
        including from remote commands (revoke, extend, activate).
        Runs on the license service thread ? must use QTimer to touch UI.
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
                    # Hard close ? no way to continue
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

    # ?? UI ?????????????????????????????????????????????????????????????????????
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = self._build_sidebar()
        root.addWidget(self._sidebar)

        right = QWidget(); right.setObjectName("content")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        rl.addWidget(self._build_topbar())
        self._stack = QStackedWidget(); self._stack.setObjectName("pageStack")
        rl.addWidget(self._stack)
        rl.addWidget(self._build_statusbar())
        root.addWidget(right, 1)

    def _build_sidebar(self):
        # Lovable AppShell sidebar ? 228px, logo + brand, gold active rail
        sb = QWidget(); sb.setObjectName("sidebar"); sb.setFixedWidth(228)
        # QWidget backgrounds need styled-background or light QSS never paints
        sb.setAttribute(Qt.WA_StyledBackground, True)
        sb.setAutoFillBackground(True)
        self._sidebar = sb
        sl = QVBoxLayout(sb); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)

        # Logo block ? HD mark + MBT / POS SYSTEM text (Lovable)
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

        # Navigation ? scrollable when many tabs / short displays
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
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setAutoFillBackground(True)
        self._topbar = bar
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

        web_btn = QPushButton("Access POS through web dashboard")
        web_btn.setObjectName("refreshBtn")
        web_btn.setCursor(Qt.PointingHandCursor)
        web_btn.setToolTip(
            "Opens the web dashboard in your browser.\n"
            "Uses local http://127.0.0.1:5050 when available;\n"
            "falls back to your mugobyte.com remote URL if configured.")
        web_btn.clicked.connect(self._open_web_dashboard)
        lay.addWidget(web_btn)

        ref_btn = QPushButton("\u21bb  Refresh"); ref_btn.setObjectName("refreshBtn")
        ref_btn.setCursor(Qt.PointingHandCursor); ref_btn.clicked.connect(self._manual_refresh)
        lay.addWidget(ref_btn)

        from desktop.utils.widgets import ThemeSwitchBar
        self._theme_btn = ThemeSwitchBar(on_toggle=self._on_theme_change)
        lay.addWidget(self._theme_btn)

        self._clk = QLabel(); self._clk.setObjectName("clockLbl")
        lay.addWidget(self._clk)

        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000); self._tick()
        return bar

    def _build_statusbar(self):
        bar = QWidget(); bar.setObjectName("statusBar"); bar.setFixedHeight(36)
        # QWidget ignores QSS backgrounds unless styled-background is on —
        # without this, light mode can leave a dark parent/chrome strip.
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setAutoFillBackground(True)
        self._status_bar = bar
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
        self._tint_statusbar()
        return bar

    def _tint_chrome_widget(self, widget, object_name: str, bg_key: str,
                            border_side: str = None):
        """Force a chrome strip to live ThemeManager colors (palette + object QSS)."""
        if widget is None:
            return
        from PyQt5.QtGui import QColor, QPalette
        bg = QColor(C.get(bg_key, C.get('panel')))
        fg = QColor(C.get('text2', '#3C5270'))
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setAutoFillBackground(True)
        pal = widget.palette()
        pal.setColor(QPalette.Window, bg)
        pal.setColor(QPalette.Base, bg)
        pal.setColor(QPalette.WindowText, fg)
        pal.setColor(QPalette.Text, fg)
        widget.setPalette(pal)
        border = ''
        if border_side == 'right':
            border = f" border-right:1px solid {C.get('border')};"
        elif border_side == 'bottom':
            border = f" border-bottom:1px solid {C.get('border')};"
        elif border_side == 'top':
            border = f" border-top:1px solid {C.get('border')};"
        widget.setStyleSheet(
            f"QWidget#{object_name} {{ background:{C.get(bg_key)};{border} }}")

    def _tint_statusbar(self):
        """Keep footer panel in sync with ThemeManager palette (light/dark)."""
        bar = getattr(self, '_status_bar', None)
        if bar is None:
            return
        self._tint_chrome_widget(bar, 'statusBar', 'panel', border_side='top')
        # Labels stay readable on the tinted strip
        bar.setStyleSheet(
            f"QWidget#statusBar {{ background:{C.get('panel')}; "
            f"border-top:1px solid {C.get('border')}; }}"
            f"QLabel#statusLeft, QLabel#statusRight {{ color:{C.get('text2')}; "
            f"background:transparent; font-size:11px; }}"
        )

    def _build_tabs(self):
        """Compat: ensure all nav tabs exist (prefer lazy _ensure_tab / warm)."""
        for tid in list(getattr(self, '_nav', {}).keys()):
            self._ensure_tab(tid)

    # ?? Navigation ??????????????????????????????????????????????????????????????
    _TAB_LABELS = {
        'dashboard':'Dashboard', 'sales':'Point of Sale', 'inventory':'Inventory',
        'debt':'Debt Management',
        'reports':'Reports', 'notes':'Notes', 'admin':'Users & Access',
        'settings':'Settings', 'security':'Security & Super-Admin',
        'license':'License & Subscription', 'diagnostics':'Diagnostics',
    }

    def _goto(self, tid: str):
        self._ensure_tab(tid)
        for bid, btn in self._nav.items():
            btn.setChecked(bid == tid)
        self._page_title.setText(self._TAB_LABELS.get(tid, tid.title()))
        if tid in self._tabs:
            self._stack.setCurrentWidget(self._tabs[tid])
            tab = self._tabs[tid]
            if hasattr(tab, 'on_show'):
                try: tab.on_show()
                except Exception as e: log.warning(f"on_show {tid}: {e}")

    # ?? Theme ???????????????????????????????????????????????????????????????????
    def _read_theme_pref(self) -> bool:
        """True if shop prefers light theme."""
        try:
            cfg = self._cfg() or {}
            theme = str(cfg.get('theme') or cfg.get('ui_theme') or 'dark').lower()
            return theme == 'light'
        except Exception:
            return False

    def _on_theme_change(self, is_light: bool):
        """ThemeToggleBtn / sales / dashboard — single apply path via _sync_theme_ui."""
        self._sync_theme_ui(is_light, persist=True)

    def _load_saved_theme(self):
        """
        Boot already applied the saved theme before widgets were built.
        Only run a full sync if preference drifted (should be rare).
        """
        try:
            want_light = getattr(self, '_boot_is_light', None)
            if want_light is None:
                want_light = self._read_theme_pref()
            if bool(want_light) == bool(ThemeManager.is_light()):
                # Ensure window does not override app QSS (light hybrid fix)
                self.setStyleSheet('')
                self._refresh_chrome_styles()
                return
            self._sync_theme_ui(bool(want_light), persist=False)
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
            # Use live palette so overlay is not stuck on dark hex in light mode
            ov.setStyleSheet(
                f"QWidget#mbtThemeOverlay {{ background: {qss_alpha(C['app'], 0.72)}; }}"
                f"QLabel#mbtThemeOverlayLbl {{ color: {C['text']}; font-size: 15px; font-weight: 700;"
                f" background: transparent; }}"
                f"QProgressBar#mbtThemeOverlayBar {{ background: {C['panel']}; border: 1px solid {C['border']};"
                f" border-radius: 6px; height: 10px; text-align: center; }}"
                f"QProgressBar#mbtThemeOverlayBar::chunk {{ background: {C['gold']}; border-radius: 5px; }}")
            lay = QVBoxLayout(ov)
            lay.setAlignment(Qt.AlignCenter)
            box = QWidget(); box.setFixedWidth(320)
            bl = QVBoxLayout(box); bl.setSpacing(12)
            lbl = QLabel('Switching theme...'); lbl.setObjectName('mbtThemeOverlayLbl')
            lbl.setAlignment(Qt.AlignCenter)
            bar = QProgressBar(); bar.setObjectName('mbtThemeOverlayBar')
            bar.setRange(0, 0)  # indeterminate ? never looks frozen
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
        Fast theme switch (~instant perceived):
        - one global QSS apply (no duplicate window stylesheet)
        - retint chrome + current tab styles only
        - defer cart rebuild, product grid, and other tabs (no overlay / WaitCursor)
        - never call tab.refresh() (DB reload was a major lag source)
        """
        if getattr(self, '_theme_switching', False):
            return
        self._theme_switching = True
        self._theme_gen = getattr(self, '_theme_gen', 0) + 1
        gen = self._theme_gen
        t0 = time.perf_counter()
        # Freeze paints while QApp stylesheet re-polishes — cuts Not Responding time
        self.setUpdatesEnabled(False)
        try:
            ThemeManager.apply(is_light, force=True)
            # Clear any leftover window-level QSS so QApplication theme reaches chrome
            self.setStyleSheet('')
            # ThemeManager already set QApplication stylesheet — do NOT also
            # self.setStyleSheet(full sheet) (second full polish was a major lag source).

            if hasattr(self, '_theme_btn') and hasattr(self._theme_btn, '_refresh_theme'):
                self._theme_btn._refresh_theme()
            elif hasattr(self, '_theme_btn') and hasattr(self._theme_btn, 'setText'):
                self._theme_btn.setText('Dark' if is_light else 'Light')

            self._refresh_chrome_styles()

            cur = self._stack.currentWidget() if hasattr(self, '_stack') else None
            cur_tid = None
            for tid, tab in getattr(self, '_tabs', {}).items():
                if tab is cur:
                    cur_tid = tid
                    break

            # Scope findChildren walk to visible page + sidebar QWidget only
            # (never pass self._nav — that is a dict of buttons, not a QWidget)
            try:
                from desktop.utils.widgets import refresh_themed_widgets
                if cur is not None:
                    refresh_themed_widgets(cur)
                side = getattr(self, '_sidebar', None)
                if side is not None and hasattr(side, 'findChildren'):
                    refresh_themed_widgets(side)
            except Exception as e:
                log.warning(f'theme widget refresh: {e}')

            if cur_tid == 'dashboard' and hasattr(cur, 'set_light_mode'):
                cur.set_light_mode(is_light)
            elif cur_tid == 'sales':
                self._apply_sales_theme(is_light, defer_heavy=True)
            elif cur is not None:
                if hasattr(cur, 'apply_theme'):
                    try: cur.apply_theme(is_light)
                    except Exception: pass
                elif hasattr(cur, 'set_light_mode'):
                    try: cur.set_light_mode(is_light)
                    except Exception: pass

            ms = (time.perf_counter() - t0) * 1000.0
            log.info('theme switch sync %.0fms ? %s', ms, 'light' if is_light else 'dark')

            pending = [
                (tid, tab) for tid, tab in getattr(self, '_tabs', {}).items()
                if tab is not cur
            ]
            self._theme_pending = pending
            self._theme_pending_light = is_light
            self._theme_persist = persist
            self._theme_pending_gen = gen
            # Unlock immediately — deferred work must not block the toggle
            self._theme_switching = False
            QTimer.singleShot(0, self._theme_apply_pending_tabs)
        except Exception as e:
            log.warning(f'theme sync: {e}')
            self._theme_switching = False
            self._theme_overlay_hide()
        finally:
            self.setUpdatesEnabled(True)

    def _theme_apply_pending_tabs(self):
        gen = getattr(self, '_theme_pending_gen', 0)
        if gen != getattr(self, '_theme_gen', 0):
            return  # superseded by a newer toggle
        is_light = getattr(self, '_theme_pending_light', False)
        pending = getattr(self, '_theme_pending', []) or []
        # One tab per tick ? keep UI responsive, no processEvents storms
        if pending:
            tid, tab = pending[0]
            self._theme_pending = pending[1:]
            try:
                if tid == 'dashboard' and hasattr(tab, 'set_light_mode'):
                    tab.set_light_mode(is_light)
                elif tid == 'sales':
                    self._apply_sales_theme(is_light, defer_heavy=True)
                elif hasattr(tab, 'apply_theme'):
                    tab.apply_theme(is_light)
                elif hasattr(tab, 'set_light_mode'):
                    tab.set_light_mode(is_light)
            except Exception:
                pass
            try:
                from desktop.utils.widgets import refresh_themed_widgets
                refresh_themed_widgets(tab)
            except Exception:
                pass
            QTimer.singleShot(0, self._theme_apply_pending_tabs)
            return

        if getattr(self, '_theme_persist', False):
            threading.Thread(
                target=self._save_theme_pref,
                args=(is_light,),
                daemon=True,
                name='SaveTheme',
            ).start()
        self._theme_overlay_hide()

    def _save_theme_pref(self, is_light: bool):
        try:
            self.api.update_settings({
                'theme': 'light' if is_light else 'dark',
                'ui_theme': 'light' if is_light else 'dark',
            })
        except Exception as e:
            log.warning(f'Save theme: {e}')

    def _apply_sales_theme(self, is_light: bool, defer_heavy: bool = True):
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
                if hasattr(sales._theme_btn, '_refresh_theme'):
                    sales._theme_btn._refresh_theme()
                elif hasattr(sales._theme_btn, 'setText'):
                    sales._theme_btn.setText('Dark' if is_light else 'Light')
            if defer_heavy:
                QTimer.singleShot(0, lambda s=sales: self._sales_theme_heavy(s))
            else:
                self._sales_theme_heavy(sales)
        except Exception as e:
            log.warning(f'Sales theme: {e}')

    def _sales_theme_heavy(self, sales):
        """Cart rebuild + product grid ? deferred so palette/QSS feels instant."""
        try:
            if getattr(sales, 'cart', None) is not None:
                sales._refresh_cart()
            if hasattr(sales, '_filter'):
                sales._filter()
        except Exception as e:
            log.warning(f'Sales theme heavy: {e}')

    def _refresh_chrome_styles(self):
        """Retint shell chrome so Light never leaves dark strips (and vice versa)."""
        # Explicit tint beats a stale window-level QSS copy from older builds
        self._tint_chrome_widget(
            getattr(self, '_sidebar', None), 'sidebar', 'sidebar', border_side='right')
        # Logo / user strips share sidebar/panel tokens
        side = getattr(self, '_sidebar', None)
        if side is not None:
            for child, oname, key, bside in (
                (side.findChild(QWidget, 'sidebarLogo'), 'sidebarLogo', 'sidebar', 'bottom'),
                (side.findChild(QWidget, 'sidebarUser'), 'sidebarUser', 'panel', 'top'),
            ):
                if child is not None:
                    self._tint_chrome_widget(child, oname, key, border_side=bside)
        self._tint_chrome_widget(
            getattr(self, '_topbar', None), 'topbar', 'panel', border_side='bottom')
        if hasattr(self, '_conn_lbl'):
            self._conn_lbl.setStyleSheet(
                f"color:{C['ok'] if getattr(self, '_conn_ok', True) else C['err']}; "
                f"font-size:13px; font-weight:700; background:transparent;")
        if hasattr(self, '_update_btn'):
            gold_fg = C.get('gold_fg', '#0A0F1A')
            self._update_btn.setStyleSheet(
                f"QPushButton#updateBtn {{ background:{C['gold']}; color:{gold_fg};"
                f" font-weight:700; font-size:13px; border:none; border-radius:6px;"
                f" padding:6px 14px; }}"
                f"QPushButton#updateBtn:hover {{ background:{C['gold_lt']}; }}")
        if hasattr(self, '_theme_btn') and hasattr(self._theme_btn, '_refresh_theme'):
            self._theme_btn._refresh_theme()
        self._tint_statusbar()

    # ?? Status slots ????????????????????????????????????????????????????????????
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
                'Remote dashboard could not auto-configure.\n\n'
                f'{err}\n\n'
                'This is usually a vendor API-token issue (deploy.local.json), '
                'not something cashiers fix with Cloudflare login.')
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

    def _open_web_dashboard(self):
        """Ensure embedded Flask is up, then open local (prefer) or remote URL."""
        import urllib.request
        import webbrowser

        _start_web_dashboard()

        local_url = BACKEND_URL
        local_ok = False
        try:
            with urllib.request.urlopen(f'{local_url}/api/health', timeout=3) as r:
                local_ok = getattr(r, 'status', 200) == 200
        except Exception:
            local_ok = False

        remote_url = ''
        try:
            from backend.cloudflare_setup import load_web_config
            wcfg = load_web_config() or {}
            domain = (wcfg.get('tunnel_domain') or '').strip()
            if (
                domain
                and wcfg.get('remote_enabled')
                and wcfg.get('remote_setup_ok')
            ):
                remote_url = f'https://{domain}'
        except Exception:
            pass

        # Prefer local when the embedded web service is healthy; else remote.
        if local_ok:
            webbrowser.open(local_url)
            log.info('Opened web dashboard: %s', local_url)
            return
        if remote_url:
            webbrowser.open(remote_url)
            log.info('Opened remote web dashboard: %s', remote_url)
            return
        webbrowser.open(local_url)
        log.info('Opened web dashboard (fallback): %s', local_url)

    # ?? Auth ????????????????????????????????????????????????????????????????????
    def _logout(self):
        if QMessageBox.question(self, "Sign Out", "Sign out of MBT POS?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._stop_services()
            self.hide()
            _show_login(self.api)

    def closeEvent(self, event):
        self._stop_services(); event.accept()


# ?? Bootstrap ??????????????????????????????????????????????????????????????????

def _start_web_dashboard():
    """
    Start embedded web dashboard + Cloudflare tunnel in a background thread.

    Must never block the Qt main thread — tunnel restart / remote HTTPS checks
    can take 1–3 minutes and previously froze splash/login (Not Responding).
    Desktop POS uses direct SQLite and does not need Flask to be ready.
    """
    global _web_svc
    if _web_svc and getattr(_web_svc, 'running', False):
        return True

    def _bg():
        global _web_svc
        try:
            try:
                from backend.cloudflare_setup import bootstrap_cloudflared
                # Local file copy only — no DNS / network (those blocked splash before)
                bootstrap_cloudflared()
            except Exception:
                pass
            from backend.web_service import WebDashboardService
            svc = WebDashboardService()
            ok = svc.start()
            _web_svc = svc
            if ok:
                log.info(f"Web dashboard: {svc.url}")
            else:
                log.warning("Web dashboard could not start — desktop POS still works")
        except Exception as e:
            log.warning(f"Web dashboard: {e}")

    threading.Thread(target=_bg, daemon=True, name='WebDashStart').start()
    return True


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
    # Single instance ? prevent duplicate POS during update restart
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
    # Manrope when bundled; Segoe UI fallback ? never crash if missing
    fam = ensure_fonts()
    try:
        # Prefer first quoted family from font_stack
        primary = fam.split(',')[0].strip().strip("'\"") or 'Segoe UI'
        app.setFont(QFont(primary, 13))
    except Exception:
        app.setFont(QFont('Segoe UI', 13))
    # Rebuild QSS now that fonts (and QApp) are ready — use saved light/dark so
    # login + MainWindow are not built dark then re-polished to light (80s freeze).
    _boot_light = False
    try:
        _cfg0 = APIClient(BACKEND_URL).get_settings() or {}
        _boot_light = str(
            _cfg0.get('theme') or _cfg0.get('ui_theme') or 'dark'
        ).lower() == 'light'
    except Exception:
        pass
    app.setStyleSheet(ThemeManager.apply(_boot_light, force=True))

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
    # Init DB directly ? no HTTP server needed
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
