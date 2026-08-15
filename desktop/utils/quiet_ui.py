"""
Non-blocking POS feedback — prefer toast/status over modal OK dialogs.

Cashiers should not get surprise MessageBoxes after every sale or on boot.
Keep QMessageBox only for: confirmations (Yes/No), hard errors, user-clicked actions.

Remaining modals use Fusion + themed QSS (no white Windows chrome).
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("mbt.quiet_ui")


def _resolve_toast_host(parent):
    """Prefer a real window host — never birth a parentless toast HWND."""
    try:
        if parent is not None:
            win = parent.window() if hasattr(parent, "window") else parent
            if win is not None:
                return win
    except Exception:
        pass
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            aw = app.activeWindow()
            if aw is not None:
                return aw
            for w in app.topLevelWidgets():
                if w is not None and w.isVisible() and w.__class__.__name__ == "MainWindow":
                    return w
    except Exception:
        pass
    return None


def info_toast(parent, message: str, *, tone: str = "ok", ms: int = 3500) -> None:
    """Show a brief toast; never blocks the UI thread."""
    msg = (message or "").strip()
    if not msg:
        return
    host = _resolve_toast_host(parent)
    if host is None:
        log.debug("toast skipped (no host): %s", msg[:60])
        return
    try:
        from desktop.utils.ui_polish import ToastNotification
        ToastNotification.show_toast(host, msg.replace("\n", " · ")[:160], tone=tone, ms=ms)
    except Exception as e:
        log.debug("toast failed: %s", e)
        try:
            if hasattr(host, "_set_status"):
                host._set_status(msg.split("\n")[0][:48])
        except Exception:
            pass


def sale_complete_feedback(parent, title: str, body: str) -> None:
    """After a successful sale — toast + status, no OK modal."""
    head = (title or "Sale complete").strip()
    text = (body or "").strip()
    lines = [ln.strip() for ln in text.replace("✓", "").splitlines() if ln.strip()]
    short = lines[0] if lines else head
    if any(ln.lower().startswith("invoice:") or ln.lower().startswith("receipt:") for ln in lines):
        inv = next(
            (ln.split(":", 1)[-1].strip() for ln in lines
             if ln.lower().startswith("invoice:") or ln.lower().startswith("receipt:")),
            "",
        )
        if inv:
            short = f"Sale recorded · {inv}"
    info_toast(parent, short, tone="ok", ms=4000)
    try:
        win = parent.window() if parent is not None else None
        if win is not None and hasattr(win, "_set_status"):
            tip = text[:400] if text else head
            win._set_status(short[:48])
            sync = getattr(win, "_sync_lbl", None)
            if sync is not None:
                sync.setToolTip(tip)
    except Exception:
        pass


def soft_warn(parent, message: str) -> None:
    info_toast(parent, message, tone="warn", ms=3200)


def _live_colors():
    try:
        from desktop.utils.theme import C
        return C
    except Exception:
        return {
            "surface": "#0B1220", "card2": "#1B2943", "card": "#16213A",
            "text": "#FFFFFF", "text2": "#B4C2D6", "muted": "#7A8BA3",
            "border2": "#2A3A55", "gold": "#FBBF24", "gold_fg": "#0B1220",
            "input": "#101A2E", "hover": "#243352", "err": "#F87171",
            "warn": "#FBBF24", "ok": "#34D399",
        }


def messagebox_qss() -> str:
    """Standalone QSS so MessageBox never falls back to white system chrome."""
    C = _live_colors()
    return (
        f"QMessageBox{{background:{C['card2']};color:{C['text']};"
        f"border:1px solid {C['border2']};}}"
        f"QMessageBox QLabel{{color:{C['text']};background:transparent;"
        f"font-size:14px;min-width:280px;}}"
        f"QMessageBox QPushButton{{"
        f"background:{C['card']};color:{C['text']};"
        f"border:1px solid {C['border2']};border-radius:8px;"
        f"min-width:90px;min-height:34px;padding:6px 16px;font-weight:700;}}"
        f"QMessageBox QPushButton:hover{{border-color:{C['gold']};color:{C['gold']};}}"
        f"QMessageBox QPushButton:default{{"
        f"background:{C['gold']};color:{C.get('gold_fg', '#0B1220')};border:none;}}"
    )


def style_message_box(box) -> None:
    """Force Fusion + themed chrome on a QMessageBox instance."""
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor, QPalette
        from PyQt5.QtWidgets import QApplication
        C = _live_colors()
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setAutoFillBackground(True)
        try:
            box.setStyle(QApplication.style())  # stay on Fusion if app uses it
        except Exception:
            pass
        pal = box.palette()
        pal.setColor(QPalette.Window, QColor(C["card2"]))
        pal.setColor(QPalette.WindowText, QColor(C["text"]))
        pal.setColor(QPalette.Base, QColor(C.get("input", C["card2"])))
        pal.setColor(QPalette.Text, QColor(C["text"]))
        pal.setColor(QPalette.Button, QColor(C["card"]))
        pal.setColor(QPalette.ButtonText, QColor(C["text"]))
        box.setPalette(pal)
        box.setStyleSheet(messagebox_qss())
    except Exception as e:
        log.debug("style_message_box failed: %s", e)


def _exec_styled(parent, icon, title, text, buttons, default_button=None):
    from PyQt5.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(str(title or "MBT POS"))
    box.setText("" if text is None else str(text))
    box.setStandardButtons(buttons)
    if default_button is not None:
        try:
            box.setDefaultButton(default_button)
        except Exception:
            pass
    style_message_box(box)
    return box.exec_()


def install_empty_messagebox_guard() -> None:
    """Back-compat alias — installs dark + empty guards."""
    install_dark_messagebox_style()


def install_dark_messagebox_style() -> None:
    """
    Route static QMessageBox.* through styled instances (no white Win chrome).
    Also suppress empty-body information/warning/critical boxes.

    Soft feedback policy (cashiers):
      - information → always toast/status (never a centered OK modal)
      - warning with only OK → toast/status
      - warning/question with Yes|No → keep as modal (destructive confirms)
      - critical → keep as modal (hard errors)
    """
    try:
        from PyQt5.QtWidgets import QMessageBox
    except Exception:
        return
    if getattr(QMessageBox, "_mbt_dark_msg", False):
        return

    def _toastish(parent, title, text, *, tone: str = "ok"):
        body = "" if text is None else str(text)
        head = ("" if title is None else str(title)).strip()
        msg = body.strip() or head
        if head and body.strip() and head.lower() not in body.lower():
            msg = f"{head}: {body.strip()}"
        if tone == "warn":
            soft_warn(parent, msg)
        else:
            info_toast(parent, msg.replace("\n", " · ")[:160], tone=tone)
        return QMessageBox.Ok

    def _info(parent, title, text, buttons=None, defaultButton=None):
        body = "" if text is None else str(text)
        if not body.strip() and not (title or "").strip():
            log.warning("Suppressed empty QMessageBox title=%r", title)
            return QMessageBox.Ok
        # Never show a centered OK information modal on POS.
        return _toastish(parent, title, text, tone="ok")

    def _warn(parent, title, text, buttons=None, defaultButton=None):
        body = "" if text is None else str(text)
        if not body.strip() and not (title or "").strip():
            log.warning("Suppressed empty QMessageBox title=%r", title)
            return QMessageBox.Ok
        btns = QMessageBox.Ok if buttons is None else buttons
        # Yes/No (or Yes/No/Cancel) stays modal — destructive / choice confirms
        try:
            has_yes = bool(int(btns) & int(QMessageBox.Yes))
            has_no = bool(int(btns) & int(QMessageBox.No))
        except Exception:
            has_yes = has_no = False
        if has_yes and has_no:
            return _exec_styled(parent, QMessageBox.Warning, title, body, btns, defaultButton)
        return _toastish(parent, title, text, tone="warn")

    def _crit(parent, title, text, buttons=None, defaultButton=None):
        body = "" if text is None else str(text)
        if not body.strip():
            log.warning("Suppressed empty QMessageBox title=%r", title)
            return QMessageBox.Ok
        btns = QMessageBox.Ok if buttons is None else buttons
        return _exec_styled(parent, QMessageBox.Critical, title, body, btns, defaultButton)

    def _question(parent, title, text, buttons=None, defaultButton=None):
        body = "" if text is None else str(text)
        btns = (QMessageBox.Yes | QMessageBox.No) if buttons is None else buttons
        dflt = QMessageBox.No if defaultButton is None else defaultButton
        return _exec_styled(parent, QMessageBox.Question, title, body, btns, dflt)

    QMessageBox.information = staticmethod(_info)
    QMessageBox.warning = staticmethod(_warn)
    QMessageBox.critical = staticmethod(_crit)
    QMessageBox.question = staticmethod(_question)
    QMessageBox._mbt_dark_msg = True
    QMessageBox._mbt_empty_guard = True


def safe_detach(widget, park_under=None) -> None:
    """Hide + DontShowOnScreen, then park under stash or detach without painting.

    Call this instead of raw ``setParent(None)`` — a free HWND with default
    Window chrome is the millisecond centered flash cashiers report.
    """
    if widget is None:
        return
    try:
        from PyQt5.QtCore import Qt
        try:
            widget.hide()
        except Exception:
            pass
        try:
            widget.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
        if park_under is not None and park_under is not widget:
            try:
                widget.setParent(park_under)
                widget.hide()
                return
            except Exception:
                pass
        try:
            widget.setParent(None)
        except Exception:
            pass
    except RuntimeError:
        pass
    except Exception:
        pass


def safe_show(widget) -> bool:
    """Show only when the widget has a real parent (never a free top-level)."""
    if widget is None:
        return False
    try:
        from PyQt5.QtCore import Qt
        if widget.parent() is None:
            try:
                widget.hide()
                widget.setAttribute(Qt.WA_DontShowOnScreen, True)
            except Exception:
                try:
                    widget.hide()
                except Exception:
                    pass
            return False
        # Parent exists but might still be a free top-level itself — walk up.
        try:
            p = widget.parent()
            while p is not None:
                if p.parent() is None and p.isWindow() and not _is_intentional_toplevel(p):
                    # Anchored under an orphan window — do not paint yet
                    widget.hide()
                    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
                    return False
                p = p.parent()
        except Exception:
            pass
        try:
            widget.setAttribute(Qt.WA_DontShowOnScreen, False)
        except Exception:
            pass
        widget.show()
        return True
    except RuntimeError:
        return False
    except Exception:
        return False


def _is_intentional_toplevel(w) -> bool:
    """Dialogs, menus, splash, combo popups, toasts, main window — not flashes."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QDialog, QMainWindow, QMenu, QMessageBox

    try:
        if isinstance(w, (QDialog, QMessageBox, QMenu, QMainWindow)):
            return True
        name = w.objectName() or ""
        if name == "mbtToast" or name.startswith("qt_"):
            return True
        # Stash hosts must never paint even if briefly parentless
        if name in ("posLayoutStash", "mbtOrphanSink"):
            return False  # treat as flash candidates if they show
        flags = int(w.windowFlags())
        if flags & int(Qt.ToolTip):
            return True
        if flags & int(Qt.Popup):
            return True
        if flags & int(Qt.SplashScreen):
            return True
        cls = type(w).__name__
        if cls in ("AiAssistantPanel", "AiFullWorkspace", "AiFabButton"):
            return True
        if flags & int(Qt.Tool) and name in ("mbtToast", "mbtAiPanel", "mbtAiFab"):
            return True
        # SalesTab / MainWindow shown as QA harness
        if cls in ("SalesTab", "MainWindow", "LoginDialog", "SplashScreen"):
            return True
    except Exception:
        return False
    return False


