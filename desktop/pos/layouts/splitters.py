"""User-adjustable POS column widths — and the Current Sale internal stack.

Every checkout layout composes its major horizontal regions inside one shared
``PosSplitter`` so cashiers can drag the gutters instead of living with fixed
stretch factors. A second, vertical ``PosSplitter`` lives inside the Current
Sale panel itself, splitting the cart line list from the order-summary/totals
block. Both persist sizes per layout under their own settings key and restore
whenever that layout is applied (or the app restarts).

Handles paint a themed grip (subtle border colour, gold on hover) so the drag
affordance reads in both dark navy and light mode. Double-clicking a handle
resets that splitter back to its shipped default proportions.
"""
from __future__ import annotations

import json
import threading

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QSizePolicy, QSplitter, QSplitterHandle, QWidget

from desktop.pos.layout_ids import (
    LAYOUT_CHECKOUT_PRO,
    LAYOUT_PRODUCT_EXPLORER,
    LAYOUT_RETAIL_CLASSIC,
    normalize_layout_id,
)
from desktop.utils.pos_components import CART_CASHIER_ROWS, cart_viewport_px

POS_SPLITTER_KEY = 'pos_splitter_sizes'
CART_SPLITTER_KEY = 'pos_cart_splitter_sizes'

# Wide enough to grab on HiDPI / touchpads. Global theme used to force 1px handles
# which made drag feel broken even when the painted grip looked fine.
HANDLE_W = 16

# Classic / Explorer stack sale+actions in one rail — leave this much drag room
# or the yellow cart↔summary grip is a dead ornament (tooltip works, sizes don't).
CART_FREE_TRAVEL = 120

# Floors that keep a pane usable rather than a sliver. Maximums stay open so the
# cashier decides how to trade catalog pixels for cart/payment pixels.
# Checkout Pro: catalog | Current Sale | payment — never let Sale/pay collapse
# to an invisible gutter (that is what produced the products-only screenshot).
MIN_WIDTHS = {
    LAYOUT_CHECKOUT_PRO: (240, 280, 300),
    LAYOUT_PRODUCT_EXPLORER: (360, 460),
    LAYOUT_RETAIL_CLASSIC: (360, 460),
}
# When the shell is narrower than the sum of floors (1024×768, square, 150% DPI),
# scale down instead of forcing overflow / overlapping panes.
HARD_MIN_WIDTHS = {
    LAYOUT_CHECKOUT_PRO: (140, 180, 200),
    LAYOUT_PRODUCT_EXPLORER: (200, 240),
    LAYOUT_RETAIL_CLASSIC: (200, 240),
}
# Square / tablet shells (1024²–1280²) — shipped floors starve catalog & clip the pay rail.
NARROW_SHELL = 1120


def _mins_for(lid: str, count: int, available: int | None = None) -> tuple:
    lid = normalize_layout_id(lid)
    mins = MIN_WIDTHS.get(lid)
    if not mins or len(mins) != count:
        if count >= 3:
            mins = MIN_WIDTHS[LAYOUT_CHECKOUT_PRO]
        elif count == 2:
            mins = (360, 460)
        else:
            mins = tuple(240 for _ in range(max(1, count)))
    mins = tuple(int(n) for n in mins)
    if (
        available is not None
        and lid == LAYOUT_CHECKOUT_PRO
        and count == 3
        and int(available) <= NARROW_SHELL
    ):
        hard = HARD_MIN_WIDTHS.get(lid, (140, 180, 200))
        avail = max(sum(hard), int(available))
        # Sale scrolls; catalog + payment need readable width on square displays.
        rail_pct = 0.36 if avail < 900 else 0.34
        rail = max(hard[2], int(avail * rail_pct))
        side = max(hard[0], int(avail * 0.30))
        mid = max(hard[1], avail - side - rail)
        if side + mid + rail > avail:
            mid = max(hard[1], avail - side - rail)
        if side + mid + rail > avail:
            side = max(hard[0], avail - mid - rail)
        return (side, mid, rail)
    if (
        available is not None
        and count == 2
        and int(available) <= NARROW_SHELL
    ):
        hard = HARD_MIN_WIDTHS.get(lid, (200, 240))
        avail = max(sum(hard), int(available))
        pin = max(hard[1], min(_PINNED_RAIL.get(lid, 560), int(avail * 0.52)))
        side = max(hard[0], avail - pin)
        return (side, pin)
    if available is None or available >= sum(mins):
        return mins
    hard = HARD_MIN_WIDTHS.get(lid)
    if not hard or len(hard) != count:
        hard = tuple(max(120, int(m * 0.5)) for m in mins)
    hard = tuple(int(n) for n in hard)
    avail = max(sum(hard), int(available))
    if avail <= sum(hard):
        return hard
    scale = avail / float(sum(mins))
    scaled = tuple(max(hard[i], int(mins[i] * scale)) for i in range(count))
    drift = avail - sum(scaled)
    if drift != 0:
        lst = list(scaled)
        lst[1 if count > 1 else 0] += drift
        scaled = tuple(lst)
    return scaled


def _sizes_meet_mins(sizes, mins) -> bool:
    if not sizes or not mins or len(sizes) != len(mins):
        return False
    return all(int(s) >= int(m) for s, m in zip(sizes, mins))


def _clamp_to_mins(sizes: list, mins: tuple, total: int) -> list:
    """Raise any pane below its floor, taking pixels from the largest pane."""
    n = len(mins)
    out = [max(1, int(s)) for s in sizes[:n]]
    while len(out) < n:
        out.append(int(mins[len(out)]))
    floor = sum(mins)
    total = max(floor, int(total))
    for i, m in enumerate(mins):
        if out[i] < m:
            need = m - out[i]
            out[i] = m
            # Steal from the currently largest pane that can spare it.
            order = sorted(range(n), key=lambda j: out[j], reverse=True)
            for j in order:
                if j == i:
                    continue
                spare = out[j] - mins[j]
                if spare <= 0:
                    continue
                take = min(spare, need)
                out[j] -= take
                need -= take
                if need <= 0:
                    break
    # Fit exactly to total while keeping floors.
    drift = total - sum(out)
    if drift != 0:
        grow = sorted(range(n), key=lambda j: out[j], reverse=True)
        idx = grow[0]
        if drift > 0:
            out[idx] += drift
        else:
            for j in grow:
                spare = out[j] - mins[j]
                if spare <= 0:
                    continue
                take = min(spare, -drift)
                out[j] -= take
                drift += take
                if drift >= 0:
                    break
    return out

