"""Compose shared POS panels into Retail Classic / Simple Counter / Checkout Pro.

Panels are created once by SalesTab and reparented here — never duplicated.
Business logic stays on SalesTab; this module only arranges geometry.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLayout, QScrollArea, QSizePolicy, QPushButton, QLabel,
    QVBoxLayout, QWidget,
)

from desktop.pos.layout_ids import (
    LAYOUT_CHECKOUT_PRO,
    LAYOUT_MODERN_CHECKOUT,
    LAYOUT_PRODUCT_EXPLORER,
    LAYOUT_SIMPLE_COUNTER,
    LAYOUT_RETAIL_CLASSIC,
    normalize_layout_id,
)


def clear_layout(layout: QLayout | None, park_under: QWidget | None = None) -> None:
    """Detach children without deleting them (safe for reparenting).

    Prefer parking under ``park_under`` (hidden stash). ``setParent(None)`` creates
    a free Windows HWND with maximize/close chrome — that is the empty floating
    popup cashiers report.
    """
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
            try:
                w.hide()
                w.setAttribute(Qt.WA_DontShowOnScreen, True)
            except Exception:
                try:
                    w.hide()
                except Exception:
                    pass
            if park_under is not None and w is not park_under:
                try:
                    w.setParent(park_under)
                    w.hide()
                except Exception:
                    pass
            else:
                # Last resort: DontShowOnScreen already set; detach without paint.
                try:
                    from desktop.utils.quiet_ui import safe_detach
                    safe_detach(w)
                except Exception:
                    try:
                        w.setParent(None)
                    except Exception:
                        pass
            continue
        child = item.layout()
        if child is not None:
            clear_layout(child, park_under=park_under)


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        _ = obj.objectName()
        return True
    except RuntimeError:
        return False


def _park_new(tab, widget: QWidget) -> QWidget:
    """Create chrome under the invisible stash — never as a free top-level."""
    stash = _ensure_stash(tab)
    try:
        widget.hide()
        widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    except Exception:
        pass
    widget.setParent(stash)
    widget.hide()
    return widget


def _ensure_stash(tab) -> QWidget:
    stash = getattr(tab, '_layout_stash', None)
    if _alive(stash):
        return stash
    host = getattr(tab, '_shell', None) or tab
    stash = QWidget(host)
    stash.setObjectName('posLayoutStash')
    stash.hide()
    stash.setAttribute(Qt.WA_DontShowOnScreen, True)
    tab._layout_stash = stash
    return stash


def _reclaim_actions_body(tab, body) -> None:
    """Take the checkout body back from its QScrollArea before re-layout.

    ``QScrollArea.setWidget`` keeps driving its widget's geometry even after the
    widget is added to another layout, which pinned the body at the scroll's own
    width (640px) and made the payment rail's contents overflow the panel.
    ``takeWidget`` is the only way to hand ownership back to the layout.
    """
    scroll = getattr(tab, '_actions_body_scroll', None)
    if not _alive(scroll) or not _alive(body):
        return
    try:
        if scroll.widget() is not body:
            return
        body.hide()          # never let takeWidget expose a parentless top-level
        scroll.takeWidget()
        _stash(tab, body)
    except Exception:
        pass


def _replace_layout(host: QWidget) -> None:
    """Remove existing layout from host so a new one can be assigned."""
    if not _alive(host):
        return
    old = host.layout()
    if old is None:
        return
    # Sink must never become a visible top-level — park under host's window.
    sink = QWidget(host.window() if host.window() is not None else host)
    sink.setAttribute(Qt.WA_DontShowOnScreen, True)
    sink.hide()
    # Park widgets under sink FIRST — never free top-level during takeAt.
    clear_layout(old, park_under=sink)
    sink.setLayout(old)
    sink.deleteLater()


def _stash(tab, *widgets) -> None:
    """Park unused chrome under an invisible stash so Qt/sip won't GC it."""
    stash = _ensure_stash(tab)
    for w in widgets:
        if _alive(w) and w is not stash:
            try:
                w.hide()
                w.setAttribute(Qt.WA_DontShowOnScreen, True)
            except Exception:
                pass
            w.setParent(stash)
            w.hide()