def _is_orphan_flash_candidate(w) -> bool:
    """True when a widget is (or is becoming) a free top-level flash HWND.

    Any parentless QWidget Show paints a decorated/undecorated OS window for
    a frame — StockBadge, SaleTypeGroup, panels, etc. All must be blocked.
    """
    if w is None:
        return False
    try:
        from PyQt5.QtWidgets import QWidget
        if not isinstance(w, QWidget):
            return False
        if _is_intentional_toplevel(w):
            return False
        # Parentless = free HWND the instant it Shows (the user-visible flash)
        if w.parent() is None:
            return True
        # Parented but still a native Window (reparent race / Window flag leak)
        try:
            if w.isWindow():
                from PyQt5.QtCore import Qt
                flags = int(w.windowFlags())
                name = (w.objectName() or "")
                cls = type(w).__name__
                if name.startswith("pos") or cls in (
                    "StockBadge", "ProductCard", "SaleTypeGroup", "CategoryChipBar",
                    "PosSplitter", "QFrame", "QScrollArea",
                ):
                    if not (flags & int(Qt.Popup)):
                        return True
        except Exception:
            pass
    except RuntimeError:
        return False
    except Exception:
        return False
    return False


# Ring buffer of flash events for QA (ms timestamps)
FLASH_EVENTS: list = []
_FLASH_GRAB_DIR = None
_FLASH_GRAB_CB = None


