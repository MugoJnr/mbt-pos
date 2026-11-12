"""A short cost record must not stop a sale that has physical stock."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CostCoverageReleaseTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "coverage.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        os.environ["MBT_TEST_INSTANCE"] = "1"
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ("owner", ac._hash_pw("owner-pass"), "superadmin", "Owner"),
        )
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, is_active) "
            "VALUES (?,?,?,?,1)",
            ("cashier", ac._hash_pw("cashier-pass"), "cashier", "Cashier"),
        )
        db.commit()
        db.close()
        import backend.app as appmod
        appmod.DB_PATH = self._db_path
        self.client = appmod.app.test_client()
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._username = "owner"
        self.api._user_id = 1
        self.today = date.today().isoformat()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _product(self, name, stock, cost=0, price=200):
        created = self.api.create_product({
            "name": name, "sku": name[:12], "price": price, "cost_price": cost, "stock": 0,
        })
        self.assertTrue(created.get("success"), created)
        db = self.ac._db()
        try:
            db.execute("UPDATE products SET stock=? WHERE id=?", (stock, created["id"]))
            db.commit()
        finally:
            db.close()
        return created["id"]

    def _layer(self, product_id, qty, cost, source):
        from desktop.utils.stock_layers import add_layer
        db = self.ac._db()
        try:
            added = add_layer(db, product_id, qty, cost, "purchase", source)
            db.commit()
        finally:
            db.close()
        self.assertTrue(added.get("success"), added)

    def _sell(self, product_id, qty, token, price=200, **extra):
        total = round(qty * price - float(extra.pop("discount", 0) or 0), 2)
        payload = {
            "items": [{
                "product_id": product_id, "quantity": qty, "unit_price": price,
                "discount": extra.pop("line_discount", 0), "total": total,
            }],
            "subtotal": round(qty * price, 2),
            "discount": 0, "tax": 0, "total": total,
            "payment_method": "Cash", "amount_paid": total,
            "client_token": token,
        }
        payload.update(extra)
        sale = self.api.create_sale(payload)
        self.assertTrue(sale.get("success"), sale)
        self.assertNotIn("cost layer", str(sale.get("error", "")).lower())
        return sale

    def _covered(self, sale_id):
        db = self.ac._db()
        try:
            row = db.execute(
                "SELECT COALESCE(SUM(quantity),0), COALESCE(SUM(quantity*unit_cost),0) "
                "FROM cost_layer_uses WHERE sale_id=? AND COALESCE(reversed,0)=0",
                (sale_id,),
            ).fetchone()
            stock_rows = db.execute("SELECT id, stock FROM products").fetchall()
        finally:
            db.close()
        return float(row[0]), float(row[1]), {int(item["id"]): float(item["stock"]) for item in stock_rows}

    def test_full_partial_none_and_physical_stock(self):
        from desktop.utils.financials import compute_financials
        full = self._product("Full Sugar", 20, cost=999)
        self._layer(full, 20, 40, "full")
        sale = self._sell(full, 5, "cov-full", price=100)
        covered, cogs, stocks = self._covered(sale["sale_id"])
        self.assertEqual(covered, 5)
        self.assertEqual(cogs, 200)
        self.assertEqual(stocks[full], 15)

        partial = self._product("Partial Sugar", 20, cost=999)
        self._layer(partial, 10, 100, "partial")
        sale = self._sell(partial, 15, "cov-partial")
        covered, cogs, stocks = self._covered(sale["sale_id"])
        self.assertEqual(covered, 10)
        self.assertEqual(cogs, 1000)
        self.assertEqual(stocks[partial], 5)

        bare = self._product("Bare Sugar", 20, cost=999)
        sale = self._sell(bare, 10, "cov-none")
        covered, cogs, stocks = self._covered(sale["sale_id"])
        self.assertEqual(covered, 0)
        self.assertEqual(cogs, 0)
        self.assertEqual(stocks[bare], 10)
        db = self.ac._db()
        try:
            fake = db.execute(
                "SELECT COUNT(*) FROM cost_layers WHERE source_type IN ('product_card','reconciliation')"
            ).fetchone()[0]
            zero = db.execute(
                "SELECT COUNT(*) FROM cost_layers WHERE unit_cost<=0"
            ).fetchone()[0]
            figures = compute_financials(db, self.today, self.today)
        finally:
            db.close()
        self.assertEqual(int(fake), 0)
        self.assertEqual(int(zero), 0)
        self.assertGreater(figures["uncosted_units"], 0)
        self.assertIsNone(figures["net_operating_result"])
        blocked = self.api.create_sale({
            "items": [{"product_id": bare, "quantity": 80, "unit_price": 200, "total": 16000}],
            "subtotal": 16000, "discount": 0, "tax": 0, "total": 16000,
            "payment_method": "Cash", "amount_paid": 16000, "client_token": "cov-short-stock",
        })
        self.assertIn("Insufficient stock", blocked.get("error", ""))

    def test_multiple_batches_keep_their_own_prices(self):
        product = self._product("Mixed Sugar", 15, cost=999)
        self._layer(product, 5, 50, "old")
        self._layer(product, 5, 70, "new")
        sale = self._sell(product, 12, "cov-mixed")
        db = self.ac._db()
        try:
            uses = db.execute(
                "SELECT quantity, unit_cost FROM cost_layer_uses "
                "WHERE sale_id=? AND COALESCE(reversed,0)=0 ORDER BY id",
                (sale["sale_id"],),
            ).fetchall()
            stock = db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual([(float(row[0]), float(row[1])) for row in uses], [(5, 50), (5, 70)])
        self.assertEqual(float(stock), 3)

    def test_later_delivery_does_not_reprice_old_uncosted_units(self):
        product = self._product("Aged Sugar", 10, cost=999)
        supplier = self.api.create_supplier({"name": "Mill"})
        received = self.api.receive_delivery(
            supplier["id"], [{"product_id": product, "quantity": 20, "unit_cost": 80}],
        )
        self.assertTrue(received.get("success"), received)
        sale = self._sell(product, 15, "cov-later")
        db = self.ac._db()
        try:
            uses = db.execute(
                "SELECT quantity, unit_cost FROM cost_layer_uses WHERE sale_id=? AND COALESCE(reversed,0)=0",
                (sale["sale_id"],),
            ).fetchall()
            remaining = db.execute(
                "SELECT COALESCE(SUM(remaining_qty),0) FROM cost_layers WHERE product_id=?",
                (product,),
            ).fetchone()[0]
            stock = db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual([(float(row[0]), float(row[1])) for row in uses], [(15, 80)])
        self.assertEqual(float(remaining), 5)
        self.assertEqual(float(stock), 15)
        self.assertEqual(float(stock) - float(remaining), 10)

    def test_discount_and_payment_methods_do_not_need_a_full_cost_record(self):
        product = self._product("Pay Sugar", 30, cost=999)
        self._layer(product, 2, 10, "tiny")
        customer = self.api.create_customer({"name": "Amina", "phone": "0700000001"})
        self.assertTrue(customer.get("success"), customer)
        cash = self._sell(product, 1, "pay-cash", price=100, line_discount=10)
        mpesa = self._sell(product, 1, "pay-mpesa", price=100, payment_method="M-Pesa", mpesa_ref="QA12345")
        card = self._sell(product, 1, "pay-card", price=100, payment_method="Card")
        split = self._sell(
            product, 1, "pay-split", price=100, payment_method="Cash",
            cash_paid=40, electronic_paid=60, electronic_method="M-Pesa",
            payment_tenders=[
                {"method": "Cash", "amount": 40},
                {"method": "M-Pesa", "amount": 30},
                {"method": "Card", "amount": 30},
            ],
        )
        credit = self._sell(
            product, 1, "pay-credit", price=100, payment_method="Credit Sale",
            amount_paid=0, customer_id=customer.get("customer_id") or customer.get("id"),
        )
        self.assertTrue(all(item.get("success") for item in (cash, mpesa, card, split, credit)))
        again = self.api.create_sale({
            "items": [{"product_id": product, "quantity": 1, "unit_price": 100, "total": 100}],
            "subtotal": 100, "discount": 0, "tax": 0, "total": 100,
            "payment_method": "Cash", "amount_paid": 100, "client_token": "pay-cash",
        })
        self.assertTrue(again.get("success") or again.get("duplicate"), again)
        db = self.ac._db()
        try:
            copies = db.execute(
                "SELECT COUNT(*) FROM sales WHERE client_token='pay-cash'"
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(int(copies), 1)

    def test_adjustment_and_consumption_are_not_blocked(self):
        product = self._product("Use Sugar", 10, cost=0)
        self._layer(product, 1, 25, "one")
        adjusted = self.api.adjust_stock(product, 6, "Count was short", pin="0000")
        self.assertTrue(adjusted.get("success"), adjusted)
        db = self.ac._db()
        try:
            db.execute("INSERT INTO departments (name, active) VALUES ('Shop', 1)")
            db.commit()
            dept = db.execute("SELECT id FROM departments").fetchone()["id"]
            stock = db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"]
        finally:
            db.close()
        self.assertEqual(float(stock), 6)
        used = self.api.create_consumption({
            "date": self.today, "department_id": dept, "reason": "Staff tea",
            "items": [{"product_id": product, "quantity": 3}],
        })
        self.assertTrue(used.get("success"), used)
        db = self.ac._db()
        try:
            stock = db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"]
            zero = db.execute("SELECT COUNT(*) FROM cost_layers WHERE unit_cost<=0").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(float(stock), 3)
        self.assertEqual(int(zero), 0)

    def test_concurrent_sales_do_not_share_one_cost_quantity(self):
        product = self._product("Race Sugar", 20, cost=999)
        self._layer(product, 10, 100, "race")
        results = []

        def sell(token):
            client = self.ac.APIClient()
            client._role = "superadmin"
            client._username = "owner"
            client._user_id = 1
            results.append(client.create_sale({
                "items": [{"product_id": product, "quantity": 8, "unit_price": 200, "total": 1600}],
                "subtotal": 1600, "discount": 0, "tax": 0, "total": 1600,
                "payment_method": "Cash", "amount_paid": 1600, "client_token": token,
            }))

        threads = [threading.Thread(target=sell, args=(f"race-{n}",)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(all(item.get("success") for item in results), results)
        db = self.ac._db()
        try:
            stock = db.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()["stock"]
            covered = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM cost_layer_uses WHERE product_id=? AND COALESCE(reversed,0)=0",
                (product,),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertEqual(float(stock), 4)
        self.assertEqual(float(covered), 10)

    def test_backup_copy_keeps_the_partial_cost_sale(self):
        product = self._product("Backup Sugar", 20, cost=999)
        self._layer(product, 10, 100, "backup")
        sale = self._sell(product, 15, "cov-backup")
        copy_path = os.path.join(self._tmpdir.name, "restored.db")
        shutil.copy(self._db_path, copy_path)
        check = sqlite3.connect(copy_path)
        try:
            stock = check.execute("SELECT stock FROM products WHERE id=?", (product,)).fetchone()[0]
            covered = check.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM cost_layer_uses WHERE sale_id=?",
                (sale["sale_id"],),
            ).fetchone()[0]
            total = check.execute("SELECT total FROM sales WHERE id=?", (sale["sale_id"],)).fetchone()[0]
        finally:
            check.close()
        self.assertEqual(float(stock), 5)
        self.assertEqual(float(covered), 10)
        self.assertEqual(float(total), 3000)