def apply_layout_shell(tab, layout_id: str) -> str:
    """Rebuild ``tab._shell`` around the shared panels. Returns normalized id."""
    lid = normalize_layout_id(layout_id)
    shell = getattr(tab, '_shell', None)
    if shell is None:
        return lid

    from desktop.utils.quiet_ui import (
        begin_layout_orphan_guard,
        end_layout_orphan_guard,
        hide_orphan_pos_flashes,
        safe_show,
    )
    begin_layout_orphan_guard()
    try:
        return _apply_layout_shell_inner(tab, lid, shell, safe_show, hide_orphan_pos_flashes)
    finally:
        end_layout_orphan_guard()


def _apply_layout_shell_inner(tab, lid: str, shell, safe_show, hide_orphan_pos_flashes) -> str:
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

    _reclaim_actions_body(tab, body)

    # Park panels under the invisible stash — NEVER setParent(None).
    # Free top-level HWNDs get Windows maximize/close chrome (empty floating popup).
    _stash(tab, product, sale, actions, body, foot)

    # Park previous shell chrome (explorer/classic right frames, payment footer)
    prev = []
    for name in ('_explorer_right', '_classic_right', '_payment_footer_bar',
                 '_explorer_scroll', '_classic_actions_scroll',
                 '_actions_body_scroll'):
        w = getattr(tab, name, None)
        if _alive(w):
            prev.append(w)
    _stash(tab, *prev)
    try:
        hide_orphan_pos_flashes(tab)
    except Exception:
        pass

    _replace_layout(shell)

    if lid == LAYOUT_CHECKOUT_PRO:
        _assemble_checkout_pro(tab, shell, product, sale, actions, body, foot)
    elif lid == LAYOUT_RETAIL_CLASSIC:
        _assemble_retail_classic(tab, shell, product, sale, actions, body, foot)
    elif lid == LAYOUT_PRODUCT_EXPLORER:
        _assemble_product_explorer(tab, shell, product, sale, actions, body, foot)
    elif lid == LAYOUT_MODERN_CHECKOUT:
        _assemble_modern_checkout(tab, shell, product, sale, actions, body, foot)
    else:
        _assemble_simple_counter(tab, shell, product, sale, actions, body, foot)

    tab._checkout_layout = lid
    tab._left_panel = getattr(tab, '_modern_catalog', product) if lid == LAYOUT_MODERN_CHECKOUT else product

    from desktop.pos.layouts import splitters as _splitters
    _splitters.install_cart(tab, lid)

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
                # Cashier min 5 rows; cart owns Current Sale (totals are foot-pinned).
                # Review (set_expanded) still expands further when toggled.
                if hasattr(clist, 'set_cashier_viewport'):
                    from desktop.utils.pos_components import CART_CASHIER_ROWS
                    clist.set_cashier_viewport(CART_CASHIER_ROWS)
                if hasattr(clist, 'set_expanded'):
                    clist.set_expanded(bool(getattr(tab, '_cart_maximized', False)))
            except Exception:
                pass
        # Outer sale cart scroll must not crush table rows into the summary.
        # The cart/summary split now lives on the cart splitter (drag-resizable),
        # so the scroll area and inner list only need a soft floor — a high
        # fixed min here previously left free=0 on short Classic rails.
        try:
            from PyQt5.QtCore import Qt as _Qt
            cart_scroll = getattr(tab, '_sale_cart_scroll', None)
            if _alive(cart_scroll):
                cart_scroll.setMinimumHeight(72)
                cart_scroll.setMaximumHeight(16777215)
                cart_scroll.setVerticalScrollBarPolicy(_Qt.ScrollBarAsNeeded)
                cart_scroll.setWidgetResizable(True)
            clist = getattr(tab, '_cart_list', None)
            if _alive(clist) and hasattr(clist, '_scroll'):
                try:
                    clist._scroll.setMaximumHeight(16777215)
                    if hasattr(clist, 'setMaximumHeight'):
                        clist.setMaximumHeight(16777215)
                except Exception:
                    pass
            # Re-apply cart splitter floors AFTER chrome mins so free travel sticks.
            from desktop.pos.layouts import splitters as _splitters2
            _splitters2.install_cart(tab, lid)
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
        # Hide duplicate Method combo. Split panel is shown only when Mixed
        # is selected (_update_rounding_ui) — do not hide it here or Split Pay
        # never appears on Classic / Explorer.
        for name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_var_frame'):
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
        # Reveal cart stack after Classic/Explorer chrome settles.
        try:
            from desktop.pos.layouts.splitters import reveal_cart_stack
            from PyQt5.QtCore import QTimer
            reveal_cart_stack(tab)
            QTimer.singleShot(0, lambda t=tab: reveal_cart_stack(t))
            QTimer.singleShot(120, lambda t=tab: reveal_cart_stack(t))
        except Exception:
            pass

    # Show only after panels are re-parented into the new shell tree.
    # Never show parentless widgets — that opens a brief top-level OS window.
    try:
        for p in (product, sale, actions, body, foot):
            if _alive(p):
                safe_show(p)
        right = getattr(tab, '_right_panel', None)
        if _alive(right):
            safe_show(right)
        scroll = getattr(tab, '_checkout_scroll', None)
        if _alive(scroll):
            safe_show(scroll)
        shell.updateGeometry()
        tab.updateGeometry()
    except Exception:
        pass
    # Re-assert column widths after show() — hidden children previously received
    # no space and could leave Checkout Pro looking like a catalog-only pane.
    try:
        from desktop.pos.layouts import splitters as _splitters
        sp = getattr(tab, '_pos_splitter', None)
        if _alive(sp) and sp.count() >= 2:
            _splitters.apply_sizes(tab, lid, sp.count())
        chips = getattr(tab, '_cat_chips', None)
        if _alive(chips) and hasattr(chips, 'repack_for_width'):
            chips.repack_for_width(force=True)
        biz = getattr(tab, '_business_day_bar', None)
        if _alive(biz) and hasattr(biz, '_apply_layout'):
            biz._apply_layout(force=True)
    except Exception:
        pass
    try:
        hide_orphan_pos_flashes(tab)
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
        clear_layout(hl, park_under=_ensure_stash(tab))
        return scroll, host, hl

    scroll = QScrollArea(_ensure_stash(tab))
    scroll.hide()
    try:
        scroll.setAttribute(Qt.WA_DontShowOnScreen, True)
    except Exception:
        pass
    _park_new(tab, scroll)
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
    host = QWidget(scroll)  # never parentless
    host.hide()
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
            b.setMinimumHeight(36 if compact else 40)
            if hasattr(b, 'setMaximumHeight'):
                b.setMaximumHeight(40 if compact else 44)
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


