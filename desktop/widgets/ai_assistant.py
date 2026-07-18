"""
Floating AI Assistant — available on every MainWindow screen.

Modern chat panel: markdown-ish rendering, streaming, suggestions, regenerate,
copy, typing indicator, conversation history. Theme follows ThemeManager.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, QSize,
)
from PyQt5.QtGui import QFont, QTextCursor, QClipboard
from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QScrollArea, QSizePolicy, QApplication, QMessageBox, QListWidget,
    QListWidgetItem, QSplitter, QInputDialog, QGraphicsOpacityEffect,
)

from desktop.utils.theme import C, ThemeManager, qss_alpha, RADIUS
from desktop.utils.ai import get_ai_service
from desktop.utils.ai.connectivity import get_connectivity, OFFLINE_BANNER
from desktop.utils.ai.actions import format_action_preview, ProposedAction
from desktop.utils.ai.conversations import get_conversation_store

log = logging.getLogger('ai.assistant')


class _ChatWorker(QThread):
    chunk = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self.payload = payload

    def run(self):
        try:
            svc = get_ai_service()

            def _cb(piece: str):
                self.chunk.emit(piece)

            out = svc.chat(
                user_message=self.payload['message'],
                api=self.payload['api'],
                user=self.payload['user'],
                module=self.payload.get('module') or 'dashboard',
                history=self.payload.get('history') or [],
                conversation_id=self.payload.get('conversation_id'),
                stream_callback=_cb,
                use_stream=True,
            )
            self.finished_ok.emit(out)
        except Exception as e:
            log.exception('chat worker')
            self.failed.emit(str(e))


def _md_to_html(text: str) -> str:
    """Lightweight markdown → HTML (bold, code, lists, newlines)."""
    import html
    import re
    s = html.escape(text or '')
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?m)^\- (.+)$', r'• \1', s)
    s = s.replace('\n', '<br/>')
    return s


# Friendly module labels for the panel subtitle
_MODULE_LABELS = {
    'dashboard': 'Dashboard Assistant',
    'sales': 'Sales Assistant',
    'inventory': 'Inventory Assistant',
    'debt': 'Credit & Debt Assistant',
    'accounting': 'Accounting Assistant',
    'reports': 'Reports Assistant',
    'purchasing': 'Purchasing Assistant',
    'settings': 'Settings Assistant',
    'diagnostics': 'Diagnostics Assistant',
    'ai_ops': 'AI Operations',
    'consumption': 'Consumption Assistant',
    'notes': 'Notes Assistant',
}


class AiAssistantPanel(QFrame):
    """Slide-over chat panel hosted by MainWindow."""

    PANEL_WIDTH = 520

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self._module = 'dashboard'
        self._conversation_id: Optional[str] = None
        self._history: List[Dict[str, str]] = []
        self._last_user_msg = ''
        self._worker: Optional[_ChatWorker] = None
        self._streaming_buf = ''
        self.setObjectName('mbtAiPanel')
        self.setMinimumWidth(self.PANEL_WIDTH)
        self.setFixedWidth(self.PANEL_WIDTH)
        self.hide()
        self._build()
        self.refresh_theme()
        conn = get_connectivity()
        conn.subscribe(lambda online: QTimer.singleShot(0, self._on_conn))
        conn.start_watch(45)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame(); hdr.setObjectName('mbtAiHdr')
        hl = QHBoxLayout(hdr); hl.setContentsMargins(18, 14, 14, 14); hl.setSpacing(10)
        self._title = QLabel('MBT AI')
        self._title.setObjectName('mbtAiTitle')
        self._sub = QLabel('Dashboard Assistant')
        self._sub.setObjectName('mbtAiSub')
        tit_col = QVBoxLayout(); tit_col.setSpacing(2)
        tit_col.addWidget(self._title); tit_col.addWidget(self._sub)
        hl.addLayout(tit_col, 1)

        self._new_btn = QPushButton('+'); self._new_btn.setFixedSize(36, 36)
        self._new_btn.setToolTip('New conversation')
        self._new_btn.clicked.connect(self.new_chat)
        self._hist_btn = QPushButton('≡'); self._hist_btn.setFixedSize(36, 36)
        self._hist_btn.setToolTip('Chat history')
        self._hist_btn.setCheckable(True)
        self._hist_btn.clicked.connect(self._toggle_history)
        self._close_btn = QPushButton('×'); self._close_btn.setFixedSize(36, 36)
        self._close_btn.setToolTip('Close assistant')
        self._close_btn.clicked.connect(self.close_panel)
        for b in (self._new_btn, self._hist_btn, self._close_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName('mbtAiIconBtn')
            hl.addWidget(b)
        root.addWidget(hdr)

        self._banner = QLabel('')
        self._banner.setObjectName('mbtAiBanner')
        self._banner.setWordWrap(True)
        self._banner.hide()
        root.addWidget(self._banner)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        # History list
        self._hist_list = QListWidget()
        self._hist_list.setObjectName('mbtAiHist')
        self._hist_list.setFixedWidth(170)
        self._hist_list.hide()
        self._hist_list.itemClicked.connect(self._load_history_item)
        body.addWidget(self._hist_list)

        # Chat column
        chat_col = QWidget()
        cl = QVBoxLayout(chat_col); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chat_host = QWidget()
        self._chat_lay = QVBoxLayout(self._chat_host)
        self._chat_lay.setContentsMargins(16, 16, 16, 16)
        self._chat_lay.setSpacing(12)
        self._chat_lay.addStretch(1)
        self._scroll.setWidget(self._chat_host)
        cl.addWidget(self._scroll, 1)

        # Suggestions — stacked full-width so labels never truncate
        sug_wrap = QFrame(); sug_wrap.setObjectName('mbtAiSugWrap')
        self._sug_col = QVBoxLayout(sug_wrap)
        self._sug_col.setContentsMargins(14, 8, 14, 8)
        self._sug_col.setSpacing(8)
        self._sug_label = QLabel('TRY ASKING')
        self._sug_label.setObjectName('mbtAiSugLabel')
        self._sug_col.addWidget(self._sug_label)
        cl.addWidget(sug_wrap)

        # Typing
        self._typing = QLabel('MBT AI is thinking…')
        self._typing.setObjectName('mbtAiTyping')
        self._typing.hide()
        cl.addWidget(self._typing)

        # Composer
        comp = QFrame(); comp.setObjectName('mbtAiComposer')
        cpl = QHBoxLayout(comp); cpl.setContentsMargins(14, 12, 14, 14); cpl.setSpacing(10)
        self._input = QTextEdit()
        self._input.setPlaceholderText(
            'Ask about sales, stock, customers, or this screen…')
        self._input.setFixedHeight(76)
        self._input.setObjectName('mbtAiInput')
        self._send = QPushButton('Send')
        self._send.setObjectName('mbtAiSend')
        self._send.setCursor(Qt.PointingHandCursor)
        self._send.setFixedHeight(76)
        self._send.setMinimumWidth(88)
        self._send.setFixedWidth(96)
        self._send.clicked.connect(self._on_send)
        cpl.addWidget(self._input, 1)
        cpl.addWidget(self._send)
        cl.addWidget(comp)

        body.addWidget(chat_col)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)

        self._empty_hint()
        self._reload_suggestions()

    def _empty_hint(self):
        tip = QLabel(
            '<p style="margin:0 0 10px 0;"><b>Ask anything about this screen</b></p>'
            '<p style="margin:0 0 8px 0;">Answers use your shop data — filtered by your role.</p>'
            '<p style="margin:0;">MBT AI never changes stock, sales, or money '
            'without your explicit approval.</p>'
        )
        tip.setObjectName('mbtAiHint')
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignCenter)
        tip.setTextFormat(Qt.RichText)
        tip.setMinimumHeight(120)
        self._chat_lay.insertWidget(self._chat_lay.count() - 1, tip)
        self._hint = tip

    def set_module(self, module: str):
        self._module = (module or 'dashboard').lower()
        label = _MODULE_LABELS.get(
            self._module,
            f'{self._module.replace("_", " ").title()} Assistant',
        )
        self._sub.setText(label)
        self._reload_suggestions()

    def _reload_suggestions(self):
        # Keep header label; clear chip buttons only
        while self._sug_col.count() > 1:
            item = self._sug_col.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()
        for s in get_ai_service().suggestions(self._module)[:3]:
            b = QPushButton(s)
            b.setObjectName('mbtAiChip')
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(40)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setStyleSheet('')  # theme QSS applies
            # Elide-proof: full text + tooltip
            b.setToolTip(s)
            b.setText(s)
            b.clicked.connect(lambda _, t=s: self._use_suggestion(t))
            self._sug_col.addWidget(b)
        self.refresh_theme()

    def _use_suggestion(self, text: str):
        self._input.setPlainText(text)
        self._on_send()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        p = C
        r = RADIUS.get('xl', 14)
        self.setStyleSheet(
            f"""
            QFrame#mbtAiPanel {{
                background:{p['card']}; border-left:1px solid {p['border']};
            }}
            QFrame#mbtAiHdr {{
                background:{p['card2']}; border-bottom:1px solid {p['border']};
            }}
            QLabel#mbtAiTitle {{
                color:{p['text']}; font-size:18px; font-weight:800; background:transparent;
            }}
            QLabel#mbtAiSub {{
                color:{p['text2']}; font-size:13px; font-weight:600; background:transparent;
            }}
            QPushButton#mbtAiIconBtn {{
                background:{p['input']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:9px; font-size:15px;
            }}
            QPushButton#mbtAiIconBtn:hover {{ border-color:{p['gold']}; color:{p['gold']}; }}
            QLabel#mbtAiBanner {{
                background:{qss_alpha(p['warn'], 0.18)}; color:{p['warn']};
                padding:10px 14px; font-size:13px; font-weight:600;
                border-bottom:1px solid {qss_alpha(p['warn'], 0.35)};
            }}
            QLabel#mbtAiTyping {{
                color:{p['gold']}; font-size:13px; font-weight:600;
                padding:6px 16px; background:transparent;
            }}
            QLabel#mbtAiHint {{
                color:{p['text2']}; font-size:15px;
                padding:24px 22px; background:transparent;
            }}
            QFrame#mbtAiSugWrap {{
                background:{p['card2']}; border-top:1px solid {p['border']};
            }}
            QLabel#mbtAiSugLabel {{
                color:{p['muted']}; font-size:12px; font-weight:800;
                letter-spacing:1px; background:transparent; border:none;
                padding:0 2px 4px 2px;
            }}
            QFrame#mbtAiComposer {{
                background:{p['card2']}; border-top:1px solid {p['border']};
            }}
            QTextEdit#mbtAiInput {{
                background:{p['input']}; color:{p['text']}; border:1.5px solid {p['border']};
                border-radius:12px; padding:10px 12px; font-size:15px;
            }}
            QTextEdit#mbtAiInput:focus {{ border-color:{p['gold']}; }}
            QPushButton#mbtAiSend {{
                background:{p['gold']}; color:{p.get('gold_fg', '#0A0F1A')};
                border:none; border-radius:12px; font-weight:800; font-size:15px;
            }}
            QPushButton#mbtAiSend:hover {{ background:{p.get('gold_lt', p['gold'])}; }}
            QPushButton#mbtAiSend:disabled {{ background:{p['border']}; color:{p['muted']}; }}
            QPushButton#mbtAiChip {{
                background:{p['input']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:10px; padding:12px 16px; font-size:14px; font-weight:600;
                text-align:left;
            }}
            QPushButton#mbtAiChip:hover {{
                border-color:{p['gold']}; color:{p['gold']};
                background:{qss_alpha(p['gold'], 0.10)};
            }}
            QListWidget#mbtAiHist {{
                background:{p['card2']}; color:{p['text']}; border:none;
                border-right:1px solid {p['border']}; font-size:13px;
            }}
            QScrollArea {{ background:transparent; border:none; }}
            """
        )
        # Restyle bubbles
        for i in range(self._chat_lay.count()):
            w = self._chat_lay.itemAt(i).widget()
            if w and hasattr(w, 'refresh_theme'):
                w.refresh_theme()

    # ── Open / close ──────────────────────────────────────────────────────────

    def open_panel(self):
        self.refresh_theme()
        self._on_conn()
        self.show()
        self.raise_()
        self._reposition()
        self._input.setFocus()

    def close_panel(self):
        self.hide()

    def toggle(self):
        if self.isVisible():
            self.close_panel()
        else:
            self.open_panel()

    def _reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        h = parent.height()
        # Leave room for status bar ~36 and topbar — panel fills right edge of content
        self.setFixedHeight(h)
        self.move(parent.width() - self.width(), 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)

    # ── Connectivity banner ───────────────────────────────────────────────────

    def _on_conn(self):
        st = get_ai_service().status()
        if st.get('banner'):
            self._banner.setText('⚠  ' + st['banner'])
            self._banner.show()
        else:
            self._banner.hide()

    # ── Chat bubbles ──────────────────────────────────────────────────────────

    def _add_bubble(self, role: str, text: str, actions: Optional[list] = None) -> '_Bubble':
        if getattr(self, '_hint', None):
            self._hint.hide()
        b = _Bubble(role, text, actions=actions or [], panel=self)
        self._chat_lay.insertWidget(self._chat_lay.count() - 1, b)
        QTimer.singleShot(30, self._scroll_bottom)
        return b

    def _scroll_bottom(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear_chat_widgets(self):
        while self._chat_lay.count() > 1:
            item = self._chat_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._empty_hint()

    def new_chat(self):
        self._conversation_id = None
        self._history = []
        self._clear_chat_widgets()

    def _toggle_history(self, on: bool):
        if on:
            self._refresh_history_list()
            self._hist_list.show()
        else:
            self._hist_list.hide()

    def _refresh_history_list(self):
        self._hist_list.clear()
        u = self.mw.user_data.get('user') or {}
        uid = str(u.get('id') or u.get('username') or '')
        for row in get_conversation_store().list(uid):
            title = row.get('title') or 'Chat'
            pin = '📌 ' if row.get('pinned') else ''
            item = QListWidgetItem(f"{pin}{title}")
            item.setData(Qt.UserRole, row)
            self._hist_list.addItem(item)

    def _load_history_item(self, item: QListWidgetItem):
        row = item.data(Qt.UserRole) or {}
        cid = row.get('id')
        if not cid:
            return
        self._conversation_id = cid
        self._history = []
        self._clear_chat_widgets()
        msgs = get_conversation_store().messages(cid)
        for m in msgs:
            role = m.get('role') or 'assistant'
            content = m.get('content') or ''
            self._add_bubble(role, content)
            if role in ('user', 'assistant'):
                self._history.append({'role': role, 'content': content})

    # ── Send / stream ─────────────────────────────────────────────────────────

    def _on_send(self):
        msg = (self._input.toPlainText() or '').strip()
        if not msg:
            return
        if self._worker and self._worker.isRunning():
            return
        self._input.clear()
        self._last_user_msg = msg
        self._add_bubble('user', msg)
        self._history.append({'role': 'user', 'content': msg})
        self._typing.show()
        try:
            from desktop.utils.audio_manager import play as _audio_play
            _audio_play('ai_thinking')
        except Exception:
            pass
        self._send.setEnabled(False)
        self._streaming_buf = ''
        self._stream_bubble = self._add_bubble('assistant', '')

        payload = {
            'message': msg,
            'api': self.mw.api,
            'user': self.mw.user_data,
            'module': self._module,
            'history': list(self._history[:-1]),
            'conversation_id': self._conversation_id,
        }
        self._worker = _ChatWorker(payload, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_chunk(self, piece: str):
        self._streaming_buf += piece
        if getattr(self, '_stream_bubble', None):
            self._stream_bubble.set_text(self._streaming_buf)
            self._scroll_bottom()

    def _on_done(self, result: dict):
        self._typing.hide()
        self._send.setEnabled(True)
        try:
            from desktop.utils.audio_manager import play as _audio_play
            _audio_play('ai_ready')
        except Exception:
            pass
        self._conversation_id = result.get('conversation_id') or self._conversation_id
        text = result.get('text') or ''
        actions = result.get('actions') or []
        if getattr(self, '_stream_bubble', None):
            # Prefer final sanitized text
            self._stream_bubble.set_text(text)
            self._stream_bubble.set_actions(actions)
        else:
            self._add_bubble('assistant', text, actions)
        self._history.append({'role': 'assistant', 'content': text})
        self._on_conn()
        for act in actions:
            self._prompt_action(act)

    def _on_fail(self, err: str):
        self._typing.hide()
        self._send.setEnabled(True)
        msg = f'AI error: {err}'
        if getattr(self, '_stream_bubble', None):
            self._stream_bubble.set_text(msg)
        else:
            self._add_bubble('assistant', msg)

    def regenerate(self):
        if not self._last_user_msg:
            return
        self._input.setPlainText(self._last_user_msg)
        self._on_send()

    def _prompt_action(self, action: ProposedAction):
        if not isinstance(action, ProposedAction):
            return
        if not action.permission_ok(self.mw.user_data):
            QMessageBox.information(
                self, 'Action not allowed',
                'Your role cannot approve this AI-proposed action.')
            return
        preview = format_action_preview(action)
        box = QMessageBox(self)
        box.setWindowTitle('Approve AI Action?')
        box.setText(
            'MBT AI proposed an action. Nothing has been changed yet.\n\n' + preview)
        approve = box.addButton('Approve', QMessageBox.AcceptRole)
        edit = box.addButton('Edit…', QMessageBox.ActionRole)
        cancel = box.addButton('Cancel', QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == cancel:
            return
        if clicked == edit:
            text, ok = QInputDialog.getMultiLineText(
                self, 'Edit action payload', 'JSON / notes:',
                str(action.payload))
            if not ok:
                return
            action.payload = {'_edited': text}
        # MVP: do not mutate DB — acknowledge and offer navigation hints
        QMessageBox.information(
            self, 'Action noted',
            f'Approved locally: {action.action}\n\n'
            'v1 records your approval in chat. '
            'Open Inventory / Purchasing to apply stock changes manually.\n'
            f'Payload: {action.payload}')
        self._add_bubble(
            'assistant',
            f'✅ You approved **{action.action}**. Apply changes from the relevant module when ready.',
        )


class _Bubble(QFrame):
    def __init__(self, role: str, text: str, actions=None, panel=None):
        super().__init__()
        self.role = role
        self.panel = panel
        self.setObjectName('mbtAiBubbleUser' if role == 'user' else 'mbtAiBubbleAi')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        who = QLabel('You' if role == 'user' else 'MBT AI')
        who.setObjectName('mbtAiWho')
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setOpenExternalLinks(False)
        lay.addWidget(who)
        lay.addWidget(self._body)
        self._actions_host = QVBoxLayout()
        lay.addLayout(self._actions_host)
        if role == 'assistant':
            row = QHBoxLayout()
            copy_btn = QPushButton('Copy')
            regen = QPushButton('Regenerate')
            for b in (copy_btn, regen):
                b.setObjectName('mbtAiMini')
                b.setCursor(Qt.PointingHandCursor)
                row.addWidget(b)
            row.addStretch()
            copy_btn.clicked.connect(self._copy)
            regen.clicked.connect(lambda: panel and panel.regenerate())
            lay.addLayout(row)
            self._copy_btn = copy_btn
            self._regen_btn = regen
        self.set_text(text)
        self.set_actions(actions or [])
        self.refresh_theme()

    def set_text(self, text: str):
        self._raw = text or ''
        self._body.setText(_md_to_html(self._raw))

    def set_actions(self, actions):
        while self._actions_host.count():
            item = self._actions_host.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for act in actions or []:
            if not isinstance(act, ProposedAction):
                continue
            b = QPushButton(f'⚡ {act.summary or act.action}')
            b.setObjectName('mbtAiAction')
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, a=act: self.panel and self.panel._prompt_action(a))
            self._actions_host.addWidget(b)

    def _copy(self):
        QApplication.clipboard().setText(self._raw or '')

    def refresh_theme(self):
        p = C
        if self.role == 'user':
            bg = qss_alpha(p['gold'], 0.14)
            border = qss_alpha(p['gold'], 0.35)
        else:
            bg = p['card2']
            border = p['border']
        self.setStyleSheet(
            f"QFrame {{ background:{bg}; border:1px solid {border}; border-radius:12px; }}"
            f"QLabel#mbtAiWho {{ color:{p['muted']}; font-size:11px; font-weight:700;"
            f" background:transparent; border:none; }}"
            f"QLabel {{ color:{p['text']}; font-size:14px; background:transparent; border:none; }}"
            f"QPushButton#mbtAiMini {{ background:transparent; color:{p['text2']}; border:none;"
            f" font-size:12px; padding:4px 8px; }}"
            f"QPushButton#mbtAiMini:hover {{ color:{p['gold']}; }}"
            f"QPushButton#mbtAiAction {{ background:{qss_alpha(p['info'], 0.15)}; color:{p['info']};"
            f" border:1px solid {qss_alpha(p['info'], 0.4)}; border-radius:8px;"
            f" padding:8px 12px; font-size:13px; font-weight:600; text-align:left; }}"
        )


class AiFabButton(QPushButton):
    """Floating launcher — bottom-right of MainWindow content."""

    def __init__(self, parent=None):
        super().__init__('✦ AI', parent)
        self.setObjectName('mbtAiFab')
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(64, 64)
        self.refresh_theme()

    def refresh_theme(self):
        p = C
        fg = p.get('gold_fg', '#0A0F1A')
        self.setStyleSheet(
            f"QPushButton#mbtAiFab {{ background:{p['gold']}; color:{fg}; border:none;"
            f" border-radius:32px; font-size:14px; font-weight:800; }}"
            f"QPushButton#mbtAiFab:hover {{ background:{p.get('gold_lt', p['gold'])}; }}"
        )
