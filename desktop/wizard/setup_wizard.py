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

from desktop.utils.theme import MBT_STYLESHEET, C
from desktop.utils.widgets import PrimaryBtn, SecondaryBtn, SuccessBtn, DangerBtn

INIT_FLAG = get_init_flag_path()

STEPS = [
    ("Welcome",          "Welcome to MBT POS"),
    ("Shop Info",        "Your Shop Details"),
    ("Admin Account",    "Create Admin Account"),
    ("Printer Setup",    "Printer Configuration"),
    ("License",          "License Activation"),
    ("Telegram & Sync",  "Remote Monitoring"),
    ("Remote Web",       "Remote Web Dashboard"),
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
        self.setStyleSheet(MBT_STYLESHEET)

        self._step   = 0
        self._data   = {}
        self._pages  = []
        self._step_btns = []

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

    def _build_sidebar(self):
        sb = QWidget()
        sb.setFixedWidth(240)
        sb.setStyleSheet(f"background:{C['app']}; border-right:1px solid {C['border']};")
        sl = QVBoxLayout(sb)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Logo area
        logo_w = QWidget()
        logo_w.setFixedHeight(100)
        logo_w.setStyleSheet(f"background:{C['app']}; border-bottom:2px solid {C['gold']};")
        ll = QVBoxLayout(logo_w)
        ll.setAlignment(Qt.AlignCenter)
        lt = QLabel("MBT")
        lt.setAlignment(Qt.AlignCenter)
        lt.setStyleSheet(f"color:{C['gold']}; font-size:32px; font-weight:900; letter-spacing:6px;")
        ls = QLabel("SETUP WIZARD")
        ls.setAlignment(Qt.AlignCenter)
        ls.setStyleSheet(f"color:{C['muted']}; font-size:10px; letter-spacing:3px;")
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
        raw_pages = [
            self._page_welcome(),
            self._page_shop(),
            self._page_admin(),
            self._page_printer(),
            self._page_license(),
            self._page_telegram(),
            self._page_remote_web(),
            self._page_complete(),
        ]
        # Scroll long steps so footer nav buttons are never covered by content.
        self._pages = [
            self._scroll_page(p) if i in (3, 4, 5, 6) else p
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

        logo = QLabel("MBT")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"color:{C['gold']}; font-size:72px; font-weight:900; letter-spacing:12px; background:transparent;")

        t1 = QLabel("Welcome to MBT POS System")
        t1.setAlignment(Qt.AlignCenter)
        t1.setStyleSheet(f"color:{C['text']}; font-size:26px; font-weight:800; background:transparent;")

        t2 = QLabel("Professional Point of Sale for your business.\nThis wizard will set up your system in under 5 minutes.")
        t2.setAlignment(Qt.AlignCenter)
        t2.setStyleSheet(f"color:{C['text2']}; font-size:15px; line-height:1.6; background:transparent;")
        t2.setWordWrap(True)

        brand = QLabel("MUGOBYTE TECHNOLOGIES  ·  mugobyte.com")
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
        detect_btn = SecondaryBtn("🔍  Detect Printers", 40)
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

        test_btn = SecondaryBtn("🖨  Print Test Page", 40)
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

    # Page 5 — License
    def _page_license(self):
        w, lay = self._page_container()
        lay.addWidget(_label("License Activation", 22, bold=True))
        lay.addWidget(_label("Activate your MBT POS license. You can skip this and activate later.", 14, color=C['text2']))
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
        hint = QLabel("Share this ID with MugoByte Technologies to receive your license key.")
        hint.setStyleSheet(f"color:{C['text2']}; font-size:12px;")
        df.addWidget(dl); df.addWidget(dv); df.addWidget(hint)
        lay.addWidget(dev_frame)
        lay.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(14)
        self.w_license_key = QLineEdit()
        self.w_license_key.setPlaceholderText("Paste license key here  (or skip to activate later)")
        self.w_license_key.setFont(QFont('Consolas', 12))
        self.w_license_key.setMinimumHeight(44)
        fl = QLabel("License Key"); fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        form.addRow(fl, self.w_license_key)
        lay.addLayout(form)

        act_btn = PrimaryBtn("✓  Validate Key", 44)
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

    def _validate_license(self):
        key = self.w_license_key.text().strip()
        if not key:
            return
        try:
            from licensing.license_engine import LicenseEngine
            engine = LicenseEngine(PROJECT_ROOT)
            ok, msg = engine.activate_with_key(key)
            self.w_lic_status.setText(("✓ " if ok else "✗ ") + msg)
            self.w_lic_status.setStyleSheet(
                f"color:{C['ok'] if ok else C['err']}; font-size:13px; font-weight:600;")
        except Exception as e:
            self.w_lic_status.setText(f"Validation error: {e}")
            self.w_lic_status.setStyleSheet(f"color:{C['warn']}; font-size:13px;")

    # Page 6 — Telegram
    def _page_telegram(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Remote Monitoring  (Optional)", 22, bold=True))
        lay.addWidget(_label("Connect Telegram for remote alerts, license management, and sync.", 14, color=C['text2']))
        lay.addSpacing(8)

        try:
            from config.deploy import load_deploy_config
            bot_user = (load_deploy_config().get('telegram_bot_username') or 'mbt_admin1_bot').lstrip('@')
        except Exception:
            bot_user = 'mbt_admin1_bot'

        info = QFrame()
        info.setStyleSheet(f"background:{C['card']}; border:1px solid {C['border']}; border-radius:8px;")
        il = QVBoxLayout(info)
        il.setContentsMargins(16, 12, 16, 12)
        il.addWidget(_label(f"Bot: @{bot_user}  is pre-configured", 13, color=C['ok']))
        il.addWidget(_label("Send any message to the bot to link your account.", 13, color=C['text2']))
        lay.addWidget(info)
        lay.addSpacing(8)

        form = QFormLayout()
        form.setSpacing(14)
        self.w_tg_chat_id = _field("Your Telegram Chat ID  (run SETUP TELEGRAM.bat to get it)")

        find_btn = SecondaryBtn("🔍  Find My Chat ID", 40)
        find_btn.setFixedWidth(180)
        find_btn.clicked.connect(self._find_chat_id)

        fl = QLabel("Your Chat ID"); fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        form.addRow(fl, self.w_tg_chat_id)
        lay.addLayout(form)
        lay.addWidget(find_btn)

        self.w_tg_status = QLabel("")
        self.w_tg_status.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        lay.addWidget(self.w_tg_status)
        lay.addStretch()
        return w

    def _find_chat_id(self):
        from config.deploy import load_deploy_config
        from backend.telegram_hub import resolve_bot_username, wait_for_chat_message

        deploy = load_deploy_config()
        bot_user = (deploy.get('telegram_bot_username') or 'mbt_admin1_bot').lstrip('@')
        self.w_tg_status.setText(f"⏳ Waiting — send any message to @{bot_user}...")
        self.w_tg_status.setStyleSheet(f"color:{C['text2']}; font-size:13px;")
        QApplication.processEvents()

        def config_getter():
            return {
                'telegram_bot_token': deploy.get('telegram_bot_token', ''),
                'shop_name': self._data.get('shop_name', 'My Shop'),
            }

        def on_chat(chat_id, _msg):
            self.w_tg_chat_id.setText(str(chat_id))
            self.w_tg_status.setText(f"✓ Chat ID found: {chat_id}")
            self.w_tg_status.setStyleSheet(f"color:{C['ok']}; font-size:13px;")

        def on_err(msg):
            self.w_tg_status.setText(f"✗ {msg}")

        def on_to():
            self.w_tg_status.setText("Timed out. You can configure Telegram later in Settings.")

        import threading
        threading.Thread(
            target=wait_for_chat_message,
            args=(config_getter, on_chat, on_to, on_err, 30),
            daemon=True,
        ).start()

    # Page 7 — Remote Web Dashboard (Cloudflare / mugobyte.com)
    def _page_remote_web(self):
        w, lay = self._page_container()
        lay.addWidget(_label("Remote Web Dashboard", 22, bold=True))
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
        self.w_cf_subdomain = _field("e.g. doe-supermarket")
        self.w_cf_subdomain.textChanged.connect(self._update_cf_preview)
        fl = QLabel("Subdomain"); fl.setStyleSheet(f"color:{C['text2']}; font-size:14px;")
        form.addRow(fl, self.w_cf_subdomain)
        rbl.addLayout(form)

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

    def _refresh_cf_subdomain(self):
        try:
            from backend.cloudflare_setup import shop_to_subdomain
            shop = self._data.get('shop_name') or self.w_shop_name.text().strip()
            if shop and not self.w_cf_subdomain.text().strip():
                self.w_cf_subdomain.setText(shop_to_subdomain(shop))
            self._update_cf_preview()
        except Exception:
            pass

    def _update_cf_preview(self, *_):
        try:
            from backend.cloudflare_setup import full_domain
            sub = self.w_cf_subdomain.text().strip()
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
        if not self._cf_mode_remote.isChecked():
            self._show_err("Select “Remote access” first.")
            return
        shop = self._data.get('shop_name') or self.w_shop_name.text().strip()
        if not shop:
            self._show_err("Enter shop name on step 2 first.")
            return
        sub = self.w_cf_subdomain.text().strip()
        if not sub:
            self._show_err("Enter a subdomain slug.")
            return

        self._cf_setup_btn.setEnabled(False)
        self._cf_test_btn.setEnabled(False)
        self.w_cf_status.setText("⏳ Setting up Cloudflare tunnel…")
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
        self._cf_setup_btn.setEnabled(True)
        self._cf_test_btn.setEnabled(True)
        self._data['cloudflare_setup_ok'] = bool(result.get('ok'))
        self._data['remote_domain'] = result.get('domain', '')
        if result.get('ok'):
            remote_ok = result.get('remote_ok', True)
            self.w_cf_status.setText(
                "✓ Cloudflare configured. "
                + ("Remote URL is live." if remote_ok else
                   "DNS may take a few minutes — use Test Connection."))
            self.w_cf_status.setStyleSheet(f"color:{C['ok']}; font-size:13px; font-weight:600;")
        else:
            errs = '; '.join(result.get('errors', [])[:2]) or 'Setup failed'
            self.w_cf_status.setText(f"✗ {errs}")
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

    # Page 8 — Complete
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

        skippable = step in (3, 4, 5, 6)
        self._skip_btn.setVisible(skippable)

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
            if not self.w_shop_name.text().strip():
                self._show_err("Shop name is required.")
                return False
        elif step == 2:
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
            self._data['shop_name']     = self.w_shop_name.text().strip()
            self._data['shop_address']  = self.w_shop_location.text().strip()
            self._data['shop_phone']    = self.w_shop_phone.text().strip()
            self._data['currency']      = self.w_currency.currentText()
        elif step == 2:
            self._data['admin_user']    = self.w_admin_user.text().strip() or 'admin'
            self._data['admin_pw']      = self.w_admin_pw.text()
            self._data['admin_pin']     = self.w_admin_pin.text().strip()
        elif step == 3:
            sel = self.w_printer_list.currentText()
            self._data['printer_port']  = sel if sel != "— Select printer —" else self.w_printer_port.text().strip()
            self._data['auto_print']    = '1' if self.w_auto_print.isChecked() else '0'
        elif step == 4:
            self._data['license_key']   = self.w_license_key.text().strip()
        elif step == 5:
            self._data['telegram_chat_id'] = self.w_tg_chat_id.text().strip()
        elif step == 6:
            remote = self._cf_mode_remote.isChecked()
            sub = self.w_cf_subdomain.text().strip()
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
        tg   = 'Connected' if self._data.get('telegram_chat_id') else 'Skipped'
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
        self.w_summary.setText(
            f"Shop: {shop}  ·  Admin: {user}\n"
            f"Printer: {prt}  ·  License: {lic}  ·  Telegram: {tg}\n"
            f"Web dashboard: {web}"
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
            bot_token = deploy.get('telegram_bot_token', '') or extra.get('telegram_bot_token', '')
            settings = {
                'shop_name':            self._data.get('shop_name', 'My Shop'),
                'shop_address':         self._data.get('shop_address', ''),
                'shop_phone':           self._data.get('shop_phone', ''),
                'currency_symbol':      self._data.get('currency', 'KES'),
                'telegram_chat_id':     self._data.get('telegram_chat_id', ''),
                'printer_port':         self._data.get('printer_port', ''),
                'auto_print':           self._data.get('auto_print', '1'),
                'telegram_bot_token':   bot_token,
                'auto_report_daily':    '1',
                'auto_report_weekly':   '0',
                'auto_report_interval_hours': '4',
                'mpesa_mode':           'manual',
                'mpesa_business_name':  self._data.get('shop_name', 'My Shop'),
            }
            if deploy.get('developer_chat_id'):
                settings['developer_chat_id'] = str(deploy['developer_chat_id'])
            for k, v in settings.items():
                db.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?,?)", (k, v))

            # Create/update admin user
            admin_user = self._data.get('admin_user', 'admin')
            admin_pw   = self._data.get('admin_pw', 'admin123')

            # Use same hash_pw from backend
            import hashlib
            salt = os.urandom(16).hex()
            pw_hash = salt + ':' + hashlib.sha256((salt + admin_pw).encode()).hexdigest()

            existing = db.execute(
                "SELECT id FROM users WHERE username=?", (admin_user,)).fetchone()
            perms = ('["dashboard","sales","inventory","reports","notes","settings",'
                     '"admin","users","license","diagnostics","security"]')
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