def set_flash_grab_dir(path) -> None:
    """QA: directory to dump PNG grabs of blocked flash widgets."""
    global _FLASH_GRAB_DIR
    from pathlib import Path
    _FLASH_GRAB_DIR = Path(path) if path else None
    if _FLASH_GRAB_DIR:
        _FLASH_GRAB_DIR.mkdir(parents=True, exist_ok=True)


def flash_event_count() -> int:
    return len(FLASH_EVENTS)


def clear_flash_events() -> None:
    FLASH_EVENTS.clear()


def _record_flash(kind: str, w, killed) -> None:
    import time
    try:
        cls = type(w).__name__
        name = w.objectName() or ""
        title = ""
        try:
            title = (w.windowTitle() or "").strip()
        except Exception:
            pass
        geom = ""
        try:
            geom = f"{w.x()},{w.y()} {w.width()}x{w.height()}"
        except Exception:
            pass
        parent = None
        try:
            parent = type(w.parent()).__name__ if w.parent() else None
        except Exception:
            pass
        row = {
            "t_ms": int(time.time() * 1000),
            "kind": kind,
            "class": cls,
            "objectName": name,
            "title": title,
            "geom": geom,
            "parent": parent,
            "killed": bool(killed),
        }
        FLASH_EVENTS.append(row)
        log.warning(
            "FLASH %s: %s name=%r title=%r geom=%s parent=%s",
            kind, cls, name, title, geom, parent,
        )
        if _FLASH_GRAB_DIR is not None and killed:
            try:
                path = _FLASH_GRAB_DIR / (
                    f"flash_{len(FLASH_EVENTS):04d}_{cls}_{name or 'noname'}.png"
                )
                # May be empty/hidden — still try
                pix = w.grab()
                if pix and not pix.isNull():
                    pix.save(str(path))
            except Exception:
                pass
    except Exception as e:
        log.debug("record flash: %s", e)


