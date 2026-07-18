"""
MBT POS — AI Operations Center

Admin/Manager/Superadmin hub: Health, Integrity, Config Audit, Analyze,
Self-Healing, Support Report, Update Verification, Knowledge Base,
Developer Assistant (superadmin). Theme-aware. Offline-safe.
"""
from __future__ import annotations

import logging
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from desktop.utils.theme import C, ThemeManager, qss_alpha
from desktop.utils.widgets import (
    PrimaryBtn, SecondaryBtn, GhostBtn, Card, page_layout, page_intro, H2, Caption,
)
from desktop.utils.ai.ops import get_ai_ops
from desktop.utils.ai.connectivity import OFFLINE_BANNER
from roles import is_superadmin_role

log = logging.getLogger('ai.ops.tab')


class _Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            log.exception('ops worker')
            self.failed.emit(str(e))


class AiOpsTab(QWidget):
    def __init__(self, api, user, db_path, config_getter):
        super().__init__()
        self.api = api
        self.user = user
        self.db_path = db_path
        self.config_getter = config_getter
        self._ops = get_ai_ops()
        self._worker = None
        self._build()
        QTimer.singleShot(200, self.refresh_health)

    def _role(self) -> str:
        return ((self.user.get('user') or self.user).get('role') or '').lower()

    def _build(self):
        lay, _ = page_layout(self)
        actions = QWidget()
        ar = QHBoxLayout(actions); ar.setContentsMargins(0, 0, 0, 0); ar.setSpacing(8)
        self._refresh_btn = PrimaryBtn('↻  Refresh Health', 40)
        self._refresh_btn.clicked.connect(self.refresh_health)
        self._support_btn = SecondaryBtn('📦  Support Report', 40)
        self._support_btn.clicked.connect(self._support_report)
        ar.addWidget(self._refresh_btn)
        ar.addWidget(self._support_btn)
        intro, _ = page_intro(
            'AI Operations Center',
            'Copilot health, integrity, config audit, self-healing, and support — vendor AI, offline-safe.',
            actions,
        )
        lay.addLayout(intro)

        self._banner = QLabel('')
        self._banner.setWordWrap(True)
        self._banner.hide()
        lay.addWidget(self._banner)

        # Score row
        score_card = Card()
        sc = score_card.layout_h((18, 16, 18, 16), 16)
        self._score_lbl = QLabel('—')
        self._score_lbl.setStyleSheet(
            f"color:{C['gold']}; font-size:42px; font-weight:800; background:transparent;")
        col = QVBoxLayout()
        self._grade_lbl = QLabel('Health Score')
        self._grade_lbl.setStyleSheet(
            f"color:{C['text']}; font-size:16px; font-weight:700; background:transparent;")
        self._score_sub = QLabel('Run refresh to compute')
        self._score_sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent;")
        self._score_sub.setWordWrap(True)
        col.addWidget(self._grade_lbl)
        col.addWidget(self._score_sub)
        sc.addWidget(self._score_lbl)
        sc.addLayout(col, 1)
        lay.addWidget(score_card)

        # Tabs for ops sections
        self._tabs = QTabWidget()
        self._tabs.setMinimumHeight(420)
        lay.addWidget(self._tabs, 1)

        self._tabs.addTab(self._build_health_page(), 'Health')
        self._tabs.addTab(self._build_integrity_page(), 'Integrity')
        self._tabs.addTab(self._build_config_page(), 'Config Audit')
        self._tabs.addTab(self._build_analyze_page(), 'Analyze Error')
        self._tabs.addTab(self._build_heal_page(), 'Self-Healing')
        self._tabs.addTab(self._build_perf_page(), 'Performance')
        self._tabs.addTab(self._build_verify_page(), 'Update Verify')
        self._tabs.addTab(self._build_kb_page(), 'Knowledge Base')
        self._tabs.addTab(self._build_support_page(), 'Support')
        if is_superadmin_role(self._role()):
            self._tabs.addTab(self._build_dev_page(), 'Developer')

        self._apply_theme_bits()

    def _mk_list(self) -> QListWidget:
        lw = QListWidget()
        lw.setStyleSheet(
            f"QListWidget {{ background:{C['card']}; color:{C['text']}; border:1px solid {C['border']};"
            f" border-radius:10px; font-size:13px; }}"
            f"QListWidget::item {{ padding:8px; }}"
            f"QListWidget::item:selected {{ background:{C['selected']}; }}"
        )
        return lw

    def _build_health_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        self._health_list = self._mk_list()
        lay.addWidget(self._health_list, 1)
        return w

    def _build_integrity_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        row = QHBoxLayout()
        btn = PrimaryBtn('▶  Run Integrity Scan', 36)
        btn.clicked.connect(self.run_integrity)
        row.addWidget(btn); row.addStretch()
        lay.addLayout(row)
        self._integrity_summary = QLabel('')
        self._integrity_summary.setWordWrap(True)
        lay.addWidget(self._integrity_summary)
        self._integrity_list = self._mk_list()
        lay.addWidget(self._integrity_list, 1)
        return w

    def _build_config_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        row = QHBoxLayout()
        btn = PrimaryBtn('▶  Audit Configuration', 36)
        btn.clicked.connect(self.run_config_audit)
        row.addWidget(btn); row.addStretch()
        lay.addLayout(row)
        self._config_summary = QLabel('')
        self._config_summary.setWordWrap(True)
        lay.addWidget(self._config_summary)
        self._config_list = self._mk_list()
        lay.addWidget(self._config_list, 1)
        return w

    def _build_analyze_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        self._err_input = QTextEdit()
        self._err_input.setPlaceholderText('Paste error / traceback / log snippet…')
        self._err_input.setMinimumHeight(120)
        lay.addWidget(self._err_input)
        btn = PrimaryBtn('✦  Analyze with AI', 40)
        btn.clicked.connect(self.run_analyze)
        lay.addWidget(btn)
        self._analyze_out = QTextEdit()
        self._analyze_out.setReadOnly(True)
        lay.addWidget(self._analyze_out, 1)
        return w

    def _build_heal_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        note = QLabel(
            'Safe actions only. High-risk changes (void/delete/SQL/inventory/accounting) '
            'are never auto-run — approval still refuses destructive heals in v1.'
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['text2']}; font-size:12px; background:transparent;")
        lay.addWidget(note)
        for act in self._ops.safe_actions():
            row = QHBoxLayout()
            lbl = QLabel(act['label'])
            lbl.setStyleSheet(f"color:{C['text']}; font-size:13px; background:transparent;")
            b = SecondaryBtn('Run', 32)
            b.clicked.connect(lambda _, a=act['id']: self.run_heal(a))
            row.addWidget(lbl, 1); row.addWidget(b)
            lay.addLayout(row)
        self._heal_out = QLabel('')
        self._heal_out.setWordWrap(True)
        lay.addWidget(self._heal_out)
        lay.addStretch()
        return w

    def _build_perf_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        btn = PrimaryBtn('▶  Analyze Performance', 36)
        btn.clicked.connect(self.run_perf)
        lay.addWidget(btn)
        self._perf_out = QTextEdit(); self._perf_out.setReadOnly(True)
        lay.addWidget(self._perf_out, 1)
        return w

    def _build_verify_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        btn = PrimaryBtn('▶  Run Update Verification', 36)
        btn.clicked.connect(self.run_verify)
        lay.addWidget(btn)
        self._verify_summary = QLabel('')
        self._verify_summary.setWordWrap(True)
        lay.addWidget(self._verify_summary)
        self._verify_list = self._mk_list()
        lay.addWidget(self._verify_list, 1)
        return w

    def _build_kb_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        row = QHBoxLayout()
        self._kb_search = QLineEdit(); self._kb_search.setPlaceholderText('Search knowledge…')
        sbtn = SecondaryBtn('Search', 32); sbtn.clicked.connect(self.refresh_kb)
        abtn = PrimaryBtn('＋ Add', 32); abtn.clicked.connect(self._kb_add)
        row.addWidget(self._kb_search, 1); row.addWidget(sbtn); row.addWidget(abtn)
        lay.addLayout(row)
        self._kb_list = self._mk_list()
        self._kb_list.itemDoubleClicked.connect(self._kb_show)
        lay.addWidget(self._kb_list, 1)
        QTimer.singleShot(400, self.refresh_kb)
        return w

    def _build_support_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        info = QLabel(
            'Builds a redacted ZIP (health, integrity sample, config audit, log tails, AI summary). '
            'Never includes API keys or the full database.'
        )
        info.setWordWrap(True)
        lay.addWidget(info)
        btn = PrimaryBtn('📦  Generate Support Package', 40)
        btn.clicked.connect(self._support_report)
        lay.addWidget(btn)
        self._support_out = QLabel('')
        self._support_out.setWordWrap(True)
        lay.addWidget(self._support_out)
        lay.addStretch()
        return w

    def _build_dev_page(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(8, 12, 8, 8)
        self._dev_topic = QTextEdit()
        self._dev_topic.setPlaceholderText('Describe the bug / feature for a Cursor-ready prompt…')
        self._dev_topic.setFixedHeight(100)
        lay.addWidget(self._dev_topic)
        btn = PrimaryBtn('Generate Developer Prompt', 40)
        btn.clicked.connect(self.run_dev_prompt)
        lay.addWidget(btn)
        self._dev_out = QTextEdit(); self._dev_out.setReadOnly(True)
        lay.addWidget(self._dev_out, 1)
        return w

    # ── Theme / banner ────────────────────────────────────────────────────────

    def _apply_theme_bits(self):
        st = self._ops.ai_status()
        if st.get('banner'):
            self._banner.setText('⚠  ' + st['banner'])
            self._banner.setStyleSheet(
                f"color:{C['warn']}; background:{qss_alpha(C['warn'], 0.15)};"
                f" padding:10px 12px; border-radius:8px; font-weight:600;")
            self._banner.show()
        else:
            self._banner.hide()

    def set_light_mode(self, is_light: bool):
        self._apply_theme_bits()
        # Retint lists
        for lw in (
            getattr(self, '_health_list', None),
            getattr(self, '_integrity_list', None),
            getattr(self, '_config_list', None),
            getattr(self, '_verify_list', None),
            getattr(self, '_kb_list', None),
        ):
            if lw:
                lw.setStyleSheet(
                    f"QListWidget {{ background:{C['card']}; color:{C['text']}; "
                    f"border:1px solid {C['border']}; border-radius:10px; font-size:13px; }}"
                    f"QListWidget::item {{ padding:8px; }}"
                    f"QListWidget::item:selected {{ background:{C['selected']}; }}"
                )

    def on_show(self):
        self._apply_theme_bits()

    # ── Async helpers ─────────────────────────────────────────────────────────

    def _run_async(self, fn, on_ok, busy_msg='Working…'):
        if self._worker and self._worker.isRunning():
            QMessageBox.information(self, 'Busy', 'Another ops task is running.')
            return
        self._refresh_btn.setEnabled(False)
        self._score_sub.setText(busy_msg)

        def _ok(result):
            self._refresh_btn.setEnabled(True)
            try:
                on_ok(result)
            except Exception as e:
                QMessageBox.warning(self, 'Ops', str(e))

        def _fail(err):
            self._refresh_btn.setEnabled(True)
            self._score_sub.setText('Error')
            QMessageBox.warning(self, 'Ops failed', err)

        self._worker = _Worker(fn, self)
        self._worker.done.connect(_ok)
        self._worker.failed.connect(_fail)
        self._worker.start()

    # ── Actions ───────────────────────────────────────────────────────────────

    def refresh_health(self):
        self._run_async(
            lambda: self._ops.health(self.api, self.db_path),
            self._on_health,
            'Computing health…',
        )

    def _on_health(self, data: dict):
        score = int(data.get('score') or 0)
        self._score_lbl.setText(str(score))
        color = C['ok'] if score >= 75 else (C['warn'] if score >= 55 else C['err'])
        self._score_lbl.setStyleSheet(
            f"color:{color}; font-size:42px; font-weight:800; background:transparent;")
        self._grade_lbl.setText(f"Health · {data.get('grade', '')}")
        alerts = data.get('alerts') or []
        self._score_sub.setText(
            '; '.join(alerts[:3]) if alerts else 'All weighted checks within tolerance.')
        self._health_list.clear()
        for name, chk in (data.get('checks') or {}).items():
            stub = ' [stub]' if chk.get('stub') else ''
            self._health_list.addItem(
                f"{name.upper()}  ·  {chk.get('score', '—')}/100{stub}  —  {chk.get('detail', '')}"
            )
        self._apply_theme_bits()

    def run_integrity(self):
        self._run_async(
            lambda: self._ops.integrity(self.db_path),
            self._on_integrity,
            'Scanning integrity…',
        )

    def _on_integrity(self, data: dict):
        self._integrity_summary.setText(data.get('summary') or '')
        self._integrity_summary.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:600; background:transparent;")
        self._integrity_list.clear()
        for iss in data.get('issues') or []:
            self._integrity_list.addItem(
                f"[{iss.get('severity', '?').upper()}] {iss.get('message', '')}"
            )
        if not data.get('issues'):
            self._integrity_list.addItem('✓ No issues found')

    def run_config_audit(self):
        self._run_async(
            lambda: self._ops.config_audit(self.api, self.user),
            self._on_config,
            'Auditing config…',
        )

    def _on_config(self, data: dict):
        self._config_summary.setText(data.get('summary') or '')
        self._config_list.clear()
        for w in data.get('warnings') or []:
            self._config_list.addItem(
                f"[{w.get('severity', '?').upper()}] {w.get('area')}: {w.get('message')}"
            )
        if not data.get('warnings'):
            self._config_list.addItem('✓ Configuration looks healthy')

    def run_analyze(self):
        text = self._err_input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, 'Analyze', 'Paste an error first.')
            return

        def _fn():
            return self._ops.analyze(text, self.api, self.user)

        self._run_async(_fn, self._on_analyze, 'Analyzing…')

    def _on_analyze(self, data: dict):
        lines = [
            f"Severity: {data.get('severity')}  ·  Confidence: {data.get('confidence')}",
            '',
            f"Root cause:\n{data.get('root_cause')}",
            '',
            f"Fix:\n{data.get('fix')}",
        ]
        steps = data.get('steps') or []
        if steps:
            lines.append('\nSteps:')
            lines.extend(f'  {i+1}. {s}' for i, s in enumerate(steps))
        if data.get('developer_prompt'):
            lines.append('\n--- Developer prompt ---\n' + data['developer_prompt'])
        if data.get('banner'):
            lines.insert(0, data['banner'] + '\n')
        self._analyze_out.setPlainText('\n'.join(lines))

    def run_heal(self, action: str):
        confirm = QMessageBox.question(
            self, 'Confirm safe heal',
            f'Run safe self-heal action:\n\n{action}\n\nContinue?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        def _fn():
            return self._ops.heal(action, api=self.api, user=self.user, approved=False)

        self._run_async(_fn, self._on_heal, f'Healing {action}…')

    def _on_heal(self, data: dict):
        if data.get('needs_approval'):
            QMessageBox.warning(self, 'Approval required', data.get('error') or 'Needs approval')
            return
        msg = data.get('detail') or data.get('error') or str(data)
        self._heal_out.setText(('✓ ' if data.get('ok') else '✗ ') + msg)
        self._heal_out.setStyleSheet(
            f"color:{C['ok'] if data.get('ok') else C['err']}; font-size:13px; background:transparent;")

    def run_perf(self):
        self._run_async(
            lambda: self._ops.performance_snapshot(self.api),
            lambda d: self._perf_out.setPlainText(
                f"Health score: {d.get('health_score')}\n"
                f"DB latency: {d.get('db_ms')} ms\n"
                f"Memory: {d.get('memory')}\n\nTips:\n- " + '\n- '.join(d.get('tips') or [])
            ),
            'Profiling…',
        )

    def run_verify(self):
        self._run_async(
            lambda: self._ops.verify_update(self.api, self.db_path),
            self._on_verify,
            'Verifying update…',
        )

    def _on_verify(self, data: dict):
        status = data.get('status')
        color = C['ok'] if status == 'PASSED' else C['err']
        self._verify_summary.setText(data.get('summary') or status)
        self._verify_summary.setStyleSheet(
            f"color:{color}; font-size:14px; font-weight:700; background:transparent;")
        self._verify_list.clear()
        for c in data.get('checks') or []:
            mark = 'PASS' if c.get('passed') else 'FAIL'
            self._verify_list.addItem(
                f"[{mark}] {c.get('name')} — {c.get('detail')} ({c.get('ms')} ms)"
            )

    def refresh_kb(self):
        self._kb_list.clear()
        for row in self._ops.kb_list(self._kb_search.text()):
            item = QListWidgetItem(row.get('title') or 'Untitled')
            item.setData(Qt.UserRole, row)
            self._kb_list.addItem(item)

    def _kb_add(self):
        title, ok = QInputDialog.getText(self, 'Knowledge', 'Title:')
        if not ok or not title.strip():
            return
        symptoms, ok2 = QInputDialog.getMultiLineText(self, 'Knowledge', 'Symptoms:')
        if not ok2:
            return
        resolution, ok3 = QInputDialog.getMultiLineText(self, 'Knowledge', 'Resolution:')
        if not ok3:
            return
        u = self.user.get('user') or {}
        self._ops.kb_add(
            title.strip(), symptoms, resolution,
            created_by=str(u.get('username') or ''),
        )
        self.refresh_kb()

    def _kb_show(self, item: QListWidgetItem):
        row = item.data(Qt.UserRole) or {}
        QMessageBox.information(
            self, row.get('title') or 'Entry',
            f"Symptoms:\n{row.get('symptoms')}\n\nResolution:\n{row.get('resolution')}",
        )

    def _support_report(self):
        self._run_async(
            lambda: self._ops.support_zip(self.api, self.user),
            self._on_support,
            'Building support package…',
        )

    def _on_support(self, data: dict):
        path = data.get('path') or ''
        self._support_out.setText(f"Saved: {path}")
        QMessageBox.information(self, 'Support Report', f'Support package saved:\n\n{path}')

    def run_dev_prompt(self):
        topic = self._dev_topic.toPlainText().strip()
        if not topic:
            return
        self._run_async(
            lambda: self._ops.developer_prompt(topic, self.api, self.user),
            lambda text: self._dev_out.setPlainText(text if isinstance(text, str) else str(text)),
            'Generating prompt…',
        )
