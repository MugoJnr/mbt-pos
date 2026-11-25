"""Inventory filters classify stock and sort a copy of the list."""
import unittest

from desktop.utils.inventory_filters import (
    UNCATEGORISED,
    filter_inventory,
    sort_inventory,
    stock_band,
)


def product(**kwargs):
    base = {
        "id": 1,
        "name": "Item",
        "sku": "",
        "barcode": "",
        "category": "",
        "stock": 0,
        "min_stock": 5,
        "price": 10,
        "created_at": "",
        "updated_at": "",
    }
    base.update(kwargs)
    return base


class StockBandTests(unittest.TestCase):
    def test_bands_follow_each_products_threshold(self):
        self.assertEqual(stock_band(product(stock=6, min_stock=5)), "in")
        self.assertEqual(stock_band(product(stock=5, min_stock=5)), "low")
        self.assertEqual(stock_band(product(stock=0.4, min_stock=1)), "low")
        self.assertEqual(stock_band(product(stock=1.5, min_stock=1)), "in")
        self.assertEqual(stock_band(product(stock=0, min_stock=5)), "out")
        self.assertEqual(stock_band(product(stock=-2, min_stock=5)), "out")
        self.assertEqual(stock_band(product(stock=3, min_stock=None)), "in")
        self.assertEqual(stock_band(product(stock=0.25, min_stock=0)), "in")

    def test_filters_combine_and_search_identifiers(self):
        rows = [
            product(id=1, name="Dairy Meal", sku="DM-70", barcode="111", category="Animal Feeds", stock=4.5, min_stock=2),
            product(id=2, name="NPK", sku="NPK-1", barcode="222", category="Fertilizers", stock=1, min_stock=3),
            product(id=3, name="Nails", sku="NAIL", barcode="333", category="General Supplies", stock=12, min_stock=4),
            product(id=4, name="Loose Salt", sku="SALT", barcode="444", category="", stock=0, min_stock=1),
            product(id=5, name="Empty Sack", sku="SACK", barcode="555", category="General Supplies", stock=0, min_stock=2),
        ]
        feeds_out = filter_inventory(rows, status="out", category="Animal Feeds")
        self.assertEqual(feeds_out, [])
        fert_low = filter_inventory(rows, status="low", category="Fertilizers")
        self.assertEqual([row["id"] for row in fert_low], [2])
        supplies_in = filter_inventory(rows, status="in", category="General Supplies")
        self.assertEqual([row["id"] for row in supplies_in], [3])
        uncategorised = filter_inventory(rows, category=UNCATEGORISED)
        self.assertEqual([row["name"] for row in sort_inventory(uncategorised, "name_asc")], ["Loose Salt"])
        self.assertEqual([row["id"] for row in filter_inventory(rows, query="dm-70")], [1])
        self.assertEqual([row["id"] for row in filter_inventory(rows, query="333", status="in")], [3])
        combined = filter_inventory(rows, query="sack", status="out", category="General Supplies")
        self.assertEqual([row["id"] for row in combined], [5])

    def test_sort_keeps_filters_and_does_not_rewrite_records(self):
        rows = [
            product(id=1, name="B", stock=2, created_at="2026-11-01", updated_at="2026-11-03"),
            product(id=2, name="A", stock=9, created_at="2026-11-20", updated_at="2026-11-02"),
            product(id=3, name="C", stock=0.5, created_at="", updated_at="2026-11-21"),
        ]
        original = [row["id"] for row in rows]
        self.assertEqual([row["name"] for row in sort_inventory(rows, "name_asc")], ["A", "B", "C"])
        self.assertEqual([row["name"] for row in sort_inventory(rows, "name_desc")], ["C", "B", "A"])
        self.assertEqual([row["id"] for row in sort_inventory(rows, "stock_asc")], [3, 1, 2])
        self.assertEqual([row["id"] for row in sort_inventory(rows, "stock_desc")], [2, 1, 3])
        self.assertEqual([row["id"] for row in sort_inventory(rows, "created")], [2, 1, 3])
        self.assertEqual([row["id"] for row in sort_inventory(rows, "updated")], [3, 1, 2])
        self.assertEqual([row["id"] for row in rows], original)
        self.assertEqual(rows[0]["stock"], 2)

    def test_hundreds_of_products_stay_unique(self):
        rows = []
        categories = ("Animal Feeds", "Fertilizers", "General Supplies", "")
        for index in range(400):
            stock = [0, 1, 8, -1][index % 4]
            rows.append(product(
                id=index + 1,
                name=f"Product {index:03d}",
                sku=f"SKU-{index:03d}",
                barcode=f"BC{index:04d}",
                category=categories[index % 4],
                stock=stock + (0.5 if index % 5 == 0 else 0),
                min_stock=2,
                created_at=f"2026-01-{(index % 28) + 1:02d}T00:00:00",
                updated_at=f"2026-02-{(index % 28) + 1:02d}T00:00:00",
            ))
        matched = filter_inventory(rows, query="sku-12", status="all", category="all")
        self.assertTrue(any(row["sku"] == "SKU-012" for row in matched) or any(row["sku"] == "SKU-120" for row in matched))
        low_feeds = sort_inventory(
            filter_inventory(rows, status="low", category="Animal Feeds"),
            "stock_asc",
        )
        ids = [row["id"] for row in low_feeds]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(stock_band(row) == "low" for row in low_feeds))
        self.assertEqual(low_feeds, sorted(low_feeds, key=lambda row: (float(row["stock"]), row["name"].casefold())))


if __name__ == "__main__":
    unittest.main()
