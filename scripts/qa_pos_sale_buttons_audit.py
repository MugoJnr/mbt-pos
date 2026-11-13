"""POS sale screen — every interactive control must be visible and not clipped.

Run:  python scripts/qa_pos_sale_buttons_audit.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WIDTHS = (1024, 1280, 1366, 1536, 1680, 1920)
# Square / near-square tablet shells — height tracks width.
SQUARE_SIZES = ((1024, 1024), (1080, 1080), (1280, 1280))
HEIGHT = 900


def _rect(w):
    try:
        g = w.geometry()
        return g.x(), g.y(), g.width(), g.height()
    except RuntimeError:
        return None


def _clipped(w, margin=2):
    """True when widget extends outside its parent viewport."""
    r = _rect(w)
    if r is None or r[2] <= 0 or r[3] <= 0:
        return True
    try:
        if not w.isVisible():
            return False
        p = w.parentWidget()
        if p is None:
            return False
        # Map to parent coords
        top_left = w.mapTo(p, w.rect().topLeft())
        bottom_right = w.mapTo(p, w.rect().bottomRight())
        pr = p.rect()
        if top_left.x() < pr.left() - margin:
            return True
        if top_left.y() < pr.top() - margin:
            return True
        if bottom_right.x() > pr.right() + margin:
            return True
        if bottom_right.y() > pr.bottom() + margin:
            return True
    except Exception:
        return False
    return False


def _overlaps(a, b):
    ra, rb = _rect(a), _rect(b)
    if ra is None or rb is None:
        return False
    ax, ay, aw, ah = ra
    bx, by, bw, bh = rb
    if aw < 4 or ah < 4 or bw < 4 or bh < 4:
        return False
    # Same parent required for meaningful overlap
    try:
        if a.parentWidget() is not b.parentWidget():
            return False
    except RuntimeError:
        return False
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _collect_buttons(root):
    from PyQt5.QtWidgets import QPushButton, QRadioButton, QToolButton
    out = []
    for cls in (QPushButton, QRadioButton, QToolButton):
        out.extend(root.findChildren(cls))
    return out


def main() -> int:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt

    app = QApplication(sys.argv)
    from desktop.utils.api_client import APIClient
    from desktop.tabs.sales_tab import SalesTab
    from desktop.pos.layout_ids import LAYOUT_CHECKOUT_PRO
    from desktop.pos.checkout_pro_chrome import apply_checkout_pro_chrome, sync_category_chips

    db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'mbt_pos.db'
    if not db.exists():
        print('FAIL no db', db)
        return 1

    api = APIClient(str(db))
    user = {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'QA'}
    tab = SalesTab(api, user, str(db), lambda: {})
    tab.resize(1680, HEIGHT)
    tab.show()
    app.processEvents()
    tab.products = [
        {'id': i, 'name': f'Product {i}', 'sku': f'P-{i}', 'category': 'General',
         'price': 100 + i, 'stock': 10, 'unit': 'pcs'} for i in range(1, 12)
    ]
    tab.set_checkout_layout(LAYOUT_CHECKOUT_PRO)
    apply_checkout_pro_chrome(tab)
    sync_category_chips(tab)
    tab._filter(defer=False)
    app.processEvents()

    # Seed cart so rail is under load
    tab.cart = [{
        'product_id': 1, 'product_name': 'DAP 50kg', 'sku': 'F-001', 'category': 'General',
        'quantity': 2, 'unit_price': 1070, 'discount': 0, 'total': 2140,
    }]
    tab._refresh_cart()
    app.processEvents()

    fails = []
    passes = 0
    must_show = (
        '_charge_btn', '_pay_seg', '_quick_actions', '_cust_card',
        '_paid', '_amount_paid_block', '_amount_block',
        '_business_day_bar', '_biz_date',
    )

    for w in WIDTHS:
        tab.resize(w, HEIGHT)
        app.processEvents()
        try:
            from desktop.pos.layout_ids import normalize_layout_id
            from desktop.pos.layouts.splitters import apply_sizes
            from desktop.pos.checkout_pro_chrome import sync_pro_square_layout
            sp = getattr(tab, '_pos_splitter', None)
            if sp is not None and sp.count() >= 2:
                apply_sizes(tab, normalize_layout_id(tab._checkout_layout), sp.count())
                app.processEvents()
            sync_pro_square_layout(tab)
        except Exception:
            pass
        app.processEvents()
        if hasattr(tab, '_cat_chips') and tab._cat_chips:
            try:
                tab._cat_chips.repack_for_width(force=True)
            except Exception:
                pass
        app.processEvents()

        for attr in must_show:
            wgt = getattr(tab, attr, None)
            if wgt is None and attr == '_amount_paid_block':
                wgt = getattr(tab, '_amount_block', None)
            if wgt is None:
                fails.append(f'{w}px missing {attr}')
                continue
            try:
                if not wgt.isVisible():
                    fails.append(f'{w}px hidden {attr}')
                elif _clipped(wgt):
                    fails.append(f'{w}px clipped {attr}')
                else:
                    passes += 1
            except RuntimeError:
                fails.append(f'{w}px dead {attr}')

        charge = getattr(tab, '_charge_btn', None)
        if charge and charge.isVisible():
            r = _rect(charge)
            if r and r[3] < 36:
                fails.append(f'{w}px Complete Sale too short h={r[3]}')

        # Scan action panel buttons
        panel = getattr(tab, '_actions_panel', None)
        if panel:
            btns = [b for b in _collect_buttons(panel) if b.isVisible()]
            clipped = [b.text() or b.objectName() for b in btns if _clipped(b)]
            if clipped:
                fails.append(f'{w}px clipped buttons in actions: {clipped[:6]}')

        view_all = None
        chips = getattr(tab, '_cat_chips', None)
        if chips:
            view_all = getattr(chips, '_view_all', None)
            if view_all and view_all.isVisible() and _clipped(view_all):
                fails.append(f'{w}px More/View All clipped')

    for w, h in SQUARE_SIZES:
        tab.resize(w, h)
        app.processEvents()
        try:
            from desktop.pos.layout_ids import normalize_layout_id
            from desktop.pos.layouts.splitters import apply_sizes
            from desktop.pos.checkout_pro_chrome import sync_pro_square_layout
            sp = getattr(tab, '_pos_splitter', None)
            if sp is not None and sp.count() >= 2:
                apply_sizes(tab, normalize_layout_id(tab._checkout_layout), sp.count())
                app.processEvents()
            sync_pro_square_layout(tab)
        except Exception:
            pass
        app.processEvents()
        if hasattr(tab, '_cat_chips') and tab._cat_chips:
            try:
                tab._cat_chips.repack_for_width(force=True)
            except Exception:
                pass
        app.processEvents()

        tag = f'{w}x{h}'
        for attr in must_show:
            wgt = getattr(tab, attr, None)
            if wgt is None and attr == '_amount_paid_block':
                wgt = getattr(tab, '_amount_block', None)
            if wgt is None:
                fails.append(f'{tag} missing {attr}')
                continue
            try:
                if not wgt.isVisible():
                    fails.append(f'{tag} hidden {attr}')
                elif _clipped(wgt):
                    fails.append(f'{tag} clipped {attr}')
                else:
                    passes += 1
            except RuntimeError:
                fails.append(f'{tag} dead {attr}')

        charge = getattr(tab, '_charge_btn', None)
        if charge and charge.isVisible():
            r = _rect(charge)
            if r and r[3] < 36:
                fails.append(f'{tag} Complete Sale too short h={r[3]}')

        panel = getattr(tab, '_actions_panel', None)
        if panel:
            btns = [b for b in _collect_buttons(panel) if b.isVisible()]
            clipped = [b.text() or b.objectName() for b in btns if _clipped(b)]
            if clipped:
                fails.append(f'{tag} clipped buttons in actions: {clipped[:6]}')

        chips = getattr(tab, '_cat_chips', None)
        if chips:
            view_all = getattr(chips, '_view_all', None)
            if view_all and view_all.isVisible() and _clipped(view_all):
                fails.append(f'{tag} More/View All clipped')

        for attr in ('_biz_today_btn', '_biz_view_btn', '_biz_copy_btn'):
            wgt = getattr(tab, attr, None)
            if wgt is None:
                fails.append(f'{w}px missing {attr}')
                continue
            try:
                if not wgt.isVisible():
                    fails.append(f'{w}px hidden {attr}')
                elif _clipped(wgt):
                    fails.append(f'{w}px clipped {attr}')
            except RuntimeError:
                fails.append(f'{w}px dead {attr}')

    tab.close()
    app.processEvents()

    print(f'pass_checks={passes}')
    if fails:
        print('FAILURES:')
        for f in fails:
            print(' ', f)
        return 1
    print('PASS all sale-screen button visibility checks')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
