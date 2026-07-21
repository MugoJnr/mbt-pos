"""
MBT POS — First-Run Setup Wizard
MugoByte Technologies | mugobyte.com
7-step guided setup. Launches once on fresh install, never again.
"""
import os, sys, json, sqlite3, time
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

from mbt_paths import get_project_root, get_init_flag_path, get_db_path, ensure_data_dirs

PROJECT_ROOT = ensure_data_dirs(get_project_root())
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from desktop.utils.theme import apply_themed_dialog,  MBT_STYLESHEET, C
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, SuccessBtn, DangerBtn

INIT_FLAG = get_init_flag_path()

STEPS = [
    ("Welcome",          "Welcome to MBT POS"),
    ("Portal Account",   "Sign In or Create Account"),
    ("License",          "Register Device & Activate"),
    ("Shop Info",        "Your Shop Details"),
    ("Admin Account",    "Create Local Admin"),
    ("Printer Setup",    "Printer Configuration"),
    ("Live Dashboard",   "Live Dashboard"),
    ("Complete",         "Setup Complete"),
]


def needs_wizard() -> bool:
    """Return True if setup wizard should run."""
    return not os.path.exists(INIT_FLAG)


def mark_initialized():
    os.makedirs(os.path.dirname(INIT_FLAG), exist_ok=True)
    with open(INIT_FLAG, 'w') as f:
        f.write(datetime.now().isoformat())


def reset_wizard():
    """Admin calls this to force wizard on next launch."""
    if os.path.exists(INIT_FLAG):
        os.remove(INIT_FLAG)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _label(text, size=14, bold=False, color=None):
    l = QLabel(text)
    c = color or C['text']
    w = 700 if bold else 400
    l.setStyleSheet(f"color:{c}; font-size:{size}px; font-weight:{w}; background:transparent;")
    l.setWordWrap(True)
    return l


def _field(placeholder='', password=False):
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setMinimumHeight(44)
    if password:
        f.setEchoMode(QLineEdit.Password)
    return f


# ── Wizard Window ──────────────────────────────────────────────────────────────