def _wire_stacked_right_rail(tab, right, sale, actions, body, foot, *, scroll_name: str):
    """Classic / Explorer right column geometry.

    Top: Current Sale (cart↔summary splitter) — stretch, drag to grow the list.
    Middle: scrollable payment / customer / sale-options / utilities zone.
    Bottom: Complete Sale pinned (never scrolls away).
    """
    _replace_layout(right)
    rl = QVBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(0)

    scroll, _host, hl = _ensure_explorer_scroll(tab)
    scroll.setObjectName(scroll_name)
    scroll.hide()  # parentless/stash scroll must not .show() yet
    try:
        scroll.setAttribute(Qt.WA_DontShowOnScreen, False)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumHeight(140)
        scroll.setMaximumHeight(16777215)
    except Exception:
        pass

    sale.setObjectName('posSalePanel')
    sale.setStyleSheet('QFrame#posSalePanel{background:transparent;border:none;}')
    try:
        from desktop.utils.pos_components import cart_viewport_px, CART_CASHIER_ROWS
        sale.setMinimumHeight(cart_viewport_px(CART_CASHIER_ROWS, include_header=True))
        sale.setMaximumHeight(16777215)
        sp = sale.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Expanding)
        sale.setSizePolicy(sp)
    except Exception:
        pass

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

    # Payment-only scroll — cart stays above so tall payment never pushes it off.
    hl.addWidget(actions, 1)
    # Bias leftover height to the cart↔summary stack; payment scrolls as needed.
    rl.addWidget(sale, 3)
    rl.addWidget(scroll, 2)
    rl.addWidget(foot, 0)
    tab._checkout_scroll = scroll
    return scroll


