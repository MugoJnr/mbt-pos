"""Compose shared POS panels into Retail Classic / Product Explorer / Checkout Pro.

Panels are created once by SalesTab and reparented here — never duplicated.
Business logic stays on SalesTab; this module only arranges geometry.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLayout, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from desktop.pos.layout_ids import (
    LAYOUT_CHECKOUT_PRO,
    LAYOUT_PRODUCT_EXPLORER,
    LAYOUT_RETAIL_CLASSIC,
    normalize_layout_id,
)


def clear_layout(layout: QLayout | None) -> None:
    """Detach children without deleting them (safe for reparenting)."""
    if layout is None:
        return
    try:
        _ = layout.count()
    except RuntimeError:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            continue
        child = item.layout()
        if child is not None:
            clear_layout(child)


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        _ = obj.objectName()
        return True
    except RuntimeError:
        return False


def _replace_layout(host: QWidget) -> None:
    """Remove existing layout from host so a new one can be assigned."""
    if not _alive(host):
        return
    old = host.layout()
    if old is None:
        return
    clear_layout(old)
    QWidget().setLayout(old)


def _stash(tab, *widgets) -> None:
    """Park unused chrome under an invisible stash so Qt/sip won't GC it."""
    stash = getattr(tab, '_layout_stash', None)
    if not _alive(stash):
        stash = QWidget(tab)
        stash.hide()
        tab._layout_stash = stash
    for w in widgets:
        if _alive(w) and w is not stash:
            w.setParent(stash)
            w.hide()


