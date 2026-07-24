"""Checkout Pro visual chrome — adapts shared POS panels to the approved design.

Does not duplicate business logic. Widgets stay owned by SalesTab / panel_factory;
this module only rearranges visibility, density, and Pro-only accessory chrome.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QSizePolicy, QVBoxLayout, QWidget, QMessageBox, QInputDialog,
)

from desktop.utils.theme import C, RADIUS, qss_alpha


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        _ = obj.objectName()
        return True
    except RuntimeError:
        return False


def style_amount_paid(tab) -> None:
    """High-contrast bordered Amount Paid input + label — all checkout layouts."""
    from desktop.utils.theme import C as _C, qss_alpha

    cap = getattr(tab, '_amount_paid_cap', None)
    if _alive(cap):
        cap.setText('Amount Paid')
        cap.setObjectName('posAmountCap')
        cap.setMinimumHeight(18)
        cap.setStyleSheet(
            f"QLabel#posAmountCap{{color:{_C['text']};font-size:13px;font-weight:800;"
            f"letter-spacing:0.3px;background:transparent;padding:0 0 2px 0;margin:0;}}")
        cap.show()

    paid = getattr(tab, '_paid', None)
    if not _alive(paid):
        return
    paid.setObjectName('posAmountPaid')
    paid.setToolTip('Amount Paid')
    paid.setMinimumHeight(48)
    try:
        paid.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    except Exception:
        pass
    try:
        cur = 'KES '
        settings = getattr(tab, 'settings', None) or {}
        if isinstance(settings, dict) and settings.get('currency'):
            cur = f"{settings.get('currency')} "
        elif hasattr(tab, '_currency') and tab._currency:
            cur = f"{tab._currency} "
        paid.setPrefix(cur)
        paid.setSuffix('')
        paid.setGroupSeparatorShown(True)
    except Exception:
        try:
            paid.setPrefix('KES ')
        except Exception:
            pass
    # Distinct editable field — strong border so it never reads as selected static text
    paid.setStyleSheet(
        f"QDoubleSpinBox#posAmountPaid{{"
        f"background:{_C['card']};color:{_C['text']};"
        f"border:2.5px solid {_C['text2']};border-radius:10px;"
        f"padding:8px 14px;font-size:18px;font-weight:800;"
        f"selection-background-color:{qss_alpha(_C['gold'], 0.22)};"
        f"selection-color:{_C['text']};}}"
        f"QDoubleSpinBox#posAmountPaid:focus{{"
        f"border:2.5px solid {_C['gold']};background:{_C['input']};}}"
        f"QDoubleSpinBox#posAmountPaid:hover{{"
        f"border-color:{_C['gold']};}}"
        f"QDoubleSpinBox#posAmountPaid:disabled{{"
        f"color:{_C['muted']};border-color:{_C['border']};"
        f"background:{qss_alpha(_C['panel'], 0.85)};}}"
        f"QDoubleSpinBox#posAmountPaid::up-button,"
        f"QDoubleSpinBox#posAmountPaid::down-button{{width:0;border:none;}}")
    paid.show()
    try:
        # Avoid blue “selected static text” look after autofill
        le = paid.lineEdit()
        if le is not None:
            le.deselect()
            le.setCursorPosition(len(le.text() or ''))
        paid.clearFocus()
    except Exception:
        pass

    block = getattr(tab, '_amount_paid_block', None) or getattr(tab, '_amount_block', None)
    if _alive(block):
        block.show()


def ensure_checkout_body_order(tab) -> None:
    """customer → payment → amount/change → extras → note (Explorer/Classic)."""
    body = getattr(tab, '_actions_body', None)
    if not _alive(body):
        return
    bl = body.layout()
    if bl is None:
        return
    names = (
        '_cust_card', '_credit_frame', '_pay_hdr', '_pay_seg',
        '_amount_paid_block', '_chg_frame',
        '_round_frame', '_split_frame', '_mpesa_frame', '_note',
    )
    always_show = {
        '_cust_card', '_pay_hdr', '_pay_seg', '_amount_paid_block', '_chg_frame', '_note',
    }
    ordered_named = []
    seen = set()
    for name in names:
        w = getattr(tab, name, None)
        if not _alive(w):
            if name == '_amount_paid_block':
                w = getattr(tab, '_amount_block', None)
            if not _alive(w):
                continue
        wid = id(w)
        if wid in seen:
            continue
        seen.add(wid)
        ordered_named.append((name, w))
    for name, w in ordered_named:
        try:
            bl.addWidget(w)
            if name in always_show:
                w.show()
        except Exception:
            pass
    for name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_var_frame'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.hide()


def style_quiet_secondary_actions(tab) -> None:
    """Visually quieter Hold/Void/Preview row so Complete Sale dominates."""
    from desktop.utils.theme import C as _C, qss_alpha

    quiet = (
        f"QPushButton{{background:transparent;color:{_C['text2']};"
        f"border:1px solid {_C['border']};border-radius:8px;"
        f"font-size:11px;font-weight:600;padding:3px 8px;}}"
        f"QPushButton:hover{{background:{_C['hover']};color:{_C['text']};"
        f"border-color:{_C['border2']};}}"
        f"QPushButton:disabled{{color:{_C['muted']};border-color:{_C['border']};}}"
    )
    danger_q = (
        f"QPushButton{{background:transparent;color:{_C['err']};"
        f"border:1.5px solid {qss_alpha(_C['err'], 0.55)};border-radius:8px;"
        f"font-size:11px;font-weight:700;padding:3px 8px;}}"
        f"QPushButton:hover{{background:{qss_alpha(_C['err'], 0.14)};"
        f"border-color:{_C['err']};}}"
        f"QPushButton:disabled{{color:{_C['muted']};border-color:{_C['border']};}}"
    )
    for name in (
        '_hold_btn', '_resume_btn', '_prv_btn', '_reprint_btn', '_returns_help_btn',
    ):
        b = getattr(tab, name, None)
        if _alive(b):
            try:
                b.setMinimumHeight(32)
                b.setMaximumHeight(34)
                b.setStyleSheet(quiet)
            except Exception:
                pass
    for name in ('_clr_btn', '_void_btn'):
        b = getattr(tab, name, None)
        if _alive(b):
            try:
                # Outline-only danger — never solid fill (avoids looking like active toggle)
                b.setObjectName('posQuietDanger')
                b.setMinimumHeight(32)
                b.setMaximumHeight(34)
                b.setStyleSheet(danger_q)
            except Exception:
                pass
    # Pro quick-action tiles — match Classic secondary height/weight
    tiles = getattr(tab, '_quick_action_tiles', None) or {}
    for t in tiles.values():
        if _alive(t) and hasattr(t, 'refresh_theme'):
            try:
                t.setMinimumHeight(32)
                t.setMaximumHeight(34)
                t.refresh_theme()
            except Exception:
                pass


def style_section_header(label, text: str | None = None) -> None:
    """Classic gold-standard section caption (Payment Method, etc.)."""
    if not _alive(label):
        return
    if text is not None:
        label.setText(text)
    label.setMinimumHeight(18)
    label.setStyleSheet(
        f"color:{C['text2']};font-size:12px;font-weight:800;letter-spacing:0.3px;"
        f"background:transparent;padding:0;margin:0;")


def align_checkout_control_baselines(tab) -> None:
    """Pixel-level control heights shared by Classic / Explorer / Pro."""
    paid = getattr(tab, '_paid', None)
    if _alive(paid):
        try:
            paid.setMinimumHeight(48)
            paid.setMaximumHeight(52)
        except Exception:
            pass
    chg = getattr(tab, '_chg_frame', None)
    if _alive(chg):
        try:
            chg.setMinimumHeight(44)
            chg.setMaximumHeight(52)
            lay = chg.layout()
            if lay is not None:
                lay.setContentsMargins(12, 8, 12, 8)
        except Exception:
            pass
    pay_seg = getattr(tab, '_pay_seg', None)
    if _alive(pay_seg) and hasattr(pay_seg, 'set_compact'):
        try:
            pay_seg.set_compact(True)
        except Exception:
            pass
    note = getattr(tab, '_note', None)
    if _alive(note):
        try:
            note.setMinimumHeight(36)
            note.setMaximumHeight(40)
        except Exception:
            pass
    new_btn = getattr(tab, '_new_cust_btn', None)
    if _alive(new_btn):
        try:
            new_btn.setMinimumHeight(36)
            new_btn.setMaximumHeight(38)
        except Exception:
            pass


def apply_checkout_foot_rhythm(tab, *, pro_primary_only: bool = False) -> None:
    """Classic foot: quiet secondary row + breathing room + Complete Sale."""
    foot = getattr(tab, '_checkout_foot', None)
    if not _alive(foot):
        return
    fl = foot.layout()
    if fl is not None:
        # Match Retail Classic: inset 12, top pad, bottom pad
        top = 12 if pro_primary_only else 8
        fl.setContentsMargins(12, top, 12, 12)
        fl.setSpacing(8)
        # Ensure one 10px breath before Complete Sale (idempotent)
        if not getattr(tab, '_foot_breathing_ok', False):
            charge = getattr(tab, '_charge_btn', None)
            if _alive(charge):
                for i in range(fl.count()):
                    item = fl.itemAt(i)
                    if item is not None and item.widget() is charge:
                        # Only insert if previous item isn't already a spacer ≥8px
                        prev = fl.itemAt(i - 1) if i > 0 else None
                        need = True
                        if prev is not None and prev.spacerItem() is not None:
                            need = prev.spacerItem().sizeHint().height() < 8
                        if need:
                            fl.insertSpacing(i, 10)
                        tab._foot_breathing_ok = True
                        break
    style_quiet_secondary_actions(tab)
    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        try:
            charge.setMinimumHeight(54)
            charge.setMaximumHeight(58)
            charge.show()
        except Exception:
            pass


def apply_shared_checkout_chrome(tab) -> None:
    """Explorer + Classic: Amount Paid treatment, quiet foot, denser payment stack."""
    ensure_checkout_body_order(tab)
    style_amount_paid(tab)
    align_checkout_control_baselines(tab)

    pay_hdr = getattr(tab, '_pay_hdr', None)
    style_section_header(pay_hdr, 'Payment Method')
    if _alive(pay_hdr):
        pay_hdr.show()

    # Hide legacy method combo / cash-paid label (tiles + Amount Paid replace them)
    for name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_var_frame'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.hide()

    chg = getattr(tab, '_chg_frame', None)
    if _alive(chg):
        lbl = getattr(tab, '_chg_lbl', None)
        val = getattr(tab, '_chg', None)
        if _alive(lbl):
            lbl.setText('Change')
            lbl.setStyleSheet(
                f"color:{C['text2']};font-size:12px;font-weight:700;background:transparent;")
        if _alive(val):
            val.setStyleSheet(
                f"color:{C['ok']};font-size:22px;font-weight:900;background:transparent;")
        chg.setStyleSheet(
            f"QFrame#posChangeDue{{background:{qss_alpha(C['ok'], 0.12)};"
            f"border:1.5px solid {qss_alpha(C['ok'], 0.36)};border-radius:10px;}}")

    # Classic gold-standard payment stack density (Explorer matches this)
    body = getattr(tab, '_actions_body', None)
    if _alive(body):
        bl = body.layout()
        if bl is not None:
            bl.setContentsMargins(12, 8, 12, 8)
            bl.setSpacing(6)

    apply_checkout_foot_rhythm(tab, pro_primary_only=False)

def _stash(tab, *widgets) -> None:
    stash = getattr(tab, '_layout_stash', None)
    if not _alive(stash):
        stash = QWidget(tab)
        stash.hide()
        tab._layout_stash = stash
    for w in widgets:
        if _alive(w) and w is not stash:
            w.setParent(stash)
            w.hide()


# ── Category chips ────────────────────────────────────────────────────────────

class CategoryChipBar(QWidget):
    """Compact horizontal category chips — selected uses gold accent."""
    categorySelected = pyqtSignal(str)  # 'All' or category name
    viewAllClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCatChipBar')
        self.setMaximumHeight(44)
        self._selected = 'All'
        self._chips = {}
        root = QHBoxLayout(self)
        # Extra right margin so More never clips against the card edge
        root.setContentsMargins(8, 2, 12, 2)
        root.setSpacing(10)

        self._view_all = QPushButton('View All')
        self._view_all.setObjectName('posCatViewAll')
        self._view_all.setCursor(Qt.PointingHandCursor)
        self._view_all.setFlat(True)
        self._view_all.setMinimumWidth(76)
        self._view_all.setMaximumHeight(28)
        self._view_all.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._view_all.clicked.connect(self.viewAllClicked.emit)

        from PyQt5.QtWidgets import QScrollArea
        self._scroll = QScrollArea()
        self._scroll.setObjectName('posCatChipScroll')
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(34)
        self._scroll.setStyleSheet(
            'QScrollArea{border:none;background:transparent;}'
            'QScrollBar:horizontal{height:4px;background:transparent;}'
            'QScrollBar::handle:horizontal{background:rgba(128,128,128,0.35);border-radius:2px;}')
        try:
            from desktop.utils.no_wheel_small_scroll import mark_wheel_scroll
            mark_wheel_scroll(self._scroll, True)
        except Exception:
            pass

        self._wrap = QWidget()
        self._wrap.setObjectName('posCatChipWrap')
        self._flow = QHBoxLayout(self._wrap)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setSpacing(5)
        self._flow.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._scroll.setWidget(self._wrap)
        root.addWidget(self._scroll, 1)
        root.addWidget(self._view_all, 0)
        self.refresh_theme()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-pack when the product column width changes (laptop / 3-col layouts)
        if getattr(self, '_packing', False):
            return
        labels = getattr(self, '_all_labels', None)
        if not labels or not self.isVisible():
            return
        try:
            w = self._scroll.viewport().width() if self._scroll.viewport() else 0
        except Exception:
            return
        prev = getattr(self, '_last_pack_w', -1)
        if abs(w - prev) < 24:
            return
        self._last_pack_w = w
        sel = self._selected
        self._packing = True
        try:
            self.set_categories([n for n in labels if n != 'All'])
            self.select(sel, emit=False)
        finally:
            self._packing = False

    def set_categories(self, names: list):
        while self._flow.count():
            item = self._flow.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._chips.clear()
        labels = ['All'] + [n for n in (names or []) if n and n != 'All']
        self._all_labels = list(labels)
        # Pack chips to available scroll width so More never overlaps labels
        try:
            avail = int(self._scroll.viewport().width()) if self._scroll.viewport() else 0
        except Exception:
            avail = 0
        if avail < 80:
            try:
                avail = max(160, int(self.width()) - 100)
            except Exception:
                avail = 360
        # Leave breathing room inside the scroll viewport
        budget = max(100, avail - 12)
        shown = []
        used = 0
        spacing = 5
        for name in labels:
            try:
                fm = self.fontMetrics()
                elide_px = 96 if len(name) > 8 else 110
                text = fm.elidedText(name, Qt.ElideRight, elide_px)
                chip_w = min(elide_px + 18, max(52, fm.horizontalAdvance(text) + 22))
            except Exception:
                text = name
                chip_w = 88
            need = chip_w + (spacing if shown else 0)
            # Always keep All + at least one named chip when present; after that stop when budget exceeded
            if shown and used + need > budget and len(shown) >= 2:
                break
            shown.append((name, text, chip_w))
            used += need
            # Hard cap so overflow always goes through More on dense category sets
            if len(shown) >= 4:
                break
        for name, text, chip_w in shown:
            b = QPushButton()
            b.setObjectName('posCatChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(26)
            b.setMaximumHeight(28)
            b.setToolTip(name)
            b.setText(text)
            b.setMaximumWidth(chip_w)
            b.setMinimumWidth(min(56, chip_w))
            b.clicked.connect(lambda _=False, n=name: self.select(n, emit=True))
            self._flow.addWidget(b)
            self._chips[name] = b
        # If selected category was truncated, still keep a chip for it
        if self._selected not in self._chips and self._selected and self._selected != 'All':
            b = QPushButton()
            b.setObjectName('posCatChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(26)
            b.setMaximumHeight(28)
            b.setToolTip(self._selected)
            try:
                fm = b.fontMetrics()
                b.setText(fm.elidedText(self._selected, Qt.ElideRight, 96))
                b.setMaximumWidth(110)
            except Exception:
                b.setText(self._selected)
            b.clicked.connect(lambda _=False, n=self._selected: self.select(n, emit=True))
            self._flow.addWidget(b)
            self._chips[self._selected] = b
        self._flow.addSpacing(4)
        self._flow.addStretch(1)
        overflow = max(0, len(labels) - len(shown))
        if overflow:
            self._view_all.setText('More ▾')
            self._view_all.setToolTip(f'{overflow} more categories — open full list')
        else:
            self._view_all.setText('View All')
            self._view_all.setToolTip('Browse all categories')
        try:
            self._last_pack_w = int(self._scroll.viewport().width()) if self._scroll.viewport() else avail
        except Exception:
            self._last_pack_w = avail
        self.select(self._selected if self._selected in self._chips else 'All', emit=False)
        self.refresh_theme()

    def select(self, name: str, emit=True):
        name = name or 'All'
        if name.startswith('All'):
            name = 'All'
        self._selected = name if name in self._chips else 'All'
        for k, b in self._chips.items():
            b.blockSignals(True)
            b.setChecked(k == self._selected)
            b.blockSignals(False)
        self._paint_chips()
        if emit:
            self.categorySelected.emit(self._selected)

    def current(self) -> str:
        return self._selected

    def _paint_chips(self):
        for k, b in self._chips.items():
            on = k == self._selected
            if on:
                b.setStyleSheet(
                    f"QPushButton#posCatChip{{background:{C['gold']};color:#1A1A1A;"
                    f"border:none;border-radius:12px;padding:3px 10px;"
                    f"font-size:11px;font-weight:800;}}")
            else:
                b.setStyleSheet(
                    f"QPushButton#posCatChip{{background:{C['card2']};color:{C['text2']};"
                    f"border:1px solid {C['border']};border-radius:12px;padding:3px 10px;"
                    f"font-size:11px;font-weight:700;}}"
                    f"QPushButton#posCatChip:hover{{border-color:{C['gold']};color:{C['text']};}}")

    def refresh_theme(self):
        self._view_all.setStyleSheet(
            f"QPushButton#posCatViewAll{{color:{C['text2']};font-size:10px;font-weight:700;"
            f"background:{C['card2']};border:1px solid {C['border']};border-radius:12px;"
            f"padding:3px 12px;min-width:72px;}}"
            f"QPushButton#posCatViewAll:hover{{border-color:{C['gold']};color:{C['text']};}}")
        self.setStyleSheet(
            f"QWidget#posCatChipBar,QWidget#posCatChipWrap{{background:transparent;}}")
        self._paint_chips()


# ── Sale type radios ──────────────────────────────────────────────────────────

class SaleTypeGroup(QWidget):
    """Cash Sale / Credit Sale / Quotation — maps onto existing payment paths."""
    saleTypeChanged = pyqtSignal(str)  # cash | credit | quotation

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posSaleType')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)
        hdr = QLabel('Sale options')
        hdr.setObjectName('posSaleTypeHdr')
        hdr.setToolTip('Separate from tender: Paid now / On account / Quote')
        lay.addWidget(hdr)
        self._group = QButtonGroup(self)
        self._radios = {}
        for key, label in (
            ('cash', 'Paid now'),
            ('credit', 'On account'),
            ('quotation', 'Quote only'),
        ):
            rb = QRadioButton(label)
            rb.setObjectName('posSaleTypeRadio')
            self._group.addButton(rb)
            self._radios[key] = rb
            lay.addWidget(rb)
            rb.toggled.connect(lambda on, k=key: on and self.saleTypeChanged.emit(k))
        self._radios['cash'].setChecked(True)
        self.refresh_theme()

    def current(self) -> str:
        for k, rb in self._radios.items():
            if rb.isChecked():
                return k
        return 'cash'

    def set_current(self, key: str, emit=False):
        rb = self._radios.get(key) or self._radios['cash']
        rb.blockSignals(True)
        rb.setChecked(True)
        rb.blockSignals(False)
        if emit:
            self.saleTypeChanged.emit(self.current())

    def refresh_theme(self):
        self.setStyleSheet(
            f"QWidget#posSaleType{{background:{C['card2']};border:1px solid {C['border']};"
            f"border-radius:{RADIUS['md']}px;}}"
            f"QLabel#posSaleTypeHdr{{color:{C['text2']};font-size:11px;font-weight:800;"
            f"letter-spacing:0.4px;background:transparent;}}"
            f"QRadioButton#posSaleTypeRadio{{color:{C['text']};font-size:12px;font-weight:700;"
            f"spacing:6px;background:transparent;}}"
            f"QRadioButton#posSaleTypeRadio::indicator{{width:14px;height:14px;}}"
            f"QRadioButton#posSaleTypeRadio::indicator:checked{{"
            f"background:{C['gold']};border:2px solid {C['gold']};border-radius:8px;}}"
            f"QRadioButton#posSaleTypeRadio::indicator:unchecked{{"
            f"background:transparent;border:2px solid {C['border2']};border-radius:8px;}}")


# ── Quick action tile ─────────────────────────────────────────────────────────

class QuickActionTile(QPushButton):
    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(label, parent)
        self._accent = accent
        self.setObjectName('posQuickTile')
        self.setCursor(Qt.PointingHandCursor)
        # Match Classic secondary action height (quiet supporting controls)
        self.setMinimumHeight(32)
        self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_theme()

    def refresh_theme(self):
        a = self._accent
        self.setStyleSheet(
            f"QPushButton#posQuickTile{{background:transparent;color:{C['text2']};"
            f"border:1px solid {C['border']};border-radius:8px;"
            f"font-size:11px;font-weight:600;padding:3px 4px;text-align:center;}}"
            f"QPushButton#posQuickTile:hover{{border-color:{a};color:{a};"
            f"background:{qss_alpha(a, 0.08)};}}"
            f"QPushButton#posQuickTile:pressed{{background:{qss_alpha(a, 0.14)};}}"
            f"QPushButton#posQuickTile:disabled{{color:{C['muted']};border-color:{C['border']};}}")


def ensure_pro_widgets(tab) -> None:
    """Create Pro-only accessory widgets once (idempotent)."""
    if not _alive(getattr(tab, '_cat_chips', None)):
        chips = CategoryChipBar()
        chips.categorySelected.connect(lambda n: _on_chip_category(tab, n))
        chips.viewAllClicked.connect(lambda: _on_view_all_categories(tab))
        tab._cat_chips = chips

    if not _alive(getattr(tab, '_sale_type', None)):
        st = SaleTypeGroup()
        st.saleTypeChanged.connect(lambda k: _on_sale_type(tab, k))
        tab._sale_type = st

    if not _alive(getattr(tab, '_new_cust_btn', None)):
        btn = QPushButton('+ New Customer')
        btn.setObjectName('posNewCustBtn')
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(36)
        btn.clicked.connect(lambda: _on_new_customer(tab))
        tab._new_cust_btn = btn

    if not _alive(getattr(tab, '_quick_actions', None)):
        wrap = QWidget()
        wrap.setObjectName('posQuickActions')
        gl = QGridLayout(wrap)
        gl.setContentsMargins(0, 2, 0, 0)
        gl.setHorizontalSpacing(6)
        gl.setVerticalSpacing(6)
        specs = [
            ('Hold Sale', C['gold'], '_hold_sale'),
            ('Suspend Sale', C.get('warn', C['gold']), '_suspend_sale'),
            ('Void Sale', C['err'], '_void_sale'),
            ('Recent Sales', C.get('info', '#3B82F6'), '_open_recent_sales'),
            ('Print Preview', C['text2'], '_preview'),
            ('Notes', C['text2'], '_focus_notes'),
        ]
        tiles = {}
        for i, (label, accent, handler) in enumerate(specs):
            t = QuickActionTile(label, accent)
            t.clicked.connect(lambda _=False, h=handler: _call_tab(tab, h))
            gl.addWidget(t, i // 3, i % 3)
            tiles[handler] = t
        tab._quick_action_tiles = tiles
        tab._quick_actions = wrap

    if not _alive(getattr(tab, '_amount_block', None)):
        # Prefer shared panel_factory Amount Paid block when present
        shared = getattr(tab, '_amount_paid_block', None)
        if _alive(shared):
            tab._amount_block = shared
            tab._amount_block_lay = shared.layout()
        else:
            block = QWidget()
            block.setObjectName('posAmountBlock')
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(4)
            paid_cap = QLabel('Amount Paid')
            paid_cap.setObjectName('posAmountCap')
            tab._amount_paid_cap = paid_cap
            bl.addWidget(paid_cap)
            tab._amount_block = block
            tab._amount_block_lay = bl
            tab._amount_paid_block = block
    if not _alive(getattr(tab, '_amount_paid_cap', None)):
        paid_cap = QLabel('Amount Paid')
        paid_cap.setObjectName('posAmountCap')
        tab._amount_paid_cap = paid_cap
        lay = getattr(tab, '_amount_block_lay', None)
        if lay is not None:
            lay.insertWidget(0, paid_cap)

    if not _alive(getattr(tab, '_cart_col_hdr', None)):
        hdr = QWidget()
        hdr.setObjectName('posCartColHdr')
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 4, 10, 4)
        hl.setSpacing(6)
        for text, stretch in (
            ('#', 0), ('Product', 4), ('Qty', 2),
            ('Price', 1), ('Disc*', 1), ('Total', 1), ('', 0),
        ):
            lab = QLabel(text)
            lab.setObjectName('posCartColLab')
            if text.startswith('Disc'):
                lab.setToolTip('Green = discount applied on that line')
            if stretch:
                hl.addWidget(lab, stretch)
            else:
                lab.setFixedWidth(22 if text == '#' else 28)
                hl.addWidget(lab)
        tab._cart_col_hdr = hdr


def _call_tab(tab, name: str):
    fn = getattr(tab, name, None)
    if callable(fn):
        fn()


def _on_chip_category(tab, name: str):
    cat = getattr(tab, '_cat', None)
    if cat is None:
        return
    target = 'All Categories' if name == 'All' else name
    idx = cat.findText(target)
    if idx < 0 and name != 'All':
        # fuzzy: category may be stored without exact match
        for i in range(cat.count()):
            if cat.itemText(i).lower() == name.lower():
                idx = i
                break
    if idx >= 0:
        cat.setCurrentIndex(idx)
    else:
        tab._filter()


def _on_view_all_categories(tab):
    cat = getattr(tab, '_cat', None)
    if cat is not None:
        cat.setCurrentIndex(0)
    chips = getattr(tab, '_cat_chips', None)
    if chips is not None:
        chips.select('All', emit=False)
    try:
        tab._filter()
    except Exception:
        pass


def _on_sale_type(tab, key: str):
    tab._pro_sale_type = key
    if key == 'credit':
        try:
            tab._select_pay_method('Credit Sale')
        except Exception:
            pass
        charge = getattr(tab, '_charge_btn', None)
        if charge is not None:
            charge.setText('Complete Credit Sale  (F9)')
    elif key == 'quotation':
        charge = getattr(tab, '_charge_btn', None)
        if charge is not None:
            charge.setText('Save Quotation  (F9)')
    else:
        # Restore tender method if stuck on Credit Sale
        pay = getattr(tab, '_pay', None)
        try:
            if pay is not None and pay.currentText() == 'Credit Sale':
                tab._select_pay_method('Cash')
        except Exception:
            pass
        charge = getattr(tab, '_charge_btn', None)
        if charge is not None:
            charge.setText('Complete Sale  (F9)')


def _on_new_customer(tab):
    card = getattr(tab, '_cust_card', None)
    if card is not None and hasattr(card, '_pick_create'):
        # Open create dialog without outer picker
        from PyQt5.QtWidgets import QDialog
        dummy = QDialog(tab)
        dummy.setAttribute(Qt.WA_DontShowOnScreen, True)
        try:
            card._pick_create(dummy)
        finally:
            dummy.deleteLater()
        return
    if card is not None and hasattr(card, '_open_picker'):
        card._open_picker()


def sync_category_chips(tab) -> None:
    chips = getattr(tab, '_cat_chips', None)
    cat = getattr(tab, '_cat', None)
    if not _alive(chips) or cat is None:
        return
    names = []
    for i in range(cat.count()):
        t = cat.itemText(i)
        if t and not t.lower().startswith('all'):
            names.append(t)
    chips.set_categories(names)
    cur = cat.currentText() or 'All Categories'
    chips.select('All' if cur.lower().startswith('all') else cur, emit=False)


def apply_checkout_pro_chrome(tab) -> None:
    """Visually align shared panels with the approved Checkout Pro reference."""
    ensure_pro_widgets(tab)
    from desktop.utils.theme import C as _C

    # ── Product column: search + chips; hide combo / focus clutter ───────────
    search_bar = getattr(tab, '_search_bar', None)
    cat = getattr(tab, '_cat', None)
    if _alive(cat):
        cat.hide()
    for name in ('_focus_btn', '_refresh_btn'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.hide()

    product = getattr(tab, '_product_panel', None)
    chips = tab._cat_chips
    if _alive(product) and _alive(chips):
        pl = product.layout()
        if pl is not None:
            # Insert chips under search if not already there
            if chips.parent() is not product:
                # Find search_bar index
                idx = 1
                if _alive(search_bar):
                    for i in range(pl.count()):
                        item = pl.itemAt(i)
                        if item and item.widget() is search_bar:
                            idx = i + 1
                            break
                pl.insertWidget(idx, chips)
            chips.show()
    sync_category_chips(tab)

    # Force-clear ghost empty overlay when catalog is present
    empty = getattr(tab, '_empty', None)
    grid = getattr(tab, '_prod_grid', None)
    if _alive(empty):
        has_cards = bool(getattr(grid, '_products', None)) if _alive(grid) else False
        if has_cards or (getattr(tab, 'products', None)):
            empty.hide()
            try:
                empty.lower()
            except Exception:
                pass

    search = getattr(tab, '_search', None)
    if _alive(search) and hasattr(search, 'set_pro_icons'):
        search.set_pro_icons(True)
        search.setPlaceholderText('Search or scan barcode, product name, SKU...')

    # Larger cards / fill scroll
    grid = getattr(tab, '_prod_grid', None)
    if _alive(grid) and hasattr(grid, 'set_pro_density'):
        grid.set_pro_density(True)

    # ── Cart: table density, column hdr, merged title, no Review ─────────────
    hdr = getattr(tab, '_sale_hdr', None)
    cnt = getattr(tab, '_cnt', None)
    if _alive(hdr):
        n = len(getattr(tab, 'cart', []) or [])
        hdr.setText(f'Current Sale ({n} item{"s" if n != 1 else ""})')
    if _alive(cnt):
        cnt.hide()
    rev = getattr(tab, '_cart_max_btn', None)
    if _alive(rev):
        rev.hide()

    clist = getattr(tab, '_cart_list', None)
    if _alive(clist):
        if hasattr(clist, 'set_density'):
            clist.set_density('table')
        if hasattr(clist, 'set_expanded'):
            clist.set_expanded(True)
        # Prefer cart_list as the sole scroller — hide outer wrapper scroll host padding
        col_hdr = tab._cart_col_hdr
        if _alive(col_hdr) and hasattr(clist, 'set_column_header'):
            clist.set_column_header(col_hdr)
        col_hdr.refresh_theme = lambda: _style_col_hdr(col_hdr)  # type: ignore
        _style_col_hdr(col_hdr)

    # Pack cart against summary — empty stretch below summary, not between cart & totals
    try:
        sale = getattr(tab, '_sale_panel', None)
        cart_scroll = getattr(tab, '_sale_cart_scroll', None)
        sl = sale.layout() if _alive(sale) else None
        if sl is not None and _alive(cart_scroll):
            for i in range(sl.count()):
                item = sl.itemAt(i)
                if item and item.widget() is cart_scroll:
                    sl.setStretch(i, 0)
                    break
            spacer = getattr(tab, '_sale_bottom_stretch', None)
            if not _alive(spacer):
                from PyQt5.QtWidgets import QSizePolicy, QWidget
                spacer = QWidget()
                spacer.setObjectName('posSaleBottomStretch')
                spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                tab._sale_bottom_stretch = spacer
            # Ensure spacer is last child (after summary)
            if spacer.parent() is not sale:
                sl.addWidget(spacer, 1)
            else:
                sl.setStretchFactor(spacer, 1)
            cart_scroll.setMinimumHeight(0)
    except Exception:
        pass

    summary = getattr(tab, '_summary', None)
    if _alive(summary) and hasattr(summary, 'set_pro_chrome'):
        summary.set_pro_chrome(True)

    # ── Right rail: customer row, payment row, amount+sale type, quick acts ──
    cust = getattr(tab, '_cust_card', None)
    new_btn = tab._new_cust_btn
    if _alive(cust) and hasattr(cust, 'set_pro_row'):
        cust.set_pro_row(True, new_btn)
    _style_new_cust(new_btn)

    pay_seg = getattr(tab, '_pay_seg', None)
    if _alive(pay_seg):
        try:
            if hasattr(pay_seg, 'set_row_layout'):
                pay_seg.set_row_layout(True)
        except Exception:
            pass
        try:
            if hasattr(pay_seg, 'set_compact'):
                pay_seg.set_compact(True)
        except Exception:
            pass

    # Hide method dropdown + legacy cash-paid label (tiles + Amount Paid replace them)
    for name in ('_pay_lbl', '_pay', '_cash_paid_lbl'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.hide()

    # Never permanently show Additional Payment Handling / till variance strip
    for name in ('_var_frame',):
        w = getattr(tab, name, None)
        if _alive(w):
            w.hide()

    # Relabel paid spin as Amount Paid; keep change frame (same pattern as Classic)
    style_amount_paid(tab)
    align_checkout_control_baselines(tab)

    chg = getattr(tab, '_chg_frame', None)
    if _alive(chg):
        lbl = getattr(tab, '_chg_lbl', None)
        val = getattr(tab, '_chg', None)
        if _alive(lbl):
            lbl.setText('Change')
            lbl.setStyleSheet(
                f"color:{C['text2']};font-size:12px;font-weight:700;background:transparent;")
        if _alive(val):
            val.setStyleSheet(
                f"color:{C['ok']};font-size:22px;font-weight:900;background:transparent;")
        # Match Classic change-due chrome exactly
        chg.setStyleSheet(
            f"QFrame#posChangeDue{{background:{qss_alpha(C['ok'], 0.12)};"
            f"border:1.5px solid {qss_alpha(C['ok'], 0.36)};border-radius:10px;}}")

    # Hide always-visible note line — Notes quick action opens it
    note = getattr(tab, '_note', None)
    if _alive(note):
        note.hide()

    # Split UI only when Mixed is selected (event-driven)
    split = getattr(tab, '_split_frame', None)
    if _alive(split):
        pay = getattr(tab, '_pay', None)
        method = ''
        try:
            method = pay.currentText() if pay is not None else ''
        except Exception:
            method = ''
        if method != 'Mixed':
            split.hide()

    # Dense payment stack — pack to top; absorb leftover height below stack (not above)
    body = getattr(tab, '_actions_body', None)
    if _alive(body):
        bl = body.layout()
        if bl is not None:
            bl.setContentsMargins(12, 6, 12, 4)
            bl.setSpacing(4)
            # Insert amount+sale-type row and quick actions if missing
            _ensure_body_pro_sections(tab, bl)
            # Prefer content at top of expandable body (no leading stretch)
            try:
                bl.setAlignment(Qt.AlignTop)
            except Exception:
                pass

    # Footer: only Complete Sale — same Classic breathing room / height rhythm
    for name in (
        '_clr_btn', '_hold_btn', '_resume_btn', '_prv_btn', '_reprint_btn',
        '_void_btn', '_returns_help_btn',
    ):
        b = getattr(tab, name, None)
        if _alive(b):
            b.hide()
    apply_checkout_foot_rhythm(tab, pro_primary_only=True)
    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        st = getattr(tab, '_pro_sale_type', 'cash')
        if st == 'credit':
            charge.setText('Complete Credit Sale  (F9)')
        elif st == 'quotation':
            charge.setText('Save Quotation  (F9)')
        else:
            charge.setText('Complete Sale  (F9)')

    # Nest quick actions into foot (above Complete Sale) — Classic bottom-action rhythm
    qa = getattr(tab, '_quick_actions', None)
    foot = getattr(tab, '_checkout_foot', None)
    if _alive(qa) and _alive(foot):
        fl = foot.layout()
        if fl is not None:
            try:
                # Remove from body if present
                bp = getattr(tab, '_actions_body', None)
                if _alive(bp):
                    bl = bp.layout()
                    if bl is not None:
                        for i in range(bl.count()):
                            item = bl.itemAt(i)
                            if item is not None and item.widget() is qa:
                                bl.takeAt(i)
                                break
                # Insert just above charge button
                insert_at = fl.count()
                if _alive(charge):
                    for i in range(fl.count()):
                        item = fl.itemAt(i)
                        if item is not None and item.widget() is charge:
                            insert_at = i
                            break
                if qa.parent() is not foot:
                    fl.insertWidget(insert_at, qa)
                qa.show()
                qgl = qa.layout()
                if qgl is not None:
                    qgl.setContentsMargins(0, 0, 0, 0)
                    qgl.setHorizontalSpacing(6)
                    qgl.setVerticalSpacing(5)
            except Exception:
                pass

    style_quiet_secondary_actions(tab)

    # Sync void tile permission
    tiles = getattr(tab, '_quick_action_tiles', {}) or {}
    void_tile = tiles.get('_void_sale')
    if _alive(void_tile):
        void_tile.setEnabled(getattr(tab, '_void_btn', None) is not None)
        void_tile.setVisible(getattr(tab, '_void_btn', None) is not None)

    qa = getattr(tab, '_quick_actions', None)
    if _alive(qa):
        for t in qa.findChildren(QuickActionTile):
            t.refresh_theme()
    st = getattr(tab, '_sale_type', None)
    if _alive(st):
        st.refresh_theme()
    if _alive(chips):
        chips.refresh_theme()


def _style_col_hdr(hdr: QWidget):
    hdr.setStyleSheet(
        f"QWidget#posCartColHdr{{background:transparent;border-bottom:1px solid {C['border']};}}"
        f"QLabel#posCartColLab{{color:{C['muted']};font-size:10px;font-weight:800;"
        f"letter-spacing:0.4px;background:transparent;}}")


def _style_new_cust(btn: QPushButton):
    if not _alive(btn):
        return
    btn.setStyleSheet(
        f"QPushButton#posNewCustBtn{{background:{qss_alpha(C['gold'], 0.12)};"
        f"color:{C['gold']};border:1.5px solid {C['gold']};border-radius:10px;"
        f"font-size:12px;font-weight:800;padding:0 12px;}}"
        f"QPushButton#posNewCustBtn:hover{{background:{qss_alpha(C['gold'], 0.22)};}}")


def _ensure_body_pro_sections(tab, bl):
    """Hierarchy: customer → payment method → amount/change → sale options → quick acts."""
    widgets_in_order = []
    for i in range(bl.count()):
        item = bl.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is not None:
            widgets_in_order.append(w)

    # Compact customer → payment gap (baseline aligns with Classic chip height)
    cust = getattr(tab, '_cust_card', None)
    if _alive(cust):
        try:
            cust.setMaximumHeight(42)
            lay = cust.layout()
            if lay is not None:
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(0)
        except Exception:
            pass
    pay_hdr = None
    for w in widgets_in_order:
        if isinstance(w, QLabel) and w.objectName() == 'posPayHdr':
            pay_hdr = w
            break
    if not _alive(pay_hdr):
        pay_hdr = getattr(tab, '_pay_hdr', None)
    style_section_header(pay_hdr, 'Payment Method')

    # Unified payment card — denser, Classic-aligned insets
    pay_card = getattr(tab, '_pro_pay_card', None)
    if not _alive(pay_card):
        pay_card = QFrame()
        pay_card.setObjectName('posProPayCard')
        pcl = QVBoxLayout(pay_card)
        pcl.setContentsMargins(10, 8, 10, 8)
        pcl.setSpacing(5)
        tab._pro_pay_card = pay_card
        tab._pro_pay_card_lay = pcl
    else:
        pcl = tab._pro_pay_card_lay
        try:
            pcl.setContentsMargins(10, 8, 10, 8)
            pcl.setSpacing(5)
        except Exception:
            pass
    pay_card.setStyleSheet(
        f"QFrame#posProPayCard{{background:{C['card2']};border:1px solid {C['border']};"
        f"border-radius:{RADIUS['md']}px;}}")
    # Section caption inside the unified payment card (same weight as Classic headers)
    if not _alive(getattr(tab, '_pro_pay_cap', None)):
        cap = QLabel('Checkout')
        cap.setObjectName('posProPayCap')
        tab._pro_pay_cap = cap
        pcl.insertWidget(0, cap)
    style_section_header(tab._pro_pay_cap, 'Checkout')
    tab._pro_pay_cap.show()

    row = getattr(tab, '_pro_amount_sale_row', None)
    if not _alive(row):
        row = QWidget()
        row.setObjectName('posProAmountSaleRow')
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        # Prefer shared Amount Paid block (caption + spin already nested)
        amt_block = (
            getattr(tab, '_amount_paid_block', None)
            or getattr(tab, '_amount_block', None)
        )
        if _alive(amt_block):
            ll.addWidget(amt_block)
        else:
            cap = getattr(tab, '_amount_paid_cap', None)
            if not _alive(cap):
                cap = QLabel('Amount Paid')
                cap.setObjectName('posAmountCap')
                tab._amount_paid_cap = cap
            style_section_header(cap, 'Amount Paid')
            ll.addWidget(cap)
            paid = getattr(tab, '_paid', None)
            if _alive(paid):
                ll.addWidget(paid)
        chg = getattr(tab, '_chg_frame', None)
        if _alive(chg):
            ll.addWidget(chg)
        rl.addWidget(left, 3)

        st = getattr(tab, '_sale_type', None)
        if _alive(st):
            rl.addWidget(st, 2)
        tab._pro_amount_sale_row = row
    else:
        # Ensure Amount Paid stays styled when row already exists
        style_amount_paid(tab)

    for i in range(bl.count() - 1, -1, -1):
        item = bl.itemAt(i)
        if item is not None and item.spacerItem() is not None:
            bl.takeAt(i)

    # Nest customer → payment method → amount/sale into pay_card
    pcl = tab._pro_pay_card_lay
    pay_seg = getattr(tab, '_pay_seg', None)
    cust = getattr(tab, '_cust_card', None)
    if _alive(cust) and cust.parent() is not pay_card:
        try:
            cust.setMaximumHeight(40)
        except Exception:
            pass
        pcl.insertWidget(1, cust)
    if _alive(pay_hdr) and pay_hdr.parent() is not pay_card:
        pcl.addWidget(pay_hdr)
    if _alive(pay_seg) and pay_seg.parent() is not pay_card:
        pcl.addWidget(pay_seg)
    if row.parent() is not pay_card:
        pcl.addWidget(row)
    row.show()
    pay_card.show()

    if pay_card.parent() is None or pay_card not in [
            bl.itemAt(i).widget() for i in range(bl.count())
            if bl.itemAt(i) and bl.itemAt(i).widget()]:
        insert_at = 0
        bl.insertWidget(insert_at, pay_card)

    qa = getattr(tab, '_quick_actions', None)
    if _alive(qa):
        if qa.parent() is None or qa not in [
                bl.itemAt(i).widget() for i in range(bl.count())
                if bl.itemAt(i) and bl.itemAt(i).widget()]:
            bl.addWidget(qa)
        qa.show()
        # Tighten quick-action grid to Classic secondary visual weight
        qgl = qa.layout()
        if qgl is not None:
            try:
                qgl.setContentsMargins(0, 0, 0, 0)
                qgl.setHorizontalSpacing(6)
                qgl.setVerticalSpacing(5)
            except Exception:
                pass
    # Keep payment stack tight: no expanding spacer inside body (foot owns leftover height)
    try:
        for i in range(bl.count() - 1, -1, -1):
            item = bl.itemAt(i)
            if item is not None and item.spacerItem() is not None:
                bl.takeAt(i)
    except Exception:
        pass


def restore_shared_chrome(tab) -> None:
    """Undo Checkout Pro–specific chrome when switching to other layouts."""
    chips = getattr(tab, '_cat_chips', None)
    if _alive(chips):
        chips.hide()
        _stash(tab, chips)

    cat = getattr(tab, '_cat', None)
    if _alive(cat):
        cat.show()
    for name in ('_focus_btn', '_refresh_btn'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.show()

    search = getattr(tab, '_search', None)
    if _alive(search) and hasattr(search, 'set_pro_icons'):
        search.set_pro_icons(False)
        search.setPlaceholderText('Search or scan barcode...')

    grid = getattr(tab, '_prod_grid', None)
    if _alive(grid) and hasattr(grid, 'set_pro_density'):
        grid.set_pro_density(False)

    hdr = getattr(tab, '_sale_hdr', None)
    if _alive(hdr):
        hdr.setText('Current Sale')
    cnt = getattr(tab, '_cnt', None)
    if _alive(cnt):
        cnt.show()
    rev = getattr(tab, '_cart_max_btn', None)
    if _alive(rev):
        rev.show()

    clist = getattr(tab, '_cart_list', None)
    if _alive(clist):
        if hasattr(clist, 'set_density'):
            clist.set_density('card')
        if hasattr(clist, 'set_column_header'):
            clist.set_column_header(None)
        if hasattr(clist, 'set_expanded'):
            clist.set_expanded(bool(getattr(tab, '_cart_maximized', False)))

    # Restore sale panel stretch (cart fills, no bottom spacer)
    try:
        sale = getattr(tab, '_sale_panel', None)
        cart_scroll = getattr(tab, '_sale_cart_scroll', None)
        spacer = getattr(tab, '_sale_bottom_stretch', None)
        sl = sale.layout() if _alive(sale) else None
        if sl is not None:
            if _alive(spacer):
                sl.removeWidget(spacer)
                spacer.setParent(None)
                spacer.hide()
            if _alive(cart_scroll):
                for i in range(sl.count()):
                    item = sl.itemAt(i)
                    if item and item.widget() is cart_scroll:
                        sl.setStretch(i, 1)
                        break
                cart_scroll.setMinimumHeight(260)
    except Exception:
        pass

    summary = getattr(tab, '_summary', None)
    if _alive(summary) and hasattr(summary, 'set_pro_chrome'):
        summary.set_pro_chrome(False)

    cust = getattr(tab, '_cust_card', None)
    if _alive(cust) and hasattr(cust, 'set_pro_row'):
        cust.set_pro_row(False)

    new_btn = getattr(tab, '_new_cust_btn', None)
    if _alive(new_btn):
        new_btn.hide()
        _stash(tab, new_btn)

    pay_seg = getattr(tab, '_pay_seg', None)
    if _alive(pay_seg):
        if hasattr(pay_seg, 'set_row_layout'):
            pay_seg.set_row_layout(False)
        if hasattr(pay_seg, 'set_compact'):
            pay_seg.set_compact(False)

    for name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_note'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.show()

    row = getattr(tab, '_pro_amount_sale_row', None)
    if _alive(row):
        # Lift paid/change/amount block out before parking the Pro amount row
        body = getattr(tab, '_actions_body', None)
        bl = body.layout() if _alive(body) else None
        amt_block = (
            getattr(tab, '_amount_paid_block', None)
            or getattr(tab, '_amount_block', None)
        )
        paid = getattr(tab, '_paid', None)
        chg = getattr(tab, '_chg_frame', None)
        if bl is not None:
            if _alive(amt_block):
                bl.addWidget(amt_block)
                amt_block.show()
            elif _alive(paid):
                bl.addWidget(paid)
                paid.show()
            if _alive(chg):
                bl.addWidget(chg)
                chg.show()
        row.hide()
        _stash(tab, row)

    pay_card = getattr(tab, '_pro_pay_card', None)
    if _alive(pay_card):
        # Re-home pay_seg / pay_hdr into body before stashing card
        body = getattr(tab, '_actions_body', None)
        bl = body.layout() if _alive(body) else None
        pay_seg = getattr(tab, '_pay_seg', None)
        if bl is not None and _alive(pay_seg):
            bl.insertWidget(1, pay_seg)
            pay_seg.show()
        pay_card.hide()
        _stash(tab, pay_card)

    qa = getattr(tab, '_quick_actions', None)
    if _alive(qa):
        qa.hide()
        _stash(tab, qa)

    st = getattr(tab, '_sale_type', None)
    if _alive(st):
        st.hide()
        _stash(tab, st)

    # Do not reparent paid/chg aggressively — chrome hide/show is enough.
    # Re-inserting into body layouts after Pro amount-row can hang Qt layouts.

    for name in (
        '_clr_btn', '_hold_btn', '_resume_btn', '_prv_btn', '_reprint_btn',
        '_void_btn', '_returns_help_btn',
    ):
        b = getattr(tab, name, None)
        if _alive(b):
            b.show()

    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        charge.setText('$  Complete Sale')
        charge.setMinimumHeight(56)

    # Ensure paid + change are visible again (may sit inside pro amount row)
    style_amount_paid(tab)
    paid = getattr(tab, '_paid', None)
    chg = getattr(tab, '_chg_frame', None)
    if _alive(paid):
        paid.show()
    if _alive(chg):
        chg.show()
        lbl = getattr(tab, '_chg_lbl', None)
        if _alive(lbl):
            lbl.setText('Change')

    body = getattr(tab, '_actions_body', None)
    if _alive(body):
        bl = body.layout()
        if bl is not None:
            bl.setContentsMargins(12, 8, 12, 8)
            bl.setSpacing(6)
