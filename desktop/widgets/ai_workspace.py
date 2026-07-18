"""
MBT AI — Full Workspace (Enterprise AI Operations Center)
Takes over the application window while POS state stays in memory.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent
from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QSizePolicy, QListWidget, QListWidgetItem, QStackedWidget,
    QGridLayout, QLineEdit, QToolButton, QSplitter, QMessageBox, QApplication,
)

from desktop.utils.theme import qss_alpha
from desktop.utils.ai.insights import _heuristic_insights
from desktop.utils.ai import get_ai_service
from desktop.utils.ai.conversations import get_conversation_store
from desktop.utils.ai.copilot_prefs import save_copilot_prefs
from desktop.utils.ai.actions import ProposedAction, format_action_preview
from desktop.widgets.ai_assistant import (
    _copilot_colors, _ChatWorker, _MODULE_LABELS, _QUICK_ACTIONS,
)

log = logging.getLogger('ai.workspace')

_SIDEBAR_NAV = [
    ('new', '＋  New Chat'),
    ('recent', 'Recent Chats'),
    ('pinned', 'Pinned'),
    ('insights', 'Business Insights'),
    ('reports', 'Saved Reports'),
    ('analytics', 'Analytics'),
    ('inventory', 'Inventory Intel'),
    ('accounting', 'Accounting Intel'),
    ('customers', 'Customer Intel'),
    ('tools', 'AI Tools'),
    ('debug', 'Debug Center'),
    ('knowledge', 'Knowledge Base'),
    ('ops', 'AI Operations'),
    ('prompts', 'Prompt Library'),
    ('settings', 'AI Settings'),
]

_WORKSPACE_TABS = [
    ('chat', 'Chat'),
    ('dashboard', 'Dashboard'),
    ('analytics', 'Analytics'),
    ('inventory', 'Inventory'),
    ('sales', 'Sales'),
    ('accounting', 'Accounting'),
    ('customers', 'Customers'),
    ('reports', 'Reports'),
    ('debug', 'Debug'),
    ('ops', 'AI Ops'),
]


class AiFullWorkspace(QFrame):
    """Full-window AI Operations Center overlay."""

    closed = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(main_window.centralWidget())
        self.mw = main_window
        self._module = 'dashboard'
        self._conversation_id = None
        self._history: List[Dict[str, str]] = []
        self._worker: Optional[_ChatWorker] = None
        self._streaming_buf = ''
        self.setObjectName('aiFullWorkspace')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.hide()
        self._build()
        self.refresh_theme()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top = QFrame(); top.setObjectName('wsTop')
        top.setFixedHeight(56)
        tl = QHBoxLayout(top); tl.setContentsMargins(16, 8, 12, 8); tl.setSpacing(10)
        brand = QLabel('✦  MBT Copilot')
        brand.setObjectName('wsBrand')
        tl.addWidget(brand)
        self._ctx = QLabel('Full Workspace')
        self._ctx.setObjectName('wsCtx')
        tl.addWidget(self._ctx)
        tl.addStretch(1)
        self._search = QLineEdit()
        self._search.setPlaceholderText('Search products, invoices, chats, reports…')
        self._search.setObjectName('wsSearch')
        self._search.setFixedWidth(320)
        self._search.setMinimumHeight(34)
        self._search.returnPressed.connect(self._on_global_search)
        tl.addWidget(self._search)
        self._model_lbl = QLabel('Model · —')
        self._model_lbl.setObjectName('wsMeta')
        self._health_lbl = QLabel('AI · —')
        self._health_lbl.setObjectName('wsMeta')
        tl.addWidget(self._model_lbl)
        tl.addWidget(self._health_lbl)
        for text, tip, slot in (
            ('🗕', 'Minimize to FAB', self._minimize),
            ('⧉', 'Dock panel', self._to_dock),
            ('✕', 'Exit Full Workspace', self.exit_workspace),
        ):
            b = QToolButton(); b.setText(text); b.setToolTip(tip)
            b.setObjectName('wsIconBtn'); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            tl.addWidget(b)
        root.addWidget(top)

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        # Left sidebar
        side = QFrame(); side.setObjectName('wsSide'); side.setFixedWidth(220)
        sl = QVBoxLayout(side); sl.setContentsMargins(10, 12, 10, 12); sl.setSpacing(4)
        self._nav = QListWidget(); self._nav.setObjectName('wsNav')
        for key, label in _SIDEBAR_NAV:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self._nav.addItem(item)
        self._nav.setCurrentRow(0)
        self._nav.currentRowChanged.connect(self._on_nav)
        sl.addWidget(self._nav, 1)
        body.addWidget(side)

        # Center
        center = QWidget()
        cl = QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(0)

        # Workspace tabs
        tab_bar = QFrame(); tab_bar.setObjectName('wsTabBar')
        tbl = QHBoxLayout(tab_bar); tbl.setContentsMargins(12, 6, 12, 6); tbl.setSpacing(4)
        self._tab_btns = {}
        for key, label in _WORKSPACE_TABS:
            b = QToolButton(); b.setText(label); b.setCheckable(True)
            b.setObjectName('wsTab'); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._show_main_tab(k))
            tbl.addWidget(b)
            self._tab_btns[key] = b
        tbl.addStretch(1)
        cl.addWidget(tab_bar)

        self._main = QStackedWidget()
        self._dash_page = self._build_dashboard()
        self._chat_page = self._build_chat()
        self._intel_page = self._build_intel_stub()
        self._main.addWidget(self._dash_page)   # 0 dashboard
        self._main.addWidget(self._chat_page)   # 1 chat
        self._main.addWidget(self._intel_page)  # 2 intel/tools stubs
        cl.addWidget(self._main, 1)
        body.addWidget(center, 1)
        root.addLayout(body, 1)

        # Bottom quick actions
        bottom = QFrame(); bottom.setObjectName('wsBottom')
        bl = QHBoxLayout(bottom); bl.setContentsMargins(12, 8, 12, 10); bl.setSpacing(6)
        bl.addWidget(QLabel('Quick Actions'))
        for label, kind, icon in _QUICK_ACTIONS[:8]:
            b = QPushButton(f'{icon} {label}')
            b.setObjectName('wsQuick')
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=label: self._quick(t))
            bl.addWidget(b)
        bl.addStretch(1)
        root.addWidget(bottom)

        self._show_main_tab('dashboard')

    def _build_dashboard(self) -> QWidget:
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget(); lay = QVBoxLayout(host)
        lay.setContentsMargins(20, 16, 20, 20); lay.setSpacing(14)

        self._greet = QLabel('Good afternoon')
        self._greet.setObjectName('wsGreet')
        lay.addWidget(self._greet)

        snap_lbl = QLabel('BUSINESS SNAPSHOT')
        snap_lbl.setObjectName('wsSection')
        lay.addWidget(snap_lbl)

        grid = QGridLayout(); grid.setSpacing(10)
        self._kpis = {}
        for i, (key, title) in enumerate((
            ('sales', "Today's Sales"),
            ('profit', 'Est. Profit'),
            ('inv', 'Inventory Alerts'),
            ('debt', 'Pending Debts'),
            ('tx', 'Transactions'),
            ('ai', 'AI Status'),
        )):
            card = QFrame(); card.setObjectName('wsCard')
            c = QVBoxLayout(card); c.setContentsMargins(14, 12, 14, 12)
            t = QLabel(title); t.setObjectName('wsCardTitle')
            v = QLabel('—'); v.setObjectName('wsCardValue'); v.setWordWrap(True)
            c.addWidget(t); c.addWidget(v)
            self._kpis[key] = v
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)

        rec_lbl = QLabel('RECOMMENDATIONS')
        rec_lbl.setObjectName('wsSection')
        lay.addWidget(rec_lbl)
        self._recs = QLabel('—')
        self._recs.setObjectName('wsBody'); self._recs.setWordWrap(True)
        lay.addWidget(self._recs)

        act = QPushButton('Start chat about this business snapshot')
        act.setObjectName('wsPrimary'); act.setMinimumHeight(42)
        act.setCursor(Qt.PointingHandCursor)
        act.clicked.connect(lambda: self._show_main_tab('chat'))
        lay.addWidget(act)
        lay.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_chat(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._chat_host = QWidget()
        self._chat_lay = QVBoxLayout(self._chat_host)
        self._chat_lay.setContentsMargins(20, 16, 20, 16); self._chat_lay.setSpacing(10)
        self._chat_lay.addStretch(1)
        self._scroll.setWidget(self._chat_host)
        lay.addWidget(self._scroll, 1)
        self._typing = QLabel('Copilot is thinking…'); self._typing.setObjectName('wsTyping')
        self._typing.hide(); lay.addWidget(self._typing)
        comp = QFrame(); comp.setObjectName('wsComposer')
        cpl = QHBoxLayout(comp); cpl.setContentsMargins(16, 10, 16, 12); cpl.setSpacing(10)
        self._input = QTextEdit(); self._input.setObjectName('wsInput')
        self._input.setPlaceholderText('Ask Copilot anything about your business…')
        self._input.setFixedHeight(72)
        self._input.installEventFilter(self)
        send = QPushButton('Send'); send.setObjectName('wsPrimary')
        send.setFixedSize(96, 72); send.setCursor(Qt.PointingHandCursor)
        send.clicked.connect(self._on_send)
        self._send = send
        cpl.addWidget(self._input, 1); cpl.addWidget(send)
        lay.addWidget(comp)
        return page

    def _build_intel_stub(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        self._intel_title = QLabel('Intelligence')
        self._intel_title.setObjectName('wsGreet')
        self._intel_body = QLabel(
            'Ask Copilot from Chat, or use Quick Actions below.\n'
            'This area shows structured insights for the selected domain.'
        )
        self._intel_body.setObjectName('wsBody'); self._intel_body.setWordWrap(True)
        lay.addWidget(self._intel_title)
        lay.addWidget(self._intel_body)
        go = QPushButton('Open Chat with this focus')
        go.setObjectName('wsPrimary'); go.setMinimumHeight(40)
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(lambda: self._show_main_tab('chat'))
        lay.addWidget(go)
        lay.addStretch(1)
        return page

    def eventFilter(self, obj, event):
        if obj is getattr(self, '_input', None) and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
                self._on_send(); return True
        return super().eventFilter(obj, event)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def enter(self, module: str = None):
        self._module = (module or getattr(self.mw, '_current_tid', None) or 'dashboard')
        label = _MODULE_LABELS.get(self._module, self._module)
        self._ctx.setText(f'Full Workspace  ·  Context: {label}')
        self.setGeometry(self.parentWidget().rect() if self.parentWidget() else self.rect())
        self.show(); self.raise_()
        self.refresh_home()
        self._refresh_status()
        save_copilot_prefs(mode='full')
        self.refresh_theme()

    def exit_workspace(self):
        self.hide()
        save_copilot_prefs(mode='minimized')
        self.closed.emit()

    def _minimize(self):
        self.exit_workspace()

    def _to_dock(self):
        self.hide()
        save_copilot_prefs(mode='docked')
        panel = getattr(self.mw, '_ai_panel', None)
        if panel:
            panel.open_panel()
        fab = getattr(self.mw, '_ai_fab', None)
        if fab:
            fab.show()
        self.closed.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.parentWidget() and self.isVisible():
            self.setGeometry(self.parentWidget().rect())

    # ── Nav / tabs ────────────────────────────────────────────────────────────

    def _on_nav(self, row: int):
        item = self._nav.item(row)
        if not item:
            return
        key = item.data(Qt.UserRole)
        if key == 'new':
            self.new_chat(); self._show_main_tab('chat'); return
        if key in ('recent', 'pinned'):
            self._load_sidebar_chats(pinned=(key == 'pinned')); self._show_main_tab('chat'); return
        if key == 'ops':
            # Jump to AI Ops tab in POS then exit? Keep in workspace stub
            self._intel_title.setText('AI Operations')
            self._intel_body.setText(
                'Open the AI Operations tab in the POS sidebar for health, healing, and support reports.\n'
                'Or ask Copilot: "Run an AI health check."')
            self._main.setCurrentIndex(2); return
        if key == 'debug':
            self._show_main_tab('debug'); return
        mapping = {
            'insights': 'dashboard', 'analytics': 'analytics', 'inventory': 'inventory',
            'accounting': 'accounting', 'customers': 'customers', 'reports': 'reports',
            'tools': 'chat', 'knowledge': 'chat', 'prompts': 'chat', 'settings': 'ops',
        }
        self._show_main_tab(mapping.get(key, 'dashboard'))

    def _show_main_tab(self, key: str):
        for k, b in self._tab_btns.items():
            b.setChecked(k == key)
        if key == 'dashboard':
            self._main.setCurrentIndex(0); self.refresh_home()
        elif key == 'chat':
            self._main.setCurrentIndex(1)
        else:
            titles = {
                'analytics': 'Analytics Intelligence',
                'inventory': 'Inventory Intelligence',
                'sales': 'Sales Intelligence',
                'accounting': 'Accounting Intelligence',
                'customers': 'Customer Intelligence',
                'reports': 'Reports',
                'debug': 'Debug Center',
                'ops': 'AI Operations',
            }
            self._intel_title.setText(titles.get(key, key.title()))
            prompts = {
                'inventory': 'Give an inventory health check with reorder priorities.',
                'sales': "Analyze today's sales and highlight risks.",
                'accounting': 'Give an accounting checklist for today.',
                'customers': 'Summarize overdue credit and collection priorities.',
                'analytics': 'What trends should management watch this week?',
                'reports': 'Which reports should I run today and why?',
                'debug': 'Scan for common POS problems and configuration risks.',
                'ops': 'Summarize AI connectivity and health.',
            }
            self._intel_body.setText(
                f'Focus: {titles.get(key, key)}.\n\n'
                'Use Quick Actions or open Chat with a focused prompt.')
            self._main.setCurrentIndex(2)
            if key in prompts:
                self._pending_prompt = prompts[key]

    def _load_sidebar_chats(self, pinned=False):
        # Populate as chat history load hint into input area via list under chat — simple: open recent
        try:
            u = (self.mw.user_data or {}).get('user') or {}
            uid = str(u.get('id') or u.get('username') or '')
            rows = get_conversation_store().list(uid)
            if pinned:
                rows = [r for r in rows if r.get('pinned')]
            if rows:
                self._open_conversation(rows[0])
        except Exception:
            pass

    def _open_conversation(self, row: dict):
        cid = row.get('id')
        if not cid:
            return
        self._conversation_id = cid
        self._history = []
        self._clear_chat()
        for m in get_conversation_store().messages(cid):
            role = m.get('role') or 'assistant'
            content = m.get('content') or ''
            self._add_bubble(role, content)
            if role in ('user', 'assistant'):
                self._history.append({'role': role, 'content': content})

    def refresh_home(self):
        hour = datetime.now().hour
        greet = 'Good morning' if hour < 12 else ('Good afternoon' if hour < 17 else 'Good evening')
        try:
            name = ((self.mw.user_data or {}).get('user') or {}).get('username') or ''
            if name:
                greet = f'{greet}, {name}'
        except Exception:
            pass
        self._greet.setText(greet)
        data = {'summary': '—', 'alerts': [], 'recommendations': []}
        try:
            if getattr(self.mw, 'api', None):
                data = _heuristic_insights(self.mw.api, self.mw.user_data or {})
        except Exception as e:
            log.debug('workspace insights: %s', e)
        self._kpis['sales'].setText(data.get('summary') or '—')
        alerts = data.get('alerts') or []
        self._kpis['inv'].setText(next((a for a in alerts if 'stock' in a.lower() or 'product' in a.lower()), alerts[0] if alerts else 'No alerts'))
        self._kpis['debt'].setText(next((a for a in alerts if 'debt' in a.lower() or 'credit' in a.lower() or 'overdue' in a.lower()), 'OK'))
        self._kpis['profit'].setText('See Accounting for live P&L')
        self._kpis['tx'].setText(data.get('summary') or '—')
        st = get_ai_service().status()
        self._kpis['ai'].setText('Online' if st.get('online') else ('Configured · offline' if st.get('configured') else 'Not configured'))
        recs = data.get('recommendations') or []
        self._recs.setText('• ' + '\n• '.join(recs[:5]) if recs else 'No recommendations yet.')

    def _refresh_status(self):
        st = get_ai_service().status()
        self._model_lbl.setText(f"Model · {st.get('model') or '—'}")
        if st.get('online'):
            self._health_lbl.setText('AI · Online')
        elif st.get('configured'):
            self._health_lbl.setText('AI · Offline')
        else:
            self._health_lbl.setText('AI · Setup needed')

    def _quick(self, label: str):
        prompts = {
            'Analyze sales today': "Summarize today's sales with KPIs and risks.",
            'Inventory health check': 'Inventory health check with reorder priorities.',
            'Customer / debt insights': 'Summarize overdue credit and collection priorities.',
            'Explain this screen': f'Explain the {self._module} context and what needs attention.',
            'Detect problems': 'Scan for POS problems: stock, payments, config.',
            'Generate report ideas': 'Which reports should I run today?',
            'Reorder suggestions': 'What should I reorder first and why?',
            'Accounting checklist': 'Short accounting checklist for today.',
        }
        self._show_main_tab('chat')
        self._input.setPlainText(prompts.get(label) or label)
        self._on_send()

    def _on_global_search(self):
        q = (self._search.text() or '').strip()
        if not q:
            return
        self._show_main_tab('chat')
        self._input.setPlainText(f'Search the business for: {q}')
        self._on_send()

    # ── Chat ──────────────────────────────────────────────────────────────────

    def new_chat(self):
        self._conversation_id = None
        self._history = []
        self._clear_chat()

    def _clear_chat(self):
        while self._chat_lay.count() > 1:
            item = self._chat_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _add_bubble(self, role: str, text: str):
        from desktop.widgets.ai_assistant import _Bubble
        b = _Bubble(role, text, panel=self)
        # Adapt regenerate to workspace
        self._chat_lay.insertWidget(self._chat_lay.count() - 1, b)
        QTimer.singleShot(20, self._scroll_bottom)
        return b

    def _scroll_bottom(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def regenerate(self):
        if self._history:
            last_user = next((h['content'] for h in reversed(self._history) if h['role'] == 'user'), '')
            if last_user:
                self._input.setPlainText(last_user)
                self._on_send()

    def _prompt_action(self, action: ProposedAction):
        if not isinstance(action, ProposedAction):
            return
        if not action.permission_ok(self.mw.user_data):
            QMessageBox.information(self, 'Not allowed', 'Your role cannot approve this action.')
            return
        box = QMessageBox(self)
        box.setWindowTitle('Approve Copilot Action?')
        box.setText('Nothing has changed yet.\n\n' + format_action_preview(action))
        box.addButton('Approve', QMessageBox.AcceptRole)
        cancel = box.addButton('Cancel', QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() == cancel:
            return
        self._add_bubble('assistant', f'✅ Approved **{action.action}**. Apply from the related POS module.')

    def _on_send(self):
        msg = (self._input.toPlainText() or '').strip()
        if not msg:
            return
        if self._worker and self._worker.isRunning():
            return
        self._input.clear()
        self._add_bubble('user', msg)
        self._history.append({'role': 'user', 'content': msg})
        self._typing.show()
        self._send.setEnabled(False)
        self._streaming_buf = ''
        self._stream_bubble = self._add_bubble('assistant', '')
        label = _MODULE_LABELS.get(self._module, self._module)
        payload = {
            'message': f'[Full Workspace · screen context: {label}]\n{msg}',
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
        self._typing.hide(); self._send.setEnabled(True)
        self._conversation_id = result.get('conversation_id') or self._conversation_id
        text = result.get('text') or ''
        actions = result.get('actions') or []
        if getattr(self, '_stream_bubble', None):
            self._stream_bubble.set_text(text)
            self._stream_bubble.set_actions(actions)
        self._history.append({'role': 'assistant', 'content': text})
        for act in actions:
            self._prompt_action(act)
        self._refresh_status()

    def _on_fail(self, err: str):
        self._typing.hide(); self._send.setEnabled(True)
        if getattr(self, '_stream_bubble', None):
            self._stream_bubble.set_text(f'Copilot error: {err}')

    def refresh_theme(self):
        p = _copilot_colors()
        self.setStyleSheet(
            f"""
            QFrame#aiFullWorkspace {{ background:{p['bg']}; }}
            QFrame#wsTop {{ background:{p['bg2']}; border-bottom:1px solid {p['border']}; }}
            QLabel#wsBrand {{ color:{p['text']}; font-size:16px; font-weight:800; background:transparent; }}
            QLabel#wsCtx {{ color:{p['accent']}; font-size:12px; font-weight:700; background:transparent; }}
            QLabel#wsMeta {{ color:{p['muted']}; font-size:11px; font-weight:600; background:transparent; padding:0 8px; }}
            QLineEdit#wsSearch {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:8px; padding:6px 10px; font-size:13px;
            }}
            QToolButton#wsIconBtn {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:8px; padding:6px 10px; font-size:14px;
            }}
            QFrame#wsSide {{ background:{p['sidebar']}; border-right:1px solid {p['border']}; }}
            QListWidget#wsNav {{
                background:transparent; color:{p['text2']}; border:none; font-size:13px; font-weight:600;
            }}
            QListWidget#wsNav::item {{ padding:10px 12px; border-radius:8px; margin:2px 0; }}
            QListWidget#wsNav::item:selected {{ background:{qss_alpha(p['accent'], 0.16)}; color:{p['accent']}; }}
            QFrame#wsTabBar {{ background:{p['bg2']}; border-bottom:1px solid {p['border']}; }}
            QToolButton#wsTab {{
                background:transparent; color:{p['muted']}; border:none; padding:8px 12px;
                font-size:12px; font-weight:700; border-radius:8px;
            }}
            QToolButton#wsTab:checked {{ background:{qss_alpha(p['accent'], 0.16)}; color:{p['accent']}; }}
            QLabel#wsGreet {{ color:{p['text']}; font-size:26px; font-weight:800; background:transparent; }}
            QLabel#wsSection {{ color:{p['muted']}; font-size:11px; font-weight:800; letter-spacing:1px; background:transparent; }}
            QLabel#wsBody {{ color:{p['text2']}; font-size:14px; background:transparent; }}
            QFrame#wsCard {{ background:{p['card']}; border:1px solid {p['border']}; border-radius:14px; }}
            QLabel#wsCardTitle {{ color:{p['muted']}; font-size:11px; font-weight:700; background:transparent; }}
            QLabel#wsCardValue {{ color:{p['text']}; font-size:15px; font-weight:700; background:transparent; }}
            QFrame#wsBottom {{ background:{p['bg2']}; border-top:1px solid {p['border']}; }}
            QPushButton#wsQuick {{
                background:{p['card']}; color:{p['text2']}; border:1px solid {p['border']};
                border-radius:8px; padding:6px 10px; font-size:11px; font-weight:600;
            }}
            QPushButton#wsQuick:hover {{ border-color:{p['accent']}; color:{p['accent']}; }}
            QPushButton#wsPrimary {{
                background:{p['accent']}; color:#0B1220; border:none; border-radius:10px; font-weight:800; font-size:13px;
            }}
            QFrame#wsComposer {{ background:{p['bg2']}; border-top:1px solid {p['border']}; }}
            QTextEdit#wsInput {{
                background:{p['card']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:10px; padding:10px; font-size:14px;
            }}
            QLabel#wsTyping {{ color:{p['accent']}; font-size:12px; font-weight:600; padding:4px 16px; }}
            QScrollArea {{ background:transparent; border:none; }}
            """
        )