def apply_layout_shell(tab, layout_id: str) -> str:
    """Rebuild ``tab._shell`` around the shared panels. Returns normalized id."""
    lid = normalize_layout_id(layout_id)
    shell = getattr(tab, '_shell', None)
    if shell is None:
        return lid

    # Exit review mode chrome before reparenting
    if getattr(tab, '_cart_maximized', False):
        tab._cart_maximized = False
        btn = getattr(tab, '_cart_max_btn', None)
        if _alive(btn):
            btn.setText('Review')
        hdr = getattr(tab, '_sale_hdr', None)
        if _alive(hdr):
            hdr.setText('Current Sale')

    # Leave Checkout Pro chrome before switching away
    prev_lid = getattr(tab, '_checkout_layout', None)
    if prev_lid == LAYOUT_CHECKOUT_PRO and lid != LAYOUT_CHECKOUT_PRO:
        try:
            from desktop.pos.checkout_pro_chrome import restore_shared_chrome
            restore_shared_chrome(tab)
        except Exception:
            pass

    product = tab._product_panel
    sale = tab._sale_panel
    actions = tab._actions_panel
    body = tab._actions_body
    foot = tab._checkout_foot

    for p in (product, sale, actions, body, foot):
        if _alive(p):
            p.setParent(None)
            p.show()

    # Park previous shell chrome (explorer/classic right frames, payment footer)
    prev = []
    for name in ('_explorer_right', '_classic_right', '_payment_footer_bar',
                 '_explorer_scroll', '_classic_actions_scroll'):
        w = getattr(tab, name, None)
        if _alive(w):
            prev.append(w)
    _stash(tab, *prev)

    _replace_layout(shell)

    if lid == LAYOUT_CHECKOUT_PRO:
        _assemble_checkout_pro(tab, shell, product, sale, actions, body, foot)
    elif lid == LAYOUT_RETAIL_CLASSIC:
        _assemble_retail_classic(tab, shell, product, sale, actions, body, foot)
    else:
        _assemble_product_explorer(tab, shell, product, sale, actions, body, foot)

    tab._checkout_layout = lid
    tab._left_panel = product

    if lid == LAYOUT_CHECKOUT_PRO:
        try:
            from desktop.pos.checkout_pro_chrome import apply_checkout_pro_chrome
            apply_checkout_pro_chrome(tab)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            try:
                print(f'[checkout_pro_chrome] apply failed: {exc}', flush=True)
            except Exception:
                pass
    else:
        # Explorer + Classic: same stable table cart as Pro (avoids card-row overlap)
        clist = getattr(tab, '_cart_list', None)
        if _alive(clist) and hasattr(clist, 'set_density'):
            try:
                clist.set_density('table')
                if hasattr(clist, 'set_expanded'):
                    clist.set_expanded(True)
            except Exception:
                pass
        # Outer sale cart scroll must not crush table rows into the summary
        try:
            from PyQt5.QtCore import Qt as _Qt
            cart_scroll = getattr(tab, '_sale_cart_scroll', None)
            if _alive(cart_scroll):
                cart_scroll.setMinimumHeight(260)
                cart_scroll.setVerticalScrollBarPolicy(_Qt.ScrollBarAsNeeded)
                cart_scroll.setWidgetResizable(True)
        except Exception:
            pass
        # Compact payment tiles + foot so Classic bottom strip doesn't clip
        try:
            if hasattr(tab, '_pay_seg') and hasattr(tab._pay_seg, 'set_compact'):
                tab._pay_seg.set_compact(True)
            if hasattr(tab, '_pay_seg') and hasattr(tab._pay_seg, 'set_row_layout'):
                # Narrow right rail: one row of tender tiles (same as Pro)
                tab._pay_seg.set_row_layout(True)
        except Exception:
            pass
        # Hide duplicate Method combo + idle split strip (Pro already hides these)
        for name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_var_frame', '_split_frame'):
            w = getattr(tab, name, None)
            if _alive(w):
                try:
                    w.hide()
                except Exception:
                    pass
        _compact_checkout_foot(tab, True)
        # Shorten overflowing footer labels; keep Clear labeled (not bare "X")
        for name, label in (
            ('_clr_btn', 'Clear'),
            ('_returns_help_btn', 'Returns'),
            ('_void_btn', 'Void'),
            ('_reprint_btn', 'Reprint'),
            ('_prv_btn', 'Preview'),
        ):
            b = getattr(tab, name, None)
            if _alive(b) and hasattr(b, 'setText'):
                try:
                    b.setText(label)
                    b.setMinimumWidth(0)
                    b.setMaximumWidth(16777215)
                except Exception:
                    pass
        clr = getattr(tab, '_clr_btn', None)
        if _alive(clr):
            try:
                clr.setFixedWidth(58)
            except Exception:
                pass
        # Shared Amount Paid + quiet secondary actions + denser payment stack
        try:
            from desktop.pos.checkout_pro_chrome import apply_shared_checkout_chrome
            apply_shared_checkout_chrome(tab)
        except Exception:
            pass

    try:
        product.show()
        sale.show()
        actions.show()
        shell.updateGeometry()
        tab.updateGeometry()
    except Exception:
        pass
    return lid


def _style_card(frame: QFrame, obj_name: str) -> None:
    from desktop.utils.theme import C, RADIUS
    frame.setObjectName(obj_name)
    frame.setAttribute(Qt.WA_StyledBackground, True)
    frame.setStyleSheet(
        f"QFrame#{obj_name} {{ background:{C['card']}; "
        f"border:1px solid {C['border']}; border-radius:{RADIUS['xl']}px; }}")


def _ensure_explorer_scroll(tab):
    scroll = getattr(tab, '_explorer_scroll', None)
    host = getattr(tab, '_explorer_scroll_host', None)
    hl = getattr(tab, '_explorer_scroll_lay', None)
    if _alive(scroll) and _alive(host) and _alive(hl):
        clear_layout(hl)
        return scroll, host, hl

    scroll = QScrollArea()
    scroll.setObjectName('posExplorerScroll')
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet('QScrollArea{border:none;background:transparent;}')
    try:
        from desktop.utils.no_wheel_small_scroll import mark_wheel_scroll
        mark_wheel_scroll(scroll, True)
    except Exception:
        pass
    host = QWidget()
    host.setStyleSheet('background:transparent;')
    hl = QVBoxLayout(host)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(0)
    scroll.setWidget(host)
    tab._explorer_scroll = scroll
    tab._explorer_scroll_host = host
    tab._explorer_scroll_lay = hl
    return scroll, host, hl