# Shipped starting widths: Pro keeps 25/50/25, Classic/Explorer keep the rail
# widths they had as fixed panels.
_PINNED_RAIL = {
    LAYOUT_PRODUCT_EXPLORER: 560,
    LAYOUT_RETAIL_CLASSIC: 600,
}

# Current Sale's internal stack (cart line list | order summary/totals).
# Floors keep a couple of cart rows / totals visible. Classic/Explorer use lower
# floors because sale shares the right rail with payment — high floors left
# free=0 and made the gutter look broken.
# Cart list floor is hard — poisoned persisted sizes that collapse the list to
# ~0px (header still shows "N items") are scrubbed below.
_CART_LIST_FLOOR = cart_viewport_px(CART_CASHIER_ROWS, include_header=True)
_CART_CLASSIC_FLOOR = _CART_LIST_FLOOR
CART_MIN_HEIGHTS = {
    # Cashier viewport ≈ header + 5×76px rows; splitter grows the list further.
    LAYOUT_CHECKOUT_PRO: (_CART_LIST_FLOOR, 140),
    LAYOUT_PRODUCT_EXPLORER: (_CART_CLASSIC_FLOOR, 90),
    LAYOUT_RETAIL_CLASSIC: (_CART_CLASSIC_FLOOR, 90),
}
# Responsive absolute floor: normal layouts ship with five complete rows above,
# but 1366x768 at 150% has only ~512 logical pixels. Preserve three usable rows
# there and scroll, instead of forcing cart/summary/payment panes to overlap.
CART_LIST_HARD_MIN = cart_viewport_px(3)
# Shipped starting split: cart gets the larger share, totals keep their natural size.
CART_DEFAULT_RATIO = 0.70
# Checkout Pro (non-Review): pack cart to the 5-row cashier viewport; summary sits under it.
# Prefer cart list over summary so cashiers see more lines; drag to tune.
CART_PRO_CASHIER_RATIO = 0.72
# Review Cart: bias heavily to the line list so 5–8 tall (~76px) rows fit on
# typical 900–1080p heights without scrolling. Summary stays a compact strip.
CART_REVIEW_RATIO = 0.86
CART_REVIEW_LIST_MIN = max(430, _CART_LIST_FLOOR)
CART_REVIEW_SUMMARY_MIN = 108  # totals strip still usable, not a second column
# Legacy soft height hint (docs / QA only) — never clamp the live splitter to this.
CART_PRO_CASHIER_LIST_MAX = 310
# Order Summary natural height under a 5-row cart (totals + discount row).
CART_PRO_CASHIER_SUMMARY = 168

TOOLTIP = 'Drag to resize columns — double-click to reset this layout'
CART_TOOLTIP = 'Drag to resize the cart list / order summary — double-click to reset'


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        _ = obj.objectName()
        return True
    except RuntimeError:
        return False


def _defer(tab, msec, fn) -> None:
    """Run ``fn`` later, but only while ``tab`` still exists.

    A bare ``QTimer.singleShot`` keeps firing after the tab is destroyed and the
    closure then touches deleted C++ objects, so the timer is parented to the tab
    and Qt cancels it during teardown.
    """
    if not _alive(tab):
        return
    timer = QTimer(tab)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: fn() if _alive(tab) else None)
    timer.start(int(msec))


class PosSplitterHandle(QSplitterHandle):
    """Themed grip: a rounded pill that lights up gold under the cursor.

    Drag is driven explicitly via ``moveSplitter`` + ``grabMouse`` — relying only
    on QSplitterHandle's internal offset broke when stylesheets / sibling paint
    effects interfered, and Classic rails with free=0 made the grip look live
    while sizes never changed.
    """

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self._dragging = False
        self._press_offset = 0
        self.setToolTip(getattr(parent, '_tooltip', TOOLTIP))
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        if orientation == Qt.Horizontal:
            self.setCursor(Qt.SplitHCursor)
        else:
            self.setCursor(Qt.SplitVCursor)

    def _claim_user_drag(self):
        """Cancel deferred programmatic restores the moment the cashier grabs us."""
        sp = self.splitter()
        tab = getattr(sp, '_tab', None) if sp is not None else None
        if tab is None:
            return
        kind = getattr(sp, '_kind', 'col')
        if kind == 'cart':
            tab._pos_cart_splitter_user_gen = getattr(tab, '_pos_cart_splitter_gen', 0)
            tab._pos_cart_splitter_dragging = True
            tab._pos_cart_splitter_applying = False
        else:
            tab._pos_splitter_user_gen = getattr(tab, '_pos_splitter_gen', 0)
            tab._pos_splitter_dragging = True
            tab._pos_splitter_applying = False

    def _clear_user_drag(self):
        sp = self.splitter()
        tab = getattr(sp, '_tab', None) if sp is not None else None
        if tab is None:
            return
        kind = getattr(sp, '_kind', 'col')
        if kind == 'cart':
            tab._pos_cart_splitter_dragging = False
        else:
            tab._pos_splitter_dragging = False

    def _splitter_pos_from_global(self, global_pos) -> int:
        """Map a global cursor point to the splitter's moveSplitter coordinate."""
        sp = self.splitter()
        local = sp.mapFromGlobal(global_pos)
        if self.orientation() == Qt.Horizontal:
            return int(local.x()) - int(self._press_offset)
        return int(local.y()) - int(self._press_offset)

    def enterEvent(self, event):
        self._hover = True
        self.raise_()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._dragging:
            self._hover = False
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._claim_user_drag()
            self.raise_()
            # Offset inside the handle so the grip doesn't jump under the cursor.
            if self.orientation() == Qt.Horizontal:
                self._press_offset = int(event.pos().x())
            else:
                self._press_offset = int(event.pos().y())
            self._dragging = True
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            try:
                self.moveSplitter(self._splitter_pos_from_global(event.globalPos()))
            except Exception:
                pass
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            try:
                if QWidget.mouseGrabber() is self:
                    self.releaseMouse()
            except Exception:
                try:
                    self.releaseMouse()
                except Exception:
                    pass
            self._clear_user_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._clear_user_drag()

    def mouseDoubleClickEvent(self, event):
        # Claim so deferred restores do not fight the reset, but clear the
        # dragging latch first — apply_*_sizes no-ops while dragging=True.
        self._dragging = False
        try:
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
        except Exception:
            try:
                self.releaseMouse()
            except Exception:
                pass
        self._claim_user_drag()
        self._clear_user_drag()
        sp = self.splitter()
        tab = getattr(sp, '_tab', None) if sp is not None else None
        kind = getattr(sp, '_kind', 'col')
        if tab is not None:
            if kind == 'cart':
                tab._pos_cart_splitter_user_gen = getattr(tab, '_pos_cart_splitter_gen', 0)
            else:
                tab._pos_splitter_user_gen = getattr(tab, '_pos_splitter_gen', 0)
        reset = getattr(sp, 'reset_to_defaults', None)
        if callable(reset):
            reset()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        from desktop.utils.theme import C
        # Full gutter fill so the hit target reads as a bar, not a 1px hairline.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        track = QColor(C.get('border', '#24304A'))
        track.setAlpha(120)
        p.setBrush(track)
        p.drawRect(self.rect())
        hot = self._hover or self._dragging or (self.isEnabled() and self.underMouse())
        colour = QColor(C.get('gold', '#F5C542') if hot else C.get('border2', '#2A4060'))
        if not hot:
            colour.setAlpha(210)
        p.setBrush(colour)
        thick = 5.0 if hot else 3.5
        if self.orientation() == Qt.Horizontal:
            length = min(float(self.height()), 112.0 if hot else 72.0)
            x = (self.width() - thick) / 2.0
            y = (self.height() - length) / 2.0
            p.drawRoundedRect(QRectF(x, y, thick, length), thick / 2.0, thick / 2.0)
        else:
            length = min(float(self.width()), 112.0 if hot else 72.0)
            x = (self.width() - length) / 2.0
            y = (self.height() - thick) / 2.0
            p.drawRoundedRect(QRectF(x, y, length, thick), thick / 2.0, thick / 2.0)
        p.end()


