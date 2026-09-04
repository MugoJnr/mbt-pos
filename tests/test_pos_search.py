"""POS checkout product search — ranking, None-safe fields, category fallback."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desktop.utils.pos_search import filter_pos_products, match_score, normalize_query


def _p(pid, name, sku='', barcode='', category='General', stock=10):
    return {
        'id': pid, 'name': name, 'sku': sku, 'barcode': barcode,
        'category': category, 'stock': stock, 'is_active': 1, 'price': 10,
    }


CATALOG = [
    _p(1, 'Zambia Sugar 1kg', 'SUG-1', '6161100123456', 'Grocery', 20),
    _p(2, 'DAP Fertilizer 50kg', 'DAP-50', '6161100999999', 'Fertilizer', 8),
    _p(3, None, 'NULL-NAME', '999', 'Grocery', 4),  # bad row must not crash
    _p(4, 'Sunlight Soap', 'SOAP-1', '  6161-1001  ', 'Hygiene', 12),
    _p(5, 'Sugar Baby Powder', 'SUG-B', '111', 'Hygiene', 3),
    *[_p(100 + i, f'Alpha Filler {i:03d}', f'AF-{i}', '', 'Grocery', 1) for i in range(80)],
]


class PosSearchTests(unittest.TestCase):
    def test_normalize_collapses_whitespace(self):
        self.assertEqual(normalize_query('  DAP   Fert  '), 'dap fert')

    def test_none_name_does_not_crash(self):
        hits = filter_pos_products(CATALOG, 'null-name')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['sku'], 'NULL-NAME')

    def test_partial_name_ranks_target_first_not_alpha_cap(self):
        hits = filter_pos_products(CATALOG, 'zambia', limit=48)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['id'], 1)

    def test_sku_and_barcode_partial(self):
        by_sku = filter_pos_products(CATALOG, 'dap-5')
        self.assertEqual(by_sku[0]['id'], 2)
        by_bar = filter_pos_products(CATALOG, '616110012')
        self.assertEqual(by_bar[0]['id'], 1)

    def test_barcode_ignores_spaces_and_dashes(self):
        hits = filter_pos_products(CATALOG, '61611001')
        ids = [p['id'] for p in hits]
        self.assertIn(4, ids)

    def test_search_finds_item_outside_selected_category(self):
        def cat_match(p):
            return (p.get('category') or '') == 'Fertilizer'
        hits = filter_pos_products(
            CATALOG, 'sunlight', category='Fertilizer', cat_match=cat_match)
        self.assertTrue(hits)
        self.assertEqual(hits[0]['id'], 4)

    def test_browse_still_respects_category(self):
        def cat_match(p):
            return (p.get('category') or '') == 'Fertilizer'
        hits = filter_pos_products(
            CATALOG, '', category='Fertilizer', cat_match=cat_match)
        self.assertEqual([p['id'] for p in hits], [2])

    def test_exact_barcode_beats_name_substring(self):
        self.assertEqual(match_score('6161100123456', CATALOG[0]), 0)
        hits = filter_pos_products(CATALOG, '6161100123456')
        self.assertEqual(hits[0]['id'], 1)

    def test_in_stock_sellable_not_dropped(self):
        hits = filter_pos_products(CATALOG, 'soap')
        self.assertTrue(any(p['id'] == 4 for p in hits))

    def test_indexed_catalog_matches_unindexed(self):
        from desktop.utils.pos_search import index_catalog_for_search
        plain = filter_pos_products(CATALOG, 'zambia', limit=10)
        indexed = index_catalog_for_search([dict(p) for p in CATALOG])
        hits = filter_pos_products(indexed, 'zambia', limit=10)
        self.assertEqual([p['id'] for p in hits], [p['id'] for p in plain])
        self.assertIn('_sx', indexed[0])


if __name__ == '__main__':
    unittest.main()
