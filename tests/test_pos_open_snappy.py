"""POS open path: catalog cache + deferred grid (no full rebuild every show)."""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PosOpenCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'data' / 'mbt_pos.db'
        if not db.exists():
            db = Path(os.environ.get('LOCALAPPDATA', '')) / 'MugoByte' / 'MBT POS' / 'mbt_pos.db'
        if not db.exists():
            raise unittest.SkipTest(f'no local db at {db}')
        cls.db_path = str(db)

    def setUp(self):
        # Fresh tab per test — avoids pollution from other modules' DB patches.
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        from desktop.utils.api_client import APIClient
        from desktop.tabs.sales_tab import SalesTab
        self.api = APIClient(self.db_path)
        self.tab = SalesTab(
            self.api,
            {'id': 1, 'username': 'admin', 'role': 'superadmin', 'full_name': 'T'},
            self.db_path,
            lambda: {},
        )

    def test_on_show_skips_db_when_catalog_fresh(self):
        tab = self.tab
        tab.refresh(force=True, defer_grid=False)
        self.app.processEvents()
        self.assertTrue(
            tab._catalog_is_fresh(),
            f'catalog not fresh after force refresh '
            f'(loaded={tab._catalog_loaded} mono={tab._catalog_mono} n={len(tab.products or [])})',
        )
        self.assertTrue(tab._grid_painted)
        with mock.patch.object(tab.api, 'get_products', wraps=tab.api.get_products) as gp:
            tab.on_show()
            self.app.processEvents()
            # Soft path: no scheduled refresh needed when fresh+painted
            self.assertEqual(gp.call_count, 0)

    def test_second_refresh_is_noop_without_force(self):
        tab = self.tab
        tab.refresh(force=True, defer_grid=False)
        self.app.processEvents()
        self.assertTrue(tab._catalog_is_fresh())
        with mock.patch.object(tab.api, 'get_products') as gp:
            tab.refresh()  # force=False, fresh cache
            gp.assert_not_called()

    def test_force_refresh_reloads(self):
        tab = self.tab
        tab.refresh(force=True, defer_grid=False)
        with mock.patch.object(tab.api, 'get_products', return_value=list(tab.products)) as gp:
            tab.refresh(force=True, defer_grid=False)
            gp.assert_called_once()

    def test_chunked_populate_accepts_flag(self):
        tab = self.tab
        tab.refresh(force=True, defer_grid=False)
        grid = tab._prod_grid
        sample = (tab.products or [{}])[:20]
        t0 = time.perf_counter()
        grid.populate(sample, columns=3, chunked=True)
        first_ms = (time.perf_counter() - t0) * 1000
        # First batch should return quickly (< full sync paint of 48 cards)
        self.assertLess(first_ms, 400)


class CustomerPopupGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_rebuild_without_focus_does_not_show_popup(self):
        from desktop.utils.pos_components import CustomerSelector
        sel = CustomerSelector()
        sel.hide()
        sel._all = [('Walk-in Customer', None), ('Jane', 1), ('John', 2)]
        with mock.patch.object(sel, 'showPopup') as sp:
            sel._rebuild(keep=None, query='j')
            sp.assert_not_called()


if __name__ == '__main__':
    unittest.main()
