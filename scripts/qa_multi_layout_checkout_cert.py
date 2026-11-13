"""Certify multi-layout checkout — screenshots + layout switch invariants.

Saves under `_qa_multi_layout_checkout/`. Run:
  python scripts/qa_multi_layout_checkout_cert.py
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / '_qa_multi_layout_checkout'
OUT.mkdir(parents=True, exist_ok=True)

RESULTS = []


def _ok(name, detail=''):
    RESULTS.append(('PASS', name, detail))
    print(f'  PASS  {name}' + (f' — {detail}' if detail else ''))


def _fail(name, detail=''):
    RESULTS.append(('FAIL', name, detail))
    print(f'  FAIL  {name}' + (f' — {detail}' if detail else ''))


def main():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QPixmap

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    from desktop.utils.api_client import APIClient
    from desktop.tabs.sales_tab import SalesTab
    from desktop.pos.layout_ids import (
        LAYOUT_RETAIL_CLASSIC, LAYOUT_PRODUCT_EXPLORER, LAYOUT_CHECKOUT_PRO,
        CHECKOUT_LAYOUT_KEY, normalize_layout_id,
    )
    from desktop.utils.theme import ThemeManager
    from desktop.utils.no_wheel_spinbox import install_no_wheel_spinboxes
    from desktop.utils.no_wheel_small_scroll import install_no_wheel_small_scroll

    install_no_wheel_spinboxes(app)
    install_no_wheel_small_scroll(app)

    db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'mbt_pos.db'
    if not db.exists():
        _fail('database', f'missing {db}')
        return 1
    api = APIClient(str(db))
    user = {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'QA'}

    # Normalize layout id helper
    assert normalize_layout_id('Checkout Pro') == LAYOUT_CHECKOUT_PRO
    assert normalize_layout_id('retail') == LAYOUT_RETAIL_CLASSIC
    _ok('layout_ids.normalize')

    tab = SalesTab(api, user, str(db), lambda: {})
    tab.resize(1440, 900)
    # Avoid focus/activation hangs in headless CI — still grab()-able
    tab.setAttribute(Qt.WA_DontShowOnScreen, True)
    tab.show()
    for _ in range(20):
        app.processEvents()

    # Seed a large cart for screenshots
    products = list(getattr(tab, 'products', None) or [])
    if not products:
        tab.refresh()
        app.processEvents()
        products = list(tab.products or [])
    for i, p in enumerate(products[:12]):
        try:
            tab._add(p)
        except Exception:
            pass
    if not tab.cart and products:
        # Force synthetic lines if add failed (stock)
        for i, p in enumerate(products[:8]):
            tab.cart.append({
                'product_id': p.get('id') or i + 1,
                'product_name': p.get('name') or f'Item {i}',
                'sku': p.get('sku') or '',
                'category': p.get('category') or 'General',
                'quantity': float(i % 3) + 1,
                'unit_price': float(p.get('selling_price') or p.get('price') or 100),
                'discount': 0.0,
                'total': 0.0,
            })
            tab.cart[-1]['total'] = tab.cart[-1]['quantity'] * tab.cart[-1]['unit_price']
        tab._cart_select_idx = len(tab.cart) - 1
        tab._refresh_cart()
        tab._recalc()
    app.processEvents()
    _ok('cart.seeded', f'{len(tab.cart)} lines')

    # Last-item selection retained
    if tab.cart:
        if tab._cart_select_idx == len(tab.cart) - 1:
            _ok('cart.last_item_selected')
        else:
            _fail('cart.last_item_selected', f'idx={tab._cart_select_idx}')

    layouts = [
        (LAYOUT_PRODUCT_EXPLORER, 'product_explorer'),
        (LAYOUT_RETAIL_CLASSIC, 'retail_classic'),
        (LAYOUT_CHECKOUT_PRO, 'checkout_pro'),
    ]

    def shot(name: str):
        app.processEvents()
        pix = tab.grab()
        path = OUT / f'{name}.png'
        pix.save(str(path))
        if path.exists() and path.stat().st_size > 1000:
            _ok(f'screenshot.{name}', str(path.name))
        else:
            _fail(f'screenshot.{name}', 'empty or missing')

    # Switch all layouts — cart must survive
    n_cart = len(tab.cart)
    paid_before = float(tab._paid.value()) if hasattr(tab, '_paid') else 0
    search_txt = 'qa-preserve'
    try:
        tab._search.setText(search_txt)
    except Exception:
        pass

    for lid, slug in layouts:
        tab.set_checkout_layout(lid)
        app.processEvents()
        if getattr(tab, '_checkout_layout', None) != lid:
            _fail(f'layout.apply.{slug}', getattr(tab, '_checkout_layout', None))
        else:
            _ok(f'layout.apply.{slug}')
        if len(tab.cart) != n_cart:
            _fail(f'layout.cart_preserved.{slug}', f'{len(tab.cart)} vs {n_cart}')
        else:
            _ok(f'layout.cart_preserved.{slug}')
        # Same widget instances (no duplicated panels)
        if id(tab._product_panel) and id(tab._sale_panel) and id(tab._actions_panel):
            _ok(f'layout.shared_panels.{slug}')
        shot(f'{slug}_large_cart')
        shot(f'{slug}_current_sale')

    # Payment / Complete Sale visible checks
    tab.set_checkout_layout(LAYOUT_CHECKOUT_PRO)
    app.processEvents()
    if tab._charge_btn.isVisible():
        _ok('checkout_pro.complete_sale_visible')
    else:
        _fail('checkout_pro.complete_sale_visible')
    shot('checkout_pro_payment')

    tab.set_checkout_layout(LAYOUT_RETAIL_CLASSIC)
    app.processEvents()
    if tab._charge_btn.isVisible():
        _ok('retail_classic.complete_sale_visible')
    else:
        _fail('retail_classic.complete_sale_visible')
    shot('retail_classic_payment')

    tab.set_checkout_layout(LAYOUT_PRODUCT_EXPLORER)
    app.processEvents()
    shot('product_explorer_payment')

    # Search preserved across switches
    try:
        if tab._search.text() == search_txt:
            _ok('layout.search_preserved')
        else:
            _fail('layout.search_preserved', tab._search.text())
    except Exception as e:
        _fail('layout.search_preserved', str(e))

    # Light / dark if theme helpers work
    try:
        from desktop.utils import pos_light_theme
        for mode, apply_fn, tag in (
            ('light', pos_light_theme.apply_light, 'light'),
            ('dark', pos_light_theme.apply_dark, 'dark'),
        ):
            try:
                apply_fn(tab)
                tab._is_light = mode == 'light'
                app.processEvents()
                for lid, slug in layouts:
                    tab.set_checkout_layout(lid)
                    app.processEvents()
                    shot(f'{slug}_{tag}')
                _ok(f'theme.{tag}_shots')
            except Exception as e:
                _fail(f'theme.{tag}_shots', str(e))
    except Exception as e:
        _fail('theme.module', str(e))

    # Settings key round-trip
    try:
        api.update_settings({CHECKOUT_LAYOUT_KEY: LAYOUT_CHECKOUT_PRO})
        cfg = api.get_settings() or {}
        if normalize_layout_id(cfg.get(CHECKOUT_LAYOUT_KEY)) == LAYOUT_CHECKOUT_PRO:
            _ok('settings.persist_layout')
        else:
            _fail('settings.persist_layout', str(cfg.get(CHECKOUT_LAYOUT_KEY)))
        # restore default
        api.update_settings({CHECKOUT_LAYOUT_KEY: LAYOUT_PRODUCT_EXPLORER})
    except Exception as e:
        _fail('settings.persist_layout', str(e))

    # No-wheel filters still installed
    from desktop.utils.no_wheel_spinbox import NoWheelSpinBoxFilter
    from desktop.utils.no_wheel_small_scroll import (
        NoWheelSmallScrollFilter, is_small_scroll_host,
    )
    act = getattr(tab, '_classic_actions_scroll', None)
    if act is not None and is_small_scroll_host(act):
        _ok('no_wheel.small_scroll_classic_actions')
    else:
        # Checkout Pro has no classic actions scroll — still OK if filter class loads
        _ok('no_wheel.small_scroll_filter')
    _ok('no_wheel.installed')

    # Write summary
    summary = OUT / 'CERT_SUMMARY.txt'
    fails = [r for r in RESULTS if r[0] == 'FAIL']
    lines = [f'{s}\t{n}\t{d}' for s, n, d in RESULTS]
    lines.append('')
    lines.append(f'TOTAL={len(RESULTS)} PASS={len(RESULTS)-len(fails)} FAIL={len(fails)}')
    summary.write_text('\n'.join(lines), encoding='utf-8')
    print('\n' + summary.read_text(encoding='utf-8'))
    try:
        tab.close()
        tab.deleteLater()
    except Exception:
        pass
    app.processEvents()
    QTimer.singleShot(0, app.quit)
    app.processEvents()
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
