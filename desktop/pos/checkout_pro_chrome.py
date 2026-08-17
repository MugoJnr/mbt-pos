"""Checkout Pro visual chrome — adapts shared POS panels to the approved design.

Does not duplicate business logic. Widgets stay owned by SalesTab / panel_factory;
this module only rearranges visibility, density, and Pro-only accessory chrome.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QRadioButton, QSizePolicy,
    QVBoxLayout, QWidget, QMessageBox, QInputDialog,
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
    foot = getattr(tab, '_checkout_foot', None)
    if getattr(tab, '_totals_pinned', False):
        always_show -= {'_amount_paid_block', '_chg_frame'}
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
        if getattr(tab, '_totals_pinned', False) and _alive(foot) and w.parent() is foot:
            continue
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
                b.setMinimumHeight(36)
                b.setMaximumHeight(40)
                b.setStyleSheet(quiet)
            except Exception:
                pass
    for name in ('_clr_btn', '_void_btn'):
        b = getattr(tab, name, None)
        if _alive(b):
            try:
                # Outline-only danger — never solid fill (avoids looking like active toggle)
                b.setObjectName('posQuietDanger')
                b.setMinimumHeight(36)
                b.setMaximumHeight(40)
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


def _place_summary_in_pro_center(tab) -> None:
    """Checkout Pro: Subtotal / Discount / Total due sit at the bottom of Current Sale."""
    from desktop.utils.quiet_ui import safe_show

    summary = getattr(tab, '_summary', None)
    wrap = getattr(tab, '_sale_summary_wrap', None)
    host = wrap if _alive(wrap) else summary
    sp = getattr(tab, '_cart_splitter', None)
    if not _alive(host) or not _alive(summary) or not _alive(sp):
        return
    if hasattr(summary, 'set_pinned_strip'):
        try:
            summary.set_pinned_strip(False)
        except Exception:
            pass
    if hasattr(summary, 'set_pro_chrome'):
        try:
            summary.set_pro_chrome(True)
        except Exception:
            pass
    try:
        host.setMaximumHeight(16777215)
        host.setMinimumHeight(88)
        pol = host.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Preferred)
        pol.setVerticalPolicy(QSizePolicy.Preferred)
        host.setSizePolicy(pol)
        host.setStyleSheet(
            'QWidget#posSaleSummaryWrap{background:transparent;border:none;}')
    except Exception:
        pass
    try:
        host.setAttribute(Qt.WA_DontShowOnScreen, False)
        summary.setAttribute(Qt.WA_DontShowOnScreen, False)
    except Exception:
        pass
    already = False
    try:
        for i in range(sp.count()):
            if sp.widget(i) is host:
                already = True
                break
    except Exception:
        already = False
    if not already:
        try:
            sp.addWidget(host)
        except Exception:
            pass
    safe_show(host)
    safe_show(summary)


def pin_checkout_totals(tab) -> None:
    """Keep Amount Paid on screen; pin Order Summary in the foot except Checkout Pro.

    Checkout Pro puts Subtotal / Discount / Total due at the bottom of the
    center Current Sale column. Classic / Explorer keep the summary strip in
    the sticky pay foot so it is not scrolled away.
    """
    from desktop.utils.quiet_ui import safe_show

    foot = getattr(tab, '_checkout_foot', None)
    if not _alive(foot):
        return
    fl = foot.layout()
    if fl is None:
        return
    summary = getattr(tab, '_summary', None)
    wrap = getattr(tab, '_sale_summary_wrap', None)
    host = wrap if _alive(wrap) else summary
    is_pro = getattr(tab, '_checkout_layout', '') == 'checkout_pro'
    if is_pro:
        _place_summary_in_pro_center(tab)
        host = None
    elif not _alive(host) or not _alive(summary):
        return

    if (not is_pro) and _alive(summary):
        if hasattr(summary, 'set_pinned_strip'):
            try:
                summary.set_pinned_strip(True)
            except Exception:
                pass
        elif hasattr(summary, 'set_review_compact'):
            try:
                summary.set_review_compact(True)
            except Exception:
                pass

    disc = getattr(tab, '_disc', None)
    if _alive(disc):
        try:
            disc.setReadOnly(False)
            disc.setMinimumHeight(32)
            disc.setMaximumHeight(36)
            disc.setFixedWidth(128)
            disc.show()
        except Exception:
            pass
    disc_lbl = getattr(tab, '_disc_lbl', None)
    if _alive(disc_lbl):
        try:
            disc_lbl.show()
        except Exception:
            pass

    amt = (
        getattr(tab, '_amount_paid_block', None)
        or getattr(tab, '_amount_block', None)
    )
    chg = getattr(tab, '_chg_frame', None)
    pro_row = getattr(tab, '_pro_amount_sale_row', None)

    if _alive(host):
        try:
            host.setMaximumHeight(220)
            host.setMinimumHeight(100)
            pol = host.sizePolicy()
            pol.setHorizontalPolicy(QSizePolicy.Preferred)
            pol.setVerticalPolicy(QSizePolicy.Maximum)
            host.setSizePolicy(pol)
        except Exception:
            pass
        if _alive(wrap):
            wrap.setStyleSheet(
                'QWidget#posSaleSummaryWrap{background:transparent;border:none;}')

    # Foot stack (top → Complete Sale): totals, Amount Paid, Change, utilities, charge.
    stack = []
    if _alive(host):
        stack.append(host)
    if _alive(amt):
        stack.append(amt)
    if _alive(chg):
        stack.append(chg)
    for w in reversed(stack):
        try:
            w.setAttribute(Qt.WA_DontShowOnScreen, False)
        except Exception:
            pass
        try:
            fl.insertWidget(0, w)
        except Exception:
            pass
        safe_show(w)
        try:
            w.show()
        except Exception:
            pass

    if _alive(pro_row):
        try:
            pro_row.hide()
        except Exception:
            pass

    tab._totals_pinned = True
    style_amount_paid(tab)

    # Classic/Explorer: cart list owns Current Sale when summary lives in the foot.
    if not is_pro:
        sp = getattr(tab, '_cart_splitter', None)
        if _alive(sp) and sp.count() == 1:
            try:
                pane = sp.widget(0)
                if _alive(pane):
                    pane.setMaximumHeight(16777215)
                    pane.setMinimumHeight(0)
                    sp.setStretchFactor(0, 1)
            except Exception:
                pass


def apply_secondary_action_grid(tab) -> None:
    """Two-row Classic/Explorer footer so Clear…Returns never cram into one strip."""
    foot = getattr(tab, '_checkout_foot', None)
    if not _alive(foot):
        return
    fl = foot.layout()
    if fl is None:
        return
    # Already converted?
    if getattr(tab, '_sec_actions_grid_ok', False):
        style_quiet_secondary_actions(tab)
        return

    buttons = []
    for name in (
        '_clr_btn', '_hold_btn', '_resume_btn', '_prv_btn',
        '_reprint_btn', '_void_btn', '_returns_help_btn',
    ):
        b = getattr(tab, name, None)
        if _alive(b):
            buttons.append(b)
    if len(buttons) < 4:
        return

    # Remove old QHBoxLayout row of secondary actions (first layout item before spacers/charge)
    old_row = getattr(tab, '_checkout_sec_row', None)
    try:
        if old_row is not None:
            # Detach widgets from old layout without deleting buttons
            while old_row.count():
                item = old_row.takeAt(0)
                w = item.widget()
                if w is not None:
                    try:
                        w.hide()
                        w.setAttribute(Qt.WA_DontShowOnScreen, True)
                    except Exception:
                        pass
                    # Keep parent until grid reparents — never free top-level.
                    # (setParent(None) here caused brief OS flash popups.)
            fl.removeItem(old_row)
    except Exception:
        pass

    from PyQt5.QtWidgets import QGridLayout
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    cols = 4
    for i, b in enumerate(buttons):
        try:
            b.setMinimumHeight(36)
            b.setMaximumHeight(40)
            b.setMinimumWidth(0)
            b.setMaximumWidth(16777215)
            if hasattr(b, 'setFixedWidth'):
                # Undo Classic Clear fixed-width crush
                b.setMinimumWidth(64)
        except Exception:
            pass
        grid.addWidget(b, i // cols, i % cols)
        b.show()
    # Insert grid at top of foot (before breathing spacer / Complete Sale)
    fl.insertLayout(0, grid)
    tab._checkout_sec_row = grid
    tab._sec_actions_grid_ok = True
    style_quiet_secondary_actions(tab)


def apply_shared_checkout_chrome(tab) -> None:
    """Explorer + Classic: Amount Paid treatment, quiet foot, denser payment stack."""
    ensure_checkout_body_order(tab)
    style_amount_paid(tab)
    align_checkout_control_baselines(tab)

    # Ensure Pro accessory widgets exist so New Customer + cart Disc header work here too
    try:
        ensure_pro_widgets(tab)
    except Exception:
        pass

    # Table cart column header (includes Disc) on Classic / Explorer
    clist = getattr(tab, '_cart_list', None)
    col_hdr = getattr(tab, '_cart_col_hdr', None)
    if _alive(clist) and _alive(col_hdr) and hasattr(clist, 'set_column_header'):
        try:
            clist.set_column_header(col_hdr)
            _style_col_hdr(col_hdr)
        except Exception:
            pass

    # New Customer reachable on Classic / Explorer (same as Pro)
    cust = getattr(tab, '_cust_card', None)
    new_btn = getattr(tab, '_new_cust_btn', None)
    if _alive(cust) and _alive(new_btn) and hasattr(cust, 'set_pro_row'):
        try:
            cust.set_pro_row(True, new_btn)
            _style_new_cust(new_btn)
            new_btn.show()
        except Exception:
            pass

    # Cart-level Discount always visible + editable
    disc = getattr(tab, '_disc', None)
    disc_lbl = getattr(tab, '_disc_lbl', None)
    if _alive(disc):
        try:
            disc.setReadOnly(False)
            disc.setMinimumWidth(120)
            disc.setFixedWidth(150)
            disc.show()
        except Exception:
            pass
    if _alive(disc_lbl):
        try:
            disc_lbl.setText('Discount (KES)')
            disc_lbl.setToolTip(
                'Cart-level discount for the whole sale. '
                'Per-item Disc is on each cart line.')
            disc_lbl.show()
        except Exception:
            pass

    pay_hdr = getattr(tab, '_pay_hdr', None)
    style_section_header(pay_hdr, 'Payment Method')
    if _alive(pay_hdr):
        pay_hdr.show()

    # Hide legacy method combo / cash-paid label (tiles + Amount Paid replace them)
    for name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_var_frame'):
        w = getattr(tab, name, None)
        if _alive(w):
            w.hide()

    # Credit Sale + Part Payment: Sale options on Classic / Explorer (same as Pro)
    st = getattr(tab, '_sale_type', None)
    body = getattr(tab, '_actions_body', None)
    bl = body.layout() if _alive(body) else None
    if _alive(st) and bl is not None:
        try:
            if hasattr(st, 'set_horizontal'):
                st.set_horizontal(True)
            st.refresh_theme()
            # Place after payment tiles / before Amount Paid
            amt = (
                getattr(tab, '_amount_paid_block', None)
                or getattr(tab, '_amount_block', None)
            )
            insert_at = bl.count()
            if _alive(amt):
                for i in range(bl.count()):
                    item = bl.itemAt(i)
                    if item is not None and item.widget() is amt:
                        insert_at = i
                        break
            if st.parent() is not body:
                bl.insertWidget(insert_at, st)
            st.show()
        except Exception:
            pass

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
            bl.setContentsMargins(12, 6, 12, 6)
            bl.setSpacing(5)

    # Ensure Amount Paid + Change stay reachable (not buried under a tall cart)
    for name in ('_amount_paid_block', '_amount_block', '_paid', '_chg_frame', '_amount_paid_cap'):
        w = getattr(tab, name, None)
        if _alive(w):
            try:
                w.show()
            except Exception:
                pass

    apply_checkout_foot_rhythm(tab, pro_primary_only=False)
    apply_secondary_action_grid(tab)
    pin_checkout_totals(tab)

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

    CHIP_BAR_H = 108
    CHIP_PILL_H = 34
    CHIP_HOST_H = 56  # air around 34px pills + 1px borders so bottoms stay round

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posCatChipBar')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(self.CHIP_BAR_H)
        self.setMaximumHeight(self.CHIP_BAR_H)
        self.setFixedHeight(self.CHIP_BAR_H)
        self._selected = 'All'
        self._chips = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 26, 12, 26)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignVCenter)

        self._wrap = QWidget(self)
        self._wrap.setObjectName('posCatChipWrap')
        self._wrap.setFixedHeight(self.CHIP_HOST_H)
        self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root = QHBoxLayout(self._wrap)
        root.setContentsMargins(0, 11, 0, 11)
        root.setSpacing(10)
        root.setAlignment(Qt.AlignVCenter)
        self._flow = root
        outer.addWidget(self._wrap, 1)

        self._view_all = QPushButton('View All')
        self._view_all.setObjectName('posCatViewAll')
        self._view_all.setCursor(Qt.PointingHandCursor)
        self._view_all.setFlat(True)
        self._view_all.setMinimumWidth(76)
        self._view_all.setFixedHeight(self.CHIP_PILL_H)
        self._view_all.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._view_all.clicked.connect(self.viewAllClicked.emit)
        # Placeholders so set_categories can insert chips before More.
        self._scroll = self
        root.addStretch(1)
        root.addWidget(self._view_all, 0)
        self.refresh_theme()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-pack when the product column width changes (laptop / 3-col layouts)
        self.repack_for_width(force=False)

    def repack_for_width(self, force: bool = False):
        """Recompute visible chips for the current product-column width.

        Called from resize and from the column splitter so a drag that narrows
        the catalog never leaves clipped tabs or a missing More control.
        """
        if getattr(self, '_packing', False):
            return
        labels = getattr(self, '_all_labels', None)
        if not labels or not self.isVisible():
            return
        try:
            w = max(0, int(self.width()) - 100)
        except Exception:
            return
        prev = getattr(self, '_last_pack_w', -1)
        if not force and abs(w - prev) < 8:
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
        # Keep More; remove only chip buttons (immediate — deleteLater left ghosts overlapping).
        to_kill = []
        for i in range(self._flow.count() - 1, -1, -1):
            item = self._flow.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None or w is self._view_all:
                continue
            self._flow.removeWidget(w)
            to_kill.append(w)
        for w in to_kill:
            try:
                w.hide()
                w.setParent(None)
            except Exception:
                pass
            try:
                w.deleteLater()
            except Exception:
                pass
        # Drop leftover spacers/stretches except the trailing stretch before More
        while self._flow.count() > 1:
            item = self._flow.takeAt(0)
            if item is None:
                break
        self._chips.clear()
        labels = ['All'] + [n for n in (names or []) if n and n != 'All']
        self._all_labels = list(labels)
        try:
            avail = max(160, int(self.width()) - 100)
        except Exception:
            avail = 360
        budget = max(100, avail - 12)
        shown = []
        used = 0
        spacing = 10
        for name in labels:
            try:
                fm = self.fontMetrics()
                elide_px = 96 if avail < 320 else (110 if avail < 420 else (120 if len(name) > 10 else 132))
                text = fm.elidedText(name, Qt.ElideRight, elide_px)
                chip_w = min(elide_px + 20, max(56, fm.horizontalAdvance(text) + 28))
            except Exception:
                text = name
                chip_w = 88
            need = chip_w + (spacing if shown else 0)
            if shown and used + need > budget and len(shown) >= 2:
                break
            shown.append((name, text, chip_w))
            used += need
            cap = 2 if avail < 300 else (3 if avail < 420 else 4)
            if len(shown) >= cap:
                break
        insert_at = 0
        for name, text, chip_w in shown:
            b = QPushButton()
            b.setObjectName('posCatChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(self.CHIP_PILL_H)
            b.setToolTip(name)
            b.setText(text)
            b.setFixedWidth(chip_w)
            b.clicked.connect(lambda _=False, n=name: self.select(n, emit=True))
            self._flow.insertWidget(insert_at, b, 0)
            insert_at += 1
            self._chips[name] = b
        if self._selected not in self._chips and self._selected and self._selected != 'All':
            b = QPushButton()
            b.setObjectName('posCatChip')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(self.CHIP_PILL_H)
            b.setToolTip(self._selected)
            try:
                fm = b.fontMetrics()
                b.setText(fm.elidedText(self._selected, Qt.ElideRight, 96))
                b.setFixedWidth(110)
            except Exception:
                b.setText(self._selected)
            b.clicked.connect(lambda _=False, n=self._selected: self.select(n, emit=True))
            self._flow.insertWidget(insert_at, b, 0)
            self._chips[self._selected] = b
        # Keep More on the right with a gap, not overlapping chips.
        self._flow.insertStretch(max(0, self._flow.count() - 1), 1)
        overflow = max(0, len(labels) - len(shown))
        self._view_all.setVisible(True)
        if overflow:
            self._view_all.setText('More ▾')
            self._view_all.setToolTip(f'{overflow} more categories — open full list')
        else:
            self._view_all.setText('View All')
            self._view_all.setToolTip('Browse all categories')
        self._last_pack_w = avail
        keep = self._selected if (
            self._selected in self._chips or self._selected == 'All') else 'All'
        self.select(keep, emit=False)
        self.refresh_theme()

    def select(self, name: str, emit=True):
        name = name or 'All'
        if str(name).lower().startswith('all'):
            name = 'All'
        self._selected = name
        # Overflow pick: pin the chosen name as a chip so it is not dropped to All.
        if (name != 'All' and name not in self._chips
                and not getattr(self, '_packing', False)):
            self._packing = True
            try:
                labels = [n for n in (getattr(self, '_all_labels', None) or [])
                          if n and n != 'All']
                if name not in labels:
                    labels.append(name)
                self.set_categories(labels)
            finally:
                self._packing = False
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
                    f"border:none;border-radius:17px;padding:0 14px;margin:0;"
                    f"min-height:{self.CHIP_PILL_H}px;max-height:{self.CHIP_PILL_H}px;"
                    f"font-size:11px;font-weight:800;}}")
            else:
                b.setStyleSheet(
                    f"QPushButton#posCatChip{{background:{C['card2']};color:{C['text2']};"
                    f"border:1px solid {C['border']};border-radius:17px;padding:0 14px;margin:0;"
                    f"min-height:{self.CHIP_PILL_H}px;max-height:{self.CHIP_PILL_H}px;"
                    f"font-size:11px;font-weight:700;}}"
                    f"QPushButton#posCatChip:hover{{border-color:{C['gold']};color:{C['text']};}}")

    def refresh_theme(self):
        self._view_all.setStyleSheet(
            f"QPushButton#posCatViewAll{{color:{C['text2']};font-size:10px;font-weight:700;"
            f"background:{C['card2']};border:1px solid {C['border']};border-radius:17px;"
            f"padding:0 12px;margin:0;min-width:72px;"
            f"min-height:{self.CHIP_PILL_H}px;max-height:{self.CHIP_PILL_H}px;}}"
            f"QPushButton#posCatViewAll:hover{{border-color:{C['gold']};color:{C['text']};}}")
        self.setStyleSheet(
            f"QWidget#posCatChipBar,QWidget#posCatChipWrap{{background:transparent;}}")
        self._paint_chips()


# ── Sale type radios ──────────────────────────────────────────────────────────

class SaleTypeGroup(QWidget):
    """Paid now / On account / Part pay / Quote — maps onto existing payment paths."""
    saleTypeChanged = pyqtSignal(str)  # cash | credit | part | quotation

    _OPTIONS = (
        ('cash', 'Paid now'),
        ('credit', 'On account'),
        ('part', 'Part pay'),
        ('quotation', 'Quote only'),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('posSaleType')
        self._horizontal = False
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(8, 6, 8, 6)
        self._root.setSpacing(3)
        self._hdr = QLabel('Sale options')
        self._hdr.setObjectName('posSaleTypeHdr')
        self._hdr.setToolTip(
            'Sale workflow (separate from tender tiles):\n'
            'Paid now · On account (credit) · Part pay · Quote only')
        self._root.addWidget(self._hdr)
        self._radio_host = QWidget(self)
        self._radio_host.setObjectName('posSaleTypeRadios')
        self._radio_lay = QVBoxLayout(self._radio_host)
        self._radio_lay.setContentsMargins(0, 0, 0, 0)
        self._radio_lay.setSpacing(3)
        self._root.addWidget(self._radio_host)
        self._group = QButtonGroup(self)
        self._radios = {}
        for key, label in self._OPTIONS:
            rb = QRadioButton(label)
            rb.setObjectName('posSaleTypeRadio')
            rb.setToolTip({
                'cash': 'Collect full payment now (Cash / M-Pesa / Card / Bank / Split)',
                'credit': 'Credit Sale — charge to customer account (pay later)',
                'part': (
                    'Part Payment — collect some now (one method or Split), '
                    'remainder on the customer account'
                ),
                'quotation': 'Save / print a quote only — no stock or payment',
            }.get(key, ''))
            self._group.addButton(rb)
            self._radios[key] = rb
            self._radio_lay.addWidget(rb)
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

    def _detach_radio_layout(self):
        while self._radio_lay.count():
            self._radio_lay.takeAt(0)
        old = self._radio_host.layout()
        if old is not None:
            sink = QWidget()
            sink.setAttribute(Qt.WA_DontShowOnScreen, True)
            sink.hide()
            sink.setLayout(old)
            sink.deleteLater()

    def set_grid(self, cols: int = 2):
        """Two-up radios — full rail width, so no option is ever clipped.

        A single row needs ~360px of label text and a single column starves the
        Amount Paid field beside it; 2x2 fits a ~400px rail comfortably.
        """
        if getattr(self, '_grid_cols', None) == int(cols):
            return
        self._grid_cols = int(cols)
        self._horizontal = None  # neither pure v nor pure h any more
        self._detach_radio_layout()
        self._root.setContentsMargins(10, 8, 10, 10)
        self._root.setSpacing(8)
        self._radio_lay = QGridLayout(self._radio_host)
        self._radio_lay.setContentsMargins(0, 2, 0, 2)
        self._radio_lay.setHorizontalSpacing(10)
        self._radio_lay.setVerticalSpacing(8)
        for i, (key, _label) in enumerate(self._OPTIONS):
            self._radio_lay.addWidget(self._radios[key], i // cols, i % cols)
        for c in range(int(cols)):
            self._radio_lay.setColumnStretch(c, 1)
        self.refresh_theme()

    def set_horizontal(self, horizontal: bool = True):
        """Compact single-row radios for Classic / Explorer rails."""
        horizontal = bool(horizontal)
        if horizontal == self._horizontal:
            return
        self._horizontal = horizontal
        self._grid_cols = None
        self._detach_radio_layout()
        if horizontal:
            self._root.setContentsMargins(6, 4, 6, 4)
            self._root.setSpacing(2)
            self._radio_lay = QHBoxLayout(self._radio_host)
            self._radio_lay.setContentsMargins(0, 0, 0, 0)
            self._radio_lay.setSpacing(8)
            for key, _label in self._OPTIONS:
                self._radio_lay.addWidget(self._radios[key], 1)
        else:
            self._root.setContentsMargins(8, 6, 8, 6)
            self._root.setSpacing(3)
            self._radio_lay = QVBoxLayout(self._radio_host)
            self._radio_lay.setContentsMargins(0, 0, 0, 0)
            self._radio_lay.setSpacing(3)
            for key, _label in self._OPTIONS:
                self._radio_lay.addWidget(self._radios[key])
        self.refresh_theme()

    def refresh_theme(self):
        fs = 11 if self._horizontal else 12
        self.setStyleSheet(
            f"QWidget#posSaleType{{background:{C['card2']};border:1px solid {C['border']};"
            f"border-radius:{RADIUS['md']}px;}}"
            f"QWidget#posSaleTypeRadios{{background:transparent;border:none;}}"
            f"QLabel#posSaleTypeHdr{{color:{C['text2']};font-size:11px;font-weight:800;"
            f"letter-spacing:0.4px;background:transparent;}}"
            f"QRadioButton#posSaleTypeRadio{{color:{C['text']};font-size:{fs}px;font-weight:700;"
            f"spacing:6px;background:transparent;min-height:{28 if not self._horizontal else 22}px;}}"
            f"QRadioButton#posSaleTypeRadio::indicator{{width:14px;height:14px;}}"
            f"QRadioButton#posSaleTypeRadio::indicator:checked{{"
            f"background:{C['gold']};border:2px solid {C['gold']};border-radius:8px;}}"
            f"QRadioButton#posSaleTypeRadio::indicator:unchecked{{"
            f"background:transparent;border:2px solid {C['border2']};border-radius:8px;}}")


# ── Quick action tile ─────────────────────────────────────────────────────────

class QuickActionTile(QPushButton):
    """Labeled tile in the Pro rail's Sale Actions pad — one click, never buried."""

    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(label, parent)
        self._accent = accent
        self.setObjectName('posQuickTile')
        self.setCursor(Qt.PointingHandCursor)
        # Grow with leftover rail height; cap so they stay buttons, not banners
        self.setMinimumHeight(40)
        self.setMaximumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.refresh_theme()

    def refresh_theme(self):
        a = self._accent
        self.setStyleSheet(
            f"QPushButton#posQuickTile{{background:{C['card2']};color:{C['text2']};"
            f"border:1px solid {C['border']};border-radius:8px;"
            f"font-size:11px;font-weight:700;padding:3px 4px;text-align:center;}}"
            f"QPushButton#posQuickTile:hover{{border-color:{a};color:{a};"
            f"background:{qss_alpha(a, 0.10)};}}"
            f"QPushButton#posQuickTile:pressed{{background:{qss_alpha(a, 0.18)};}}"
            f"QPushButton#posQuickTile:disabled{{color:{C['muted']};"
            f"background:{C['panel']};border-color:{C['border']};}}")