def _compact_checkout_foot(tab, compact: bool) -> None:
    """Shrink / wrap sticky footer controls; Complete Sale gets breathing room."""
    # Soften secondary button heights so Complete Sale stays primary
    for name in (
        '_clr_btn', '_hold_btn', '_resume_btn', '_prv_btn', '_reprint_btn',
        '_void_btn', '_returns_help_btn',
    ):
        b = getattr(tab, name, None)
        if b is None:
            continue
        try:
            b.setMinimumHeight(32 if compact else 36)
            if hasattr(b, 'setMaximumHeight'):
                b.setMaximumHeight(34 if compact else 38)
        except Exception:
            pass
    if not compact:
        try:
            if hasattr(tab, '_pay_seg') and hasattr(tab._pay_seg, 'set_compact'):
                tab._pay_seg.set_compact(False)
        except Exception:
            pass
    try:
        from desktop.pos.checkout_pro_chrome import apply_checkout_foot_rhythm
        apply_checkout_foot_rhythm(tab, pro_primary_only=False)
    except Exception:
        try:
            from desktop.pos.checkout_pro_chrome import style_quiet_secondary_actions
            style_quiet_secondary_actions(tab)
        except Exception:
            pass
        foot = getattr(tab, '_checkout_foot', None)
        if foot is not None:
            fl = foot.layout()
            if fl is not None:
                fl.setContentsMargins(12, 8, 12, 12)
                fl.setSpacing(8)
        charge = getattr(tab, '_charge_btn', None)
        if charge is not None:
            try:
                charge.setMinimumHeight(54 if compact else 56)
            except Exception:
                pass


def _assemble_product_explorer(tab, shell, product, sale, actions, body, foot):
    """Browse-first grid + Current Sale / payment column (prior POS philosophy)."""
    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    # Match Classic panel-gap (pixel alignment across layouts)
    lay.setSpacing(10)

    _style_card(product, 'posProductPanel')
    product.setMinimumWidth(0)
    product.setMaximumWidth(16777215)
    sp = product.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Expanding)
    product.setSizePolicy(sp)
    lay.addWidget(product, 6)

    right = getattr(tab, '_explorer_right', None)
    if not _alive(right):
        right = QFrame()
        tab._explorer_right = right
    _style_card(right, 'posCartPanel')
    # Browse-first: slightly narrower checkout rail than Classic (more catalog pixels)
    right.setMinimumWidth(480)
    right.setMaximumWidth(680)
    right.setFixedWidth(560)
    right.show()
    _replace_layout(right)
    rl = QVBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(0)

    scroll, host, hl = _ensure_explorer_scroll(tab)
    scroll.show()

    sale.setObjectName('posSalePanel')
    sale.setStyleSheet('QFrame#posSalePanel{background:transparent;border:none;}')
    actions.setObjectName('posActionsPanel')
    actions.setStyleSheet('QFrame#posActionsPanel{background:transparent;border:none;}')
    _replace_layout(actions)
    al = QVBoxLayout(actions)
    al.setContentsMargins(0, 0, 0, 0)
    al.setSpacing(0)
    al.addWidget(body, 1)
    # Same Classic quiet secondary + Complete Sale breathing room
    _compact_checkout_foot(tab, True)
    try:
        bl = body.layout()
        if bl is not None:
            bl.setContentsMargins(12, 8, 12, 8)
            bl.setSpacing(6)
    except Exception:
        pass

    hl.addWidget(sale, 1)
    hl.addWidget(actions, 0)
    rl.addWidget(scroll, 1)
    rl.addWidget(foot, 0)

    lay.addWidget(right, 5)
    tab._right_panel = right
    tab._center_panel = None
    tab._checkout_scroll = scroll
    tab._classic_right = getattr(tab, '_classic_right', None)


