"""P10: durable single-slot hold — save / load / clear under app data."""
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


def _sample_snap(n=1):
    cart = [
        {
            'product_id': i,
            'name': f'Item {i}',
            'quantity': float(i),
            'unit_price': 100.0 * i,
            'discount': 0.0,
            'total': 100.0 * i * i,
        }
        for i in range(1, n + 1)
    ]
    return {
        'cart': cart,
        'customer_id': 42,
        'disc': '5',
        'note': 'parked',
        'payment': 'M-Pesa',
        'credit_to_apply': 10.5,
    }


class HeldSaleDurableUnit(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._root = self._tmpdir.name
        self._data = os.path.join(self._root, 'data')
        os.makedirs(self._data, exist_ok=True)
        self._patches = [
            patch('mbt_paths.get_project_root', return_value=self._root),
            patch('mbt_paths.get_data_dir', return_value=self._data),
            patch(
                'mbt_paths.ensure_data_dirs',
                side_effect=lambda root=None: self._root,
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_save_load_clear(self):
        from desktop.utils.held_sale import (
            clear_held_sale,
            held_sale_path,
            load_held_sale,
            save_held_sale,
        )

        self.assertIsNone(load_held_sale())
        snap = _sample_snap(2)
        self.assertTrue(save_held_sale(snap))
        path = held_sale_path()
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.startswith(self._data))

        loaded = load_held_sale()
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded['cart']), 2)
        self.assertEqual(loaded['customer_id'], 42)
        self.assertEqual(loaded['payment'], 'M-Pesa')
        self.assertEqual(loaded['credit_to_apply'], 10.5)
        self.assertEqual(loaded['note'], 'parked')

        clear_held_sale()
        self.assertFalse(os.path.isfile(path))
        self.assertIsNone(load_held_sale())

    def test_save_rejects_empty_cart(self):
        from desktop.utils.held_sale import load_held_sale, save_held_sale

        self.assertFalse(save_held_sale({'cart': []}))
        self.assertFalse(save_held_sale({}))
        self.assertIsNone(load_held_sale())

    def test_survives_tab_recreate_simulation(self):
        """Session + disk: hold on tab A, new tab B restores from disk."""
        from desktop.utils import held_sale as hs
        from desktop.tabs.sales_tab import SalesTab

        # Tab A parks
        tab_a = SimpleNamespace(
            cart=_sample_snap(1)['cart'],
            _held=None,
            _credit_to_apply=0.0,
            _customer=SimpleNamespace(selected_id=lambda: 7),
            _disc=SimpleNamespace(text=lambda: '0'),
            _note=SimpleNamespace(text=lambda: 'note-a'),
            _pay=SimpleNamespace(currentText=lambda: 'Cash'),
        )
        tab_a._snapshot_pos = lambda: SalesTab._snapshot_pos(tab_a)
        snap = tab_a._snapshot_pos()
        self.assertTrue(hs.save_held_sale(snap))

        # Tab B (recreate) loads from disk — no in-memory handoff
        tab_b_held = hs.load_held_sale()
        self.assertIsNotNone(tab_b_held)
        self.assertEqual(len(tab_b_held['cart']), 1)
        self.assertEqual(tab_b_held['customer_id'], 7)
        self.assertEqual(tab_b_held['note'], 'note-a')

        # Resume clears durable slot
        hs.clear_held_sale()
        self.assertIsNone(hs.load_held_sale())


if __name__ == '__main__':
    unittest.main()