_QUICK_ACTION_TIPS = {
    '_hold_sale': 'Park the current cart (in-memory; cleared on exit)',
    '_resume_held': 'Restore the held cart',
    '_suspend_sale': 'Suspend this sale to the register queue',
    '_clear': 'Clear every line from the cart',
    '_void_sale': 'Void a completed sale (reason + Super-Admin PIN)',
    '_open_return_sale': 'Return items from a completed receipt (restock + refund)',
    '_reprint_receipt': 'Reprint a completed receipt',
    '_preview': 'Preview / print the current sale',
    '_open_recent_sales': 'Browse recent sales for this business day',
    '_focus_notes': 'Add a note to this sale',
    '_toggle_cart_maximized': 'Enlarge the cart to review and edit many lines',
    '_toggle_focus_mode': 'Maximize Point of Sale — hide sidebar and top bar (Esc to exit)',
}


def ensure_pro_widgets(tab) -> None:
    """Create Pro-only accessory widgets once (idempotent)."""
    if not _alive(getattr(tab, '_cat_chips', None)):
        chips = CategoryChipBar()
        chips.categorySelected.connect(lambda n: _on_chip_category(tab, n))
        chips.viewAllClicked.connect(lambda: _on_view_all_categories(tab))
        tab._cat_chips = chips

    if not _alive(getattr(tab, '_sale_type', None)):
        st = SaleTypeGroup(tab)
        st.hide()
        try:
            st.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
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
        wrap = QWidget(tab)
        wrap.hide()
        try:
            wrap.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
        wrap.setObjectName('posQuickActions')
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        gl = QGridLayout(wrap)
        gl.setContentsMargins(0, 2, 0, 0)
        gl.setHorizontalSpacing(8)
        gl.setVerticalSpacing(8)
        info = C.get('info', '#3B82F6')
        warn = C.get('warn', C['gold'])
        # Every secondary POS action the shared footer owns is mirrored here, so
        # Checkout Pro hides the cramped footer strip without burying anything.
        specs = [
            ('Hold Sale', C['gold'], '_hold_sale'),
            ('Resume', C['gold'], '_resume_held'),
            ('Suspend Sale', warn, '_suspend_sale'),
            ('Clear Cart', C['err'], '_clear'),
            ('Void Sale', C['err'], '_void_sale'),
            ('Return / Exchange', warn, '_open_return_sale'),
            ('Reprint', info, '_reprint_receipt'),
            ('Print Preview', info, '_preview'),
            ('Recent Sales', info, '_open_recent_sales'),
            ('Notes', C['text2'], '_focus_notes'),
            ('Review Cart', C['text2'], '_toggle_cart_maximized'),
            ('Focus Mode', C['text2'], '_toggle_focus_mode'),
        ]
        tiles = {}
        for i, (label, accent, handler) in enumerate(specs):
            t = QuickActionTile(label, accent)
            t.setToolTip(_QUICK_ACTION_TIPS.get(handler, label))
            t.clicked.connect(lambda _=False, h=handler: _call_tab(tab, h))
            gl.addWidget(t, i // 3, i % 3)
            tiles[handler] = t
        for c in range(3):
            gl.setColumnStretch(c, 1)
        for r in range(4):
            gl.setRowStretch(r, 1)
        tab._quick_action_tiles = tiles
        tab._quick_actions = wrap

    if not _alive(getattr(tab, '_quick_actions_cap', None)):
        cap = QLabel('Sale Actions')
        cap.setObjectName('posQuickActionsCap')
        tab._quick_actions_cap = cap

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
        # Built from CartLineRow's own column spec — captions cannot drift off
        # their columns the way the old hand-tuned stretch factors did.
        from desktop.utils.pos_components import build_cart_column_header
        tab._cart_col_hdr = build_cart_column_header()


def _call_tab(tab, name: str):
    fn = getattr(tab, name, None)
    if callable(fn):
        fn()


def _on_chip_category(tab, name: str):
    cat = getattr(tab, '_cat', None)
    target = 'All Categories' if (not name or name == 'All') else name
    idx = -1
    if cat is not None:
        idx = cat.findText(target)
        if idx < 0 and name not in ('All', '', None):
            for i in range(cat.count()):
                item = cat.itemText(i)
                if item.lower() == str(name).lower() or item.lower().endswith(
                        str(name).lower()):
                    idx = i
                    break
                # "A — Antibiotics" vs "Antibiotics"
                if '—' in item and item.split('—', 1)[-1].strip().lower() == str(name).lower():
                    idx = i
                    break
                if '—' in str(name) and str(name).split('—', 1)[-1].strip().lower() == item.lower():
                    idx = i
                    break
        if idx >= 0:
            cat.blockSignals(True)
            try:
                cat.setCurrentIndex(idx)
            finally:
                cat.blockSignals(False)
        elif target == 'All Categories':
            cat.blockSignals(True)
            try:
                cat.setCurrentIndex(0)
            finally:
                cat.blockSignals(False)
    try:
        tab._apply_product_filter(False)
    except Exception:
        try:
            tab._filter()
        except Exception:
            pass


def _on_view_all_categories(tab):
    """More ▾ — pick any category from a clickable list. View All — all products."""
    chips = getattr(tab, '_cat_chips', None)
    labels = []
    if chips is not None:
        labels = [n for n in (getattr(chips, '_all_labels', None) or []) if n]
    shown = set((getattr(chips, '_chips', None) or {}).keys()) if chips is not None else set()
    overflow = [n for n in labels if n != 'All' and n not in shown]
    if overflow and chips is not None and _alive(getattr(chips, '_view_all', None)):
        _show_category_pick_popup(tab, chips, labels)
        return
    cat = getattr(tab, '_cat', None)
    if cat is not None:
        cat.blockSignals(True)
        try:
            cat.setCurrentIndex(0)
        finally:
            cat.blockSignals(False)
    if chips is not None:
        chips.select('All', emit=False)
    try:
        tab._apply_product_filter(False)
    except Exception:
        try:
            tab._filter()
        except Exception:
            pass


def _show_category_pick_popup(tab, chips, labels):
    """Single-column popup list — not QMenu (global QWidget QSS + auto-columns
    made items look like dead labels and ate clicks)."""
    btn = chips._view_all
    names = ['All'] + [n for n in labels if n and n != 'All']
    popup = QFrame(chips.window() if chips.window() else chips, Qt.Popup)
    popup.setObjectName('posCatOverflow')
    popup.setAttribute(Qt.WA_StyledBackground, True)
    popup.setAutoFillBackground(True)
    popup.setAttribute(Qt.WA_TransparentForMouseEvents, False)
    bg = C.get('card') or '#121C30'
    fg = C.get('text') or '#F5F7FA'
    hover = C.get('hover') or '#162A44'
    sel = C.get('selected') or hover
    gold = C.get('gold') or '#F2A800'
    border = C.get('border2') or C.get('border') or '#18283E'
    popup.setStyleSheet(
        f"QFrame#posCatOverflow{{background:{bg};color:{fg};"
        f"border:1px solid {border};border-radius:8px;}}"
        f"QListWidget#posCatOverflowList,QListWidget#posCatOverflowList QWidget{{"
        f"background:{bg};color:{fg};border:none;outline:0;}}"
        f"QListWidget#posCatOverflowList{{padding:4px;}}"
        f"QListWidget#posCatOverflowList::item{{background:{bg};color:{fg};"
        f"padding:8px 14px;min-height:32px;border-radius:6px;}}"
        f"QListWidget#posCatOverflowList::item:hover{{background:{hover};color:{fg};}}"
        f"QListWidget#posCatOverflowList::item:selected{{background:{sel};color:{gold};}}"
    )
    lay = QVBoxLayout(popup)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.setSpacing(0)
    lst = QListWidget(popup)
    lst.setObjectName('posCatOverflowList')
    lst.setAttribute(Qt.WA_StyledBackground, True)
    lst.setAutoFillBackground(True)
    lst.setAttribute(Qt.WA_TransparentForMouseEvents, False)
    lst.setMouseTracking(True)
    lst.setFocusPolicy(Qt.StrongFocus)
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lst.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    lst.setSelectionMode(QAbstractItemView.SingleSelection)
    lst.setWrapping(False)
    try:
        lst.setFlow(QListWidget.TopToBottom)
        lst.setViewMode(QListWidget.ListMode)
    except Exception:
        pass
    try:
        vp = lst.viewport()
        vp.setAutoFillBackground(True)
        vp.setAttribute(Qt.WA_StyledBackground, True)
        vp.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        vp.setStyleSheet(f"background:{bg};color:{fg};")
    except Exception:
        pass
    current = chips.current() if chips is not None else 'All'
    for n in names:
        label = 'All categories' if n == 'All' else n
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, n)
        lst.addItem(item)
        if n == current or (n == 'All' and str(current).lower().startswith('all')):
            lst.setCurrentItem(item)
    lay.addWidget(lst)

    picked = {'done': False}

    def _pick(item):
        if picked['done'] or item is None:
            return
        picked['done'] = True
        name = item.data(Qt.UserRole) or item.text() or 'All'
        popup.close()
        popup.deleteLater()
        chips.select(name, emit=True)

    lst.itemClicked.connect(_pick)
    lst.itemActivated.connect(_pick)

    fm = lst.fontMetrics()
    w = 240
    for n in names:
        label = 'All categories' if n == 'All' else n
        w = max(w, fm.horizontalAdvance(label) + 48)
    row_h = lst.sizeHintForRow(0)
    if row_h < 16:
        row_h = 36
    h = min(360, max(48, row_h * min(len(names), 12) + 16))
    popup.setFixedSize(min(420, w), h)
    pos = btn.mapToGlobal(btn.rect().bottomLeft())
    popup.move(pos)
    popup.show()
    lst.setFocus()
    tab._cat_overflow_popup = popup