class SetupWizard(QDialog):
    completed = pyqtSignal(dict)   # emits collected config

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MBT POS — Setup Wizard")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(960, 640)
        self.resize(980, 660)
        apply_themed_dialog(self)

        self._step   = 0
        self._data   = {}
        self._pages  = []
        self._step_btns = []
        self._cf_setup_running = False
        self._tg_polling = False

        self._build_ui()
        self._center()

    def _center(self):
        s = QApplication.primaryScreen().geometry()
        self.move(s.center().x() - self.width()//2, s.center().y() - self.height()//2)

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        root.addWidget(self._build_sidebar())

        # Right: header + stack + footer
        right = QWidget()
        right.setObjectName("wizardContent")
        right.setStyleSheet(f"background:{C['surface']};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        rl.addWidget(self._build_header())

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{C['surface']};")
        rl.addWidget(self._stack, 1)

        rl.addWidget(self._build_footer())

        self._build_pages()
        self._go_to(0)
        root.addWidget(right, 1)
        self._cloud_restore_offer = None

    def _build_sidebar(self):
        sb = QWidget()
        sb.setFixedWidth(240)
        sb.setStyleSheet(f"background:{C['app']}; border-right:1px solid {C['border']};")
        sl = QVBoxLayout(sb)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Logo area — exact HD mark (transparent)
        logo_w = QWidget()
        logo_w.setFixedHeight(110)
        logo_w.setStyleSheet(f"background:{C['app']}; border-bottom:2px solid {C['gold']};")
        ll = QVBoxLayout(logo_w)
        ll.setAlignment(Qt.AlignCenter)
        ll.setContentsMargins(8, 8, 8, 4)
        lt = QLabel()
        lt.setAlignment(Qt.AlignCenter)
        lt.setStyleSheet("background:transparent; border:none;")
        _assets = os.path.join(PROJECT_ROOT, 'assets')
        if getattr(sys, 'frozen', False):
            _assets = os.path.join(sys._MEIPASS, 'assets')
        for _name in ('mbt_logo_hd.png', 'mbt_icon_256.png', 'mbt_icon.png'):
            _p = os.path.join(_assets, _name)
            if os.path.exists(_p):
                _pm = QPixmap(_p)
                if not _pm.isNull():
                    lt.setPixmap(
                        _pm.scaled(200, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    break
        ls = QLabel("SETUP WIZARD")
        ls.setAlignment(Qt.AlignCenter)
        ls.setStyleSheet(f"color:{C['muted']}; font-size:10px; letter-spacing:3px; background:transparent;")
        ll.addWidget(lt); ll.addWidget(ls)
        sl.addWidget(logo_w)

        sl.addSpacing(16)

        # Step list
        for i, (label, _) in enumerate(STEPS):
            btn = QLabel(f"  {i+1:02d}  {label}")
            btn.setFixedHeight(44)
            btn.setStyleSheet(self._step_style('pending'))
            sl.addWidget(btn)
            self._step_btns.append(btn)

        sl.addStretch()

        foot = QLabel("mugobyte.com")
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet(f"color:{C['muted']}; font-size:11px; padding:12px;")
        sl.addWidget(foot)
        return sb

    def _step_style(self, state):
        if state == 'active':
            return (f"color:{C['gold']}; font-size:14px; font-weight:700;"
                    f"background:{C['card']}; border-left:3px solid {C['gold']};")
        elif state == 'done':
            return f"color:{C['ok']}; font-size:14px; background:transparent; border-left:3px solid {C['ok']};"
        else:
            return f"color:{C['muted']}; font-size:14px; background:transparent; border-left:3px solid transparent;"

    def _build_header(self):
        hdr = QWidget()
        hdr.setFixedHeight(64)
        hdr.setStyleSheet(f"background:{C['card']}; border-bottom:1px solid {C['border']};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(32, 0, 32, 0)

        self._step_lbl = QLabel("Step 1 of 7")
        self._step_lbl.setStyleSheet(f"color:{C['muted']}; font-size:12px; font-weight:700; letter-spacing:1px;")

        self._prog = QProgressBar()
        self._prog.setRange(0, len(STEPS) - 1)
        self._prog.setValue(0)
        self._prog.setFixedWidth(200)
        self._prog.setFixedHeight(6)

        self._title_hdr = QLabel("Welcome")
        self._title_hdr.setStyleSheet(f"color:{C['text']}; font-size:18px; font-weight:700;")

        hl.addWidget(self._step_lbl)
        hl.addSpacing(16)
        hl.addWidget(self._prog)
        hl.addStretch()
        hl.addWidget(self._title_hdr)
        return hdr

    def _build_footer(self):
        foot = QWidget()
        foot.setFixedHeight(64)
        foot.setStyleSheet(f"background:{C['card']}; border-top:1px solid {C['border']};")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(32, 0, 32, 0)
        fl.setSpacing(12)

        self._back_btn = SecondaryBtn("← Back", 42)
        self._back_btn.setObjectName("backBtn")
        self._back_btn.setFixedWidth(120)
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._prev)

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setFixedWidth(90)
        self._skip_btn.setStyleSheet(
            f"QPushButton {{ color:{C['text']}; background:transparent; border:1px solid {C['border2']}; "
            f"border-radius:8px; padding:8px 16px; font-size:13px; font-weight:600; }}"
            f"QPushButton:hover {{ background:{C['hover']}; color:{C['text']}; }}")
        self._skip_btn.setCursor(Qt.PointingHandCursor)
        self._skip_btn.clicked.connect(self._next)
        self._skip_btn.hide()

        self._next_btn = PrimaryBtn("Continue →", 42)
        self._next_btn.setObjectName("primaryBtn")
        self._next_btn.setFixedWidth(160)
        self._next_btn.setFixedHeight(44)
        self._next_btn.clicked.connect(self._next)

        fl.addWidget(self._back_btn)
        fl.addStretch()
        fl.addWidget(self._skip_btn)
        fl.addWidget(self._next_btn)
        return foot

    # ── Pages ───────────────────────────────────────────────────────────────────

    def _build_pages(self):
        # Portal-first: Account → License/Device → local shop init → Live Dashboard
        raw_pages = [
            self._page_welcome(),
            self._page_portal_account(),
            self._page_license(),
            self._page_shop(),
            self._page_admin(),
            self._page_printer(),
            self._page_remote_web(),
            self._page_complete(),
        ]
        # Scroll long steps so footer nav buttons are never covered by content.
        self._pages = [
            self._scroll_page(p) if i in (1, 2, 5, 6) else p
            for i, p in enumerate(raw_pages)
        ]
        for p in self._pages:
            self._stack.addWidget(p)

    def _scroll_page(self, inner):
        """Wrap inner widget in a scroll area."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        return scroll

    def _page_container(self):
        w = QWidget()
        w.setStyleSheet(f"background:{C['surface']};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(48, 40, 48, 40)
        lay.setSpacing(20)
        return w, lay

    # Page 1 — Welcome
    def _page_welcome(self):
        w, lay = self._page_container()
        lay.addStretch()

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background:transparent; border:none;")
        _assets = os.path.join(PROJECT_ROOT, 'assets')
        if getattr(sys, 'frozen', False):
            _assets = os.path.join(sys._MEIPASS, 'assets')
        for _name in ('mbt_logo_hd.png', 'mbt_icon_256.png', 'mbt_icon.png'):
            _p = os.path.join(_assets, _name)
            if os.path.exists(_p):
                _pm = QPixmap(_p)
                if not _pm.isNull():
                    logo.setPixmap(
                        _pm.scaled(360, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    break

        t1 = QLabel("Welcome to MBT POS")
        t1.setAlignment(Qt.AlignCenter)
        t1.setStyleSheet(f"color:{C['text']}; font-size:26px; font-weight:800; background:transparent;")

        t2 = QLabel(
            "Professional Point of Sale for your business.\n\n"
            "Portal-first setup: create or sign in at portal.mugobyte.com,\n"
            "verify your email, register this device, then activate your license.\n\n"
            "There is no free trial and no Telegram. After activation,\n"
            "sales continue offline with a configurable grace period."
        )
        t2.setAlignment(Qt.AlignCenter)
        t2.setStyleSheet(f"color:{C['text2']}; font-size:14px; line-height:1.6; background:transparent;")
        t2.setWordWrap(True)

        brand = QLabel("MUGOBYTE TECHNOLOGIES  ·  portal.mugobyte.com")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet(f"color:{C['muted']}; font-size:12px; letter-spacing:2px; background:transparent;")

        lay.addWidget(logo)
        lay.addSpacing(8)
        lay.addWidget(t1)
        lay.addSpacing(8)
        lay.addWidget(t2)
        lay.addSpacing(24)
        lay.addWidget(brand)
        lay.addStretch()
        return w

    # Page 2 — Shop
    def _page_shop(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Your Shop Details", 22, bold=True))
        lay.addWidget(_label("This information appears on receipts, reports, and documents.", 14, color=C['text2']))
        lay.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(16)
        form.setLabelAlignment(Qt.AlignRight)

        self.w_shop_name     = _field("e.g. Doe Supermarket  (required)")
        self.w_shop_location = _field("Street address or area  (optional)")
        self.w_shop_phone    = _field("+254 700 000 000  (optional)")
        self.w_currency      = QComboBox()
        for cur in ['KES', 'USD', 'EUR', 'GBP', 'TZS', 'UGX', 'ZAR']:
            self.w_currency.addItem(cur)

        for lbl, widget in [
            ("Shop Name *", self.w_shop_name),
            ("Address",     self.w_shop_location),
            ("Phone",       self.w_shop_phone),
            ("Currency",    self.w_currency),
        ]:
            fl = QLabel(lbl)
            fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
            form.addRow(fl, widget)

        lay.addLayout(form)
        lay.addStretch()
        return w

    # Page 3 — Admin
    def _page_admin(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Create Admin Account", 22, bold=True))
        lay.addWidget(_label("This account controls all settings, users, and licensing.", 14, color=C['text2']))
        lay.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(16)
        form.setLabelAlignment(Qt.AlignRight)

        self.w_admin_user = _field("admin")
        self.w_admin_pw   = _field("Minimum 8 characters", password=True)
        self.w_admin_pw2  = _field("Confirm password", password=True)
        self.w_admin_pin  = _field("4-digit PIN for quick login  (optional)")

        self._pw_strength = QProgressBar()
        self._pw_strength.setRange(0, 4)
        self._pw_strength.setValue(0)
        self._pw_strength.setFixedHeight(5)
        self._pw_strength.setTextVisible(False)
        self.w_admin_pw.textChanged.connect(self._update_pw_strength)

        self._pw_match = QLabel("")
        self._pw_match.setStyleSheet("font-size:12px;")
        self.w_admin_pw2.textChanged.connect(self._check_pw_match)

        for lbl, widget in [
            ("Username",        self.w_admin_user),
            ("Password",        self.w_admin_pw),
            ("",                self._pw_strength),
            ("Confirm",         self.w_admin_pw2),
            ("",                self._pw_match),
            ("Quick PIN",       self.w_admin_pin),
        ]:
            fl = QLabel(lbl)
            fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
            form.addRow(fl, widget)

        lay.addLayout(form)
        lay.addStretch()
        return w

    def _update_pw_strength(self, pw):
        score = 0
        if len(pw) >= 8: score += 1
        if any(c.isupper() for c in pw): score += 1
        if any(c.isdigit() for c in pw): score += 1
        if any(c in '!@#$%^&*' for c in pw): score += 1
        self._pw_strength.setValue(score)
        colors = ['#E74C3C','#E67E22','#F0A500','#27AE60']
        if score > 0:
            self._pw_strength.setStyleSheet(
                f"QProgressBar::chunk {{ background:{colors[score-1]}; border-radius:3px; }}")

    def _check_pw_match(self, pw2):
        pw1 = self.w_admin_pw.text()
        if pw2 and pw2 == pw1:
            self._pw_match.setText("✓ Passwords match")
            self._pw_match.setStyleSheet(f"color:{C['ok']}; font-size:12px;")
        elif pw2:
            self._pw_match.setText("✗ Passwords do not match")
            self._pw_match.setStyleSheet(f"color:{C['err']}; font-size:12px;")
        else:
            self._pw_match.setText("")

    # Page 4 — Printer
    def _page_printer(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Printer Configuration", 22, bold=True))
        lay.addWidget(_label("Configure your 80mm USB Thermal Printer for receipt printing.", 14, color=C['text2']))
        lay.addSpacing(8)

        detect_row = QHBoxLayout()
        detect_btn = SecondaryBtn("Detect Printers", 40)
        detect_btn.setFixedWidth(180)
        detect_btn.clicked.connect(self._detect_printers)

        self.w_printer_list = QComboBox()
        self.w_printer_list.addItem("— Select printer —")
        detect_row.addWidget(detect_btn)
        detect_row.addWidget(self.w_printer_list, 1)
        lay.addLayout(detect_row)

        form = QFormLayout()
        form.setSpacing(14)
        self.w_printer_port = _field("e.g. USB, COM3, /dev/usb/lp0")
        self.w_auto_print   = QCheckBox("Automatically print receipt after each sale")
        self.w_auto_print.setChecked(True)

        fl1 = QLabel("Manual Port"); fl1.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        fl2 = QLabel(""); fl2.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        form.addRow(fl1, self.w_printer_port)
        form.addRow(fl2, self.w_auto_print)
        lay.addLayout(form)

        test_btn = SecondaryBtn("Print Test Page", 40)
        test_btn.setFixedWidth(180)
        test_btn.clicked.connect(self._test_print)
        lay.addWidget(test_btn)

        self.w_printer_status = QLabel("No printer tested yet.")
        self.w_printer_status.setStyleSheet(f"color:{C['muted']}; font-size:13px;")
        lay.addWidget(self.w_printer_status)
        lay.addStretch()
        return w

    def _detect_printers(self):
        ports = []
        import sys as _sys
        if _sys.platform.startswith('linux'):
            import glob
            ports = glob.glob('/dev/usb/lp*') + glob.glob('/dev/ttyUSB*')
        elif _sys.platform == 'win32':
            ports = ['LPT1', 'COM1', 'COM2', 'COM3', 'USB']
        self.w_printer_list.clear()
        self.w_printer_list.addItem("— Select printer —")
        for p in ports:
            self.w_printer_list.addItem(p)
        if ports:
            self.w_printer_status.setText(f"Found {len(ports)} device(s)")
            self.w_printer_status.setStyleSheet(f"color:{C['ok']}; font-size:13px;")
        else:
            self.w_printer_status.setText("No USB printers detected. You can configure manually.")
            self.w_printer_status.setStyleSheet(f"color:{C['warn']}; font-size:13px;")

    def _test_print(self):
        self.w_printer_status.setText("Sending test page...")
        QApplication.processEvents()
        try:
            from printing.printer_engine import PrinterManager
            pm = PrinterManager(lambda: {'shop_name': self._data.get('shop_name','MBT POS')})
            pm.test_print()
            self.w_printer_status.setText("✓ Test page sent to printer.")
            self.w_printer_status.setStyleSheet(f"color:{C['ok']}; font-size:13px;")
        except Exception as e:
            self.w_printer_status.setText(f"Printer not available — skip and configure later.")
            self.w_printer_status.setStyleSheet(f"color:{C['warn']}; font-size:13px;")

    # Page — License + device registration
    def _page_license(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Register Device & Activate", 22, bold=True))
        lay.addWidget(_label(
            "This PC is registered to your Portal organization. Activate with your Portal license — "
            "no trial mode and no manual serial codes.",
            14, color=C['text2']))
        lay.addSpacing(8)

        # Device ID display
        try:
            from licensing.license_engine import get_device_id
            did = get_device_id()
            did_display = did[:8] + '•'*16 + did[-8:]
        except Exception:
            did_display = "Unavailable"

        dev_frame = QFrame()
        dev_frame.setStyleSheet(f"background:{C['card']}; border:1px solid {C['border']}; border-radius:8px;")
        df = QVBoxLayout(dev_frame)
        df.setContentsMargins(16, 12, 16, 12)
        dl = QLabel("YOUR DEVICE ID")
        dl.setStyleSheet(f"color:{C['muted']}; font-size:11px; letter-spacing:2px; font-weight:700;")
        dv = QLabel(did_display)
        dv.setStyleSheet(f"color:{C['gold']}; font-size:13px; font-family:Consolas;")
        dv.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hint = QLabel("Visible in Portal → Devices. An organization admin must approve new devices.")
        hint.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        df.addWidget(dl); df.addWidget(dv); df.addWidget(hint)
        lay.addWidget(dev_frame)
        lay.addSpacing(8)

        reg_btn = SecondaryBtn("Register Device with Portal", 42)
        reg_btn.clicked.connect(self._register_device_now)
        lay.addWidget(reg_btn, 0, Qt.AlignLeft)

        form = QFormLayout()
        form.setSpacing(14)
        self.w_license_key = QLineEdit()
        self.w_license_key.setPlaceholderText("Paste your Portal license key")
        self.w_license_key.setFont(QFont('Consolas', 12))
        self.w_license_key.setMinimumHeight(44)
        fl = QLabel("License Key"); fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        form.addRow(fl, self.w_license_key)
        lay.addLayout(form)

        act_btn = PrimaryBtn("✓  Activate License", 44)
        act_btn.setObjectName("primaryBtn")
        act_btn.setMinimumHeight(44)
        act_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        act_btn.clicked.connect(self._validate_license)
        lay.addWidget(act_btn, 0, Qt.AlignLeft)

        self.w_lic_status = QLabel("")
        self.w_lic_status.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        lay.addWidget(self.w_lic_status)
        lay.addStretch()
        return w

    def _register_device_now(self):
        try:
            from backend.cloud.device_service import get_device_service
            ok, msg = get_device_service(lambda: self._data).register()
            self.w_lic_status.setText(("✓ " if ok else "✗ ") + msg)
            self.w_lic_status.setStyleSheet(
                f"color:{C['ok'] if ok else C['err']}; font-size:13px; font-weight:600;")
            self._data['device_registered'] = bool(ok)
        except Exception as e:
            self.w_lic_status.setText(f"Device registration failed: {e}")
            self.w_lic_status.setStyleSheet(f"color:{C['err']}; font-size:13px;")

    def _validate_license(self):
        key = self.w_license_key.text().strip()
        if not key:
            self.w_lic_status.setText("License key is required.")
            self.w_lic_status.setStyleSheet(f"color:{C['err']}; font-size:13px;")
            return
        try:
            self._register_device_now()
            from licensing.license_engine import LicenseEngine
            engine = LicenseEngine(PROJECT_ROOT)
            ok, msg = engine.activate_with_key(key)
            if ok:
                self._data['license_key'] = key
                self._data['license_activated'] = True
            self.w_lic_status.setText(("✓ " if ok else "✗ ") + msg)
            self.w_lic_status.setStyleSheet(
                f"color:{C['ok'] if ok else C['err']}; font-size:13px; font-weight:600;")
        except Exception as e:
            self.w_lic_status.setText(f"Validation error: {e}")
            self.w_lic_status.setStyleSheet(f"color:{C['warn']}; font-size:13px;")

    def _page_telegram_removed(self):
        """Legacy stub — Telegram permanently removed from onboarding."""
        w, lay = self._page_container()
        lay.addWidget(_label("MugoByte Workspace", 22, bold=True))
        lay.addWidget(_label(
            "Manage licenses, devices, downloads and support at portal.mugobyte.com.\n"
            "Telegram has been permanently removed — use Portal notifications and email.",
            14, color=C['text2']))
        lay.addSpacing(8)

        info = QFrame()
        info.setStyleSheet(f"background:{C['card']}; border:1px solid {C['border']}; border-radius:8px;")
        il = QVBoxLayout(info)
        il.setContentsMargins(16, 12, 16, 12)
        il.addWidget(_label(
            "Recommended flow:\n"
            "1. Create or sign in at portal.mugobyte.com\n"
            "2. Download the latest installer from Downloads\n"
            "3. Activate this device with your Portal license key\n"
            "4. Live shop ops stay on {shop}.mugobyte.com (separate from Portal)",
            13, color=C['text2']))
        lay.addWidget(info)
        lay.addSpacing(8)

        self.w_tg_chat_id = _field("")
        self.w_tg_chat_id.hide()

        open_btn = PrimaryBtn("Open Portal Download Center", 44)
        open_btn.clicked.connect(self._start_tg_connect)
        lay.addWidget(open_btn)

        self.w_tg_status = QLabel("Optional — open Portal now, or continue and finish later in Settings.")
        self.w_tg_status.setWordWrap(True)
        self.w_tg_status.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        lay.addWidget(self.w_tg_status)
        lay.addStretch()
        return w

    def _start_tg_connect(self):
        import webbrowser
        webbrowser.open("https://portal.mugobyte.com/downloads")
        self.w_tg_status.setText("Opened portal.mugobyte.com/downloads — notifications use Portal + email.")
        self.w_tg_status.setStyleSheet(f"color:{C['ok']}; font-size:13px;")

    # Page 7 — Live Dashboard (Cloudflare / mugobyte.com)
    def _page_remote_web(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Live Dashboard", 22, bold=True))
        lay.addWidget(_label(
            "View shop sales and inventory from anywhere via your mugobyte.com link. "
            "Local access (same Wi‑Fi) works without Cloudflare.",
            14, color=C['text2']))
        lay.addSpacing(8)

        self._cf_mode_lan = QRadioButton("LAN only — http://<shop-pc-ip>:5050  (no setup needed)")
        self._cf_mode_remote = QRadioButton("Remote access — https://<shop>.mugobyte.com")
        self._cf_mode_lan.setChecked(True)
        self._cf_mode_lan.setStyleSheet(f"color:{C['text']}; font-size:14px;")
        self._cf_mode_remote.setStyleSheet(f"color:{C['text']}; font-size:14px;")
        lay.addWidget(self._cf_mode_lan)
        lay.addWidget(self._cf_mode_remote)

        remote_box = QFrame()
        remote_box.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:8px; }}")
        rbl = QVBoxLayout(remote_box)
        rbl.setContentsMargins(16, 14, 16, 14)
        rbl.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)
        self.w_cf_subdomain_lbl = QLabel("—")
        self.w_cf_subdomain_lbl.setStyleSheet(
            f"color:{C['text']}; font-size:14px; font-weight:600; background:transparent;")
        fl = QLabel("Your web link (from shop name)")
        fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        form.addRow(fl, self.w_cf_subdomain_lbl)
        rbl.addLayout(form)

        cf_note = QLabel(
            "After setup, your link may take up to 5 minutes to work. "
            "MBT POS fixes slow shop-router DNS on this PC automatically. "
            "Windows may show Allow once — click Yes. "
            "Click Set Up Cloudflare once and wait.")
        cf_note.setWordWrap(True)
        cf_note.setStyleSheet(f"color:{C['muted']}; font-size:11px; background:transparent;")
        rbl.addWidget(cf_note)

        self.w_cf_preview = QLabel("https://….mugobyte.com")
        self.w_cf_preview.setStyleSheet(
            f"color:{C['gold']}; font-size:15px; font-weight:700; font-family:Consolas;")
        rbl.addWidget(self.w_cf_preview)

        btn_row = QHBoxLayout()
        self._cf_setup_btn = PrimaryBtn("Set Up Cloudflare → mugobyte.com", 40)
        self._cf_setup_btn.clicked.connect(self._run_cloudflare_setup)
        self._cf_test_btn = SecondaryBtn("Test Connection", 40)
        self._cf_test_btn.clicked.connect(self._test_cloudflare)
        btn_row.addWidget(self._cf_setup_btn)
        btn_row.addWidget(self._cf_test_btn)
        rbl.addLayout(btn_row)

        self.w_cf_status = QLabel("Choose remote access, then click Set Up Cloudflare.")
        self.w_cf_status.setWordWrap(True)
        self.w_cf_status.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        rbl.addWidget(self.w_cf_status)

        self.w_cf_log = QTextEdit()
        self.w_cf_log.setReadOnly(True)
        self.w_cf_log.setMinimumHeight(120)
        self.w_cf_log.setPlaceholderText("Setup log appears here…")
        self.w_cf_log.setStyleSheet(
            f"background:{C['surface']}; color:{C['text2']}; font-family:Consolas; font-size:11px;")
        rbl.addWidget(self.w_cf_log)

        lay.addWidget(remote_box)
        self._cf_remote_box = remote_box
        self._cf_mode_lan.toggled.connect(self._toggle_cf_remote_box)
        self._cf_mode_remote.toggled.connect(self._toggle_cf_remote_box)
        self._toggle_cf_remote_box()
        lay.addStretch()
        return w

    def _toggle_cf_remote_box(self):
        remote = self._cf_mode_remote.isChecked()
        self._cf_remote_box.setEnabled(remote)
        if remote:
            self._refresh_cf_subdomain()

    def _wizard_subdomain(self) -> str:
        try:
            from backend.cloudflare_setup import shop_to_subdomain
            shop = self._data.get('shop_name') or self.w_shop_name.text().strip()
            return shop_to_subdomain(shop) if shop else ''
        except Exception:
            return ''

    def _refresh_cf_subdomain(self):
        sub = self._wizard_subdomain()
        if hasattr(self, 'w_cf_subdomain_lbl'):
            self.w_cf_subdomain_lbl.setText(sub or '—')
        self._update_cf_preview()

    def _update_cf_preview(self, *_):
        try:
            from backend.cloudflare_setup import full_domain
            sub = self._wizard_subdomain()
            dom = full_domain(sub) if sub else '….mugobyte.com'
            self.w_cf_preview.setText(f'https://{dom}')
        except Exception:
            pass

    def _cf_log_append(self, level: str, msg: str):
        colours = {'error': C['err'], 'warn': C['warn'], 'ok': C['ok']}
        colour = colours.get(level, C['text2'])
        self.w_cf_log.append(f'<span style="color:{colour}">{msg}</span>')
        self.w_cf_log.verticalScrollBar().setValue(
            self.w_cf_log.verticalScrollBar().maximum())

    def _run_cloudflare_setup(self):
        if self._cf_setup_running:
            return
        if not self._cf_mode_remote.isChecked():
            self._show_err("Select “Remote access” first.")
            return
        shop = self._data.get('shop_name') or self.w_shop_name.text().strip()
        if not shop:
            self._show_err("Enter shop name on step 2 first.")
            return
        sub = self._wizard_subdomain()
        if not sub:
            self._show_err("Shop name could not be converted to a web link.")
            return

        self._cf_setup_running = True
        self._cf_setup_btn.setEnabled(False)
        self._cf_test_btn.setEnabled(False)
        self.w_cf_status.setText("⏳ Setting up your web link… This can take 1–3 minutes.")
        self.w_cf_log.clear()
        self._data['cloudflare_setup_ok'] = False

        def _cb(level, msg):
            QTimer.singleShot(0, lambda l=level, m=msg: self._cf_log_append(l, m))

        def worker():
            try:
                from backend.cloudflare_setup import CloudflareSetup
                result = CloudflareSetup(
                    shop, subdomain=sub, log_callback=_cb,
                ).run()
                QTimer.singleShot(0, lambda: self._on_cf_setup_done(result))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_cf_setup_done({
                    'ok': False, 'errors': [str(e)], 'log_path': '',
                }))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_cf_setup_done(self, result: dict):
        self._cf_setup_running = False
        self._cf_setup_btn.setEnabled(True)
        self._cf_test_btn.setEnabled(True)
        self._data['cloudflare_setup_ok'] = bool(result.get('ok'))
        self._data['remote_domain'] = result.get('domain', '')
        if result.get('ok'):
            if result.get('remote_pending_dns'):
                self.w_cf_status.setText(
                    "✓ Setup finished. Your link may take up to 5 minutes to work. "
                    "Keep MBT POS open, then click Test Connection.")
            elif result.get('remote_ok', True):
                self.w_cf_status.setText("✓ Your web link is ready.")
            else:
                self.w_cf_status.setText(
                    "✓ Setup finished. Click Test Connection — DNS may need a few minutes.")
            self.w_cf_status.setStyleSheet(f"color:{C['ok']}; font-size:13px; font-weight:600;")
        else:
            errs = '; '.join(result.get('errors', [])[:2]) or 'Setup failed'
            self.w_cf_status.setText(
                f"✗ {errs}\n\nTry again once. If it keeps failing, choose LAN only and contact MugoByte.")
            self.w_cf_status.setStyleSheet(f"color:{C['err']}; font-size:13px; font-weight:600;")
            log_path = result.get('log_path', '')
            if log_path:
                self.w_cf_log.append(
                    f'<span style="color:{C["muted"]}">Full log: {log_path}</span>')

    def _test_cloudflare(self):
        self.w_cf_status.setText("⏳ Running diagnostics…")
        self._cf_test_btn.setEnabled(False)

        def _cb(level, msg):
            QTimer.singleShot(0, lambda l=level, m=msg: self._cf_log_append(l, m))

        def worker():
            try:
                from backend.cloudflare_setup import run_diagnostics
                rep = run_diagnostics(_cb)
                QTimer.singleShot(0, lambda: self._on_cf_test_done(rep))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_cf_test_done({'ok': False, 'checks': []}))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_cf_test_done(self, report: dict):
        self._cf_test_btn.setEnabled(True)
        ok = report.get('ok', False)
        self.w_cf_status.setText(
            "✓ All checks passed." if ok else "✗ Some checks failed — see log below.")
        self.w_cf_status.setStyleSheet(
            f"color:{C['ok' if ok else 'err']}; font-size:13px; font-weight:600;")
        for c in report.get('checks', []):
            mark = 'OK' if c.get('ok') else 'FAIL'
            fix = f" — Fix: {c['fix']}" if not c.get('ok') and c.get('fix') else ''
            self._cf_log_append(
                'ok' if c.get('ok') else 'error',
                f'{mark}: {c.get("name")} ({c.get("detail", "")}){fix}')

    # Page — Portal Account (required for new installs)
    def _page_portal_account(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Portal Account", 22, True))
        lay.addWidget(_label(
            "Create an account or sign in to MugoByte Workspace. Email verification is required. "
            "This device will appear under Portal → Devices for approval.",
            13, color=C['text2']))
        lay.addSpacing(12)

        open_btn = SecondaryBtn("Open portal.mugobyte.com", 40)
        open_btn.clicked.connect(
            lambda: __import__('webbrowser').open('https://portal.mugobyte.com/register'))
        lay.addWidget(open_btn, 0, Qt.AlignLeft)
        lay.addSpacing(8)

        self.w_cloud_email = _field("Business email")
        self.w_cloud_pw = _field("Password (12+ characters)", password=True)
        self.w_cloud_biz = _field("Business name (for Create Account)")
        for f in (self.w_cloud_email, self.w_cloud_pw, self.w_cloud_biz):
            lay.addWidget(f)
            lay.addSpacing(8)

        btn_row = QHBoxLayout()
        create_btn = PrimaryBtn("Create Account", 42)
        create_btn.clicked.connect(self._cloud_create)
        login_btn = SecondaryBtn("Sign In", 42)
        login_btn.clicked.connect(self._cloud_login)
        btn_row.addWidget(create_btn)
        btn_row.addWidget(login_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self.w_cloud_status = _label(
            "Internet required. After create/sign-in, verify your email if prompted, then continue.",
            12, color=C['muted'])
        lay.addSpacing(10)
        lay.addWidget(self.w_cloud_status)
        lay.addStretch()
        return w

    def _cloud_create(self):
        email = self.w_cloud_email.text().strip()
        pw = self.w_cloud_pw.text()
        name = self.w_cloud_biz.text().strip() or self._data.get('shop_name') or 'My Business'
        if not email or not pw:
            self.w_cloud_status.setText("Email and password are required.")
            return
        if len(pw) < 12:
            self.w_cloud_status.setText("Password must be at least 12 characters.")
            return
        try:
            from backend.cloud_backup.auth_service import create_business
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                self.w_cloud_status.setText(
                    "Cloud credentials missing on this PC. Contact MugoByte support — "
                    "installer should ship production Portal config.")
                self._data['cloud_mode'] = 'skipped_unconfigured'
                return
            r = create_business(email, pw, name)
            self._data['cloud_mode'] = 'created'
            self._data['cloud_business_id'] = r.get('business_id')
            self._data['portal_notifications'] = True
            try:
                from backend.cloud.device_service import get_device_service
                get_device_service(lambda: self._data).register()
            except Exception:
                pass
            self.w_cloud_status.setText(
                f"Account ready · device {r.get('device_id')}. "
                "If email verification is required, confirm it before activating a license.")
        except Exception as e:
            self.w_cloud_status.setText(f"Cloud create failed: {e}")

    def _cloud_login(self):
        email = self.w_cloud_email.text().strip()
        pw = self.w_cloud_pw.text()
        if not email or not pw:
            self.w_cloud_status.setText("Email and password are required.")
            return
        try:
            from backend.cloud_backup.auth_service import login_existing
            from backend.cloud_backup.paths import is_cloud_configured
            if not is_cloud_configured():
                self.w_cloud_status.setText(
                    "Cloud credentials missing on this PC. Contact MugoByte support.")
                return
            r = login_existing(email, pw)
            self._data['cloud_mode'] = 'login'
            self._data['cloud_business_id'] = r.get('business_id')
            self._data['portal_notifications'] = True
            try:
                from backend.cloud.device_service import get_device_service
                get_device_service(lambda: self._data).register()
            except Exception:
                pass
            if r.get('has_backups'):
                n = len(r.get('backups') or [])
                self.w_cloud_status.setText(
                    f"Signed in — {n} backup(s) found. Restore from Settings after launch "
                    "(or use Restore Latest there).")
                reply = QMessageBox.question(
                    self, "Restore from cloud?",
                    f"Found {n} backup(s) for this business.\n\n"
                    "Restore the latest backup onto this PC now?\n"
                    "(A pre-restore copy of the local DB is kept.)",
                    QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    try:
                        from backend.cloud_backup.restore_manager import RestoreManager
                        RestoreManager().restore_latest(password=pw)
                        self.w_cloud_status.setText(
                            "Restore complete — restart POS after wizard finishes.")
                        self._data['cloud_restored'] = True
                    except Exception as re:
                        self.w_cloud_status.setText(f"Restore later in Settings: {re}")
            else:
                self.w_cloud_status.setText(
                    f"Signed in · device {r.get('device_id')}. Continue to activate license.")
        except Exception as e:
            self.w_cloud_status.setText(f"Cloud login failed: {e}")

    def _cloud_skip(self):
        """Fresh installs cannot skip Portal account creation."""
        self.w_cloud_status.setText(
            "Portal account is required for new installations. Sign in or create an account.")
        self.w_cloud_status.setStyleSheet(f"color:{C['err']}; font-size:13px;")

    # Page 9 — Complete
    def _page_complete(self):
        w, lay = self._page_container()
        lay.addStretch()

        check = QLabel("✓")
        check.setAlignment(Qt.AlignCenter)
        check.setStyleSheet(f"color:{C['ok']}; font-size:72px; background:transparent;")

        t1 = QLabel("Setup Complete!")
        t1.setAlignment(Qt.AlignCenter)
        t1.setStyleSheet(f"color:{C['text']}; font-size:26px; font-weight:800; background:transparent;")

        self.w_summary = QLabel("")
        self.w_summary.setAlignment(Qt.AlignCenter)
        self.w_summary.setStyleSheet(f"color:{C['text2']}; font-size:14px; background:transparent;")
        self.w_summary.setWordWrap(True)

        brand = QLabel("MUGOBYTE TECHNOLOGIES  ·  mugobyte.com")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet(f"color:{C['muted']}; font-size:12px; letter-spacing:2px; background:transparent;")

        lay.addWidget(check)
        lay.addSpacing(8)
        lay.addWidget(t1)
        lay.addSpacing(12)
        lay.addWidget(self.w_summary)
        lay.addSpacing(24)
        lay.addWidget(brand)
        lay.addStretch()
        return w

    # ── Navigation ──────────────────────────────────────────────────────────────

    def _go_to(self, step):
        self._step = step
        self._stack.setCurrentIndex(step)
        self._step_lbl.setText(f"Step {step+1} of {len(STEPS)}")
        self._title_hdr.setText(STEPS[step][1])
        self._prog.setValue(step)
        self._back_btn.setEnabled(step > 0)

        # Printer + Live Dashboard remain optional; Portal + License are required.
        skippable = step in (5, 6)
        self._skip_btn.setVisible(skippable)

        if step == 1:
            if hasattr(self, 'w_cloud_biz') and not self.w_cloud_biz.text().strip():
                self.w_cloud_biz.setText(self._data.get('shop_name') or '')
            try:
                from backend.cloud_backup.device_manager import get_or_create_device_id
                get_or_create_device_id()
            except Exception:
                pass

        if step == 6:
            self._refresh_cf_subdomain()

        if step == len(STEPS) - 1:
            self._next_btn.setText("Launch POS  →")
            self._next_btn.setObjectName("successBtn")
            self._next_btn.style().unpolish(self._next_btn)
            self._next_btn.style().polish(self._next_btn)
            self._update_summary()
        else:
            self._next_btn.setText("Continue  →")
            self._next_btn.setObjectName("primaryBtn")
            self._next_btn.style().unpolish(self._next_btn)
            self._next_btn.style().polish(self._next_btn)

        for i, btn in enumerate(self._step_btns):
            if i < step:
                btn.setStyleSheet(self._step_style('done'))
                btn.setText(f"  ✓ {i+1:02d}  {STEPS[i][0]}")
            elif i == step:
                btn.setStyleSheet(self._step_style('active'))
                btn.setText(f"  ▶ {i+1:02d}  {STEPS[i][0]}")
            else:
                btn.setStyleSheet(self._step_style('pending'))
                btn.setText(f"  {i+1:02d}  {STEPS[i][0]}")

    def _prev(self):
        if self._step > 0:
            self._go_to(self._step - 1)

    def _next(self):
        if not self._validate_step():
            return
        self._collect_step()
        if self._step < len(STEPS) - 1:
            self._go_to(self._step + 1)
        else:
            self._finish()

    def _validate_step(self) -> bool:
        step = self._step
        if step == 1:
            mode = self._data.get('cloud_mode')
            if mode not in ('created', 'login'):
                self._show_err("Sign in or create a Portal account before continuing.")
                return False
        elif step == 2:
            key = self.w_license_key.text().strip()
            if not key and not self._data.get('license_activated'):
                self._show_err("Activate your Portal license key to continue. There is no trial mode.")
                return False
        elif step == 3:
            if not self.w_shop_name.text().strip():
                self._show_err("Shop name is required.")
                return False
        elif step == 4:
            u = self.w_admin_user.text().strip()
            p = self.w_admin_pw.text()
            p2 = self.w_admin_pw2.text()
            if not u:
                self._show_err("Username is required.")
                return False
            if len(p) < 8:
                self._show_err("Password must be at least 8 characters.")
                return False
            if p != p2:
                self._show_err("Passwords do not match.")
                return False
        return True

    def _collect_step(self):
        step = self._step
        if step == 1:
            self._data['portal_notifications'] = True
            self._data['telegram_chat_id'] = ''
        elif step == 2:
            self._data['license_key'] = self.w_license_key.text().strip()
        elif step == 3:
            self._data['shop_name']     = self.w_shop_name.text().strip()
            self._data['shop_address']  = self.w_shop_location.text().strip()
            self._data['shop_phone']    = self.w_shop_phone.text().strip()
            self._data['currency']      = self.w_currency.currentText()
        elif step == 4:
            self._data['admin_user']    = self.w_admin_user.text().strip() or 'admin'
            self._data['admin_pw']      = self.w_admin_pw.text()
            self._data['admin_pin']     = self.w_admin_pin.text().strip()
        elif step == 5:
            sel = self.w_printer_list.currentText()
            self._data['printer_port']  = sel if sel != "— Select printer —" else self.w_printer_port.text().strip()
            self._data['auto_print']    = '1' if self.w_auto_print.isChecked() else '0'
        elif step == 6:
            remote = self._cf_mode_remote.isChecked()
            sub = self._wizard_subdomain()
            self._data['remote_web'] = remote
            self._data['tunnel_subdomain'] = sub
            try:
                from backend.cloudflare_setup import (
                    full_domain, save_web_config, shop_to_subdomain,
                )
                if remote and sub:
                    save_web_config({
                        'base_domain': 'mugobyte.com',
                        'tunnel_subdomain': shop_to_subdomain(sub),
                        'tunnel_domain': full_domain(sub),
                        'tunnel_name': f"mbt-pos-{shop_to_subdomain(sub)}",
                        'remote_enabled': True,
                        'remote_setup_ok': bool(self._data.get('cloudflare_setup_ok')),
                    })
                else:
                    save_web_config({'remote_enabled': False})
            except Exception:
                pass

    def _update_summary(self):
        shop = self._data.get('shop_name', '(not set)')
        user = self._data.get('admin_user', 'admin')
        prt  = self._data.get('printer_port', 'Not configured')
        lic  = 'Activated' if self._data.get('license_key') else 'Pending'
        notif = 'Portal + Email'
        if self._data.get('remote_web'):
            dom = self._data.get('remote_domain') or ''
            if not dom and self._data.get('tunnel_subdomain'):
                try:
                    from backend.cloudflare_setup import full_domain
                    dom = full_domain(self._data['tunnel_subdomain'])
                except Exception:
                    dom = ''
            web = f'https://{dom}' if dom else 'Remote (setup pending)'
        else:
            web = 'LAN only (port 5050)'
        cloud = {
            'created': 'Cloud business created',
            'login': 'Cloud logged in',
            'offline': 'Cloud offline',
            'skipped': 'Cloud skipped',
            'skipped_unconfigured': 'Cloud (not configured)',
        }.get(self._data.get('cloud_mode'), 'Cloud optional')
        if self._data.get('cloud_restored'):
            cloud += ' · restored'
        self.w_summary.setText(
            f"Shop: {shop}  ·  Admin: {user}\n"
            f"Printer: {prt}  ·  License: {lic}  ·  Notifications: {notif}\n"
            f"Web dashboard: {web}\n"
            f"{cloud}"
        )

    def _show_err(self, msg):
        QMessageBox.warning(self, "Validation", msg)

    def _finish(self):
        self._collect_step()
        self._apply_config()
        mark_initialized()
        self.completed.emit(self._data)
        self.accept()

    def _apply_config(self):
        """Write wizard data into the database."""
        try:
            db_path = get_db_path()
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

            # Ensure schema exists before writing — creates DB if it doesn't exist yet
            import sys as _sys
            _sys.path.insert(0, PROJECT_ROOT)
            from desktop.utils.api_client import _db as _get_db, _ensure_schema
            _init_conn = _get_db()   # this creates + seeds the DB
            _init_conn.close()

            db = sqlite3.connect(db_path)
            try:
                from config.deploy import load_deploy_config, shop_settings_defaults
                deploy = load_deploy_config()
                extra  = shop_settings_defaults()
            except Exception:
                deploy = {}
                extra  = {}
            settings = {
                'shop_name':            self._data.get('shop_name', 'My Shop'),
                'shop_address':         self._data.get('shop_address', ''),
                'shop_phone':           self._data.get('shop_phone', ''),
                'currency_symbol':      self._data.get('currency', 'KES'),
                'printer_port':         self._data.get('printer_port', ''),
                'auto_print':           self._data.get('auto_print', '1'),
                'auto_report_daily':    '1',
                'auto_report_weekly':   '0',
                'auto_report_interval_hours': '4',
                'auto_db_backup': '1',
                'auto_local_db_backup': '1',
                'auto_local_db_backup_interval_hours': '6',
                'mpesa_mode':           'manual',
                'mpesa_business_name':  self._data.get('shop_name', 'My Shop'),
            }
            if deploy.get('developer_chat_id'):
                settings['developer_chat_id'] = str(deploy['developer_chat_id'])
            for k, v in settings.items():
                db.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?,?)", (k, v))

            # Create/update admin user (same hash format as login API)
            admin_user = self._data.get('admin_user', 'admin')
            admin_pw   = self._data.get('admin_pw', 'admin123')

            from desktop.utils.api_client import _hash_pw
            from roles import default_tab_permissions
            import json as _json
            pw_hash = _hash_pw(admin_pw)

            existing = db.execute(
                "SELECT id FROM users WHERE username=?", (admin_user,)).fetchone()
            perms = _json.dumps(default_tab_permissions('superadmin'))
            if existing:
                db.execute(
                    "UPDATE users SET password_hash=?, role=?, tab_permissions=? WHERE username=?",
                    (pw_hash, 'superadmin', perms, admin_user))
            else:
                db.execute(
                    "INSERT INTO users (username, password_hash, role, full_name, tab_permissions) "
                    "VALUES (?,?,?,?,?)",
                    (admin_user, pw_hash, 'superadmin', 'Shop Owner', perms))

            db.commit()
            db.close()
        except Exception as e:
            import logging as _lg
            _lg.getLogger('setup_wizard').error(f"_apply_config failed: {e}", exc_info=True)
            # Show error to user so they know to re-enter password after relaunch
            try:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(None, 'Setup Warning',
                    f'Settings were saved but some configuration failed:\n{e}\n\n'
                    'You can log in with the default password "admin123" and update it in Admin → Users.')
            except Exception:
                pass
