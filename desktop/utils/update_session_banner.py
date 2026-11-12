"""Update strip under the top bar. Applying a state does no work that can stall."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from backend.update_session import session_view
from desktop.utils.theme import C, RADIUS


class UpdateSessionBanner(QWidget):
    install_clicked = pyqtSignal()
    later_clicked = pyqtSignal()
    retry_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('updateSessionBanner')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setVisible(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._title = QLabel('')
        self._title.setObjectName('updateSessionTitle')
        self._title.setWordWrap(False)
        row.addWidget(self._title, 1)

        self._primary = QPushButton('')
        self._primary.setObjectName('updateSessionPrimary')
        self._primary.setCursor(Qt.PointingHandCursor)
        self._primary.clicked.connect(self._on_primary)
        row.addWidget(self._primary)

        self._later = QPushButton('Later')
        self._later.setObjectName('updateSessionLater')
        self._later.setCursor(Qt.PointingHandCursor)
        self._later.clicked.connect(self.later_clicked.emit)
        row.addWidget(self._later)
        root.addLayout(row)

        self._detail = QLabel('')
        self._detail.setObjectName('updateSessionDetail')
        self._detail.setWordWrap(True)
        root.addWidget(self._detail)

        self._bar = QProgressBar()
        self._bar.setObjectName('updateSessionBar')
        self._bar.setTextVisible(True)
        self._bar.setFormat('%p%')
        self._bar.setFixedHeight(16)
        self._bar.setRange(0, 100)
        root.addWidget(self._bar)

        self._view = session_view('idle')
        self._paint()
        self._apply_chrome()

    def show_state(self, state: str, version: str = '', percent=None, detail: str = ''):
        self._view = session_view(state, version, percent, detail)
        self._apply_chrome()
        self.setVisible(bool(self._view['visible']))

    def view(self) -> dict:
        return dict(self._view)

    def _on_primary(self):
        if self._view.get('state') == 'failed':
            self.retry_clicked.emit()
            return
        self.install_clicked.emit()

    def _apply_chrome(self):
        view = self._view
        gold = C.get('gold', '#F5C518')
        gold_fg = C.get('gold_fg', '#0A0F1A')
        text = C.get('text', '#F4F7FB')
        muted = C.get('text2', '#A8B3C7')
        panel = C.get('panel', '#121A2B')
        border = C.get('border', '#2A3650')
        radius = RADIUS.get('md', 8)
        self.setStyleSheet(
            f"QWidget#updateSessionBanner {{ background:{panel};"
            f" border-bottom:1px solid {gold}; }}"
            f"QLabel#updateSessionTitle {{ color:{text}; font-size:14px; font-weight:700;"
            f" background:transparent; }}"
            f"QLabel#updateSessionDetail {{ color:{muted}; font-size:12px;"
            f" background:transparent; }}"
            f"QProgressBar#updateSessionBar {{ border:1px solid {border}; border-radius:6px;"
            f" background:{C.get('bg', '#0B1220')}; color:{text}; text-align:center;"
            f" font-size:11px; font-weight:600; }}"
            f"QProgressBar#updateSessionBar::chunk {{ background:{gold}; border-radius:5px; }}"
            f"QPushButton#updateSessionPrimary {{ background:{gold}; color:{gold_fg};"
            f" font-weight:700; border:none; border-radius:{radius}px; padding:6px 14px;"
            f" min-height:32px; }}"
            f"QPushButton#updateSessionLater {{ background:transparent; color:{text};"
            f" border:1px solid {border}; border-radius:{radius}px; padding:6px 12px;"
            f" min-height:32px; }}"
        )
        self._paint()

    def _paint(self):
        view = self._view
        self._title.setText(view.get('title') or '')
        self._detail.setText(view.get('detail') or '')
        primary = view.get('primary') or ''
        self._primary.setText(primary)
        self._primary.setVisible(bool(primary))
        self._later.setVisible(bool(view.get('secondary')))
        bar = view.get('bar') or 'hidden'
        if bar == 'hidden':
            self._bar.hide()
            return
        self._bar.show()
        if bar == 'busy':
            self._bar.setRange(0, 0)
            self._bar.setFormat('')
            return
        self._bar.setRange(0, 100)
        self._bar.setFormat('%p%')
        self._bar.setValue(int(view.get('percent') or 0))