def _charge_label_for_sale_type(key: str) -> str:
    return {
        'credit': 'Complete Credit Sale  (F9)',
        'part': 'Complete Part Payment  (F9)',
        'quotation': 'Save Quotation  (F9)',
    }.get(key, 'Complete Sale  (F9)')


def _on_sale_type(tab, key: str):
    tab._pro_sale_type = key
    pay = getattr(tab, '_pay', None)
    if key == 'credit':
        try:
            tab._select_pay_method('Credit Sale')
        except Exception:
            pass
    elif key == 'part':
        # Keep Cash / M-Pesa / Split tiles so cashiers can split tenders
        # and still leave a debt for the remainder.
        try:
            current = pay.currentText() if pay is not None else 'Cash'
            if current in ('Credit Sale', 'Credit Account', 'Part Payment'):
                tab._select_pay_method('Cash')
            elif hasattr(tab, '_on_payment_changed'):
                tab._on_payment_changed(current)
            if hasattr(tab, '_prepare_part_pay_amounts'):
                tab._prepare_part_pay_amounts()
        except Exception:
            pass
    elif key == 'quotation':
        pass
    else:
        # Restore tender method if stuck on credit / part payment
        try:
            if pay is not None and pay.currentText() in (
                'Credit Sale', 'Credit Account', 'Part Payment',
            ):
                tab._select_pay_method('Cash')
        except Exception:
            pass
    charge = getattr(tab, '_charge_btn', None)
    if charge is not None:
        charge.setText(_charge_label_for_sale_type(key))