def _kill_orphan(w) -> tuple | None:
    try:
        cls = type(w).__name__
        name = w.objectName() or ""
        title = ""
        try:
            title = (w.windowTitle() or "").strip()
        except Exception:
            pass
        try:
            w.hide()
        except Exception:
            pass
        try:
            from PyQt5.QtCore import Qt
            w.setAttribute(Qt.WA_DontShowOnScreen, True)
            # Prevent Windows from painting decorated chrome if HWND already exists
            try:
                w.setWindowOpacity(0.0)
            except Exception:
                pass
        except Exception:
            pass
        return (cls, name, title)
    except RuntimeError:
        return None
    except Exception:
        return None


class _OrphanFlashFilter:
    """Application event filter — blocks Show/WinId on parentless flash panels.

    Flashes last milliseconds; 200ms polling misses them. Intercepting Show
    before paint is the only reliable kill.
    """

    _installed = False
    _depth = 0
    _blocked: list = []
    _filter_obj = None
    _log_all_shows = False  # QA can enable

    @classmethod
    def install(cls) -> None:
        if cls._installed:
            return
        try:
            from PyQt5.QtCore import QEvent, QObject
            from PyQt5.QtWidgets import QApplication, QWidget
        except Exception:
            return

        class _Filter(QObject):
            def eventFilter(self, obj, event):  # noqa: N802
                try:
                    if not isinstance(obj, QWidget):
                        return False
                    et = event.type()
                    # WinIdChange: HWND born — kill parentless before first paint
                    if et == QEvent.WinIdChange:
                        if _is_orphan_flash_candidate(obj):
                            killed = _kill_orphan(obj)
                            _record_flash("WinIdChange", obj, killed)
                            if killed:
                                _OrphanFlashFilter._blocked.append(killed)
                            return False  # don't eat WinIdChange
                    if et in (QEvent.Show, QEvent.ShowToParent):
                        # Fast path: any parentless non-intentional widget Show
                        # is a flash — kill before paint (StockBadge etc.).
                        try:
                            parentless = obj.parent() is None
                        except Exception:
                            parentless = False
                        if parentless and not _is_intentional_toplevel(obj):
                            killed = _kill_orphan(obj)
                            _record_flash("Show", obj, killed)
                            if killed:
                                _OrphanFlashFilter._blocked.append(killed)
                            return True
                        if _OrphanFlashFilter._log_all_shows:
                            try:
                                if obj.parent() is None or obj.isWindow():
                                    _record_flash("ShowTrace", obj, False)
                            except Exception:
                                pass
                        if _is_orphan_flash_candidate(obj):
                            killed = _kill_orphan(obj)
                            _record_flash("Show", obj, killed)
                            if killed:
                                _OrphanFlashFilter._blocked.append(killed)
                                log.warning(
                                    "Blocked orphan Show: %s name=%r title=%r",
                                    killed[0], killed[1], killed[2],
                                )
                            return True
                        if _OrphanFlashFilter._depth > 0:
                            hide_orphan_pos_flashes()
                    if et == QEvent.Polish and _is_orphan_flash_candidate(obj):
                        _kill_orphan(obj)
                        _record_flash("Polish", obj, True)
                except RuntimeError:
                    pass
                except Exception as e:
                    log.debug("orphan filter: %s", e)
                return False

        app = QApplication.instance()
        if app is None:
            return
        flt = _Filter(app)
        app.installEventFilter(flt)
        cls._filter_obj = flt
        cls._installed = True
        log.info("Orphan flash Show/WinId filter installed")

    @classmethod
    def begin(cls) -> None:
        cls.install()
        cls._depth += 1

    @classmethod
    def end(cls) -> list:
        cls._depth = max(0, cls._depth - 1)
        hid = hide_orphan_pos_flashes()
        blocked = list(cls._blocked)
        if cls._depth == 0:
            cls._blocked = []
        return blocked + hid


