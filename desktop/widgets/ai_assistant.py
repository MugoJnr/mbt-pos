"""
MBT AI — Enterprise Business Copilot
MugoByte Technologies | mugobyte.com

Collapsible right drawer (not a permanent chatbot). Home dashboard,
context awareness, quick actions, structured replies, workspace history.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPoint, QSize,
)
from PyQt5.QtGui import QFont, QColor, QPainter, QMouseEvent
from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QSizePolicy, QApplication, QMessageBox, QListWidget,
    QListWidgetItem, QStackedWidget, QGridLayout, QLineEdit, QSplitter,
    QGraphicsDropShadowEffect, QToolButton, QAbstractItemView,
)

from desktop.utils.theme import C, ThemeManager, qss_alpha, RADIUS
from desktop.utils.ai import get_ai_service
from desktop.utils.ai.connectivity import get_connectivity
from desktop.utils.ai.actions import format_action_preview, ProposedAction
from desktop.utils.ai.conversations import get_conversation_store
from desktop.utils.ai.insights import get_dashboard_insights, _heuristic_insights
from desktop.utils.ai.copilot_prefs import load_copilot_prefs, save_copilot_prefs

log = logging.getLogger('ai.copilot')

# Enterprise Copilot palette (overlays theme; follows light/dark)
def _copilot_colors() -> dict:
    light = ThemeManager.is_light()
    if light:
        return {
            'bg': '#F8FAFC',
            'bg2': '#FFFFFF',
            'card': '#FFFFFF',
            'sidebar': '#F1F5F9',
            'border': '#E2E8F0',
            'accent': '#D97706',
            'ok': '#059669',
            'warn': '#D97706',
            'danger': '#DC2626',
            'info': '#2563EB',
            'text': '#0F172A',
            'text2': '#475569',
            'muted': '#64748B',
        }
    return {
        'bg': '#0B1220',
        'bg2': '#111827',
        'card': '#1A2335',
        'sidebar': '#0F172A',
        'border': '#273449',
        'accent': '#FBBF24',
        'ok': '#10B981',
        'warn': '#F59E0B',
        'danger': '#EF4444',
        'info': '#3B82F6',
        'text': '#F8FAFC',
        'text2': '#CBD5E1',
        'muted': '#94A3B8',
    }


_MODULE_LABELS = {
    'dashboard': 'Dashboard',
    'sales': 'Sales / POS',
    'inventory': 'Inventory',
    'debt': 'Credit & Debt',
    'accounting': 'Accounting',
    'reports': 'Reports',
    'purchasing': 'Purchasing',
    'settings': 'Settings',
    'diagnostics': 'Diagnostics',
    'ai_ops': 'AI Operations',
    'consumption': 'Internal Consumption',
    'notes': 'Notes',
    'admin': 'Users & Admin',
    'security': 'Security',
    'license': 'License',
}

_QUICK_ACTIONS = [
    ('Analyze sales today', 'sales', '$'),
    ('Inventory health check', 'inventory', '#'),
    ('Customer / debt insights', 'debt', '@'),
    ('Explain this screen', 'context', 'o'),
    ('Detect problems', 'diagnostics', '!'),
    ('Generate report ideas', 'reports', '*'),
    ('Reorder suggestions', 'inventory', '>'),
    ('Accounting checklist', 'accounting', '='),
]


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
    import html
    import re
    s = html.escape(text or '')
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?m)^\- (.+)$', r'• \1', s)
    s = s.replace('\n', '<br/>')
    return s


class _ResizeHandle(QFrame):
    """Left-edge drag to resize docked drawer."""
    resized = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(6)
        self.setCursor(Qt.SizeHorCursor)
        self._dragging = False
        self._origin_x = 0
        self._origin_w = 0

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._origin_x = e.globalPos().x()
            self._origin_w = self.parentWidget().width() if self.parentWidget() else 380
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging:
            dx = self._origin_x - e.globalPos().x()
            self.resized.emit(self._origin_w + dx)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        self._dragging = False
        super().mouseReleaseEvent(e)


class _KpiCard(QFrame):
    def __init__(self, title: str, value: str = '—', tone: str = 'info', parent=None):
        super().__init__(parent)
        self.setObjectName('copilotKpi')
        self._tone = tone
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        self._t = QLabel(title)
        self._t.setObjectName('copilotKpiTitle')
        self._v = QLabel(value)
        self._v.setObjectName('copilotKpiValue')
        self._v.setWordWrap(True)
        lay.addWidget(self._t)
        lay.addWidget(self._v)

    def set_value(self, value: str, tone: str = None):
        self._v.setText(value)
        if tone:
            self._tone = tone


class _ActionCard(QPushButton):
    def __init__(self, label: str, icon: str = '', parent=None):
        super().__init__(parent)
        self.setObjectName('copilotAction')
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setText(f'{icon}  {label}' if icon else label)
        self.setToolTip(label)


class AiAssistantPanel(QFrame):
    """Enterprise Copilot drawer — docked to MainWindow right edge."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self._module = 'dashboard'
        self._conversation_id: Optional[str] = None
        self._history: List[Dict[str, str]] = []
        self._last_user_msg = ''
        self._worker: Optional[_ChatWorker] = None
        self._streaming_buf = ''
        self._prefs = load_copilot_prefs()
        self._floating = False
        self.setObjectName('mbtCopilot')
        self.setMinimumWidth(340)
        self.setMaximumWidth(640)
        w = int(self._prefs.get('width') or 380)
        self.setFixedWidth(w)
        self.hide()
        self._build()
        self.refresh_theme()
        conn = get_connectivity()
        conn.subscribe(lambda online: QTimer.singleShot(0, self._on_conn))
        conn.start_watch(45)
        QTimer.singleShot(100, self._refresh_home)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._handle = _ResizeHandle(self)
        self._handle.resized.connect(self._on_resize_drag)
        outer.addWidget(self._handle)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        outer.addLayout(root, 1)

        # Header
        hdr = QFrame(); hdr.setObjectName('copilotHdr')
        hv = QVBoxLayout(hdr); hv.setContentsMargins(12, 10, 10, 8); hv.setSpacing(8)
        hl = QHBoxLayout(); hl.setSpacing(8)
        tit = QVBoxLayout(); tit.setSpacing(2)
        self._title = QLabel('MBT Copilot')
        self._title.setObjectName('copilotTitle')
        self._context = QLabel('Context: Dashboard')
        self._context.setObjectName('copilotContext')
        tit.addWidget(self._title)
        tit.addWidget(self._context)
        hl.addLayout(tit, 1)

        self._full_btn = QToolButton()
        self._full_btn.setText('⛶')
        self._full_btn.setObjectName('copilotIconBtn')
        self._full_btn.setToolTip('Full Workspace — AI Operations Center')
        self._full_btn.setCursor(Qt.PointingHandCursor)
        self._full_btn.clicked.connect(self.open_full_workspace)
        self._mode_btn = QToolButton()
        self._mode_btn.setText('Float')
        self._mode_btn.setObjectName('copilotIconBtn')
        self._mode_btn.setToolTip('Toggle floating window')
        self._mode_btn.setCursor(Qt.PointingHandCursor)
        self._mode_btn.clicked.connect(self._toggle_float)
        self._close_btn = QToolButton()
        self._close_btn.setText('×')
        self._close_btn.setObjectName('copilotIconBtn')
        self._close_btn.setToolTip('Close')
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self.close_panel)
        hl.addWidget(self._full_btn)
        hl.addWidget(self._mode_btn)
        hl.addWidget(self._close_btn)
        hv.addLayout(hl)

        tabs = QHBoxLayout(); tabs.setSpacing(4)
        self._tab_home = QToolButton(); self._tab_home.setText('Home')
        self._tab_chat = QToolButton(); self._tab_chat.setText('Chat')
        self._tab_ws = QToolButton(); self._tab_ws.setText('Workspace')
        for b, key in (
            (self._tab_home, 'home'),
            (self._tab_chat, 'chat'),
            (self._tab_ws, 'workspace'),
        ):
            b.setCheckable(True)
            b.setObjectName('copilotTab')
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._show_tab(k))
            tabs.addWidget(b)
        tabs.addStretch(1)
        hv.addLayout(tabs)
        root.addWidget(hdr)

        self._banner = QLabel('')
        self._banner.setObjectName('copilotBanner')
        self._banner.setWordWrap(True)
        self._banner.hide()
        root.addWidget(self._banner)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_home())
        self._stack.addWidget(self._build_chat())
        self._stack.addWidget(self._build_workspace())
        root.addWidget(self._stack, 1)

        tab = self._prefs.get('last_tab') or 'home'
        self._show_tab(tab)

    def _build_home(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        hour = datetime.now().hour
        greet = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')
        self._greet = QLabel(greet)
        self._greet.setObjectName('copilotGreet')
        lay.addWidget(self._greet)

        self._status_line = QLabel('Store status · loading…')
        self._status_line.setObjectName('copilotStatus')
        self._status_line.setWordWrap(True)
        lay.addWidget(self._status_line)

        grid = QGridLayout(); grid.setSpacing(8)
        self._kpi_sales = _KpiCard('Today\'s sales', '—')
        self._kpi_inv = _KpiCard('Inventory alerts', '—', 'warn')
        self._kpi_cust = _KpiCard('Credit / debt', '—')
        self._kpi_ai = _KpiCard('AI status', '—')
        grid.addWidget(self._kpi_sales, 0, 0)
        grid.addWidget(self._kpi_inv, 0, 1)
        grid.addWidget(self._kpi_cust, 1, 0)
        grid.addWidget(self._kpi_ai, 1, 1)
        lay.addLayout(grid)

        rec_lbl = QLabel('AI RECOMMENDATIONS')
        rec_lbl.setObjectName('copilotSection')
        lay.addWidget(rec_lbl)
        self._recs = QLabel('—')
        self._recs.setObjectName('copilotRecs')
        self._recs.setWordWrap(True)
        lay.addWidget(self._recs)

        act_lbl = QLabel('QUICK ACTIONS')
        act_lbl.setObjectName('copilotSection')
        lay.addWidget(act_lbl)
        ag = QGridLayout(); ag.setSpacing(8)
        for i, (label, kind, icon) in enumerate(_QUICK_ACTIONS):
            btn = _ActionCard(label, icon)
            btn.clicked.connect(lambda _=False, t=label, k=kind: self._run_quick(t, k))
            ag.addWidget(btn, i // 2, i % 2)
        lay.addLayout(ag)

        pin_lbl = QLabel('RECENT CONVERSATIONS')
        pin_lbl.setObjectName('copilotSection')
        lay.addWidget(pin_lbl)
        self._home_recent = QListWidget()
        self._home_recent.setObjectName('copilotList')
        self._home_recent.setMaximumHeight(120)
        self._home_recent.itemClicked.connect(self._open_recent_item)
        lay.addWidget(self._home_recent)

        new_btn = QPushButton('＋  New chat about this screen')
        new_btn.setObjectName('copilotPrimary')
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.setMinimumHeight(42)
        new_btn.clicked.connect(self._start_context_chat)
        lay.addWidget(new_btn)
        lay.addStretch(1)

        scroll.setWidget(host)
        wrap = QVBoxLayout(page)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(scroll)
        return page

    def _build_chat(self) -> QWidget:
        page = QWidget()
        cl = QVBoxLayout(page)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chat_host = QWidget()
        self._chat_lay = QVBoxLayout(self._chat_host)
        self._chat_lay.setContentsMargins(12, 12, 12, 12)
        self._chat_lay.setSpacing(10)
        self._chat_lay.addStretch(1)
        self._scroll.setWidget(self._chat_host)
        cl.addWidget(self._scroll, 1)

        self._typing = QLabel('Copilot is thinking…')
        self._typing.setObjectName('copilotTyping')
        self._typing.hide()
        cl.addWidget(self._typing)

        sug = QFrame(); sug.setObjectName('copilotSugBar')
        sl = QHBoxLayout(sug); sl.setContentsMargins(10, 6, 10, 6); sl.setSpacing(6)
        self._chip_row = sl
        cl.addWidget(sug)

        comp = QFrame(); comp.setObjectName('copilotComposer')
        cpl = QHBoxLayout(comp); cpl.setContentsMargins(10, 10, 10, 12); cpl.setSpacing(8)
        self._input = QTextEdit()
        self._input.setPlaceholderText('Ask Copilot… (Enter to send, Shift+Enter for new line)')
        self._input.setFixedHeight(64)
        self._input.setObjectName('copilotInput')
        self._input.installEventFilter(self)
        self._send = QPushButton('Send')
        self._send.setObjectName('copilotSend')
        self._send.setCursor(Qt.PointingHandCursor)
        self._send.setFixedHeight(64)
        self._send.setFixedWidth(78)
        self._send.clicked.connect(self._on_send)
        cpl.addWidget(self._input, 1)
        cpl.addWidget(self._send)
        cl.addWidget(comp)

        self._empty_hint()
        return page

    def _build_workspace(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self._ws_search = QLineEdit()
        self._ws_search.setPlaceholderText('Search conversations…')
        self._ws_search.setObjectName('copilotSearch')
        self._ws_search.setMinimumHeight(36)
        self._ws_search.textChanged.connect(self._refresh_workspace)
        lay.addWidget(self._ws_search)

        for title in ('Pinned', 'Recent', 'Saved analyses'):
            lbl = QLabel(title.upper())
            lbl.setObjectName('copilotSection')
            lay.addWidget(lbl)
            if title == 'Pinned':
                self._ws_pinned = QListWidget()
                self._ws_pinned.setObjectName('copilotList')
                self._ws_pinned.itemClicked.connect(self._open_recent_item)
                lay.addWidget(self._ws_pinned, 1)
            elif title == 'Recent':
                self._ws_recent = QListWidget()
                self._ws_recent.setObjectName('copilotList')
                self._ws_recent.itemClicked.connect(self._open_recent_item)
                lay.addWidget(self._ws_recent, 2)
            else:
                tip = QLabel('Pin chats from history to keep analyses here.')
                tip.setObjectName('copilotMuted')
                tip.setWordWrap(True)
                lay.addWidget(tip)

        new_btn = QPushButton('New conversation')
        new_btn.setObjectName('copilotPrimary')
        new_btn.setMinimumHeight(40)
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self.new_chat)
        lay.addWidget(new_btn)
        return page

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _empty_hint(self):
        tip = QLabel(
            '<b>Ask about this screen</b><br/>'
            'Copilot uses role-filtered shop data.<br/>'
            'It never changes stock, sales, or money without your approval.'
        )
        tip.setObjectName('copilotHint')
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignCenter)
        tip.setTextFormat(Qt.RichText)
        self._chat_lay.insertWidget(self._chat_lay.count() - 1, tip)
        self._hint = tip

    # ── Tabs / layout ─────────────────────────────────────────────────────────

    def _show_tab(self, key: str):
        idx = {'home': 0, 'chat': 1, 'workspace': 2}.get(key, 0)
        self._stack.setCurrentIndex(idx)
        self._tab_home.setChecked(key == 'home')
        self._tab_chat.setChecked(key == 'chat')
        self._tab_ws.setChecked(key == 'workspace')
        save_copilot_prefs(last_tab=key)
        if key == 'home':
            self._refresh_home()
        elif key == 'workspace':
            self._refresh_workspace()
        elif key == 'chat':
            self._reload_suggestions()

    def _on_resize_drag(self, width: int):
        w = max(340, min(640, int(width)))
        self.setFixedWidth(w)
        self._reposition()
        save_copilot_prefs(width=w)

    def _toggle_float(self):
        if self._floating:
            self._dock()
        else:
            self._undock()

    def _undock(self):
        self._floating = True
        self.setParent(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('MBT Copilot')
        self.resize(self.width(), max(520, (self.mw.height() if self.mw else 640) - 80))
        if self.mw:
            g = self.mw.geometry()
            self.move(g.right() - self.width() - 24, g.top() + 60)
        self.show()
        self._mode_btn.setText('Dock')
        save_copilot_prefs(mode='floating')
        self.refresh_theme()

    def _dock(self):
        self._floating = False
        self.setParent(self.mw)
        self.setWindowFlags(Qt.Widget)
        self._mode_btn.setText('Float')
        self.show()
        self._reposition()
        save_copilot_prefs(mode='docked')
        self.refresh_theme()

    # ── Module / home ─────────────────────────────────────────────────────────

    def set_module(self, module: str):
        self._module = (module or 'dashboard').lower()
        label = _MODULE_LABELS.get(self._module, self._module.replace('_', ' ').title())
        self._context.setText(f'Context · {label}')
        self._reload_suggestions()
        if self._stack.currentIndex() == 0:
            self._refresh_home()

    def _refresh_home(self):
        hour = datetime.now().hour
        greet = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')
        try:
            name = ((self.mw.user_data or {}).get('user') or {}).get('username') or ''
            if name:
                greet = f'{greet}, {name}'
        except Exception:
            pass
        self._greet.setText(greet)

        api = getattr(self.mw, 'api', None)
        user = getattr(self.mw, 'user_data', {}) or {}
        data = {}
        try:
            if api:
                data = _heuristic_insights(api, user)
        except Exception as e:
            log.debug('home insights: %s', e)
            data = {'summary': '—', 'alerts': [], 'recommendations': []}

        self._status_line.setText(data.get('summary') or 'Store snapshot unavailable.')
        alerts = data.get('alerts') or []
        self._kpi_inv.set_value(alerts[0] if alerts else 'No urgent alerts', 'ok' if not alerts or 'No urgent' in str(alerts[0]) else 'warn')
        self._kpi_sales.set_value(data.get('summary') or '—')
        debt_alert = next((a for a in alerts if 'credit' in a.lower() or 'debt' in a.lower() or 'overdue' in a.lower()), None)
        self._kpi_cust.set_value(debt_alert or 'Credit OK')
        st = get_ai_service().status()
        if st.get('configured') and st.get('online'):
            self._kpi_ai.set_value('Online · ready', 'ok')
        elif st.get('configured'):
            self._kpi_ai.set_value('Offline · local mode', 'warn')
        else:
            self._kpi_ai.set_value('Not configured', 'danger')

        recs = data.get('recommendations') or []
        self._recs.setText('• ' + '\n• '.join(recs[:4]) if recs else 'No recommendations yet.')

        self._home_recent.clear()
        try:
            u = user.get('user') or user
            uid = str(u.get('id') or u.get('username') or '')
            for row in get_conversation_store().list(uid)[:6]:
                title = row.get('title') or 'Chat'
                item = QListWidgetItem(('* ' if row.get('pinned') else '') + title)
                item.setData(Qt.UserRole, row)
                self._home_recent.addItem(item)
        except Exception:
            pass
        self.refresh_theme()

    def _run_quick(self, label: str, kind: str):
        # Map quick action to a concrete prompt + optional module switch context
        prompts = {
            'Analyze sales today': 'Summarize today\'s sales performance with key KPIs and any risks.',
            'Inventory health check': 'Give an inventory health check: low stock, overstock risks, and reorder priorities.',
            'Customer / debt insights': 'Summarize credit and debt: overdue accounts and collection priorities.',
            'Explain this screen': f'Explain the {self._module} screen and what I should focus on right now.',
            'Detect problems': 'Scan for common POS problems: stock mismatches, payment variance, and config risks.',
            'Generate report ideas': 'Suggest the most useful reports for today\'s decisions.',
            'Reorder suggestions': 'Which products should I reorder first and why?',
            'Accounting checklist': 'Give a short accounting checklist for today (journals, cash, variances).',
        }
        msg = prompts.get(label) or label
        if kind in _MODULE_LABELS and kind != 'context':
            # keep current module unless action implies another — still ok to ask in context
            pass
        self._show_tab('chat')
        self._input.setPlainText(msg)
        self._on_send()

    def _start_context_chat(self):
        self.new_chat()
        self._show_tab('chat')
        label = _MODULE_LABELS.get(self._module, self._module)
        self._input.setPlainText(f'Explain this {label} screen and highlight what needs attention.')
        self._input.setFocus()

    def _reload_suggestions(self):
        while self._chip_row.count():
            item = self._chip_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for s in get_ai_service().suggestions(self._module)[:3]:
            b = QPushButton(s)
            b.setObjectName('copilotChip')
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(s)
            b.clicked.connect(lambda _, t=s: self._use_suggestion(t))
            self._chip_row.addWidget(b)
        self._chip_row.addStretch(1)

    def _use_suggestion(self, text: str):
        self._input.setPlainText(text)
        self._on_send()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        p = _copilot_colors()
        self.setStyleSheet(
            f"""
            QFrame#mbtCopilot {{ background:{p['bg']}; border-left:1px solid {p['border']}; }}
            QFrame#copilotHdr {{ background:{p['bg2']}; border-bottom:1px solid {p['border']}; }}
            QLabel#copilotTitle {{ color:{p['text']}; font-size:16px; font-weight:800; background:transparent; }}
            QLabel#copilotContext {{
                color:{p['accent']}; font-size:12px; font-weight:700; background:transparent;
            }}
            QToolButton#copilotTab {{
                background:transparent; color:{p['muted']}; border:none; padding:6px 10px;
                font-size:12px; font-weight:700; border-radius:8px;
            }}
            QToolButton#copilotTab:checked {{
                background:{qss_alpha(p['accent'], 0.16)}; color:{p['accent']};
            }}
            QToolButton#copilotIconBtn {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:8px; padding:6px 10px; font-size:14px; font-weight:700;
            }}
            QLabel#copilotBanner {{
                background:{qss_alpha(p['warn'], 0.15)}; color:{p['warn']};
                padding:8px 12px; font-size:12px; font-weight:600;
            }}
            QLabel#copilotGreet {{ color:{p['text']}; font-size:20px; font-weight:800; background:transparent; }}
            QLabel#copilotStatus {{ color:{p['text2']}; font-size:13px; background:transparent; }}
            QLabel#copilotSection {{
                color:{p['muted']}; font-size:11px; font-weight:800; letter-spacing:1px;
                background:transparent; padding-top:4px;
            }}
            QLabel#copilotRecs {{ color:{p['text2']}; font-size:13px; background:transparent; }}
            QLabel#copilotMuted {{ color:{p['muted']}; font-size:12px; background:transparent; }}
            QFrame#copilotKpi {{
                background:{p['card']}; border:1px solid {p['border']}; border-radius:12px;
            }}
            QLabel#copilotKpiTitle {{ color:{p['muted']}; font-size:11px; font-weight:700; background:transparent; }}
            QLabel#copilotKpiValue {{ color:{p['text']}; font-size:13px; font-weight:700; background:transparent; }}
            QPushButton#copilotAction {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:12px; padding:10px 12px; font-size:12px; font-weight:600; text-align:left;
            }}
            QPushButton#copilotAction:hover {{ border-color:{p['accent']}; color:{p['accent']}; }}
            QPushButton#copilotPrimary {{
                background:{p['accent']}; color:#0B1220; border:none; border-radius:10px;
                font-size:13px; font-weight:800;
            }}
            QPushButton#copilotPrimary:hover {{ background:#FCD34D; }}
            QLineEdit#copilotSearch, QTextEdit#copilotInput {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:10px; padding:8px 10px; font-size:13px;
            }}
            QTextEdit#copilotInput:focus, QLineEdit#copilotSearch:focus {{ border-color:{p['accent']}; }}
            QPushButton#copilotSend {{
                background:{p['accent']}; color:#0B1220; border:none; border-radius:10px;
                font-weight:800; font-size:13px;
            }}
            QFrame#copilotComposer, QFrame#copilotSugBar {{
                background:{p['bg2']}; border-top:1px solid {p['border']};
            }}
            QPushButton#copilotChip {{
                background:{p['card']}; color:{p['text2']}; border:1px solid {p['border']};
                border-radius:14px; padding:6px 10px; font-size:11px; font-weight:600;
            }}
            QPushButton#copilotChip:hover {{ border-color:{p['accent']}; color:{p['accent']}; }}
            QLabel#copilotTyping {{ color:{p['accent']}; font-size:12px; font-weight:600; padding:4px 12px; }}
            QLabel#copilotHint {{ color:{p['text2']}; font-size:13px; padding:20px; background:transparent; }}
            QListWidget#copilotList {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:10px; font-size:12px; outline:none;
            }}
            QListWidget#copilotList::item {{ padding:8px 10px; }}
            QListWidget#copilotList::item:selected {{ background:{qss_alpha(p['accent'], 0.18)}; color:{p['accent']}; }}
            QScrollArea {{ background:transparent; border:none; }}
            """
        )
        for i in range(self._chat_lay.count()):
            w = self._chat_lay.itemAt(i).widget()
            if w and hasattr(w, 'refresh_theme'):
                w.refresh_theme()

    # ── Open / close ──────────────────────────────────────────────────────────

    def open_full_workspace(self):
        """Enter flagship Full Workspace (POS state stays in memory)."""
        self.hide()
        if self._floating:
            self._dock()
        enter = getattr(self.mw, 'enter_ai_full_workspace', None)
        if callable(enter):
            enter()
        else:
            QMessageBox.information(self, 'Copilot', 'Full Workspace is unavailable.')

    def open_panel(self):
        self.refresh_theme()
        self._on_conn()
        # Never auto-enter floating/full on open — user chooses explicitly
        if self._floating:
            self.show()
        else:
            self.show()
            self.raise_()
            self._reposition()
        save_copilot_prefs(mode='docked' if not self._floating else 'floating')
        self._refresh_home()
        if self._stack.currentIndex() == 1:
            self._input.setFocus()

    def close_panel(self):
        if self._floating:
            self._dock()
        self.hide()
        save_copilot_prefs(mode='minimized')

    def toggle(self):
        if self.isVisible():
            self.close_panel()
        else:
            self.open_panel()

    def _reposition(self):
        if self._floating or not self.parentWidget():
            return
        parent = self.parentWidget()
        self.setFixedHeight(parent.height())
        self.move(parent.width() - self.width(), 0)

    def _on_conn(self):
        st = get_ai_service().status()
        if st.get('banner'):
            self._banner.setText('!  ' + st['banner'])
            self._banner.show()
        else:
            self._banner.hide()

    # ── Chat ──────────────────────────────────────────────────────────────────

    def _add_bubble(self, role: str, text: str, actions: Optional[list] = None,
                    structured: Optional[dict] = None) -> '_Bubble':
        if getattr(self, '_hint', None):
            self._hint.hide()
        b = _Bubble(role, text, actions=actions or [], panel=self, structured=structured)
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
        self._show_tab('chat')

    def _refresh_workspace(self, *_):
        q = (self._ws_search.text() or '').strip().lower()
        self._ws_pinned.clear()
        self._ws_recent.clear()
        try:
            u = (self.mw.user_data or {}).get('user') or {}
            uid = str(u.get('id') or u.get('username') or '')
            for row in get_conversation_store().list(uid):
                title = row.get('title') or 'Chat'
                if q and q not in title.lower():
                    continue
                item = QListWidgetItem(('* ' if row.get('pinned') else '') + title)
                item.setData(Qt.UserRole, row)
                if row.get('pinned'):
                    self._ws_pinned.addItem(item)
                else:
                    self._ws_recent.addItem(item)
        except Exception:
            pass

    def _open_recent_item(self, item: QListWidgetItem):
        row = item.data(Qt.UserRole) or {}
        cid = row.get('id')
        if not cid:
            return
        self._conversation_id = cid
        self._history = []
        self._clear_chat_widgets()
        self._show_tab('chat')
        for m in get_conversation_store().messages(cid):
            role = m.get('role') or 'assistant'
            content = m.get('content') or ''
            self._add_bubble(role, content)
            if role in ('user', 'assistant'):
                self._history.append({'role': role, 'content': content})

    def _on_send(self):
        msg = (self._input.toPlainText() or '').strip()
        if not msg:
            return
        if self._worker and self._worker.isRunning():
            return
        self._show_tab('chat')
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

        # Inject screen context into message for awareness
        label = _MODULE_LABELS.get(self._module, self._module)
        contextual = f'[Screen context: {label}]\n{msg}'

        payload = {
            'message': contextual,
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
        structured = self._maybe_structure(text)
        if getattr(self, '_stream_bubble', None):
            self._stream_bubble.set_text(text)
            self._stream_bubble.set_actions(actions)
            if structured:
                self._stream_bubble.set_structured(structured)
        else:
            self._add_bubble('assistant', text, actions, structured)
        self._history.append({'role': 'assistant', 'content': text})
        self._on_conn()
        for act in actions:
            self._prompt_action(act)

    def _maybe_structure(self, text: str) -> Optional[dict]:
        """Lightweight structured card when response has bullet KPIs."""
        if not text:
            return None
        lines = [ln.strip('•- ').strip() for ln in text.splitlines() if ln.strip().startswith(('•', '-', '*'))]
        if len(lines) >= 2:
            return {'type': 'bullets', 'items': lines[:6]}
        return None

    def _on_fail(self, err: str):
        self._typing.hide()
        self._send.setEnabled(True)
        msg = f'Copilot error: {err}'
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
                'Your role cannot approve this Copilot-proposed action.')
            return
        preview = format_action_preview(action)
        box = QMessageBox(self)
        box.setWindowTitle('Approve Copilot Action?')
        box.setText(
            'MBT Copilot proposed an action. Nothing has been changed yet.\n\n' + preview)
        approve = box.addButton('Approve', QMessageBox.AcceptRole)
        cancel = box.addButton('Cancel', QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() == cancel:
            return
        QMessageBox.information(
            self, 'Action noted',
            f'Approved locally: {action.action}\n\n'
            'Apply changes from the relevant module when ready.\n'
            f'Payload: {action.payload}')
        self._add_bubble(
            'assistant',
            f'OK — You approved **{action.action}**. Open the related module to apply.',
        )


class _Bubble(QFrame):
    def __init__(self, role: str, text: str, actions=None, panel=None, structured=None):
        super().__init__()
        self.role = role
        self.panel = panel
        self.setObjectName('copilotBubbleUser' if role == 'user' else 'copilotBubbleAi')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        who = QLabel('You' if role == 'user' else 'Copilot')
        who.setObjectName('copilotWho')
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(who)
        lay.addWidget(self._body)
        self._struct_host = QVBoxLayout()
        lay.addLayout(self._struct_host)
        self._actions_host = QVBoxLayout()
        lay.addLayout(self._actions_host)
        if role == 'assistant':
            row = QHBoxLayout()
            copy_btn = QPushButton('Copy')
            regen = QPushButton('Regenerate')
            for b in (copy_btn, regen):
                b.setObjectName('copilotMini')
                b.setCursor(Qt.PointingHandCursor)
                row.addWidget(b)
            row.addStretch()
            copy_btn.clicked.connect(self._copy)
            regen.clicked.connect(lambda: panel and panel.regenerate())
            lay.addLayout(row)
        self.set_text(text)
        self.set_actions(actions or [])
        if structured:
            self.set_structured(structured)
        self.refresh_theme()

    def set_text(self, text: str):
        self._raw = text or ''
        self._body.setText(_md_to_html(self._raw))

    def set_structured(self, data: dict):
        while self._struct_host.count():
            item = self._struct_host.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not data:
            return
        if data.get('type') == 'bullets':
            card = QFrame()
            card.setObjectName('copilotStructCard')
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            title = QLabel('Key points')
            title.setObjectName('copilotWho')
            cl.addWidget(title)
            for it in data.get('items') or []:
                lbl = QLabel('• ' + it)
                lbl.setWordWrap(True)
                cl.addWidget(lbl)
            self._struct_host.addWidget(card)

    def set_actions(self, actions):
        while self._actions_host.count():
            item = self._actions_host.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for act in actions or []:
            if not isinstance(act, ProposedAction):
                continue
            b = QPushButton(f'> {act.summary or act.action}')
            b.setObjectName('copilotActionBtn')
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _, a=act: self.panel and self.panel._prompt_action(a))
            self._actions_host.addWidget(b)

    def _copy(self):
        QApplication.clipboard().setText(self._raw or '')

    def refresh_theme(self):
        p = _copilot_colors()
        if self.role == 'user':
            bg = qss_alpha(p['accent'], 0.14)
            border = qss_alpha(p['accent'], 0.35)
        else:
            bg = p['card']
            border = p['border']
        self.setStyleSheet(
            f"QFrame {{ background:{bg}; border:1px solid {border}; border-radius:12px; }}"
            f"QLabel#copilotWho {{ color:{p['muted']}; font-size:11px; font-weight:700;"
            f" background:transparent; border:none; }}"
            f"QLabel {{ color:{p['text']}; font-size:13px; background:transparent; border:none; }}"
            f"QFrame#copilotStructCard {{ background:{p['bg2']}; border:1px solid {p['border']};"
            f" border-radius:10px; }}"
            f"QPushButton#copilotMini {{ background:transparent; color:{p['text2']}; border:none;"
            f" font-size:11px; padding:2px 6px; }}"
            f"QPushButton#copilotMini:hover {{ color:{p['accent']}; }}"
            f"QPushButton#copilotActionBtn {{ background:{qss_alpha(p['info'], 0.15)}; color:{p['info']};"
            f" border:1px solid {qss_alpha(p['info'], 0.4)}; border-radius:8px;"
            f" padding:6px 10px; font-size:12px; font-weight:600; text-align:left; }}"
        )


class AiFabButton(QPushButton):
    """Floating Copilot launcher — bottom-right."""

    def __init__(self, parent=None):
        super().__init__('✦  Copilot', parent)
        self.setObjectName('mbtCopilotFab')
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(118, 48)
        self.refresh_theme()

    def refresh_theme(self):
        p = _copilot_colors()
        self.setStyleSheet(
            f"QPushButton#mbtCopilotFab {{"
            f" background:{p['accent']}; color:#0B1220; border:none;"
            f" border-radius:24px; font-size:13px; font-weight:800;"
            f" padding:0 14px; }}"
            f"QPushButton#mbtCopilotFab:hover {{ background:#FCD34D; }}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)