def sync_sale_type_from_method(tab, method: str) -> None:
    """Keep Sale options radios aligned when tender tiles / combo change."""
    st = getattr(tab, '_sale_type', None)
    if not _alive(st):
        return
    if method in ('Credit Sale', 'Credit Account'):
        want = 'credit'
    elif method == 'Part Payment':
        want = 'part'
    else:
        # Do not clobber Quote only when cashier is only changing tender
        if getattr(tab, '_pro_sale_type', 'cash') == 'quotation':
            return
        # Tender tiles (Cash / Split / M-Pesa) stay under Part pay
        if getattr(tab, '_pro_sale_type', 'cash') == 'part':
            want = 'part'
        else:
            want = 'cash'
    if st.current() != want:
        st.set_current(want, emit=False)
    tab._pro_sale_type = want
    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        charge.setText(_charge_label_for_sale_type(want))


def _on_new_customer(tab):
    card = getattr(tab, '_cust_card', None)
    if card is not None and hasattr(card, '_pick_create'):
        # Open create dialog without outer picker — never use a QDialog
        # dummy (Windows can still flash an empty framed HWND).
        card._pick_create(None)
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


NARROW_RAIL = 340
NARROW_PRODUCT = 400
NARROW_SALE = 480


def sync_pro_sale_panel(tab) -> None:
    """Let the center Current Sale column shrink with column splitters — scroll/compact, don't clip."""
    from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO, normalize_layout_id

    if normalize_layout_id(getattr(tab, '_checkout_layout', '')) != LAYOUT_CHECKOUT_PRO:
        return
    sale = getattr(tab, '_sale_panel', None)
    if not _alive(sale):
        return
    sw = int(sale.width() or 0)
    narrow = sw > 0 and sw < NARROW_SALE
    try:
        from PyQt5.QtWidgets import QSizePolicy as _SP
        sale.setMaximumWidth(16777215)
        pol = sale.sizePolicy()
        pol.setHorizontalPolicy(_SP.Ignored)
        pol.setVerticalPolicy(_SP.Preferred)
        sale.setSizePolicy(pol)
        for attr in ('_sale_cart_scroll', '_sale_summary_wrap', '_cart_hdr', '_cart_splitter'):
            w = getattr(tab, attr, None)
            if not _alive(w):
                continue
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)
            p = w.sizePolicy()
            p.setHorizontalPolicy(_SP.Ignored)
            w.setSizePolicy(p)
    except Exception:
        pass
    clist = getattr(tab, '_cart_list', None)
    if _alive(clist):
        try:
            if hasattr(clist, 'set_compact_table'):
                clist.set_compact_table(narrow)
            if hasattr(clist, 'sync_width_fit'):
                clist.sync_width_fit(sw)
        except Exception:
            pass
    disc = getattr(tab, '_disc', None)
    if _alive(disc):
        try:
            disc.setFixedWidth(100 if narrow else 150)
        except Exception:
            pass


