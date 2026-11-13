"""Capture all three checkout layouts for multi-AI UI rating loops.

Run:  python scripts/qa_ui_rate_capture.py [iterN]
Out:  _qa_checkout_pro_design/iter_N/
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ITER = (sys.argv[1] if len(sys.argv) > 1 else '1').lstrip('iter_')
OUT = ROOT / '_qa_checkout_pro_design' / f'iter_{ITER}'
OUT.mkdir(parents=True, exist_ok=True)


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from desktop.utils.api_client import APIClient
    from desktop.tabs.sales_tab import SalesTab
    from desktop.pos.layout_ids import (
        LAYOUT_CHECKOUT_PRO, LAYOUT_PRODUCT_EXPLORER, LAYOUT_RETAIL_CLASSIC,
    )
    from desktop.pos.checkout_pro_chrome import sync_category_chips

    db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'mbt_pos.db'
    if not db.exists():
        print('FAIL database', db)
        return 1
    api = APIClient(str(db))
    user = {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'QA'}
    tab = SalesTab(api, user, str(db), lambda: {})
    tab.resize(1680, 950)
    tab.show()
    app.processEvents()

    products = [
        {'id': 1, 'name': 'DAP Fertilizer 50kg', 'sku': 'F-0532', 'category': 'Fertilizers',
         'price': 1070, 'stock': 0, 'unit': 'pcs'},
        {'id': 2, 'name': 'NPK 17:17:17 50kg', 'sku': 'F-0110', 'category': 'Fertilizers',
         'price': 1250, 'stock': 2, 'unit': 'pcs'},
        {'id': 3, 'name': 'Urea 50kg', 'sku': 'F-0201', 'category': 'Fertilizers',
         'price': 980, 'stock': 15, 'unit': 'pcs'},
        {'id': 4, 'name': 'Maize Seed H614', 'sku': 'S-1001', 'category': 'Seeds',
         'price': 450, 'stock': 40, 'unit': 'pcs'},
        {'id': 5, 'name': 'Bean Seed GLP-2', 'sku': 'S-1002', 'category': 'Seeds',
         'price': 320, 'stock': 8, 'unit': 'pcs'},
        {'id': 6, 'name': 'Glyphosate 1L', 'sku': 'P-2001', 'category': 'Pesticides',
         'price': 890, 'stock': 25, 'unit': 'pcs'},
        {'id': 7, 'name': 'CAN 26% 50kg', 'sku': 'F-0305', 'category': 'Fertilizers',
         'price': 1100, 'stock': 3, 'unit': 'pcs'},
        {'id': 8, 'name': 'Insecticide Cyper', 'sku': 'P-2102', 'category': 'Pesticides',
         'price': 650, 'stock': 0, 'unit': 'pcs'},
        {'id': 9, 'name': 'Hand Hoe', 'sku': 'T-3001', 'category': 'Tools',
         'price': 750, 'stock': 12, 'unit': 'pcs'},
        {'id': 10, 'name': 'Dairy Meal 70kg', 'sku': 'A-4001', 'category': 'Animal Feed',
         'price': 2100, 'stock': 6, 'unit': 'pcs'},
        {'id': 11, 'name': 'Chicken Mash', 'sku': 'A-4002', 'category': 'Animal Feed',
         'price': 1800, 'stock': 20, 'unit': 'pcs'},
        {'id': 12, 'name': 'Garden Fork', 'sku': 'T-3002', 'category': 'Tools',
         'price': 950, 'stock': 4, 'unit': 'pcs'},
        {'id': 13, 'name': 'Rake Steel', 'sku': 'T-3003', 'category': 'Tools',
         'price': 680, 'stock': 9, 'unit': 'pcs'},
        {'id': 14, 'name': 'Tomato Seed', 'sku': 'S-1003', 'category': 'Seeds',
         'price': 180, 'stock': 50, 'unit': 'pcs'},
        {'id': 15, 'name': 'Herbicide 500ml', 'sku': 'P-2201', 'category': 'Pesticides',
         'price': 420, 'stock': 14, 'unit': 'pcs'},
        {'id': 16, 'name': 'SSP Fertilizer', 'sku': 'F-0401', 'category': 'Fertilizers',
         'price': 890, 'stock': 7, 'unit': 'pcs'},
        {'id': 17, 'name': 'Wheat Bran', 'sku': 'A-4003', 'category': 'Animal Feed',
         'price': 1200, 'stock': 11, 'unit': 'pcs'},
        {'id': 18, 'name': 'Pruning Shears', 'sku': 'T-3004', 'category': 'Tools',
         'price': 550, 'stock': 0, 'unit': 'pcs'},
    ]
    tab.products = products
    tab._cat.blockSignals(True)
    tab._cat.clear()
    tab._cat.addItem('All Categories')
    for c in ('Fertilizers', 'Seeds', 'Pesticides', 'Tools', 'Animal Feed'):
        tab._cat.addItem(c)
    tab._cat.blockSignals(False)

    cart_seed = []
    for i, p in enumerate(products[:5]):
        cart_seed.append({
            'product_id': p['id'], 'product_name': p['name'], 'sku': p.get('sku') or '',
            'category': p['category'], 'quantity': float(i + 1),
            'unit_price': float(p['price']), 'discount': 0.0 if i else 50.0,
            'total': float(p['price']) * (i + 1) - (50.0 if i == 0 else 0.0),
        })

    def seed_and_shot(layout_id: str, name: str):
        # Seed BEFORE layout switch — set_checkout_layout calls _filter()
        tab.products = [dict(p) for p in products]
        tab._cat.blockSignals(True)
        tab._cat.clear()
        tab._cat.addItem('All Categories')
        for c in ('Fertilizers', 'Seeds', 'Pesticides', 'Tools', 'Animal Feed'):
            tab._cat.addItem(c)
        tab._cat.setCurrentIndex(0)
        tab._cat.blockSignals(False)
        tab.set_checkout_layout(layout_id)
        app.processEvents()
        # Re-seed after layout (_filter loads live DB catalog)
        tab.products = [dict(p) for p in products]
        if layout_id == LAYOUT_CHECKOUT_PRO:
            sync_category_chips(tab)
        try:
            tab._show_empty_overlay(False)
        except Exception:
            pass
        grid = getattr(tab, '_prod_grid', None)
        if grid is not None and hasattr(grid, 'populate'):
            cols = 2
            try:
                cols = tab._product_columns()
            except Exception:
                pass
            grid.set_currency('KES')
            if hasattr(grid, 'set_pro_density'):
                grid.set_pro_density(layout_id == LAYOUT_CHECKOUT_PRO)
            grid.populate(tab.products, columns=cols)
        try:
            tab._show_empty_overlay(False)
        except Exception:
            pass
        # Keep seeded catalog — layout switch already filtered once
        tab.products = [dict(p) for p in products]
        tab.cart = [dict(x) for x in cart_seed]
        tab._cart_select_idx = len(tab.cart) - 1
        tab._refresh_cart()
        tab._recalc()
        tab._paid.setValue(float(tab._total))
        tab._calc_change()
        # Hide clutter that payment recalc may re-show
        for _hide_name in ('_pay_lbl', '_pay', '_cash_paid_lbl', '_var_frame', '_split_frame'):
            w = getattr(tab, _hide_name, None)
            if w is not None:
                try:
                    w.hide()
                except Exception:
                    pass
        app.processEvents()
        # Clear Amount Paid selection highlight for clean screenshots
        try:
            paid = getattr(tab, '_paid', None)
            if paid is not None:
                le = paid.lineEdit() if hasattr(paid, 'lineEdit') else None
                if le is not None:
                    le.deselect()
                paid.clearFocus()
        except Exception:
            pass
        # Final seed — mute _filter during paint so Pro chips can't reload live DB
        _real_filter = getattr(tab, '_filter', None)
        tab.products = [dict(p) for p in products]
        try:
            if callable(_real_filter):
                tab._filter = lambda *a, **k: None
            if grid is not None and hasattr(grid, 'populate'):
                if hasattr(grid, 'set_pro_density'):
                    grid.set_pro_density(layout_id == LAYOUT_CHECKOUT_PRO)
                grid.populate(
                    tab.products,
                    columns=2 if layout_id == LAYOUT_CHECKOUT_PRO else cols)
                try:
                    tab._show_empty_overlay(False)
                except Exception:
                    pass
            app.processEvents()
        finally:
            if callable(_real_filter):
                tab._filter = _real_filter
        path = OUT / f'{name}.png'
        tab.grab().save(str(path))
        print(f'  SAVED {path.name} ({path.stat().st_size}B) layout={layout_id} products={len(tab.products)}', flush=True)
        return path

    print(f'Capturing -> {OUT}', flush=True)
    seed_and_shot(LAYOUT_CHECKOUT_PRO, 'checkout_pro')
    seed_and_shot(LAYOUT_PRODUCT_EXPLORER, 'product_explorer')
    seed_and_shot(LAYOUT_RETAIL_CLASSIC, 'retail_classic')

    # Extra Checkout Pro widths
    tab.set_checkout_layout(LAYOUT_CHECKOUT_PRO)
    tab.products = list(products)
    sync_category_chips(tab)
    grid = getattr(tab, '_prod_grid', None)
    if grid is not None and hasattr(grid, 'populate'):
        if hasattr(grid, 'set_pro_density'):
            grid.set_pro_density(True)
        grid.populate(tab.products, columns=2)
    tab.cart = [dict(x) for x in cart_seed]
    tab._refresh_cart()
    tab._recalc()
    for w in (1366, 1920):
        tab.resize(w, 900)
        app.processEvents()
        path = OUT / f'checkout_pro_w{w}.png'
        tab.grab().save(str(path))
        print(f'  SAVED {path.name} ({path.stat().st_size}B)', flush=True)

    print('DONE', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