def install_orphan_flash_guard() -> None:
    """Install the always-on Show filter (call once at app boot)."""
    _OrphanFlashFilter.install()


def begin_layout_orphan_guard() -> None:
    """Nestable: call around apply_layout_shell / splitter rebuilds."""
    _OrphanFlashFilter.begin()


def end_layout_orphan_guard() -> list:
    return _OrphanFlashFilter.end()


def hide_orphan_pos_flashes(anchor=None) -> list:
    """
    Hide accidental top-level panel flashes (parentless QFrame/QScrollArea/QWidget/
    QSplitter). Skips main window, intentional dialogs/menus, toasts, splash, popups.
    Returns a list of (class, objectName, title) for anything it hid.
    """
    hidden = []
    try:
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return hidden

    app = QApplication.instance()
    if app is None:
        return hidden

    main = None
    if anchor is not None:
        try:
            main = anchor.window()
        except Exception:
            main = None

    for w in list(app.topLevelWidgets()):
        if w is None:
            continue
        try:
            if main is not None and (w is main or w is anchor):
                continue
            if not _is_orphan_flash_candidate(w):
                continue
            killed = _kill_orphan(w)
            if killed:
                hidden.append(killed)
                _record_flash("Sweep", w, killed)
                log.warning(
                    "Hid orphan top-level flash: %s name=%r title=%r",
                    killed[0], killed[1], killed[2],
                )
        except RuntimeError:
            continue
        except Exception as e:
            log.debug("orphan sweep: %s", e)
    return hidden


