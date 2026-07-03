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
from PyQt5.QtGui import QFont

try:
    from desktop.utils.theme import C
except Exception:
    C = {
        'gold': '#F0A500', 'gold_lt': '#FFBE3A', 'gold_dk': '#D4880A',
        'ok': '#00D68F', 'err': '#FF4757', 'warn': '#FFAA00',
        'text': '#F0F4FC', 'text2': '#6E8FA8', 'muted': '#374F66',
        'app': '#070C14', 'card': '#111F33', 'card2': '#162540',
        'border2': '#1A2D44', 'hover': '#192D48', 'input': '#0F1C30',
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

        self._tg_btn = QPushButton("Wait for Key (Telegram)")
        _style_success(self._tg_btn)
        self._tg_btn.clicked.connect(self._start_tg_listen)
        al.addWidget(self._tg_btn)

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

        content.addWidget(eye)
        content.addWidget(title)
        content.addWidget(sub)

        # Step 1 — device ID
        content.addWidget(self._section_label("Step 1 — Your Hardware ID"))
        did_card = self._card()
        dl = QVBoxLayout(did_card)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.setSpacing(8)
        dl.addWidget(self._hint(
            "Send this ID to MugoByte to receive your activation key."))

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
        self._key_input.setPlaceholderText("Paste your license key here…")
        self._key_input.setFont(QFont("Consolas", 10))
        self._key_input.setMinimumHeight(42)
        self._style_input(self._key_input, gold=False)
        self._key_input.returnPressed.connect(self._activate)
        kl.addWidget(self._key_input)
        content.addWidget(key_card)

        tg_note = self._hint(
            "Telegram option: message @mbt_admin1_bot, then tap "
            "\"Wait for Key (Telegram)\" at the top.")
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
                QMessageBox.information(
                    self, "Activated",
                    f"{msg}\n\nThe application will now start.")
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
        try:
            import sqlite3
            from backend.telegram_hub import resolve_bot_token
            db_path = get_db_path()
            cfg = {}
            if os.path.exists(db_path):
                db = sqlite3.connect(db_path)
                rows = db.execute(
                    "SELECT key, value FROM system_settings "
                    "WHERE key IN ('telegram_bot_token', 'shop_name')"
                ).fetchall()
                db.close()
                cfg = {k: v for k, v in rows}
            return resolve_bot_token(cfg)
        except Exception:
            pass
        try:
            from config.deploy import load_deploy_config
            return (load_deploy_config().get('telegram_bot_token') or '').strip()
        except Exception:
            return ''

    def _early_cfg(self) -> dict:
        try:
            import sqlite3
            db_path = get_db_path()
            if os.path.exists(db_path):
                db = sqlite3.connect(db_path)
                rows = db.execute("SELECT key, value FROM system_settings").fetchall()
                db.close()
                return {k: v for k, v in rows}
        except Exception:
            pass
        try:
            from config.deploy import shop_settings_defaults
            return shop_settings_defaults()
        except Exception:
            return {}

    def _start_tg_listen(self):
        if self._tg_polling:
            return
        token = self._get_bot_token()
        if not token:
            QMessageBox.warning(
                self, "Not Ready",
                "Bot token is not configured.\n"
                "Contact MugoByte Technologies.")
            return

        try:
            from backend.telegram_hub import resolve_bot_username, get_hub, start_hub
            bot = resolve_bot_username()
        except Exception:
            from backend.telegram_hub import get_hub, start_hub
            bot = 'mbt_admin1_bot'

        if not get_hub():
            start_hub(self._early_cfg)

        self._tg_polling = True
        self._tg_btn.setEnabled(False)
        self._tg_btn.setText("Listening…")
        self._tg_status.setText(
            f"Open Telegram, message @{bot}, then wait here…")
        self._tg_status.setStyleSheet(
            f"color:{C['warn']}; font-size:12px; background:transparent;")

        hub = get_hub()

        def on_update(upd: dict) -> bool:
            if not self._tg_polling:
                return True
            text = (upd.get('message', {}) or {}).get('text', '').strip()
            key = None
            if text.startswith('/send_key '):
                key = text[len('/send_key '):].strip()
            elif '.' in text and len(text) > 40 and ' ' not in text:
                key = text
            if key:
                self._chat_id_found.emit(key)
                return True
            return False

        hub._advance_offset_past_backlog(token)
        hub.begin_capture(on_update, 300)

        def _timer():
            deadline = time.time() + 300
            while self._tg_polling and time.time() < deadline:
                time.sleep(1)
            if self._tg_polling:
                self._tg_timeout.emit()
                hub.end_capture()

        threading.Thread(target=_timer, daemon=True).start()

    def _on_chat_found(self, key: str):
        self._tg_polling = False
        self._tg_btn.setEnabled(True)
        self._tg_btn.setText("Wait for Key (Telegram)")
        self._tg_status.setText("Key received — activating…")
        self._tg_status.setStyleSheet(
            f"color:{C['ok']}; font-size:12px; background:transparent;")
        self._key_input.setText(key)
        self._activate()

    def _on_tg_timeout(self):
        self._tg_polling = False
        self._tg_btn.setEnabled(True)
        self._tg_btn.setText("Wait for Key (Telegram)")
        self._tg_status.setText("Timed out — paste your key above or try again.")
        self._tg_status.setStyleSheet(
            f"color:{C['err']}; font-size:12px; background:transparent;")


def show_activation_screen(device_id, engine):
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication.instance() or QApplication(sys.argv)
    dlg = ActivationDialog(device_id, engine)
    return dlg.exec_() == QDialog.Accepted
