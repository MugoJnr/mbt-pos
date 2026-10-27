import unittest

from desktop.utils.pos_search import inventory_name_matches
from desktop.utils.pos_components import set_pos_qty_step


class InventoryNameSearchTests(unittest.TestCase):
    def test_name_match_ignores_case_and_spaces(self):
        product = {"name": "Unga Cook", "sku": "SKU-991", "category": "Flour", "cost_price": 12}
        self.assertTrue(inventory_name_matches("unga", product))
        self.assertTrue(inventory_name_matches("UNGA", product))
        self.assertTrue(inventory_name_matches("  UnGa   cook ", product))
        self.assertTrue(inventory_name_matches("cook", product))

    def test_name_search_does_not_use_sku_or_cost(self):
        product = {"name": "Sugar", "sku": "cook", "category": "unga", "cost_price": 150}
        self.assertFalse(inventory_name_matches("cook", product))
        self.assertFalse(inventory_name_matches("unga", product))
        self.assertFalse(inventory_name_matches("150", product))

    def test_empty_search_keeps_every_product(self):
        product = {"name": "Rice"}
        self.assertTrue(inventory_name_matches("", product))
        self.assertTrue(inventory_name_matches("   ", product))

    def test_pos_step_rejects_zero_and_keeps_default(self):
        self.assertEqual(set_pos_qty_step(0.25), 0.25)
        self.assertEqual(set_pos_qty_step(0), 0.25)
        self.assertEqual(set_pos_qty_step(-1), 0.25)
        self.assertEqual(set_pos_qty_step("bad"), 0.25)
        self.assertEqual(set_pos_qty_step(0.5), 0.5)
        set_pos_qty_step(0.25)


if __name__ == "__main__":
    unittest.main()