def _assemble_simple_counter(tab, shell, product, sale, actions, body, foot):
    """Fast two-column counter: catalogue | Current Sale, payment and checkout.

    This replaces Product Explorer.  It retains the same shared panels and
    handlers, so cash, M-Pesa, split, debt, stock checks and receipt actions
    behave exactly as they do in the other checkout layouts.
    """
    from desktop.pos.layouts import splitters

    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    split = splitters.ensure_splitter(tab)

    _style_card(product, 'posProductPanel')
    sp = product.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Expanding)
    product.setSizePolicy(sp)
    split.addWidget(product)

    right = getattr(tab, '_explorer_right', None)
    if not _alive(right):
        right = QFrame(_ensure_stash(tab))
        right.hide()
        try:
            right.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
        _park_new(tab, right)
        tab._explorer_right = right
    _style_card(right, 'posCartPanel')
    right.hide()  # stay hidden until parented into shell

    _wire_stacked_right_rail(
        tab, right, sale, actions, body, foot, scroll_name='posExplorerScroll')

    split.addWidget(right)
    lay.addWidget(split, 1)
    from desktop.utils.quiet_ui import safe_show
    safe_show(split)
    splitters.install(tab, LAYOUT_SIMPLE_COUNTER, (product, right))
    tab._right_panel = right
    tab._center_panel = None
    tab._classic_right = getattr(tab, '_classic_right', None)


def _assemble_product_explorer(tab, shell, product, sale, actions, body, foot):
    """Restored browse-first layout retained for existing shops."""
    _assemble_two_column_checkout(
        tab, shell, product, sale, actions, body, foot,
        layout_id=LAYOUT_PRODUCT_EXPLORER, right_attr='_product_explorer_right',
        scroll_name='posProductExplorerScroll')


def _assemble_modern_checkout(tab, shell, product, sale, actions, body, foot):
    """Modern two-panel checkout using the existing cart and payment engine."""
    catalog = _ensure_modern_catalog(tab, product)
    _assemble_two_column_checkout(
        tab, shell, catalog, sale, actions, body, foot,
        layout_id=LAYOUT_MODERN_CHECKOUT, right_attr='_modern_checkout_right',
        scroll_name='posModernCheckoutScroll')


