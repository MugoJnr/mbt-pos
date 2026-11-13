"""Dump cart row geometries for the three checkout layouts."""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

from desktop.utils.api_client import APIClient
from desktop.tabs.sales_tab import SalesTab
from desktop.pos.layout_ids import (
    LAYOUT_CHECKOUT_PRO, LAYOUT_PRODUCT_EXPLORER, LAYOUT_RETAIL_CLASSIC,
)

db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'mbt_pos.db'
api = APIClient(str(db))
tab = SalesTab(api, {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'QA'}, str(db), lambda: {})
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
]
cart = []
for i, p in enumerate(products):
    cart.append({
        'product_id': p['id'], 'product_name': p['name'], 'sku': p['sku'],
        'category': p['category'], 'quantity': float(i + 1),
        'unit_price': float(p['price']), 'discount': 50.0 if i == 0 else 0.0,
        'total': float(p['price']) * (i + 1) - (50.0 if i == 0 else 0.0),
    })


def dump(lid, name):
    tab.products = list(products)
    tab.set_checkout_layout(lid)
    app.processEvents()
    tab.products = list(products)
    g = getattr(tab, '_prod_grid', None)
    if g:
        g.set_pro_density(lid == LAYOUT_CHECKOUT_PRO)
        cols = 2 if lid == LAYOUT_CHECKOUT_PRO else tab._product_columns()
        g.populate(tab.products, columns=cols)
    tab.cart = [dict(x) for x in cart]
    tab._cart_select_idx = len(tab.cart) - 1
    tab._refresh_cart()
    tab._recalc()
    app.processEvents()
    cl = tab._cart_list
    print('===', name, 'density=', cl._density, 'rows', len(cl._rows),
          'clist', cl.width(), 'x', cl.height(), 'scrollH', cl._scroll.height())
    sale = tab._sale_panel
    print('  sale', sale.width(), 'x', sale.height())
    for i, r in enumerate(cl._rows):
        print(f'  row{i}: dens={r._density} geo={r.geometry().getRect()} '
              f'h={r.height()} maxH={r.maximumHeight()} sel={r.is_selected()}')
        print(f'        qty={r._qty.geometry().getRect()} name={r._name.geometry().getRect()} '
              f'tot={r._line_total.geometry().getRect()}')
        if getattr(r, '_price_lbl', None) is not None:
            print(f'        plbl vis={r._price_lbl.isVisible()} {r._price_lbl.geometry().getRect()} '
                  f'pspin vis={r._price.isVisible()} {r._price.geometry().getRect()}')


for lid, name in (
    (LAYOUT_CHECKOUT_PRO, 'pro'),
    (LAYOUT_PRODUCT_EXPLORER, 'explorer'),
    (LAYOUT_RETAIL_CLASSIC, 'classic'),
):
    dump(lid, name)