class PosSplitter(QSplitter):
    """Splitter that owns a POS gutter (column widths or the Current Sale stack)."""

    def __init__(self, tab, parent=None, orientation=Qt.Horizontal, kind='col'):
        super().__init__(orientation, parent)
        self._tab = tab
        self._kind = kind
        self._tooltip = TOOLTIP if kind == 'col' else CART_TOOLTIP
        self.setObjectName('posSplitter' if kind == 'col' else 'posCartSplitter')
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)
        self.setHandleWidth(HANDLE_W)
        # Explicit handle size beats the app-wide ``QSplitter::handle{width:1px}``
        # rule in theme.py — without this, cashiers see a grip they cannot grab.
        self.setStyleSheet(
            f'QSplitter{{background:transparent;border:none;}}'
            f'QSplitter::handle{{'
            f'background:rgba(36,48,74,90);'
            f'width:{HANDLE_W}px;height:{HANDLE_W}px;margin:0;padding:0;}}')

    def createHandle(self):
        return PosSplitterHandle(self.orientation(), self)

    def reset_to_defaults(self):
        tab = self._tab
        lid = normalize_layout_id(getattr(tab, '_checkout_layout', None))
        if self._kind == 'cart':
            cfg = _read_cart_cfg(tab)
            cfg.pop(lid, None)
            _queue_cart_flush(tab)
            apply_cart_sizes(tab, lid)
            return
        cfg = _read_cfg(tab)
        cfg.pop(lid, None)
        _queue_flush(tab)
        apply_sizes(tab, lid, self.count())
        _queue_relayout(tab)


# ── persistence ───────────────────────────────────────────────────────────────

def _read_cfg(tab) -> dict:
    """Layout id -> saved pane widths. Cached on the tab; DB read happens once.

    Entries that collapse Current Sale / payment below hard minimums are dropped
    and rewritten so a bad persist cannot reopen as a products-only shell.
    """
    cached = getattr(tab, '_pos_splitter_cfg', None)
    if isinstance(cached, dict):
        return cached
    data: dict = {}
    scrubbed = False
    try:
        raw = (tab.api.get_settings() or {}).get(POS_SPLITTER_KEY)
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key, sizes in parsed.items():
                    if not isinstance(sizes, (list, tuple)) or not sizes:
                        scrubbed = True
                        continue
                    if not all(isinstance(n, (int, float)) and n > 0 for n in sizes):
                        scrubbed = True
                        continue
                    lid = normalize_layout_id(key)
                    cleaned = [int(n) for n in sizes]
                    mins = _mins_for(lid, len(cleaned))
                    if not _sizes_meet_mins(cleaned, mins):
                        scrubbed = True
                        continue
                    data[lid] = cleaned
    except Exception:
        data = {}
        scrubbed = True
    tab._pos_splitter_cfg = data
    if scrubbed:
        # Persist the cleaned map so the next cold start does not re-poison.
        _queue_flush(tab)
    return data


def _flush(tab) -> None:
    cfg = getattr(tab, '_pos_splitter_cfg', None)
    if not isinstance(cfg, dict):
        return
    payload = json.dumps(cfg, separators=(',', ':'))

    def _write():
        try:
            tab.api.update_settings({POS_SPLITTER_KEY: payload})
        except Exception:
            pass

    # Off the UI thread: a drag can settle while the cashier keeps scanning.
    threading.Thread(target=_write, daemon=True, name='SavePosSplitter').start()


def _queue_flush(tab) -> None:
    timer = getattr(tab, '_pos_splitter_save_timer', None)
    if timer is None:
        timer = QTimer(tab)
        timer.setSingleShot(True)
        timer.setInterval(700)
        timer.timeout.connect(lambda: _flush(tab))
        tab._pos_splitter_save_timer = timer
    timer.start()


def _remember(tab) -> None:
    if getattr(tab, '_pos_splitter_applying', False):
        return  # programmatic restore — never treat as a cashier drag
    sp = getattr(tab, '_pos_splitter', None)
    if not _alive(sp):
        return
    lid = normalize_layout_id(getattr(tab, '_checkout_layout', None))
    sizes = list(sp.sizes())
    if len(sizes) != sp.count() or any(s <= 0 for s in sizes):
        return  # mid-transition or a pane is hidden (review mode) — don't persist
    mins = _mins_for(lid, len(sizes))
    if not _sizes_meet_mins(sizes, mins):
        return  # refuse to persist a products-only / collapsed layout
    # Ensure every pane is actually visible before we trust the widths.
    for i in range(sp.count()):
        w = sp.widget(i)
        if not _alive(w) or not w.isVisibleTo(sp):
            return
    cfg = _read_cfg(tab)
    if cfg.get(lid) == sizes:
        return
    cfg[lid] = sizes
    _queue_flush(tab)


# ── product grid reflow ───────────────────────────────────────────────────────

