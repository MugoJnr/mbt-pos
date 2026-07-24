"""
MBT POS — Lightweight UI polish helpers (toasts, empty states, FAB, KPI motion).
Keep animations 150–300ms; no heavy dependencies.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QRect,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import QCursor, QFont
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop.utils.theme import C, RADIUS, qss_alpha


def apply_card_shadow(widget: QWidget, blur: int = 18, dy: int = 6, alpha: int = 64) -> None:
    """Subtle elevation — disabled by default on Windows to avoid Qt effect crashes."""
    # QGraphicsDropShadowEffect + many cards can crash some GPU/driver combos.
    # Keep API for call sites; visual depth comes from border/hover instead.
    return


def fade_in(widget: QWidget, duration: int = 220) -> None:
    # Skip opacity effects on Windows — can conflict with layout/paint.
    return


class EmptyState(QFrame):
    """Centered empty placeholder — painted icon + title + muted caption."""

    def __init__(self, icon: str, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("mbtEmptyState")
        self._icon_key = icon or "box"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 32, 24, 32)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignCenter)
        self._icon = QLabel()
        self._icon.setFixedSize(52, 52)
        self._icon.setAlignment(Qt.AlignCenter)
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._sub = QLabel(subtitle)
        self._sub.setAlignment(Qt.AlignCenter)
        self._sub.setWordWrap(True)
        lay.addWidget(self._icon, 0, Qt.AlignCenter)
        lay.addWidget(self._title)
        if subtitle:
            lay.addWidget(self._sub)
        self.refresh_theme()

    def refresh_theme(self):
        gold = C["gold"]
        self.setStyleSheet(
            f"QFrame#mbtEmptyState {{ background:transparent; border:none; }}"
        )
        self._icon.setStyleSheet(
            f"background:{qss_alpha(gold, 0.12)}; border-radius:26px; border:none;"
        )
        try:
            from desktop.utils.nav_icons import kpi_pixmap
            self._icon.setPixmap(kpi_pixmap(self._icon_key, 26, accent=gold))
            self._icon.setText("")
        except Exception:
            self._icon.setText("·")
            self._icon.setStyleSheet(
                f"font-size:22px; font-weight:800; color:{gold}; "
                f"background:{qss_alpha(gold, 0.12)}; border-radius:26px; border:none;"
            )
        self._title.setStyleSheet(
            f"color:{C['text']}; font-size:15px; font-weight:700; background:transparent; border:none;"
        )
        self._sub.setStyleSheet(
            f"color:{C['text2']}; font-size:13px; background:transparent; border:none;"
        )


class ToastNotification(QFrame):
    """Auto-dismiss toast — bottom-center of parent."""

    _active: List["ToastNotification"] = []

    def __init__(self, message: str, tone: str = "ok", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("mbtToast")
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)
        tone_map = {
            "ok": C["ok"],
            "warn": C["warn"],
            "err": C["err"],
            "info": C["info"],
            "gold": C["gold"],
        }
        color = tone_map.get(tone, C["ok"])
        dot = QLabel("*")
        dot.setStyleSheet(f"color:{color}; font-size:12px; background:transparent; border:none;")
        msg = QLabel(message)
        msg.setStyleSheet(
            f"color:{C['text']}; font-size:13px; font-weight:600; background:transparent; border:none;"
        )
        lay.addWidget(dot)
        lay.addWidget(msg)
        r = RADIUS["xl"]
        self.setStyleSheet(
            f"QFrame#mbtToast {{ background:{C['card2']}; border:1px solid {qss_alpha(color, 0.45)}; "
            f"border-radius:{r}px; }}"
        )
        apply_card_shadow(self, blur=22, dy=8, alpha=90)
        self.adjustSize()

    @classmethod
    def show_toast(
        cls,
        parent: QWidget,
        message: str,
        tone: str = "ok",
        ms: int = 4000,
    ) -> "ToastNotification":
        toast = cls(message, tone=tone, parent=parent.window() if parent else None)
        host = parent.window() if parent else parent
        toast.setParent(host)
        toast.show()
        toast.raise_()
        # Stack from bottom
        cls._active = [t for t in cls._active if t.isVisible()]
        cls._active.append(toast)
        cls._reposition(host)
        fade_in(toast, 180)

        def _close():
            try:
                if toast in cls._active:
                    cls._active.remove(toast)
                toast.close()
                toast.deleteLater()
                cls._reposition(host)
            except Exception:
                pass

        QTimer.singleShot(ms, _close)
        return toast

    @classmethod
    def _reposition(cls, host: Optional[QWidget]):
        if not host:
            return
        margin = 24
        y = host.height() - margin
        for t in reversed(cls._active):
            if not t.isVisible():
                continue
            t.adjustSize()
            x = (host.width() - t.width()) // 2
            y -= t.height() + 10
            t.move(max(12, x), max(12, y))


class FloatingActionButton(QWidget):
    """Bottom-right + FAB that expands into quick actions."""

    def __init__(self, actions: List[Tuple[str, str, Callable]], parent=None):
        """
        actions: list of (icon_label, text, callback)
        """
        super().__init__(parent)
        self._actions = actions
        self._open = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._menu = QFrame(self)
        self._menu.setObjectName("mbtFabMenu")
        ml = QVBoxLayout(self._menu)
        ml.setContentsMargins(10, 10, 10, 10)
        ml.setSpacing(8)
        self._menu_btns = []
        for icon, text, cb in actions:
            b = QPushButton(f"{icon}  {text}")
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(40)
            b.clicked.connect(self._make_handler(cb))
            ml.addWidget(b)
            self._menu_btns.append(b)
        self._menu.hide()

        self._fab = QPushButton("+", self)
        self._fab.setObjectName("mbtFab")
        self._fab.setFixedSize(56, 56)
        self._fab.setCursor(Qt.PointingHandCursor)
        self._fab.clicked.connect(self.toggle)
        self.refresh_theme()
        self._menu.adjustSize()
        self.sync_footprint()

    def _make_handler(self, cb: Callable):
        def _h():
            self.close_menu()
            try:
                cb()
            except Exception:
                pass
        return _h

    def sync_footprint(self):
        """Collapsed = button only; open = menu + button (avoids overlaying charts)."""
        if self._open:
            self._menu.adjustSize()
            mw = max(180, self._menu.sizeHint().width())
            mh = self._menu.sizeHint().height()
            self.setFixedSize(max(220, mw + 16), mh + 56 + 24)
        else:
            self.setFixedSize(72, 72)
        self._layout_children()

    def refresh_theme(self):
        r = 28
        gold = C["gold"]
        fg = C.get("gold_fg", "#0B1120")
        self._fab.setStyleSheet(
            f"QPushButton#mbtFab {{ background:{gold}; color:{fg}; border:none; "
            f"border-radius:{r}px; font-size:26px; font-weight:700; }}"
            f"QPushButton#mbtFab:hover {{ background:{C['gold_lt']}; }}"
        )
        apply_card_shadow(self._fab, blur=20, dy=6, alpha=100)
        card = C["card"]
        border = C["border"]
        rr = RADIUS["xl"]
        self._menu.setStyleSheet(
            f"QFrame#mbtFabMenu {{ background:{card}; border:1px solid {border}; "
            f"border-radius:{rr}px; }}"
            f"QPushButton {{ background:{C['card2']}; color:{C['text']}; border:1px solid {border}; "
            f"border-radius:10px; font-size:13px; font-weight:600; text-align:left; padding:0 12px; }}"
            f"QPushButton:hover {{ border-color:{gold}; color:{gold}; }}"
        )
        self.sync_footprint()

    def _layout_children(self):
        self._fab.move(self.width() - 56 - 8, self.height() - 56 - 8)
        mw = self._menu.sizeHint().width()
        mh = self._menu.sizeHint().height()
        self._menu.setFixedSize(max(180, mw), mh)
        self._menu.move(
            self.width() - self._menu.width() - 8,
            self.height() - 56 - 16 - self._menu.height(),
        )

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_children()

    def toggle(self):
        if self._open:
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        self._open = True
        self._menu.show()
        self._fab.setText("×")
        self.sync_footprint()

    def close_menu(self):
        self._open = False
        self._menu.hide()
        self._fab.setText("+")
        self.sync_footprint()


class AnimatedKPI(QFrame):
    """KPI card with hover lift, glow accent, trend chip, animated numeric value."""

    clicked = pyqtSignal()

    def __init__(
        self,
        label: str,
        icon: str,
        value: str = "--",
        sub: str = "",
        accent: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._accent = accent or C["gold"]
        self._label = label
        self._icon_key = icon
        self._numeric_target: Optional[float] = None
        self._numeric_current = 0.0
        self._is_money = False
        self._prefix = ""
        self._anim_timer: Optional[QTimer] = None
        self._actionable = False
        self.setMinimumHeight(112)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.NoFocus)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        self._icon = QLabel()
        self._icon.setFixedSize(48, 48)
        self._icon.setAlignment(Qt.AlignCenter)
        root.addWidget(self._icon)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        self._lbl = QLabel(label)
        self._val = QLabel(str(value))
        self._sub = QLabel(str(sub))
        self._trend = QLabel("")
        self._trend.hide()
        col.addWidget(self._lbl)
        col.addWidget(self._val)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._sub)
        row.addWidget(self._trend)
        row.addStretch()
        col.addLayout(row)
        root.addLayout(col, 1)
        self.refresh_theme()
        fade_in(self, 200)

    def set_actionable(self, enabled: bool, tooltip: str = "", accessible_name: str = ""):
        """Mark KPI as a clickable control (keyboard + mouse)."""
        self._actionable = bool(enabled)
        if self._actionable:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            self.setToolTip(tooltip or f"Open {self._label}")
            self.setAccessibleName(accessible_name or self._label)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.setFocusPolicy(Qt.NoFocus)
            self.setToolTip("")

    def mouseReleaseEvent(self, e):
        if self._actionable and e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if self._actionable and e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def refresh_theme(self):
        a = self._accent or C["gold"]
        r = RADIUS["xl"]
        self.setStyleSheet(
            f"QFrame {{ background:{C['card']}; border:1px solid {C['border']}; "
            f"border-radius:{r}px; border-left:4px solid {a}; }}"
            f"QFrame:hover {{ background:{C['card2']}; border-color:{qss_alpha(a, 0.55)}; }}"
        )
        self._icon.setStyleSheet(
            f"background:{qss_alpha(a, 0.14)}; border-radius:24px; "
            f"border:none;"
        )
        try:
            from desktop.utils.nav_icons import kpi_pixmap
            self._icon.setPixmap(kpi_pixmap(self._icon_key, 24, accent=a))
            self._icon.setText("")
        except Exception:
            pass
        self._lbl.setStyleSheet(
            f"color:{C['muted']}; font-size:11px; font-weight:700; letter-spacing:0.6px; "
            f"background:transparent; border:none;"
        )
        self._val.setStyleSheet(
            f"color:{a}; font-size:32px; font-weight:800; background:transparent; border:none;"
        )
        self._val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Tabular figures so KPI decimals/columns scan consistently across the row
        try:
            f = self._val.font()
            f.setStyleHint(QFont.TypeWriter)
            f.setFamilies(["Cascadia Mono", "Consolas", "Segoe UI", f.family()])
            self._val.setFont(f)
        except Exception:
            pass
        self._sub.setStyleSheet(
            f"color:{C['text2']}; font-size:12px; background:transparent; border:none;"
        )

    def enterEvent(self, e):
        super().enterEvent(e)
        # Hover style is QSS-only — avoid geometry animation (breaks layouts).

    def leaveEvent(self, e):
        super().leaveEvent(e)

    def set_value(self, v, color=None):
        """Set display value; animates when purely numeric or KES money-like."""
        if color:
            self._accent = color
            self.refresh_theme()
        text = str(v)
        # Try animate integers / money
        cleaned = text.replace(",", "").replace(self._prefix, "").strip()
        money = False
        prefix = ""
        for pfx in ("KES ", "KES", "$", "£"):
            if text.startswith(pfx):
                money = True
                prefix = "KES " if "KES" in pfx else pfx
                cleaned = text[len(pfx):].replace(",", "").strip()
                break
        try:
            target = float(cleaned)
            self._prefix = prefix
            self._numeric_current = target
            # Always commit the final figure immediately — animated count-up caused
            # mid-tween screenshots / glanceable mismatches across tabs during refresh.
            if money or prefix:
                self._val.setText(f"{prefix}{target:,.2f}")
            elif abs(target - round(target)) < 0.01:
                self._val.setText(str(int(round(target))))
            else:
                self._val.setText(f"{target:,.1f}")
            return
        except Exception:
            pass
        self._val.setText(text)

    def set_sub(self, s: str):
        self._sub.setText(str(s))

    def set_trend(self, pct: Optional[float]):
        """pct: positive = up (green), negative = down (red). None hides."""
        if pct is None:
            self._trend.hide()
            return
        up = pct >= 0
        arrow = "▲" if up else "▼"
        color = C["ok"] if up else C["err"]
        self._trend.setText(f"{arrow} {abs(pct):.0f}%")
        self._trend.setStyleSheet(
            f"color:{color}; font-size:12px; font-weight:700; background:transparent; border:none;"
        )
        self._trend.show()

    def _animate_to(self, target: float, money: bool = False, prefix: str = ""):
        if self._anim_timer:
            self._anim_timer.stop()
        start = self._numeric_current
        steps = 14
        step_i = {"i": 0}

        def tick():
            step_i["i"] += 1
            t = min(1.0, step_i["i"] / steps)
            # ease out
            t = 1 - (1 - t) ** 2
            cur = start + (target - start) * t
            self._numeric_current = cur
            if money:
                self._val.setText(f"{prefix}{cur:,.2f}")
            elif abs(target - round(target)) < 0.01:
                self._val.setText(str(int(round(cur))))
            else:
                self._val.setText(f"{cur:,.1f}")
            if step_i["i"] >= steps:
                self._numeric_current = target
                if money:
                    self._val.setText(f"{prefix}{target:,.2f}")
                elif abs(target - round(target)) < 0.01:
                    self._val.setText(str(int(round(target))))
                self._anim_timer.stop()

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(tick)
        self._anim_timer.start(33)  # ~30fps — avoid flooding Qt event loop


def time_greeting(full_name: str) -> Tuple[str, str]:
    """Return (headline, subline) based on local hour."""
    from datetime import datetime, date
    hour = datetime.now().hour
    if hour < 12:
        hello = "Good Morning"
    elif hour < 17:
        hello = "Good Afternoon"
    else:
        hello = "Good Evening"
    raw = (full_name or "there").strip()
    parts = raw.split()
    # Prefer a real given name; skip generic role words
    skip = {"system", "administrator", "admin", "user", "cashier", "manager"}
    first = next((p for p in parts if p.lower() not in skip), parts[0] if parts else "there")
    if first.lower() in skip and len(parts) > 1:
        first = parts[-1]
    today = date.today()
    headline = f"{hello}, {first}"
    sub = f"{today.strftime('%A, %B %d')}  ·  Here's what's happening today."
    return headline, sub