def _ensure_modern_catalog(tab, product):
    """Reference-style dynamic category rail around the shared product panel."""
    host = getattr(tab, '_modern_catalog', None)
    if not _alive(host):
        host = QFrame(_ensure_stash(tab))
        host.setObjectName('posModernCatalog')
        host.setStyleSheet('QFrame#posModernCatalog{background:#07192D;border:none;}')
        root = QVBoxLayout(host)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        header = QFrame(host)
        header.setObjectName('posModernHeader')
        header.setStyleSheet(
            'QFrame#posModernHeader{background:#09213B;border:1px solid #1D3858;border-radius:10px;}'
            'QLabel{background:transparent;color:#F8FAFC;}')
        head_lay = QHBoxLayout(header)
        head_lay.setContentsMargins(14, 10, 14, 10)
        brand = QLabel('MBT POS')
        brand.setStyleSheet('font-size:20px;font-weight:900;color:#F9C73D;background:transparent;')
        day = QLabel(f'Business Day: {getattr(tab, "_business_day", "Today")}')
        day.setStyleSheet('font-size:12px;font-weight:700;color:#D7E5F5;background:transparent;')
        status = QLabel('OPEN')
        status.setStyleSheet('font-size:11px;font-weight:900;color:#55E6A5;background:#103A32;border-radius:6px;padding:5px 8px;')
        head_lay.addWidget(brand)
        head_lay.addStretch(1)
        head_lay.addWidget(day)
        head_lay.addWidget(status)
        root.addWidget(header)
        content = QWidget(host)
        lay = QHBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        rail = QScrollArea(content)
        rail.setObjectName('posModernCategoryRail')
        rail.setWidgetResizable(True)
        rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rail.setFixedWidth(156)
        rail.setFrameShape(QFrame.NoFrame)
        rail.setStyleSheet(
            'QScrollArea#posModernCategoryRail{background:#0B1E36;border:none;}'
            'QScrollArea#posModernCategoryRail QWidget{background:#0B1E36;}')
        rail_body = QWidget(rail)
        rail_body.setObjectName('posModernCategoryRailBody')
        rail_lay = QVBoxLayout(rail_body)
        rail_lay.setContentsMargins(8, 8, 4, 8)
        rail_lay.setSpacing(5)
        rail.setWidget(rail_body)
        lay.addWidget(rail)
        lay.addWidget(product, 1)
        root.addWidget(content, 1)
        tab._modern_catalog = host
        tab._modern_catalog_content = content
        tab._modern_category_rail = rail_body
        tab._modern_category_lay = rail_lay
    else:
        layout = tab._modern_catalog_content.layout()
        if product.parentWidget() is not tab._modern_catalog_content:
            layout.addWidget(product, 1)
    rail_lay = tab._modern_category_lay
    while rail_lay.count():
        item = rail_lay.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    cat = getattr(tab, '_cat', None)
    labels = ['All Products']
    if cat is not None:
        labels.extend(cat.itemText(i) for i in range(cat.count())
                      if cat.itemText(i) and not cat.itemText(i).lower().startswith('all'))
    for label in labels:
        button = QPushButton(label, tab._modern_category_rail)
        button.setMinimumHeight(38)
        button.setCheckable(True)
        active = (cat is None and label == 'All Products') or (
            cat is not None and ((label == 'All Products' and cat.currentText().lower().startswith('all'))
                             or cat.currentText() == label))
        button.setChecked(active)
        button.setStyleSheet(
            'QPushButton{color:#E5EDF8;background:#102744;border:1px solid #233C60;'
            'border-radius:7px;text-align:left;padding:0 10px;font-weight:600;}'
            'QPushButton:checked{color:#FFD056;background:#263847;border-color:#C99A2E;}')
        target = 'All Categories' if label == 'All Products' else label
        button.clicked.connect(lambda _checked=False, value=target: cat.setCurrentText(value) if cat else None)
        rail_lay.addWidget(button)
    rail_lay.addStretch(1)
    return host


def _assemble_two_column_checkout(tab, shell, product, sale, actions, body, foot, *, layout_id, right_attr, scroll_name):
    """Shared two-panel shell; widgets remain the real shared POS controls."""
    from desktop.pos.layouts import splitters
    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    split = splitters.ensure_splitter(tab)
    _style_card(product, 'posProductPanel')
    split.addWidget(product)
    right = getattr(tab, right_attr, None)
    if not _alive(right):
        right = QFrame(_ensure_stash(tab))
        _park_new(tab, right)
        setattr(tab, right_attr, right)
    _style_card(right, 'posCartPanel')
    _wire_stacked_right_rail(tab, right, sale, actions, body, foot, scroll_name=scroll_name)
    split.addWidget(right)
    lay.addWidget(split, 1)
    from desktop.utils.quiet_ui import safe_show
    safe_show(split)
    splitters.install(tab, layout_id, (product, right))
    tab._right_panel = right
    tab._center_panel = None