def _relayout(tab) -> None:
    try:
        cols = tab._product_columns()
    except Exception:
        return
    if getattr(tab, '_last_cols', None) == cols:
        return
    tab._last_cols = cols
    try:
        tab._filter(defer=False)
    except Exception:
        pass


def _queue_relayout(tab) -> None:
    timer = getattr(tab, '_pos_splitter_reflow_timer', None)
    if timer is None:
        timer = QTimer(tab)
        timer.setSingleShot(True)
        timer.setInterval(90)
        timer.timeout.connect(lambda: _relayout(tab))
        tab._pos_splitter_reflow_timer = timer
    timer.start()


def _on_moved(tab) -> None:
    # Programmatic setSizes also emits splitterMoved — ignore those so a deferred
    # restore after layout settle is not permanently cancelled.
    if getattr(tab, '_pos_splitter_applying', False):
        return
    # Mark this apply generation as user-owned so deferred restores stand down.
    tab._pos_splitter_user_gen = getattr(tab, '_pos_splitter_gen', 0)
    _remember(tab)
    _queue_relayout(tab)
    try:
        from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO, normalize_layout_id
        if normalize_layout_id(getattr(tab, '_checkout_layout', '')) == LAYOUT_CHECKOUT_PRO:
            from desktop.pos.checkout_pro_chrome import sync_pro_sale_panel
            sync_pro_sale_panel(tab)
    except Exception:
        pass
    # Category chips pack to the product-column width — nudge them on drag.
    try:
        chips = getattr(tab, '_cat_chips', None)
        if _alive(chips) and hasattr(chips, 'repack_for_width'):
            chips.repack_for_width(force=True)
    except Exception:
        pass


# ── Current Sale internal stack (cart list | order summary) ────────────────────

def _read_cart_cfg(tab) -> dict:
    """Layout id -> saved [cart_h, summary_h]. Cached on the tab like column cfg."""
    cached = getattr(tab, '_pos_cart_splitter_cfg', None)
    if isinstance(cached, dict):
        return cached
    data: dict = {}
    scrubbed = False
    try:
        raw = (tab.api.get_settings() or {}).get(CART_SPLITTER_KEY)
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key, sizes in parsed.items():
                    if not isinstance(sizes, (list, tuple)) or len(sizes) != 2:
                        scrubbed = True
                        continue
                    if not all(isinstance(n, (int, float)) and n > 0 for n in sizes):
                        scrubbed = True
                        continue
                    lid = normalize_layout_id(key)
                    cleaned = [int(n) for n in sizes]
                    mins = CART_MIN_HEIGHTS.get(lid, (120, 120))
                    # Drop poisoned extremes: collapsed cart list (header still
                    # shows count), or sizes pinned so the grip cannot travel.
                    if cleaned[0] < CART_LIST_HARD_MIN:
                        scrubbed = True
                        continue
                    # 3.0.37 hard-capped Pro carts at ~310px — drop those locks so
                    # ratio defaults restore an adjustable split on upgrade.
                    if (
                        lid == LAYOUT_CHECKOUT_PRO
                        and cleaned[0] <= CART_PRO_CASHIER_LIST_MAX
                        and cleaned[0] >= CART_PRO_CASHIER_LIST_MAX - 8
                    ):
                        scrubbed = True
                        continue
                    if not _sizes_meet_mins(cleaned, mins):
                        scrubbed = True
                        continue
                    data[lid] = cleaned
    except Exception:
        data = {}
        scrubbed = True
    tab._pos_cart_splitter_cfg = data
    if scrubbed:
        _queue_cart_flush(tab)
    return data


def _flush_cart(tab) -> None:
    cfg = getattr(tab, '_pos_cart_splitter_cfg', None)
    if not isinstance(cfg, dict):
        return
    payload = json.dumps(cfg, separators=(',', ':'))

    def _write():
        try:
            tab.api.update_settings({CART_SPLITTER_KEY: payload})
        except Exception:
            pass

    threading.Thread(target=_write, daemon=True, name='SavePosCartSplitter').start()


def _queue_cart_flush(tab) -> None:
    timer = getattr(tab, '_pos_cart_splitter_save_timer', None)
    if timer is None:
        timer = QTimer(tab)
        timer.setSingleShot(True)
        timer.setInterval(700)
        timer.timeout.connect(lambda: _flush_cart(tab))
        tab._pos_cart_splitter_save_timer = timer
    timer.start()


def _review_mode(tab) -> bool:
    return bool(getattr(tab, '_cart_maximized', False))


def _cart_mins_for(tab, lid: str) -> tuple:
    """Per-layout floors; Review raises the list floor and shrinks summary."""
    lid = normalize_layout_id(lid)
    if _review_mode(tab):
        return (CART_REVIEW_LIST_MIN, CART_REVIEW_SUMMARY_MIN)
    return CART_MIN_HEIGHTS.get(lid, (150, 190))


def _remember_cart(tab) -> None:
    if getattr(tab, '_pos_cart_splitter_applying', False):
        return
    # Never persist Review proportions — Restore must reopen the normal split.
    if _review_mode(tab):
        return
    sp = getattr(tab, '_cart_splitter', None)
    if not _alive(sp):
        return
    lid = normalize_layout_id(getattr(tab, '_checkout_layout', None))
    sizes = list(sp.sizes())
    if len(sizes) != 2 or any(s <= 0 for s in sizes):
        return
    mins = CART_MIN_HEIGHTS.get(lid, (150, 190))
    if not _sizes_meet_mins(sizes, mins):
        return
    cfg = _read_cart_cfg(tab)
    if cfg.get(lid) == sizes:
        return
    cfg[lid] = sizes
    _queue_cart_flush(tab)


def _on_cart_moved(tab) -> None:
    if getattr(tab, '_pos_cart_splitter_applying', False):
        return
    tab._pos_cart_splitter_user_gen = getattr(tab, '_pos_cart_splitter_gen', 0)
    _remember_cart(tab)


def ensure_cart_splitter(tab):
    """Return the tab's Current-Sale stack splitter, creating it once."""
    sp = getattr(tab, '_cart_splitter', None)
    if _alive(sp):
        return sp
    # Always parent under the tab — never construct a free top-level QSplitter.
    # Birth under DontShowOnScreen avoids a free HWND flash; install_cart /
    # reveal_cart_stack must clear that flag once the splitter is laid out.
    sp = PosSplitter(tab, parent=tab, orientation=Qt.Vertical, kind='cart')
    sp.hide()
    try:
        sp.setAttribute(Qt.WA_DontShowOnScreen, True)
    except Exception:
        pass
    sp.splitterMoved.connect(lambda *_a: _on_cart_moved(tab))
    tab._cart_splitter = sp
    return sp


