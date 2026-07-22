"""
MBT POS — Activation Screen
MugoByte Technologies | mugobyte.com
Shown on first launch when no valid license is found.
"""
import sys
import os
import threading
import time

from mbt_paths import get_project_root, get_db_path

PROJECT_ROOT = get_project_root()
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QScrollArea, QWidget, QMessageBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QIcon

try:
    from desktop.utils.theme import C
except Exception:
    C = {
        'gold': '#F2A800', 'gold_lt': '#FFBE3A', 'gold_dk': '#C07800',
        'ok': '#00C97E', 'err': '#FF3D50', 'warn': '#F0A500',
        'text': '#EEF2FC', 'text2': '#6880A0', 'muted': '#334D68',
        'app': '#05080F', 'card': '#0F1A2E', 'card2': '#132034',
        'border2': '#18283E', 'hover': '#162A44', 'input': '#0C1626',
        'gold_fg': '#0A0F1A',
    }

# Footer must fit 3 full-size buttons on 125–150 % Windows scaling
_FOOTER_MIN_H = 188
_BTN_H = 50


def _style_primary(btn: QPushButton):
    btn.setMinimumHeight(_BTN_H)
    btn.setMaximumHeight(_BTN_H + 8)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{"
        f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        f"    stop:0 {C['gold_lt']}, stop:1 {C['gold']});"
        f"  color: #0A0F18;"
        f"  border: none;"
        f"  border-radius: 8px;"
        f"  font-size: 15px;"
        f"  font-weight: 800;"
        f"  padding: 0 16px;"
        f"}}"
        f"QPushButton:hover {{ background: {C['gold_lt']}; }}"
        f"QPushButton:pressed {{ background: {C['gold_dk']}; }}"
        f"QPushButton:disabled {{"
        f"  background: {C['card2']}; color: {C['muted']};"
        f"  border: 1px solid {C['border2']}; }}"
    )


def _style_success(btn: QPushButton):
    btn.setMinimumHeight(_BTN_H)
    btn.setMaximumHeight(_BTN_H + 8)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{"
        f"  background: {C['ok']};"
        f"  color: #0A0F18;"
        f"  border: none;"
        f"  border-radius: 8px;"
        f"  font-size: 14px;"
        f"  font-weight: 700;"
        f"  padding: 0 12px;"
        f"}}"
        f"QPushButton:hover {{ background: #1DFAA0; }}"
        f"QPushButton:disabled {{"
        f"  background: {C['card2']}; color: {C['muted']};"
        f"  border: 1px solid {C['border2']}; }}"
    )


def _style_secondary(btn: QPushButton):
    btn.setMinimumHeight(44)
    btn.setMaximumHeight(52)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{"
        f"  background: {C['card2']};"
        f"  color: {C['text']};"
        f"  border: 1px solid {C['border2']};"
        f"  border-radius: 8px;"
        f"  font-size: 14px;"
        f"  font-weight: 600;"
        f"  padding: 0 12px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: {C['hover']}; border-color: {C['gold']}; }}"
    )