def inventory_toplevels(anchor=None) -> list:
    """Snapshot of visible top-level widgets for QA evidence."""
    rows = []
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return rows
    app = QApplication.instance()
    if app is None:
        return rows
    main = None
    if anchor is not None:
        try:
            main = anchor.window()
        except Exception:
            pass
    for w in app.topLevelWidgets():
        try:
            if not w.isVisible():
                continue
            flags = int(w.windowFlags())
            rows.append({
                "class": type(w).__name__,
                "objectName": w.objectName() or "",
                "title": (w.windowTitle() or "").strip(),
                "is_main": bool(main is not None and w is main),
                "is_window": bool(w.isWindow()),
                "tooltip": bool(flags & int(Qt.ToolTip)),
                "popup": bool(flags & int(Qt.Popup)),
                "parent": type(w.parent()).__name__ if w.parent() else None,
            })
        except RuntimeError:
            continue
        except Exception:
            continue
    return rows

# -- Debug: last top-level window log (user can send this file) ----------------

_DEBUG_TL_PATH = None
_DEBUG_TL_LAST = ""
_DEBUG_TL_TIMER = None


def _debug_tl_path():
    global _DEBUG_TL_PATH
    if _DEBUG_TL_PATH:
        return _DEBUG_TL_PATH
    import os
    from pathlib import Path
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "MugoByte" / "MBT POS" / "logs"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path(".")
    _DEBUG_TL_PATH = base / "toplevel_debug.log"
    return _DEBUG_TL_PATH


def log_toplevel_snapshot(anchor=None, *, reason: str = "") -> None:
    """Append a snapshot of visible top-level widgets to toplevel_debug.log."""
    global _DEBUG_TL_LAST
    try:
        rows = inventory_toplevels(anchor)
        line = (
            f"{__import__('datetime').datetime.now().isoformat(timespec='seconds')} "
            f"reason={reason!r} count={len(rows)} "
            + " | ".join(
                f"{r['class']}[{r['objectName'] or '-'}]"
                f" title={r['title']!r} main={r['is_main']} tip={r['tooltip']} popup={r['popup']}"
                for r in rows
            )
        )
        if line == _DEBUG_TL_LAST:
            return
        _DEBUG_TL_LAST = line
        path = _debug_tl_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        log.debug("toplevel snapshot failed: %s", e)


def install_toplevel_debug_logger(main_window=None) -> None:
    """Poll top-level widgets every 16ms + orphan sweep (flash-catch cadence)."""
    global _DEBUG_TL_TIMER
    try:
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication
    except Exception:
        return
    if _DEBUG_TL_TIMER is not None:
        return
    app = QApplication.instance()
    if app is None:
        return

    def _tick():
        try:
            hide_orphan_pos_flashes(main_window)
            log_toplevel_snapshot(main_window, reason="poll16")
        except Exception:
            pass

    t = QTimer(app)
    t.setInterval(16)
    t.timeout.connect(_tick)
    t.start()
    _DEBUG_TL_TIMER = t
    log.info("Toplevel debug logger 16ms ? %s", _debug_tl_path())