def reveal_cart_stack(tab) -> None:
    """Clear flash-park flags and show the cart list + summary stack.

    3.0.34 flash audit left ``posCartSplitter`` (and sometimes its panes /
    CartList) with ``WA_DontShowOnScreen`` after birth/stash. Layout still
    reserved the middle column, so cashiers saw "Current Sale (N items)" /
    Review Cart with a hollow dark band and no rows.
    """
    from desktop.utils.quiet_ui import safe_show

    sp = getattr(tab, '_cart_splitter', None)
    if _alive(sp):
        try:
            sp.setAttribute(Qt.WA_DontShowOnScreen, False)
        except Exception:
            pass
        safe_show(sp)
        for i in range(sp.count()):
            pane = sp.widget(i)
            if not _alive(pane):
                continue
            try:
                pane.setAttribute(Qt.WA_DontShowOnScreen, False)
            except Exception:
                pass
            safe_show(pane)
            try:
                mh = int(pane.minimumHeight() or 0)
                if i == 0 and mh < CART_LIST_HARD_MIN:
                    pane.setMinimumHeight(CART_LIST_HARD_MIN)
            except Exception:
                pass

    for attr in ('_sale_cart_scroll', '_sale_summary_wrap', '_cart_list', '_summary'):
        w = getattr(tab, attr, None)
        if not _alive(w):
            continue
        try:
            w.setAttribute(Qt.WA_DontShowOnScreen, False)
        except Exception:
            pass
        safe_show(w)

    clist = getattr(tab, '_cart_list', None)
    if _alive(clist):
        scroll = getattr(clist, '_scroll', None)
        body = getattr(clist, '_body', None)
        for w in (scroll, body):
            if not _alive(w):
                continue
            try:
                w.setAttribute(Qt.WA_DontShowOnScreen, False)
            except Exception:
                pass
            safe_show(w)
        for row in list(getattr(clist, '_rows', None) or []):
            if not _alive(row):
                continue
            try:
                row.setAttribute(Qt.WA_DontShowOnScreen, False)
            except Exception:
                pass
            try:
                if not row.isVisible():
                    safe_show(row)
            except Exception:
                pass

    # If the cart has lines but the list pane was collapsed to a sliver, restore.
    try:
        n_items = len(getattr(tab, 'cart', []) or [])
    except Exception:
        n_items = 0
    if n_items > 0 and _alive(sp) and sp.count() == 2:
        try:
            sizes = list(sp.sizes())
            hard = CART_LIST_HARD_MIN
            if _review_mode(tab) and sum(sizes) >= (CART_REVIEW_LIST_MIN + CART_REVIEW_SUMMARY_MIN):
                hard = CART_REVIEW_LIST_MIN
            if len(sizes) == 2 and sizes[0] < hard:
                lid = normalize_layout_id(getattr(tab, '_checkout_layout', None))
                if not _review_mode(tab):
                    cfg = _read_cart_cfg(tab)
                    cfg.pop(lid, None)
                    _queue_cart_flush(tab)
                apply_cart_sizes(tab, lid)
        except Exception:
            pass


def default_cart_sizes(lid: str, total: int, review: bool = False) -> list:
    lid = normalize_layout_id(lid)
    if review:
        mins = (CART_REVIEW_LIST_MIN, CART_REVIEW_SUMMARY_MIN)
        ratio = CART_REVIEW_RATIO
    elif lid == LAYOUT_CHECKOUT_PRO:
        mins = CART_MIN_HEIGHTS.get(lid, (268, 140))
        ratio = CART_PRO_CASHIER_RATIO
    else:
        mins = CART_MIN_HEIGHTS.get(lid, (150, 190))
        ratio = CART_DEFAULT_RATIO
    total = max(sum(mins), int(total))
    # All layouts: ratio-based cart vs summary — fully adjustable, no hard max.
    cart = max(mins[0], int(total * ratio))
    summary = max(mins[1], total - cart)
    # Prefer cart when floors fight the total (short Review windows).
    if cart + summary > total:
        summary = max(mins[1], total - cart)
        cart = max(mins[0], total - summary)
    cart = max(mins[0], total - summary)
    return _clamp_to_mins([cart, summary], mins, total)