def sync_pro_square_layout(tab) -> None:
    """Repack Checkout Pro chrome on square / narrow shells (1024²–1280²)."""
    from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO, normalize_layout_id

    if normalize_layout_id(getattr(tab, '_checkout_layout', '')) != LAYOUT_CHECKOUT_PRO:
        return

    actions = getattr(tab, '_actions_panel', None)
    product = getattr(tab, '_product_panel', None)
    rail_w = int(actions.width()) if _alive(actions) else 0
    prod_w = int(product.width()) if _alive(product) else 0
    narrow_rail = rail_w > 0 and rail_w < NARROW_RAIL
    narrow_prod = prod_w > 0 and prod_w < NARROW_PRODUCT

    pay_seg = getattr(tab, '_pay_seg', None)
    if _alive(pay_seg):
        try:
            if hasattr(pay_seg, 'set_row_layout'):
                pay_seg.set_row_layout(not narrow_rail)
            if hasattr(pay_seg, 'set_compact'):
                pay_seg.set_compact(True)
        except Exception:
            pass

    new_btn = getattr(tab, '_new_cust_btn', None)
    if _alive(new_btn):
        try:
            if narrow_rail:
                new_btn.setText('+ New')
                new_btn.setFixedWidth(68)
            else:
                new_btn.setText('+ New Customer')
                new_btn.setMaximumWidth(16777215)
        except Exception:
            pass

    layout_combo = getattr(tab, '_layout_combo', None)
    if _alive(layout_combo):
        try:
            layout_combo.setFixedWidth(112 if narrow_prod else 150)
        except Exception:
            pass

    search_bar = getattr(tab, '_search_bar', None)
    search_row_lay = search_bar.layout() if _alive(search_bar) else None
    if search_row_lay is not None:
        try:
            if narrow_prod:
                search_row_lay.setContentsMargins(8, 8, 8, 8)
                search_row_lay.setSpacing(6)
            else:
                search_row_lay.setContentsMargins(12, 10, 12, 10)
                search_row_lay.setSpacing(8)
        except Exception:
            pass

    pay_card = getattr(tab, '_pro_pay_card', None)
    pcl = getattr(tab, '_pro_pay_card_lay', None)
    if _alive(pay_card) and pcl is not None:
        try:
            inset = 6 if narrow_rail else 10
            pcl.setContentsMargins(inset, 8, inset, 8)
        except Exception:
            pass

    paid = getattr(tab, '_paid', None)
    if _alive(paid):
        try:
            paid.setMinimumHeight(44 if narrow_rail else 48)
        except Exception:
            pass

    chips = getattr(tab, '_cat_chips', None)
    if _alive(chips) and hasattr(chips, 'repack_for_width'):
        try:
            chips.repack_for_width(force=True)
        except Exception:
            pass

    qa = getattr(tab, '_quick_actions', None)
    if _alive(qa):
        try:
            from PyQt5.QtWidgets import QSizePolicy as _SP
            qa.setSizePolicy(_SP.Expanding, _SP.Preferred)
            gl = qa.layout()
            if gl is not None:
                cols = 2 if narrow_rail else 3
                tiles = list(getattr(tab, '_quick_action_tiles', {}) or {})
                if tiles:
                    order = [
                        '_hold_sale', '_resume_held', '_suspend_sale', '_clear',
                        '_void_sale', '_open_return_sale', '_reprint_receipt', '_preview',
                        '_open_recent_sales', '_focus_notes', '_toggle_cart_maximized',
                        '_toggle_focus_mode',
                    ]
                    widgets = [tiles[k] for k in order if k in tiles and _alive(tiles[k])]
                    while gl.count():
                        gl.takeAt(0)
                    for i, t in enumerate(widgets):
                        t.setMinimumWidth(0)
                        t.setSizePolicy(_SP.Expanding, _SP.Fixed)
                        gl.addWidget(t, i // cols, i % cols)
                    for c in range(cols):
                        gl.setColumnStretch(c, 1)
        except Exception:
            pass

    body = getattr(tab, '_actions_body', None)
    scroll = getattr(tab, '_actions_body_scroll', None)
    for w in (body, scroll, pay_card):
        if not _alive(w):
            continue
        try:
            from PyQt5.QtWidgets import QSizePolicy as _SP
            pol = w.sizePolicy()
            pol.setHorizontalPolicy(_SP.Ignored if narrow_rail else _SP.Preferred)
            w.setSizePolicy(pol)
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)
        except Exception:
            pass
    if _alive(body):
        try:
            for ch in body.findChildren(QWidget):
                if _alive(ch):
                    ch.setMinimumWidth(0)
        except Exception:
            pass

    sync_pro_sale_panel(tab)


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
    # Layout switcher stays visible so cashiers can leave Checkout Pro without Settings
    layout_combo = getattr(tab, '_layout_combo', None)
    if _alive(layout_combo):
        layout_combo.show()

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
            try:
                from PyQt5.QtWidgets import QSizePolicy as _SP
                if _alive(search_bar):
                    search_bar.setSizePolicy(_SP.Expanding, _SP.Fixed)
                chips.setSizePolicy(_SP.Expanding, _SP.Fixed)
                chips.setFixedHeight(CategoryChipBar.CHIP_BAR_H)
            except Exception:
                pass
            try:
                pl.setSpacing(10)
            except Exception:
                pass
            chips.show()
            try:
                chips.raise_()
            except Exception:
                pass
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
        # The long form clipped to "Search or sca..." once the Layout combo took
        # its fixed 168px out of a ~410px column. Full text moves to the tooltip.
        search.setPlaceholderText('Search or scan…')
        search.setToolTip('Search or scan barcode, product name or SKU')
    if _alive(layout_combo):
        layout_combo.setFixedWidth(150)
        layout_combo.setToolTip(
            'Checkout layout — Retail Classic / Product Explorer / Checkout Pro.\n'
            'Also available in Settings → Jump: Checkout')
    search_row_lay = search_bar.layout() if _alive(search_bar) else None
    if search_row_lay is not None:
        search_row_lay.setContentsMargins(12, 10, 12, 10)
        search_row_lay.setSpacing(8)

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
        review = bool(getattr(tab, '_cart_maximized', False))
        if hasattr(clist, 'set_cashier_viewport'):
            from desktop.utils.pos_components import CART_CASHIER_ROWS
            clist.set_cashier_viewport(0 if review else CART_CASHIER_ROWS)
        if hasattr(clist, 'set_expanded'):
            # Review expands further; otherwise min 5 rows, grows with splitter.
            clist.set_expanded(review)
        # Prefer cart_list as the sole scroller — hide outer wrapper scroll host padding
        col_hdr = tab._cart_col_hdr
        if _alive(col_hdr) and hasattr(clist, 'set_column_header'):
            clist.set_column_header(col_hdr)
        col_hdr.refresh_theme = lambda: _style_col_hdr(col_hdr)  # type: ignore
        _style_col_hdr(col_hdr)

    # Cart stays a 5-row minimum viewport; Order Summary sits under it.
    # Leftover Current Sale height goes INTO the cart↔summary splitter (drag to
    # grow the list and shrink summary / give room for more line items).
    try:
        sale = getattr(tab, '_sale_panel', None)
        cart_scroll = getattr(tab, '_sale_cart_scroll', None)
        sl = sale.layout() if _alive(sale) else None
        if sl is not None and _alive(cart_scroll):
            spacer = getattr(tab, '_sale_bottom_stretch', None)
            if _alive(spacer):
                try:
                    sl.removeWidget(spacer)
                    from desktop.utils.quiet_ui import safe_detach
                    safe_detach(spacer)
                except Exception:
                    pass
            try:
                cart_scroll.setMaximumHeight(16777215)
                cart_scroll.setMinimumHeight(0)
            except Exception:
                pass
            # Drop waste stretch below the stack — splitter owns leftover height.
            try:
                for i in range(sl.count() - 1, -1, -1):
                    item = sl.itemAt(i)
                    if item is not None and item.spacerItem() is not None:
                        sl.takeAt(i)
                tab._sale_tail_stretch_ok = False
            except Exception:
                pass
            try:
                cart_sp = getattr(tab, '_cart_splitter', None)
                if _alive(cart_sp):
                    for i in range(sl.count()):
                        item = sl.itemAt(i)
                        if item is not None and item.widget() is cart_sp:
                            sl.setStretch(i, 1)
                            break
            except Exception:
                pass
    except Exception:
        pass

    summary = getattr(tab, '_summary', None)
    if _alive(summary) and hasattr(summary, 'set_pro_chrome'):
        summary.set_pro_chrome(True)
    # Keep cart-level Discount editable + clearly labeled (never read-only total)
    disc = getattr(tab, '_disc', None)
    disc_lbl = getattr(tab, '_disc_lbl', None)
    if _alive(disc):
        try:
            disc.setReadOnly(False)
            disc.setMinimumWidth(120)
            disc.setFixedWidth(150)
            disc.show()
        except Exception:
            pass
    if _alive(disc_lbl):
        try:
            disc_lbl.setText('Discount (KES)')
            disc_lbl.setToolTip(
                'Cart-level discount for the whole sale. '
                'Per-item Disc is on each cart line.')
            disc_lbl.show()
        except Exception:
            pass

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

    # Sale note: Pro uses the Notes tile (not a permanent field in the rail).
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
            bl.setContentsMargins(12, 8, 12, 10)
            bl.setSpacing(10)
            # Insert amount/change stack, sale options, note and action pad
            _ensure_body_pro_sections(tab, bl)

    # Footer: only Complete Sale — payment/utility stack scrolls in the body above.
    for name in (
        '_clr_btn', '_hold_btn', '_resume_btn', '_prv_btn', '_reprint_btn',
        '_void_btn', '_returns_help_btn',
    ):
        b = getattr(tab, name, None)
        if _alive(b):
            b.hide()
    # Keep Payment Method + Sale Actions in the scrollable body (not the foot).
    foot = getattr(tab, '_checkout_foot', None)
    if _alive(foot):
        fl = foot.layout()
        body = getattr(tab, '_actions_body', None)
        bl = body.layout() if _alive(body) else None
        if fl is not None and bl is not None:
            for name in ('_pay_hdr', '_pay_seg', '_quick_actions', '_quick_actions_cap'):
                w = getattr(tab, name, None)
                if not _alive(w):
                    continue
                try:
                    if w.parent() is foot:
                        fl.removeWidget(w)
                        bl.addWidget(w)
                        w.show()
                except Exception:
                    pass
    apply_checkout_foot_rhythm(tab, pro_primary_only=True)
    pin_checkout_totals(tab)
    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        charge.setText(_charge_label_for_sale_type(
            getattr(tab, '_pro_sale_type', 'cash')))

    style_quiet_secondary_actions(tab)

    # Mirror permission / availability from the shared footer buttons
    sync_quick_action_state(tab)

    qa = getattr(tab, '_quick_actions', None)
    if _alive(qa):
        for t in qa.findChildren(QuickActionTile):
            t.refresh_theme()
    st = getattr(tab, '_sale_type', None)
    if _alive(st):
        st.refresh_theme()
    if _alive(chips):
        chips.refresh_theme()

    # 3.0.35: cart stack must paint after Pro chrome (DontShowOnScreen park).
    try:
        from desktop.pos.layouts.splitters import install_cart, reveal_cart_stack
        reveal_cart_stack(tab)
        install_cart(tab, 'checkout_pro')
        pin_checkout_totals(tab)
    except Exception:
        pass
    sync_pro_square_layout(tab)