def _assemble_retail_classic(tab, shell, product, sale, actions, body, foot):
    """Two-column Classic: large catalog | cart + payment stacked (same pattern as Explorer)."""
    from desktop.pos.layouts import splitters

    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    split = splitters.ensure_splitter(tab)

    _style_card(product, 'posProductPanel')
    sp = product.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Expanding)
    product.setSizePolicy(sp)
    split.addWidget(product)

    right = getattr(tab, '_classic_right', None)
    if not _alive(right):
        right = QFrame(_ensure_stash(tab))
        right.hide()
        try:
            right.setAttribute(Qt.WA_DontShowOnScreen, True)
        except Exception:
            pass
        _park_new(tab, right)
        tab._classic_right = right
    _style_card(right, 'posCartPanel')
    right.hide()  # stay hidden until parented into shell

    # Park unused classic payment footer if present (hide before detach)
    pay_foot = getattr(tab, '_payment_footer_bar', None)
    if _alive(pay_foot):
        _stash(tab, pay_foot)

    _wire_stacked_right_rail(
        tab, right, sale, actions, body, foot, scroll_name='posClassicScroll')

    split.addWidget(right)
    lay.addWidget(split, 1)
    from desktop.utils.quiet_ui import safe_show
    safe_show(split)
    splitters.install(tab, LAYOUT_RETAIL_CLASSIC, (product, right))
    tab._right_panel = right
    tab._center_panel = None

    charge = getattr(tab, '_charge_btn', None)
    if _alive(charge):
        try:
            charge.setMinimumHeight(54)
            charge.setText('$  Complete Sale')
        except Exception:
            pass



def _assemble_checkout_pro(tab, shell, product, sale, actions, body, foot):
    """Three columns — adjustable cart↔summary; payment may scroll; Complete Sale pinned.

    Default width target: products ~25% | Current Sale ~50% | payment ~25%.
    Scroll layers (independent):
      1) CartList min ~3 rows; grows when the cart↔summary splitter is dragged
      2) Payment body scroll when the right rail is shorter than content
      3) Complete Sale stays in the sticky foot — never scrolls off-screen
    """
    from desktop.pos.layouts import splitters

    lay = QHBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    split = splitters.ensure_splitter(tab)

    _style_card(product, 'posProductPanel')
    split.addWidget(product)

    _style_card(sale, 'posSalePanel')
    split.addWidget(sale)

    _style_card(actions, 'posActionsPanel')
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
    # Payment stack scrolls inside the rail; Complete Sale stays pinned below.
    body_scroll = getattr(tab, '_actions_body_scroll', None)
    if _alive(body_scroll):
        try:
            body.setAttribute(Qt.WA_DontShowOnScreen, False)
            body_scroll.setAttribute(Qt.WA_DontShowOnScreen, False)
            body_scroll.setWidgetResizable(True)
            body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            if body_scroll.widget() is not body:
                body_scroll.setWidget(body)
            al.addWidget(body_scroll, 1)
            tab._checkout_scroll = body_scroll
        except Exception:
            al.addWidget(body, 1)
            tab._checkout_scroll = getattr(tab, '_sale_cart_scroll', None)
    else:
        al.addWidget(body, 1)
        tab._checkout_scroll = getattr(tab, '_sale_cart_scroll', None)
    al.addWidget(foot, 0)
    split.addWidget(actions)
    lay.addWidget(split, 1)
    from desktop.utils.quiet_ui import safe_show
    safe_show(split)
    splitters.install(tab, LAYOUT_CHECKOUT_PRO, (product, sale, actions))

    tab._right_panel = actions
    tab._center_panel = sale
    # Cashier viewport: 5 rows; Review (set_expanded) overrides to tall list.
    clist = getattr(tab, '_cart_list', None)
    if _alive(clist):
        try:
            if hasattr(clist, 'set_cashier_viewport'):
                from desktop.utils.pos_components import CART_CASHIER_ROWS
                clist.set_cashier_viewport(CART_CASHIER_ROWS)
            if hasattr(clist, 'set_expanded'):
                clist.set_expanded(bool(getattr(tab, '_cart_maximized', False)))
        except Exception:
            pass