def apply_cart_sizes(tab, lid: str) -> None:
    """Restore saved cart/summary heights for ``lid`` (scaled to current height)."""
    if getattr(tab, '_pos_cart_splitter_dragging', False):
        return
    sp = getattr(tab, '_cart_splitter', None)
    if not _alive(sp) or sp.count() != 2:
        return
    lid = normalize_layout_id(lid)
    review = _review_mode(tab)
    # Prefer live widget floors (install_cart may have scaled them down on short rails).
    mins = []
    shipped = _cart_mins_for(tab, lid)
    for i in range(2):
        w = sp.widget(i)
        live = int(w.minimumHeight()) if _alive(w) else 0
        floor = live if live > 0 else shipped[i]
        if i == 0:
            floor = max(floor, CART_LIST_HARD_MIN)
            if review:
                floor = max(floor, min(CART_REVIEW_LIST_MIN, shipped[0]))
        elif review:
            # Cap summary floor so it cannot steal Review list pixels.
            floor = min(floor, CART_REVIEW_SUMMARY_MIN) if floor > 0 else CART_REVIEW_SUMMARY_MIN
            floor = max(CART_REVIEW_SUMMARY_MIN // 2, min(floor, CART_REVIEW_SUMMARY_MIN))
        mins.append(floor)
    mins = tuple(mins)
    total = sp.height()
    if total <= HANDLE_W:
        total = max(int(getattr(tab, 'height', lambda: 0)()) - 260, 420)
    total = max(sum(mins) + 40, total - HANDLE_W)

    # Review always uses the tall-list default — ignore persisted day-to-day sizes.
    saved = None if review else _read_cart_cfg(tab).get(lid)
    sizes = None
    if saved and len(saved) == 2 and sum(saved) > 0 and _sizes_meet_mins(saved, mins):
        scale = total / float(sum(saved))
        sizes = [max(1, int(round(s * scale))) for s in saved]
        sizes = _clamp_to_mins(sizes, mins, total)
    if sizes is None:
        if saved is not None and not _sizes_meet_mins(saved, mins):
            cfg = _read_cart_cfg(tab)
            cfg.pop(lid, None)
            _queue_cart_flush(tab)
        sizes = default_cart_sizes(lid, total, review=review)
        # Re-clamp with live mins (default_cart_sizes uses shipped floors).
        sizes = _clamp_to_mins(sizes, mins, total)

    # 3.0.38: never clamp cart height to CART_PRO_CASHIER_LIST_MAX — the
    # cart↔summary splitter must stay fully adjustable on every layout.

    tab._pos_cart_splitter_applying = True
    try:
        # blockSignals so splitterMoved does not look like a cashier drag.
        sp.blockSignals(True)
        try:
            sp.setSizes(sizes)
        finally:
            sp.blockSignals(False)
        # Refuse a vanishing cart list when lines exist (poisoned save / race).
        try:
            n_items = len(getattr(tab, 'cart', []) or [])
        except Exception:
            n_items = 0
        got = list(sp.sizes())
        hard = CART_REVIEW_LIST_MIN if review and total >= (CART_REVIEW_LIST_MIN + CART_REVIEW_SUMMARY_MIN + 40) else CART_LIST_HARD_MIN
        if n_items > 0 and len(got) == 2 and got[0] < hard:
            sizes = default_cart_sizes(lid, total, review=review)
            sizes = _clamp_to_mins(sizes, mins, total)
            sp.blockSignals(True)
            try:
                sp.setSizes(sizes)
            finally:
                sp.blockSignals(False)
        for i in range(1, sp.count()):
            h = sp.handle(i)
            if h is not None:
                h.raise_()
                h.setEnabled(True)
    except Exception:
        pass
    finally:
        tab._pos_cart_splitter_applying = False


def install_cart(tab, lid: str) -> None:
    """Apply per-layout minimums, then restore heights now and once laid out."""
    sp = getattr(tab, '_cart_splitter', None)
    if not _alive(sp):
        return
    lid = normalize_layout_id(lid)
    review = _review_mode(tab)
    mins = list(_cart_mins_for(tab, lid))
    # Short right-rails (Explorer/Classic) can equal sum(mins) exactly — leave
    # CART_FREE_TRAVEL so the gutter is never a dead ornament.
    # Review already demands a tall list; keep free travel modest so floors hold.
    free_travel = max(48, CART_FREE_TRAVEL // 2) if review else CART_FREE_TRAVEL
    try:
        avail = max(int(sp.height()), int(getattr(tab, 'height', lambda: 0)()) - 280, 280)
    except Exception:
        avail = 280
    need = sum(mins) + HANDLE_W + free_travel
    if avail < need:
        budget = max(140, avail - HANDLE_W - free_travel)
        scale = budget / float(sum(mins))
        mins = [
            max(
                (CART_REVIEW_LIST_MIN if review else CART_LIST_HARD_MIN) if i == 0
                else (CART_REVIEW_SUMMARY_MIN if review else 64),
                int(m * scale),
            )
            for i, m in enumerate(mins)
        ]
        # On a short rail in Review, still prefer list pixels over summary.
        if review and sum(mins) > budget:
            mins = [
                max(CART_LIST_HARD_MIN, budget - CART_REVIEW_SUMMARY_MIN),
                min(CART_REVIEW_SUMMARY_MIN, max(72, budget // 5)),
            ]
    mins = tuple(mins)
    # Flash-park clear BEFORE size restore — DontShowOnScreen widgets lay out
    # but never paint (hollow Current Sale / Review Cart).
    reveal_cart_stack(tab)
    for i in range(sp.count()):
        pane = sp.widget(i)
        if not _alive(pane):
            continue
        try:
            floor = mins[i] if i < len(mins) else 80
            if i == 0:
                floor = max(floor, CART_LIST_HARD_MIN)
            pane.setMinimumHeight(floor)
            if review and i == 1:
                # Keep Order Summary a compact strip — do not let sizeHint inflate it.
                pane.setMaximumHeight(max(floor + 40, int(avail * (1.0 - CART_REVIEW_RATIO)) + 24))
            else:
                # Always adjustable — no hard max on cart or summary panes.
                pane.setMaximumHeight(16777215)
            # Ignored vertical policy: sizeHint must not fight QSplitter drag.
            pol = pane.sizePolicy()
            pol.setHorizontalPolicy(QSizePolicy.Preferred)
            pol.setVerticalPolicy(QSizePolicy.Ignored)
            # Cart list takes leftover height; summary stays compact but draggable.
            if i == 0:
                stretch = 4
            else:
                stretch = 0
            pol.setVerticalStretch(stretch)
            pane.setSizePolicy(pol)
            sp.setStretchFactor(i, stretch)
            from desktop.utils.quiet_ui import safe_show
            if not pane.isVisible():
                safe_show(pane)
            # Drop-shadow on the summary card paints into the handle and makes
            # the gutter feel dead — kill it on every layout, not just Pro.
            if i == 1:
                try:
                    card = getattr(tab, '_summary', None)
                    if _alive(card) and card.graphicsEffect() is not None:
                        card.setGraphicsEffect(None)
                except Exception:
                    pass
                try:
                    if pane.graphicsEffect() is not None:
                        pane.setGraphicsEffect(None)
                except Exception:
                    pass
        except Exception:
            pass
    try:
        sp.setChildrenCollapsible(False)
        sp.setHandleWidth(HANDLE_W)
        sp.setOpaqueResize(True)
        sale = getattr(tab, '_sale_panel', None)
        sl = sale.layout() if _alive(sale) else None
        # Cart↔summary stack fills Current Sale; drag the gutter to trade space
        # between line items and Order Summary / (on Classic) the pay stack.
        sp.setMaximumHeight(16777215)
        if review:
            sp.setMinimumHeight(CART_REVIEW_LIST_MIN + CART_REVIEW_SUMMARY_MIN + HANDLE_W)
        elif sp.count() < 2:
            # Totals moved to the checkout foot — cart list uses the full sale pane.
            sp.setMinimumHeight(CART_LIST_HARD_MIN)
        else:
            sp.setMinimumHeight(max(sum(mins) + HANDLE_W, CART_LIST_HARD_MIN + 80))
        if sl is not None:
            # Drop competing tail stretch so the cart stack owns Current Sale.
            try:
                for i in range(sl.count() - 1, -1, -1):
                    item = sl.itemAt(i)
                    if item is not None and item.spacerItem() is not None:
                        sl.takeAt(i)
                tab._sale_tail_stretch_ok = False
            except Exception:
                pass
            try:
                cart_scroll = getattr(tab, '_sale_cart_scroll', None)
                if _alive(cart_scroll):
                    cart_scroll.setMaximumHeight(16777215)
                    cart_scroll.setMinimumHeight(0)
            except Exception:
                pass
            for i in range(sl.count()):
                item = sl.itemAt(i)
                if item is not None and item.widget() is sp:
                    sl.setStretch(i, 1)
                    break
            try:
                cart_scroll = getattr(tab, '_sale_cart_scroll', None)
                if _alive(cart_scroll):
                    cart_scroll.setMaximumHeight(16777215)
                    cart_scroll.setMinimumHeight(72)
                clist = getattr(tab, '_cart_list', None)
                if _alive(clist):
                    clist.setMaximumHeight(16777215)
                    if hasattr(clist, '_scroll') and clist._scroll is not None:
                        clist._scroll.setMaximumHeight(16777215)
                        clist._scroll.setMinimumHeight(80)
            except Exception:
                pass
    except Exception:
        pass
    for i in range(1, sp.count()):
        h = sp.handle(i)
        if h is not None:
            h.setEnabled(True)
            h.raise_()
    sp.setToolTip('')

    gen = int(getattr(tab, '_pos_cart_splitter_gen', 0)) + 1
    tab._pos_cart_splitter_gen = gen
    if int(getattr(tab, '_pos_cart_splitter_user_gen', -1)) == gen:
        tab._pos_cart_splitter_user_gen = -1

    def _restore():
        if not _alive(tab) or not _alive(sp):
            return
        if int(getattr(tab, '_pos_cart_splitter_gen', 0)) != gen:
            return
        if int(getattr(tab, '_pos_cart_splitter_user_gen', -1)) == gen:
            return
        if getattr(tab, '_pos_cart_splitter_dragging', False):
            return
        reveal_cart_stack(tab)
        apply_cart_sizes(tab, lid)
        # Final free-travel check after settle — if still jammed, force defaults.
        try:
            got = list(sp.sizes())
            live_mins = [int(sp.widget(i).minimumHeight()) for i in range(2)]
            hard = (
                CART_REVIEW_LIST_MIN
                if _review_mode(tab) and sum(got) >= (CART_REVIEW_LIST_MIN + CART_REVIEW_SUMMARY_MIN)
                else CART_LIST_HARD_MIN
            )
            if got and got[0] < hard:
                cfg = _read_cart_cfg(tab)
                if not _review_mode(tab):
                    cfg.pop(lid, None)
                    _queue_cart_flush(tab)
                apply_cart_sizes(tab, lid)
                reveal_cart_stack(tab)
                return
            free = sum(got) - sum(live_mins)
            if free < max(40, free_travel // 3) and not _review_mode(tab):
                cfg = _read_cart_cfg(tab)
                cfg.pop(lid, None)
                _queue_cart_flush(tab)
                # Soften floors one more notch so the grip can move — never
                # below the hard cart-list floor.
                for i in range(2):
                    w = sp.widget(i)
                    if _alive(w):
                        soft = max(
                            CART_LIST_HARD_MIN if i == 0 else 56,
                            live_mins[i] // 2,
                        )
                        w.setMinimumHeight(soft)
                apply_cart_sizes(tab, lid)
                reveal_cart_stack(tab)
        except Exception:
            pass

    _restore()
    _defer(tab, 0, _restore)
    _defer(tab, 120, _restore)
    _defer(tab, 280, _restore)


# ── build / restore ───────────────────────────────────────────────────────────

def ensure_splitter(tab):
    """Return the tab's splitter, emptied and ready to receive panes."""
    from desktop.pos.layouts.shells import _park_new, _stash

    sp = getattr(tab, '_pos_splitter', None)
    if _alive(sp):
        while sp.count():
            w = sp.widget(0)
            if w is None:
                break
            try:
                # Stash — never setParent(None) (creates decorated OS chrome).
                _stash(tab, w)
            except Exception:
                try:
                    from desktop.utils.quiet_ui import safe_detach
                    safe_detach(w)
                except Exception:
                    break
        return sp

    # Build under stash first — PosSplitter(tab) alone is a free top-level HWND.
    host = getattr(tab, '_layout_stash', None)
    if not _alive(host):
        host = QWidget(tab)
        host.hide()
        host.setAttribute(Qt.WA_DontShowOnScreen, True)
        tab._layout_stash = host
    sp = PosSplitter(tab, parent=host)
    sp.hide()
    try:
        sp.setAttribute(Qt.WA_DontShowOnScreen, True)
    except Exception:
        pass
    _park_new(tab, sp)
    sp.splitterMoved.connect(lambda *_a: _on_moved(tab))
    tab._pos_splitter = sp
    return sp


def default_sizes(lid: str, total: int, count: int) -> list:
    lid = normalize_layout_id(lid)
    mins = _mins_for(lid, count, total)
    total = max(sum(mins), int(total))
    if count >= 3:
        if total <= NARROW_SHELL:
            # Square tablets: bias to catalog + pay; Current Sale scrolls internally.
            side = max(mins[0], int(total * 0.30))
            rail = max(mins[2], int(total * 0.34))
            mid = max(mins[1], total - side - rail)
        else:
            # Catalog needs ~560px for two 248px Pro cards; 25/50/25 left one column
            # at 1366–1920 and failed the Checkout Pro layout cert.
            side = max(mins[0], int(total * 0.41))
            rail = max(mins[2], int(total * 0.22))
            mid = max(mins[1], total - side - rail)
        return _clamp_to_mins([side, mid, rail], mins, total)
    pin = _PINNED_RAIL.get(lid, 560)
    if total <= NARROW_SHELL:
        pin = max(mins[1], min(pin, int(total * 0.52)))
    # Never let the pinned rail starve the catalog on small screens.
    pin = max(mins[1], min(pin, total - mins[0]))
    return _clamp_to_mins([max(mins[0], total - pin), pin], mins, total)


def apply_sizes(tab, lid: str, count: int) -> None:
    """Restore saved widths for ``lid`` (scaled to the current shell width).

    Saved sizes that fall below hard minimums are discarded, defaults applied,
    and the cleaned map rewritten to settings.
    """
    if getattr(tab, '_pos_splitter_dragging', False):
        return
    sp = getattr(tab, '_pos_splitter', None)
    if not _alive(sp) or count <= 1:
        return
    lid = normalize_layout_id(lid)
    raw_total = sp.width()
    if raw_total <= count * HANDLE_W:
        raw_total = max(int(getattr(tab, 'width', lambda: 0)()) - 24, 720)
    usable = max(count * 80, raw_total - HANDLE_W * (count - 1))
    mins = _mins_for(lid, count, usable)
    total = max(sum(mins), usable)

    cfg = _read_cfg(tab)
    saved = cfg.get(lid)
    if (
        saved and len(saved) == count and lid == LAYOUT_CHECKOUT_PRO and count >= 3
        and sum(saved) > 0 and (saved[0] / float(sum(saved))) < 0.35
    ):
        # Pre-3.0.50 defaults (25% catalog) clipped to one product column.
        saved = None
        cfg.pop(lid, None)
        _queue_flush(tab)
    if (
        saved and len(saved) == count and lid == LAYOUT_CHECKOUT_PRO and count >= 3
        and usable <= NARROW_SHELL and sum(saved) > 0
        and (saved[2] / float(sum(saved))) < 0.28
    ):
        # Poisoned narrow saves starved the payment rail on square tablets.
        saved = None
        cfg.pop(lid, None)
        _queue_flush(tab)
    sizes = None
    if saved and len(saved) == count and sum(saved) > 0 and _sizes_meet_mins(saved, mins):
        # Saved on a different window width — keep the ratio, not the pixels.
        scale = total / float(sum(saved))
        sizes = [max(1, int(round(s * scale))) for s in saved]
        sizes = _clamp_to_mins(sizes, mins, total)
    else:
        if saved is not None:
            cfg.pop(lid, None)
            _queue_flush(tab)
        sizes = default_sizes(lid, total, count)
        sizes = _clamp_to_mins(sizes, mins, total)

    # Make sure every pane is visible before sizing — a hidden child steals no
    # space and leaves the catalog looking like a single full-width column.
    for i in range(sp.count()):
        w = sp.widget(i)
        if _alive(w) and not w.isVisible():
            try:
                from desktop.utils.quiet_ui import safe_show
                safe_show(w)
            except Exception:
                pass

    tab._pos_splitter_applying = True
    try:
        sp.blockSignals(True)
        try:
            sp.setSizes(sizes)
        finally:
            sp.blockSignals(False)
        # If Qt still collapsed a pane (e.g. transient tiny shell), force defaults.
        got = list(sp.sizes())
        if not _sizes_meet_mins(got, mins) or any(s <= 0 for s in got):
            sizes = _clamp_to_mins(default_sizes(lid, total, count), mins, total)
            sp.blockSignals(True)
            try:
                sp.setSizes(sizes)
            finally:
                sp.blockSignals(False)
            cfg.pop(lid, None)
            cfg[lid] = list(sp.sizes()) if _sizes_meet_mins(list(sp.sizes()), mins) else sizes
            _queue_flush(tab)
        for i in range(1, sp.count()):
            h = sp.handle(i)
            if h is not None:
                h.setEnabled(True)
                h.raise_()
    except Exception:
        pass
    finally:
        tab._pos_splitter_applying = False


def install(tab, lid: str, panes) -> None:
    """Apply per-layout minimums, then restore widths now and once laid out."""
    sp = getattr(tab, '_pos_splitter', None)
    if not _alive(sp):
        return
    lid = normalize_layout_id(lid)
    count = sp.count()
    raw_total = max(
        int(sp.width() or 0),
        int(getattr(tab, 'width', lambda: 0)()) - 24,
        720,
    )
    avail = max(1, raw_total - HANDLE_W * max(0, (len(panes) or count) - 1))
    mins = _mins_for(lid, len(panes) or count, avail if avail > 80 else None)
    for i, pane in enumerate(panes):
        if not _alive(pane):
            continue
        try:
            # Fixed widths would defeat the drag entirely.
            pane.setMinimumWidth(mins[i] if i < len(mins) else 240)
            pane.setMaximumWidth(16777215)
            pol = pane.sizePolicy()
            # Ignored horizontal policy so sizeHint cannot fight column drag.
            pol.setHorizontalPolicy(QSizePolicy.Ignored)
            pol.setVerticalPolicy(QSizePolicy.Preferred)
            pol.setHorizontalStretch(1)
            pane.setSizePolicy(pol)
            from desktop.utils.quiet_ui import safe_show
            if not pane.isVisible():
                safe_show(pane)
            sp.setStretchFactor(i, 1)
        except Exception:
            pass
        if lid == LAYOUT_CHECKOUT_PRO and i == 1:
            try:
                from desktop.pos.checkout_pro_chrome import sync_pro_sale_panel
                sync_pro_sale_panel(tab)
            except Exception:
                pass
    try:
        sp.setChildrenCollapsible(False)
        sp.setHandleWidth(HANDLE_W)
        sp.setOpaqueResize(True)
    except Exception:
        pass
    for i in range(1, sp.count()):
        h = sp.handle(i)
        if h is not None:
            h.setEnabled(True)
            h.raise_()
    sp.setToolTip('')

    gen = int(getattr(tab, '_pos_splitter_gen', 0)) + 1
    tab._pos_splitter_gen = gen
    # Clear stale "user dragged" from a prior apply so deferred restores run.
    if int(getattr(tab, '_pos_splitter_user_gen', -1)) == gen:
        tab._pos_splitter_user_gen = -1
    count = sp.count()

    def _restore():
        if not _alive(tab) or not _alive(sp):
            return
        # A newer layout apply, or the cashier already dragged — leave it alone.
        if int(getattr(tab, '_pos_splitter_gen', 0)) != gen:
            return
        if int(getattr(tab, '_pos_splitter_user_gen', -1)) == gen:
            return
        if getattr(tab, '_pos_splitter_dragging', False):
            return
        apply_sizes(tab, lid, count)
        # After settle, refuse to leave Sale/pay under their floors.
        try:
            got = list(sp.sizes())
            if count >= 2 and not _sizes_meet_mins(got, _mins_for(lid, count)):
                cfg = _read_cfg(tab)
                cfg.pop(lid, None)
                _queue_flush(tab)
                apply_sizes(tab, lid, count)
            if lid == LAYOUT_CHECKOUT_PRO:
                from desktop.pos.checkout_pro_chrome import sync_pro_square_layout
                sync_pro_square_layout(tab)
        except Exception:
            pass

    _restore()
    # Shell width is still stale on the first pass; settle after layout runs.
    _defer(tab, 0, _restore)
    _defer(tab, 120, _restore)
    _defer(tab, 120, lambda: _queue_relayout(tab))


def restyle(tab) -> None:
    """Repaint handles after a light/dark switch."""
    for attr in ('_pos_splitter', '_cart_splitter'):
        sp = getattr(tab, attr, None)
        if not _alive(sp):
            continue
        for i in range(sp.count()):
            h = sp.handle(i)
            if h is not None:
                h.update()
        sp.update()