def _assemble_retail_classic(tab, shell, product, sale, actions, body, foot):
    """Two-column Classic: large catalog | cart + payment stacked (same pattern as Explorer)."""
    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)

    _style_card(product, 'posProductPanel')
    product.setMinimumWidth(0)
    product.setMaximumWidth(16777215)
    sp = product.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Expanding)
    product.setSizePolicy(sp)
    lay.addWidget(product, 7)

    right = getattr(tab, '_classic_right', None)
    if not _alive(right):
        right = QFrame()
        tab._classic_right = right
    _style_card(right, 'posCartPanel')
    right.setMinimumWidth(480)
    right.setMaximumWidth(700)
    right.setFixedWidth(600)
    right.show()
    _replace_layout(right)
    rl = QVBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(0)

    # Park unused classic payment footer if present
    pay_foot = getattr(tab, '_payment_footer_bar', None)
    if _alive(pay_foot):
        pay_foot.hide()
        pay_foot.setParent(None)

    scroll, host, hl = _ensure_explorer_scroll(tab)
    # Reuse explorer scroll host for classic stack (cart then payment)
    scroll.setObjectName('posClassicScroll')
    scroll.show()

    sale.setObjectName('posSalePanel')
    sale.setStyleSheet('QFrame#posSalePanel{background:transparent;border:none;}')
    actions.setObjectName('posActionsPanel')
    actions.setStyleSheet('QFrame#posActionsPanel{background:transparent;border:none;}')
    _replace_layout(actions)
    al = QVBoxLayout(actions)
    al.setContentsMargins(0, 0, 0, 0)
    al.setSpacing(0)
    al.addWidget(body, 1)
    _compact_checkout_foot(tab, True)
    try:
        bl = body.layout()
        if bl is not None:
            bl.setContentsMargins(12, 8, 12, 8)
            bl.setSpacing(6)
    except Exception:
        pass

    hl.addWidget(sale, 1)
    hl.addWidget(actions, 0)
    rl.addWidget(scroll, 1)
    rl.addWidget(foot, 0)

    lay.addWidget(right, 5)
    tab._right_panel = right
    tab._center_panel = None
    tab._checkout_scroll = scroll

    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        try:
            charge.setMinimumHeight(54)
            charge.setText('$  Complete Sale')
        except Exception:
            pass



def _assemble_checkout_pro(tab, shell, product, sale, actions, body, foot):
    """Three fixed columns — product + cart list scroll; right actions never scroll."""
    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)

    _style_card(product, 'posProductPanel')
    product.setMinimumWidth(260)
    product.setMaximumWidth(16777215)
    lay.addWidget(product, 4)

    _style_card(sale, 'posSalePanel')
    sale.setMinimumWidth(360)
    sale.setMaximumWidth(16777215)
    lay.addWidget(sale, 5)

    _style_card(actions, 'posActionsPanel')
    # Wide enough that payment tiles / Amount Paid / Complete Sale never clip
    actions.setMinimumWidth(380)
    actions.setMaximumWidth(560)
    _replace_layout(actions)
    al = QVBoxLayout(actions)
    al.setContentsMargins(0, 0, 0, 0)
    al.setSpacing(0)

    try:
        bl = body.layout()
        if bl is not None:
            # Align horizontal inset with Classic/Explorer (12px)
            bl.setContentsMargins(12, 6, 12, 4)
            bl.setSpacing(5)
    except Exception:
        pass
    # Compact payment tiles + footer for narrow rail
    try:
        if hasattr(tab, '_pay_seg') and hasattr(tab._pay_seg, 'set_row_layout'):
            # Row layout is applied by checkout_pro_chrome; keep compact heights here
            pass
        if hasattr(tab, '_pay_seg') and hasattr(tab._pay_seg, 'set_compact'):
            tab._pay_seg.set_compact(True)
    except Exception:
        pass
    _compact_checkout_foot(tab, True)
    # Classic pattern: body expands, content packs top; foot sticky (no empty top rail)
    al.addWidget(body, 1)
    al.addWidget(foot, 0)
    lay.addWidget(actions, 5)

    tab._right_panel = actions
    tab._center_panel = sale
    tab._checkout_scroll = getattr(tab, '_sale_cart_scroll', None)
    # Cart list fills sale pane (no 520px compress)
    clist = getattr(tab, '_cart_list', None)
    if _alive(clist) and hasattr(clist, 'set_expanded'):
        clist.set_expanded(True)
