"""Evidence gates for PARTIAL polish: P01/P05/D02/U03/U05 (no P11/V05 invention)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class P01SearchBarcodeGate(unittest.TestCase):
    """P01: substring filter + barcode/SKU Enter add path (SalesTab logic)."""

    def setUp(self):
        from desktop.tabs.sales_tab import SalesTab

        self.added = []
        self.tab = SimpleNamespace(
            products=[
                {
                    'id': 1,
                    'name': 'Maize Flour 2kg',
                    'sku': 'MZ-2KG',
                    'barcode': '6001234567890',
                    'stock': 10,
                    'price': 120,
                    'category': 'Flour',
                    'is_active': 1,
                },
                {
                    'id': 2,
                    'name': 'Cooking Oil 1L',
                    'sku': 'OIL-1L',
                    'barcode': '6009876543210',
                    'stock': 5,
                    'price': 350,
                    'category': 'Oils',
                    'is_active': 1,
                },
                {
                    'id': 3,
                    'name': 'Sugar 1kg',
                    'sku': 'SUG-1KG',
                    'barcode': '',
                    'stock': 0,
                    'price': 180,
                    'category': 'General',
                    'is_active': 1,
                },
            ],
            cart=[],
            _currency='KES',
            _is_light=False,
            _categories_by_name={},
            _empty=SimpleNamespace(show=lambda: None, hide=lambda: None),
            _prod_grid=SimpleNamespace(
                clear=lambda: None,
                set_currency=lambda *_: None,
                set_light=lambda *_: None,
                set_categories_map=lambda *_: None,
                populate=lambda *_a, **_k: None,
            ),
            _search=SimpleNamespace(
                text=lambda: getattr(self, '_q', ''),
                clear=lambda: setattr(self, '_q', ''),
                setFocus=lambda *_: None,
            ),
            _cat=SimpleNamespace(currentText=lambda: 'All Categories'),
            _product_columns=lambda: 3,
            _add=lambda p, from_scan=False: self.added.append((p.get('id'), from_scan)),
        )
        self.tab._filter = lambda: SalesTab._filter(self.tab)
        self.tab._on_barcode_enter = lambda t: SalesTab._on_barcode_enter(self.tab, t)

    def test_filter_substring_sku_and_difflib(self):
        self._q = 'maize'
        # Capture populate args via side effect
        seen = []

        def _populate(items, columns=3, chunked=False):
            seen.append(list(items))

        self.tab._prod_grid.populate = _populate
        self.tab._filter()
        self.assertEqual(len(seen[-1]), 1)
        self.assertEqual(seen[-1][0]['sku'], 'MZ-2KG')

        self._q = 'mz-2'
        self.tab._filter()
        self.assertEqual(seen[-1][0]['sku'], 'MZ-2KG')

        # Typo tolerance when substring empty
        self._q = 'maise flour'
        self.tab._filter()
        self.assertTrue(seen[-1])
        self.assertEqual(seen[-1][0]['id'], 1)

    def test_barcode_enter_exact_and_unique_partial(self):
        self.added.clear()
        self.tab._on_barcode_enter('6001234567890')
        self.assertEqual(self.added, [(1, True)])

        self.added.clear()
        self.tab._on_barcode_enter('OIL-1L')
        self.assertEqual(self.added, [(2, True)])

        self.added.clear()
        self.tab._on_barcode_enter('oil')  # unique partial name/sku
        self.assertEqual(self.added, [(2, True)])


class P05ReprintPrintDataGate(unittest.TestCase):
    """P05: reprint loads sale → _build_print_data; voided blocked in source."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, 'test.db')
        self._patches = [
            patch('mbt_paths.get_db_path', return_value=self._db_path),
            patch('desktop.utils.api_client.get_db_path', return_value=self._db_path),
        ]
        for p in self._patches:
            p.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = 'superadmin'
        self.api._user_id = 1
        self.api._username = 'admin'
        db = ac._db()
        existing = db.execute(
            "SELECT id FROM users WHERE username=?", ('admin',)
        ).fetchone()
        if existing:
            self.api._user_id = int(existing['id'])
        else:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                ('admin', 'x:y', 'superadmin'),
            )
            self.api._user_id = int(
                db.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
        db.execute(
            "UPDATE users SET role='superadmin' WHERE id=?",
            (self.api._user_id,),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, min_stock) "
            "VALUES (?,?,?,?,?,?)",
            ('Reprint Gate Item', 'RG-1', 100.0, 40.0, 20, 1),
        )
        db.commit()
        db.close()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_build_print_data_after_sale(self):
        from desktop.tabs.sales_tab import SalesTab

        sale = self.api.create_sale({
            'items': [{
                'product_id': 1,
                'product_name': 'Reprint Gate Item',
                'sku': 'RG-1',
                'quantity': 1,
                'unit_price': 100.0,
                'discount': 0,
                'total': 100.0,
            }],
            'subtotal': 100.0,
            'discount': 0,
            'tax': 0,
            'total': 100.0,
            'payment_method': 'Cash',
            'amount_paid': 100.0,
            'change_amount': 0,
        })
        self.assertTrue(
            sale.get('success') or sale.get('sale_id') or sale.get('receipt_number'),
            sale,
        )
        sale_id = int(sale.get('sale_id') or sale.get('id') or 0)
        if not sale_id:
            db = self.ac._db()
            sale_id = int(db.execute(
                "SELECT id FROM sales ORDER BY id DESC LIMIT 1"
            ).fetchone()[0])
            db.close()
        rn = sale.get('receipt_number')
        tab = SimpleNamespace(
            api=self.api,
            config_getter=lambda: {
                'mpesa_till': '000000',
                'receipt_footer': 'Thanks',
            },
        )
        data = SalesTab._build_print_data(tab, sale_id, rn)
        self.assertIsNotNone(data)
        self.assertTrue(data['receipt_number'])
        self.assertEqual(float(data['total']), 100.0)
        self.assertTrue(data['items'])

    def test_reprint_void_guard_in_source(self):
        path = os.path.join(ROOT, 'desktop', 'tabs', 'sales_tab.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('def _reprint_receipt(self):', src)
        self.assertIn("row['status'] == 'voided'", src)
        self.assertIn('Receipt number to reprint:', src)
        self.assertIn('def _build_print_data(self, sale_id, receipt_number=None):', src)


class D02ChartExpandGate(unittest.TestCase):
    """D02: ChartCard Expand + ChartDetailsDialog wired on dashboard."""

    def test_chart_card_expand_button(self):
        from PyQt5.QtWidgets import QApplication, QLabel

        app = QApplication.instance() or QApplication([])
        from desktop.utils.charts import ChartCard, ChartDetailsDialog

        chart = QLabel('chart')
        card = ChartCard('Sales | Last 7 Days', chart, expandable=True)
        self.assertIsNotNone(card._expand_btn)
        self.assertEqual(card._expand_btn.text(), 'Expand')
        fired = []
        card.activated.connect(lambda: fired.append(1))
        card._expand_btn.click()
        self.assertEqual(fired, [1])

        dlg = ChartDetailsDialog(
            'trend',
            'Sales | Last 7 Days',
            [{'label': 'Mon', 'value': 10}],
            currency='KES',
        )
        self.assertIn('Sales', dlg.windowTitle())
        dlg.close()
        card.close()
        del app  # keep ref for linters; QApp may be shared

    def test_dashboard_wires_expand(self):
        path = os.path.join(ROOT, 'desktop', 'tabs', 'dashboard_tab.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('expandable=True', src)
        self.assertIn("lambda: self._open_chart_detail('trend')", src)
        self.assertIn("lambda: self._open_chart_detail('payment')", src)
        self.assertIn('def _open_chart_detail(self, kind):', src)
        self.assertIn('ChartDetailsDialog(', src)


class U03GlobalSearchGate(unittest.TestCase):
    """U03: Ctrl+K dialog covers products / receipts / customers."""

    def test_dialog_searches_three_domains(self):
        path = os.path.join(ROOT, 'desktop', 'dialogs', 'global_search_dialog.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertIn('class GlobalSearchDialog', src)
        self.assertIn('# Products', src)
        self.assertIn('# Customers', src)
        self.assertIn('# Receipts', src)
        self.assertIn('get_products', src)
        self.assertIn('get_sales', src)
        main = open(os.path.join(ROOT, 'desktop', 'main.py'), encoding='utf-8').read()
        self.assertIn('_open_global_search', main)
        self.assertIn('GlobalSearchDialog', main)


class U05NoDeadPoStkReturnsGate(unittest.TestCase):
    """U05: no clickable STK / fake-PO; returns now real."""

    def test_payment_segment_no_gift_stub(self):
        from desktop.utils.pos_components import PaymentSegment

        keys = [t[0] for t in PaymentSegment.TILES]
        self.assertNotIn('Gift Card', keys)
        self.assertEqual(
            set(keys),
            {'Cash', 'M-Pesa', 'Card', 'Bank Transfer', 'Mixed'},
        )

    def test_fab_and_settings_clean(self):
        dash = open(
            os.path.join(ROOT, 'desktop', 'tabs', 'dashboard_tab.py'), encoding='utf-8'
        ).read()
        start = dash.find('def _install_fab')
        end = dash.find('def resizeEvent', start)
        fab = dash[start:end]
        low = fab.lower()
        self.assertNotIn('purchase', low)
        self.assertNotIn('stk', low)
        self.assertNotIn('return', low)

        settings = open(
            os.path.join(ROOT, 'desktop', 'tabs', 'settings_tab.py'), encoding='utf-8'
        ).read()
        self.assertIn('self.mpesa_mode.hide()', settings)
        self.assertIn('STK Push is not implemented', settings)

        sales = open(
            os.path.join(ROOT, 'desktop', 'tabs', 'sales_tab.py'), encoding='utf-8'
        ).read()
        panel = open(
            os.path.join(ROOT, 'desktop', 'pos', 'panel_factory.py'), encoding='utf-8'
        ).read()
        self.assertIn('_open_return_sale', sales)
        self.assertIn('prompt_return_sale', sales)
        self.assertIn('Return / Exchange', panel)


if __name__ == '__main__':
    unittest.main()