class ActivationDialog(QDialog):

    _chat_id_found = pyqtSignal(str)
    _tg_timeout    = pyqtSignal()

    def __init__(self, device_id, license_engine):
        super().__init__()
        self.device_id   = device_id
        self.engine      = license_engine
        self._tg_polling = False

        self.setWindowTitle("MBT POS — Activation Required")
        self.setMinimumSize(440, 620)
        self.resize(520, 760)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.setStyleSheet(self._base_stylesheet())

        self._chat_id_found.connect(self._on_chat_found)
        self._tg_timeout.connect(self._on_tg_timeout)
        self._build_ui()
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(max(geo.x(), x), max(geo.y(), y))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top: action buttons (fixed height, never scrolled away) ─────────
        actions = QFrame()
        actions.setObjectName("actActions")
        actions.setMinimumHeight(_FOOTER_MIN_H)
        actions.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        al = QVBoxLayout(actions)
        al.setContentsMargins(20, 16, 20, 16)
        al.setSpacing(10)

        act_hint = QLabel("Step 3 — Activate")
        act_hint.setStyleSheet(
            f"color:{C['gold']}; font-size:11px; font-weight:700; "
            f"letter-spacing:1px; background:transparent;")
        al.addWidget(act_hint)

        self._act_btn = QPushButton("Activate License")
        _style_primary(self._act_btn)
        self._act_btn.clicked.connect(self._activate)
        al.addWidget(self._act_btn)

        self._cloud_btn = QPushButton("Activate with Cloud Key")
        _style_success(self._cloud_btn)
        self._cloud_btn.setToolTip("Use a license key from portal.mugobyte.com (Telegram removed)")
        self._cloud_btn.clicked.connect(self._focus_key_field)
        al.addWidget(self._cloud_btn)

        exit_btn = QPushButton("Exit Application")
        _style_secondary(exit_btn)
        exit_btn.clicked.connect(self.reject)
        al.addWidget(exit_btn)

        root.addWidget(actions)

        # ── Bottom: scrollable instructions + fields ───────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{C['app']}; border: none; }}"
            f"QScrollBar:vertical {{ background:{C['card']}; width: 10px; }}"
            f"QScrollBar::handle:vertical {{ background:{C['border2']}; "
            f"border-radius: 5px; min-height: 24px; }}"
        )

        body = QWidget()
        body.setStyleSheet(f"background:{C['app']};")
        content = QVBoxLayout(body)
        content.setContentsMargins(20, 16, 20, 20)
        content.setSpacing(12)

        # Exact HD logo (transparent — no black/white plate)
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
                        _pm.scaled(260, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    break
        ico = os.path.join(_assets, 'mbt_icon.ico')
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        eye = QLabel("MUGOBYTE TECHNOLOGIES")
        eye.setAlignment(Qt.AlignCenter)
        eye.setStyleSheet(
            f"color:{C['text2']}; font-size:10px; letter-spacing:2px; "
            f"font-weight:600; background:transparent;")

        title = QLabel("Software Activation")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color:{C['gold']}; font-size:22px; font-weight:900; "
            f"background:transparent;")

        sub = QLabel("Activate this computer to use MBT POS.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")

        content.addWidget(logo)
        content.addWidget(eye)
        content.addWidget(title)
        content.addWidget(sub)

        # Step 1 — Sign in to MugoByte (cloud-first: auto-activates this device)
        content.addWidget(self._section_label("Step 1 — Sign in to MugoByte"))
        signin_card = self._card()
        sl = QVBoxLayout(signin_card)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(8)
        sl.addWidget(self._hint(
            "Sign in and this device is licensed automatically from your account. "
            "No key needed if a seat is available."))

        self._cloud_email = QLineEdit()
        self._cloud_email.setPlaceholderText("Business email")
        self._cloud_email.setMinimumHeight(40)
        self._style_input(self._cloud_email)
        sl.addWidget(self._cloud_email)

        self._cloud_pw = QLineEdit()
        self._cloud_pw.setPlaceholderText("Password")
        self._cloud_pw.setEchoMode(QLineEdit.Password)
        self._cloud_pw.setMinimumHeight(40)
        self._style_input(self._cloud_pw)
        self._cloud_pw.returnPressed.connect(self._cloud_signin_activate)
        sl.addWidget(self._cloud_pw)

        self._signin_btn = QPushButton("Sign In & Activate")
        _style_primary(self._signin_btn)
        self._signin_btn.clicked.connect(self._cloud_signin_activate)
        sl.addWidget(self._signin_btn)
        content.addWidget(signin_card)

        # Prefill from an existing cloud identity if present
        try:
            from backend.cloud_backup.paths import load_identity
            _pref = (load_identity().get('email') or '').strip()
            if _pref:
                self._cloud_email.setText(_pref)
        except Exception:
            pass

        # Manual Portal key (online keys only — no local keygen)
        content.addWidget(self._section_label("Or paste your online license key"))
        content.addWidget(self._hint(
            "Get an MBT-… key from portal.mugobyte.com → Licenses. "
            "Local/offline keygen keys are not accepted."))

        # Step 1 — device ID
        content.addWidget(self._section_label("Your Hardware ID"))
        did_card = self._card()
        dl = QVBoxLayout(did_card)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setSpacing(8)
        dl.addWidget(self._hint(
            "Shown for support. Activation uses your Portal account or online MBT-… key."))

        self._hwid_edit = QLineEdit(self.device_id)
        self._hwid_edit.setReadOnly(True)
        self._hwid_edit.setFont(QFont("Consolas", 9))
        self._hwid_edit.setMinimumHeight(40)
        self._style_input(self._hwid_edit, gold=True)
        dl.addWidget(self._hwid_edit)

        copy_btn = QPushButton("Copy Hardware ID")
        _style_secondary(copy_btn)
        copy_btn.clicked.connect(self._copy_hwid)
        dl.addWidget(copy_btn)
        content.addWidget(did_card)

        # Step 2 — key
        content.addWidget(self._section_label("Step 2 — Activation Key"))
        key_card = self._card()
        kl = QVBoxLayout(key_card)
        kl.setContentsMargins(12, 10, 12, 10)
        kl.setSpacing(8)
        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("MBT-… online key from portal.mugobyte.com")
        self._key_input.setFont(QFont("Consolas", 10))
        self._key_input.setMinimumHeight(42)
        self._style_input(self._key_input, gold=False)
        self._key_input.returnPressed.connect(self._activate)
        kl.addWidget(self._key_input)
        content.addWidget(key_card)

        tg_note = self._hint(
            "Get a license key from portal.mugobyte.com (Licenses), then paste it above and Activate.")
        content.addWidget(tg_note)

        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        self._result_lbl.setMinimumHeight(20)
        self._result_lbl.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        content.addWidget(self._result_lbl)

        self._tg_status = QLabel("")
        self._tg_status.setWordWrap(True)
        self._tg_status.setMinimumHeight(20)
        self._tg_status.setStyleSheet(
            f"color:{C['warn']}; font-size:12px; background:transparent;")
        content.addWidget(self._tg_status)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    @staticmethod
    def _base_stylesheet():
        return f"""
        QDialog {{ background: {C['app']}; color: {C['text']}; }}
        QFrame#actActions {{
            background: {C['card']};
            border-bottom: 2px solid {C['gold']};
        }}
        QFrame#actCard {{
            background: {C['card']};
            border: 1px solid {C['border2']};
            border-radius: 10px;
        }}
        QLabel {{ background: transparent; }}
        """

    @staticmethod
    def _card():
        f = QFrame()
        f.setObjectName("actCard")
        return f

    def _section_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{C['text']}; font-size:12px; font-weight:700; "
            f"background:transparent; margin-top:4px;")
        return l

    def _hint(self, text):
        l = QLabel(text)
        l.setWordWrap(True)
        l.setStyleSheet(
            f"color:{C['text2']}; font-size:11px; background:transparent;")
        return l

    def _style_input(self, field: QLineEdit, gold: bool = False):
        color = C['gold'] if gold else C['text']
        field.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {C['input']};"
            f"  color: {color};"
            f"  border: 1px solid {C['border2']};"
            f"  border-radius: 8px;"
            f"  padding: 8px 10px;"
            f"  font-size: 13px;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {C['gold']}; }}"
        )

    def _copy_hwid(self):
        QApplication.clipboard().setText(self.device_id)
        self._result_lbl.setText("Hardware ID copied to clipboard.")
        self._result_lbl.setStyleSheet(
            f"color:{C['ok']}; font-size:12px; background:transparent;")

    def _cloud_signin_activate(self):
        email = self._cloud_email.text().strip()
        pw = self._cloud_pw.text()
        if not email or not pw:
            self._set_result("Enter your MugoByte email and password.", error=True)
            return

        self._signin_btn.setEnabled(False)
        self._signin_btn.setText("Signing in…")
        QApplication.processEvents()
        try:
            from licensing.cloud_onboarding import auto_claim_device_license
            res = auto_claim_device_license(self.engine, email=email, password=pw)
            if res.get('ok'):
                self._set_result(res.get('message') or "Device activated from your account.")
                self.accept()
                return
            reason = res.get('reason') or ''
            msg = res.get('message') or "Could not auto-activate."
            if reason in ('no_seat', 'no_org'):
                msg += "  You can paste a license key below instead."
            self._set_result(msg, error=True)
        except Exception as e:
            self._set_result(f"Sign in failed: {e}", error=True)
        finally:
            self._signin_btn.setEnabled(True)
            self._signin_btn.setText("Sign In & Activate")

    def _activate(self):
        key = self._key_input.text().strip()
        if not key:
            self._set_result("Please enter the activation key.", error=True)
            return

        self._act_btn.setEnabled(False)
        self._act_btn.setText("Activating…")
        QApplication.processEvents()

        try:
            ok, msg = self.engine.activate_with_key(key)
            self._set_result(msg, error=not ok)
            if ok:
                # Inline result label already shows success — no extra OK MessageBox
                self.accept()
        finally:
            self._act_btn.setEnabled(True)
            self._act_btn.setText("Activate License")

    def _set_result(self, msg, error=False):
        color = C['err'] if error else C['ok']
        self._result_lbl.setText(msg)
        self._result_lbl.setStyleSheet(
            f"color:{color}; font-size:12px; background:transparent;")

    def _get_bot_token(self) -> str:
        return ''  # Telegram removed — use license key or cloud activation

    def _focus_key_field(self):
        self._set_result(
            'Paste your cloud license key from portal.mugobyte.com, then click Activate.',
            error=False,
        )
        try:
            self._key_input.setFocus()
            self._key_input.selectAll()
        except Exception:
            pass

    def _start_tg_listen(self):
        self._focus_key_field()

    def _on_chat_found(self, key: str):
        self._key_input.setText(key)
        self._activate()

    def _on_tg_timeout(self):
        self._set_result('Paste your license key above.', error=True)


def show_activation_screen(device_id, engine):
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication.instance() or QApplication(sys.argv)
    dlg = ActivationDialog(device_id, engine)
    return dlg.exec_() == QDialog.Accepted