def sync_quick_action_state(tab) -> None:
    """Keep Pro action tiles in step with the shared footer buttons they mirror.

    Void is permission-gated and Hold / Resume depend on cart state, so the
    tiles must not offer actions the underlying button would refuse.
    """
    tiles = getattr(tab, '_quick_action_tiles', None) or {}
    if not tiles:
        return
    void_tile = tiles.get('_void_sale')
    if _alive(void_tile):
        allowed = getattr(tab, '_void_btn', None) is not None
        void_tile.setEnabled(allowed)
        void_tile.setVisible(allowed)
    for handler, btn_name in (
        ('_resume_held', '_resume_btn'),
        ('_hold_sale', '_hold_btn'),
    ):
        tile = tiles.get(handler)
        btn = getattr(tab, btn_name, None)
        if _alive(tile) and _alive(btn):
            tile.setEnabled(btn.isEnabled())
            tip = btn.toolTip()
            if tip:
                tile.setToolTip(tip)


def _style_col_hdr(hdr: QWidget):
    hdr.setStyleSheet(
        f"QWidget#posCartColHdr{{background:transparent;border-bottom:1px solid {C['border']};}}"
        f"QLabel#posCartColLab{{color:{C['muted']};font-size:11px;font-weight:800;"
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
        pay_card = QFrame(tab)
        pay_card.hide()
        try:
            pay_card.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
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

    # Amount Paid + Change stack. When totals are foot-pinned, leave them in
    # the sticky foot (do not nest back into the scrolling Checkout card).
    row = getattr(tab, '_pro_amount_sale_row', None)
    amt_block = (
        getattr(tab, '_amount_paid_block', None)
        or getattr(tab, '_amount_block', None)
    )
    if getattr(tab, '_totals_pinned', False):
        if _alive(row):
            try:
                row.hide()
            except Exception:
                pass
    elif not _alive(row):
        row = QWidget(tab)
        row.hide()
        try:
            row.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
        row.setObjectName('posProAmountSaleRow')
        rl = QVBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        amt_block = (
            getattr(tab, '_amount_paid_block', None)
            or getattr(tab, '_amount_block', None)
        )
        if _alive(amt_block):
            rl.addWidget(amt_block)
        else:
            cap = getattr(tab, '_amount_paid_cap', None)
            if not _alive(cap):
                cap = QLabel('Amount Paid')
                cap.setObjectName('posAmountCap')
                tab._amount_paid_cap = cap
            style_section_header(cap, 'Amount Paid')
            rl.addWidget(cap)
            paid = getattr(tab, '_paid', None)
            if _alive(paid):
                rl.addWidget(paid)
        chg = getattr(tab, '_chg_frame', None)
        if _alive(chg):
            rl.addWidget(chg)
        tab._pro_amount_sale_row = row
    else:
        # Ensure Amount Paid stays styled when row already exists
        style_amount_paid(tab)

    # Sale options becomes its own full-width labeled block below the card
    st = getattr(tab, '_sale_type', None)
    if _alive(st):
        if hasattr(st, 'set_grid'):
            st.set_grid(2)
        elif hasattr(st, 'set_horizontal'):
            st.set_horizontal(False)
        st.refresh_theme()
        try:
            st.setAttribute(Qt.WA_DontShowOnScreen, False)
        except Exception:
            pass
        from desktop.utils.quiet_ui import safe_show
        safe_show(st)

    for i in range(bl.count() - 1, -1, -1):
        item = bl.itemAt(i)
        if item is not None and item.spacerItem() is not None:
            bl.takeAt(i)

    # Nest customer → amount/sale into pay_card. Payment Method stays in the
    # scrollable body with Customer / Amount / Sale Options / Notes / Actions so
    # the whole payment block scrolls together; only Complete Sale is foot-pinned.
    pcl = tab._pro_pay_card_lay
    cust = getattr(tab, '_cust_card', None)
    if _alive(cust) and cust.parent() is not pay_card:
        try:
            cust.setMaximumHeight(40)
        except Exception:
            pass
        pcl.insertWidget(1, cust)
    if _alive(row) and not getattr(tab, '_totals_pinned', False):
        if row.parent() is not pay_card:
            pcl.addWidget(row)
        row.show()
    elif _alive(row):
        try:
            row.hide()
        except Exception:
            pass
    pay_card.show()

    def _in_body(w):
        return _alive(w) and w in [
            bl.itemAt(i).widget() for i in range(bl.count())
            if bl.itemAt(i) and bl.itemAt(i).widget()]

    if not _in_body(pay_card):
        bl.insertWidget(0, pay_card)

    # Payment Method (header + tiles) stays in the body — immediately under Checkout.
    pay_seg = getattr(tab, '_pay_seg', None)
    if _alive(pay_hdr) and not _in_body(pay_hdr):
        idx = 1
        for i in range(bl.count()):
            item = bl.itemAt(i)
            if item is not None and item.widget() is pay_card:
                idx = i + 1
                break
        bl.insertWidget(idx, pay_hdr)
        pay_hdr.show()
    elif _alive(pay_hdr):
        pay_hdr.show()
    if _alive(pay_seg) and not _in_body(pay_seg):
        idx = 2
        for i in range(bl.count()):
            item = bl.itemAt(i)
            if item is not None and item.widget() is pay_hdr:
                idx = i + 1
                break
        bl.insertWidget(idx, pay_seg)
        pay_seg.show()
    elif _alive(pay_seg):
        pay_seg.show()

    # Sale options directly under the Checkout card (full rail width, 2x2)
    if _alive(st) and not _in_body(st):
        bl.addWidget(st)

    # Sale note is reachable via the Notes quick-action tile (keeps rail compact).
    note = getattr(tab, '_note', None)
    if _alive(note):
        note.setPlaceholderText('Note for this sale (optional)…')
        note.setMinimumHeight(40)
        note.setMaximumHeight(44)
        if not _in_body(note):
            bl.addWidget(note)
        note.hide()

    cap = getattr(tab, '_quick_actions_cap', None)
    if _alive(cap):
        style_section_header(cap, 'Sale Actions')
        cap.setContentsMargins(0, 4, 0, 2)
        if not _in_body(cap):
            bl.addWidget(cap)
        cap.show()

    qa = getattr(tab, '_quick_actions', None)
    if _alive(qa):
        qa.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if not _in_body(qa):
            bl.addWidget(qa)
        qa.show()
        qgl = qa.layout()
        if qgl is not None:
            try:
                qgl.setContentsMargins(0, 0, 0, 0)
                qgl.setHorizontalSpacing(8)
                qgl.setVerticalSpacing(8)
                if hasattr(qgl, 'setRowStretch'):
                    for r in range(4):
                        qgl.setRowStretch(r, 1)
                    for c in range(3):
                        qgl.setColumnStretch(c, 1)
            except Exception:
                pass
        for t in qa.findChildren(QuickActionTile):
            t.setMinimumHeight(40)
            t.setMaximumHeight(64)
            t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # Leftover rail height goes into Sale Actions (not an empty stretch).
    try:
        for i in range(bl.count() - 1, -1, -1):
            item = bl.itemAt(i)
            if item is not None and item.spacerItem() is not None:
                bl.takeAt(i)
        for i in range(bl.count()):
            item = bl.itemAt(i)
            w = item.widget() if item is not None else None
            bl.setStretch(i, 1 if w is qa else 0)
        body = getattr(tab, '_actions_body', None)
        if _alive(body):
            body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
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
            clist.set_density('table')
        if hasattr(clist, 'set_column_header'):
            clist.set_column_header(None)
        if hasattr(clist, 'set_expanded'):
            clist.set_expanded(bool(getattr(tab, '_cart_maximized', False)))

    # Restore sale panel stretch (cart fills, no bottom spacer). The cart/summary
    # split is owned by the draggable cart splitter's own per-layout minimums.
    try:
        sale = getattr(tab, '_sale_panel', None)
        spacer = getattr(tab, '_sale_bottom_stretch', None)
        sl = sale.layout() if _alive(sale) else None
        if sl is not None and _alive(spacer):
            sl.removeWidget(spacer)
            from desktop.utils.quiet_ui import safe_detach
            safe_detach(spacer)
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
        pay_card.hide()
        _stash(tab, pay_card)

    # Payment Method was pinned in the footer during Pro Chrome — move it
    # back into the checkout body for Classic/Explorer layouts.
    body = getattr(tab, '_actions_body', None)
    bl = body.layout() if _alive(body) else None
    pay_hdr = getattr(tab, '_pay_hdr', None)
    pay_seg = getattr(tab, '_pay_seg', None)
    if bl is not None:
        if _alive(pay_hdr):
            bl.insertWidget(0, pay_hdr)
            pay_hdr.show()
        if _alive(pay_seg):
            bl.insertWidget(1 if _alive(pay_hdr) else 0, pay_seg)
            pay_seg.show()

    cap = getattr(tab, '_quick_actions_cap', None)
    if _alive(cap):
        cap.hide()
        _stash(tab, cap)

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
