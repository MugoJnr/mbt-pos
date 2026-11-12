"""Profit uses recorded cost only. A missing cost stays visible and is not invented."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ProfitIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "profit.db")
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

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _login(self, username, password):
        response = self.client.post(
            "/api/auth/login", json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def test_landed_cost_sale_matches_the_worked_example(self):
        created = self.api.create_product({
            "name": "Product A", "sku": "QA-A", "price": 100, "cost_price": 60, "stock": 0,
        })
        self.assertTrue(created.get("success"), created)
        supplier = self.api.create_supplier({"name": "QA Supplies"})
        self.assertTrue(supplier.get("success"), supplier)
        received = self.api.receive_delivery(
            supplier["id"],
            [{"product_id": created["id"], "quantity": 3, "unit_cost": 60}],
            delivery_extra=15,
            reference="INV-A",
        )
        self.assertTrue(received.get("success"), received)
        sale = self.api.create_sale({
            "items": [{"product_id": created["id"], "quantity": 3, "unit_price": 100}],
            "subtotal": 300, "discount": 0, "tax": 0, "total": 300,
            "payment_method": "Cash", "amount_paid": 300,
            "client_token": "landed-a",
        })
        self.assertTrue(sale.get("success"), sale)
        self.assertEqual(sale.get("total") or 300, 300)
        today = date.today().isoformat()
        from desktop.utils.financials import compute_financials
        db = self.ac._db()
        try:
            layer = db.execute(
                "SELECT unit_cost, purchase_unit_cost, extra_unit_cost FROM cost_layers"
            ).fetchone()
            self.assertEqual(float(layer["unit_cost"]), 65)
            self.assertEqual(float(layer["purchase_unit_cost"]), 60)
            self.assertEqual(float(layer["extra_unit_cost"]), 5)
            figures = compute_financials(db, today, today)
            stored = db.execute("SELECT total FROM sales").fetchone()
        finally:
            db.close()
        self.assertEqual(stored["total"], 300)
        self.assertEqual(figures["total_sales"], 300)
        self.assertEqual(figures["cogs"], 195)
        self.assertEqual(figures["gross_profit"], 105)
        self.assertEqual(figures["uncosted_lines"], 0)
        self.assertEqual(figures["net_operating_result"], 105)

    def test_product_card_cost_is_snapshotted_and_a_blank_cost_stays_unknown(self):
        priced = self.api.create_product({
            "name": "Card Soap", "sku": "QA-CARD", "price": 100, "cost_price": 40, "stock": 0,
        })
        blank = self.api.create_product({
            "name": "Unknown Soap", "sku": "QA-UNK", "price": 80, "cost_price": 0, "stock": 0,
        })
        db = self.ac._db()
        db.execute("UPDATE products SET stock=2 WHERE id=?", (priced["id"],))
        db.execute("UPDATE products SET stock=1 WHERE id=?", (blank["id"],))
        db.commit()
        db.close()
        card_sale = self.api.create_sale({
            "items": [{"product_id": priced["id"], "quantity": 2, "unit_price": 100}],
            "subtotal": 200, "discount": 0, "tax": 0, "total": 200,
            "payment_method": "Cash", "amount_paid": 200,
            "client_token": "card-cost",
        })
        self.assertTrue(card_sale.get("success"), card_sale)
        bare_sale = self.api.create_sale({
            "items": [{"product_id": blank["id"], "quantity": 1, "unit_price": 80}],
            "subtotal": 80, "discount": 0, "tax": 0, "total": 80,
            "payment_method": "Cash", "amount_paid": 80,
            "client_token": "no-cost",
        })
        self.assertTrue(bare_sale.get("success"), bare_sale)
        today = date.today().isoformat()
        from desktop.utils.financials import compute_financials
        db = self.ac._db()
        try:
            source = db.execute(
                "SELECT COUNT(*) AS n FROM cost_layers WHERE product_id=?",
                (priced["id"],),
            ).fetchone()
            self.assertEqual(int(source["n"]), 0)
            figures = compute_financials(db, today, today)
            listed = None
        finally:
            db.close()
        self.assertEqual(figures["cogs"], 0)
        self.assertEqual(figures["gross_profit"], 0)
        self.assertEqual(figures["uncosted_lines"], 2)
        self.assertEqual(figures["uncosted_sales"], 280)
        self.assertIsNone(figures["net_operating_result"])
        owner = self._login("owner", "owner-pass")
        body = self.client.get(
            f"/api/cost-reconciliation?start={today}&end={today}", headers=owner,
        )
        self.assertEqual(body.status_code, 200, body.get_json())
        listed = body.get_json()
        self.assertEqual(listed["lines"], 2)
        self.assertEqual(listed["revenue"], 280)
        self.assertEqual(listed["categories"]["no_buying_price"]["lines"], 1)
        cashier = self._login("cashier", "cashier-pass")
        hidden = self.client.get(
            f"/api/cost-reconciliation?start={today}&end={today}", headers=cashier,
        )
        self.assertEqual(hidden.status_code, 403)
        denied = self.client.post("/api/cost-reconciliation", headers=cashier, json={
            "sale_id": bare_sale["sale_id"], "product_id": blank["id"],
            "unit_cost": 30, "reason": "Guess",
        })
        self.assertEqual(denied.status_code, 403)
        corrected = self.client.post("/api/cost-reconciliation", headers=owner, json={
            "sale_id": bare_sale["sale_id"], "product_id": blank["id"],
            "unit_cost": 30, "reason": "Supplier invoice 9", "evidence": "INV-9",
        })
        self.assertEqual(corrected.status_code, 200, corrected.get_json())
        self.assertEqual(corrected.get_json()["sale_total"], 80)
        again = self.client.post("/api/cost-reconciliation", headers=owner, json={
            "sale_id": bare_sale["sale_id"], "product_id": blank["id"],
            "unit_cost": 10, "reason": "Second attempt",
        })
        self.assertEqual(again.status_code, 400)
        db = self.ac._db()
        try:
            from desktop.utils.financials import compute_financials as compute
            after = compute(db, today, today)
            total = db.execute(
                "SELECT total FROM sales WHERE id=?", (bare_sale["sale_id"],),
            ).fetchone()
            audit = db.execute("SELECT reason, new_unit_cost, username FROM cost_reconciliations").fetchone()
        finally:
            db.close()
        self.assertEqual(total["total"], 80)
        self.assertEqual(after["uncosted_lines"], 1)
        self.assertEqual(after["cogs"], 30)
        self.assertEqual(after["gross_profit"], 50)
        self.assertEqual(audit["reason"], "Supplier invoice 9")
        self.assertEqual(float(audit["new_unit_cost"]), 30)
        self.assertEqual(audit["username"], "owner")

    def test_web_sale_uses_the_same_cost_snapshot(self):
        created = self.api.create_product({
            "name": "Web Soap", "sku": "QA-WEB", "price": 50, "cost_price": 20, "stock": 1,
        })
        headers = self._login("owner", "owner-pass")
        sale = self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": created["id"], "quantity": 1, "unit_price": 50}],
            "subtotal": 50, "discount": 0, "tax": 0, "total": 50,
            "payment_method": "cash", "amount_paid": 50,
            "client_token": "web-card-cost",
        })
        self.assertEqual(sale.status_code, 200, sale.get_json())
        today = date.today().isoformat()
        summary = self.client.get(
            f"/api/reports/summary?start={today}&end={today}", headers=headers,
        )
        body = summary.get_json()["summary"]
        self.assertEqual(body["gross_profit"], 30)
        self.assertEqual(body["cogs"], 20)
        self.assertEqual(body["uncosted_lines"], 0)
        self.assertNotIn("gross_profit", self.client.get(
            f"/api/reports/summary?start={today}&end={today}",
            headers=self._login("cashier", "cashier-pass"),
        ).get_json()["summary"])

    def test_missing_sale_journal_uses_recorded_cost_and_matches_the_register(self):
        priced = self.api.create_product({
            "name": "Layered Item", "sku": "QA-J1", "price": 100,
            "cost_price": 40, "stock": 0,
        })
        self.assertTrue(priced.get("success"), priced)
        blank = self.api.create_product({
            "name": "No Cost Item", "sku": "QA-J2", "price": 50,
            "cost_price": 0, "stock": 0,
        })
        self.assertTrue(blank.get("success"), blank)
        from desktop.utils.stock_layers import add_layer
        db = self.ac._db()
        try:
            db.execute("UPDATE products SET stock=2 WHERE id=?", (priced["id"],))
            db.execute("UPDATE products SET stock=1 WHERE id=?", (blank["id"],))
            added = add_layer(db, priced["id"], 2, 40, "purchase", "journal-layer")
            db.commit()
        finally:
            db.close()
        self.assertTrue(added.get("success"), added)
        known = self.api.create_sale({
            "items": [{"product_id": priced["id"], "quantity": 2, "unit_price": 100}],
            "subtotal": 200, "discount": 0, "tax": 0, "total": 200,
            "payment_method": "Cash", "amount_paid": 200,
            "client_token": "journal-known",
        })
        unknown = self.api.create_sale({
            "items": [{"product_id": blank["id"], "quantity": 1, "unit_price": 50}],
            "subtotal": 50, "discount": 0, "tax": 0, "total": 50,
            "payment_method": "Cash", "amount_paid": 50,
            "client_token": "journal-unknown",
        })
        self.assertTrue(known.get("success"), known)
        self.assertTrue(unknown.get("success"), unknown)
        db = self.ac._db()
        try:
            db.execute("UPDATE products SET cost_price=999 WHERE id=?", (priced["id"],))
            db.execute("UPDATE products SET cost_price=999 WHERE id=?", (blank["id"],))
            db.execute(
                "DELETE FROM journal_lines WHERE journal_id IN "
                "(SELECT id FROM journal_entries WHERE source_module='sales' "
                "AND entry_type='sale')"
            )
            db.execute(
                "DELETE FROM journal_entries WHERE source_module='sales' "
                "AND entry_type='sale'"
            )
            db.commit()
        finally:
            db.close()
        today = date.today().isoformat()
        report = self.api.accounting_pnl(today, today)
        self.assertAlmostEqual(float(report["total_income"]), 250, places=2)
        self.assertAlmostEqual(float(report["total_cogs"]), 80, places=2)
        self.assertAlmostEqual(float(report["register_sales"]), 250, places=2)
        self.assertAlmostEqual(float(report["register_cogs"]), 80, places=2)
        self.assertAlmostEqual(float(report["register_gross"]), 120, places=2)
        self.assertEqual(int(report["register_uncosted_lines"]), 1)
        self.assertAlmostEqual(float(report["register_uncosted_sales"]), 50, places=2)
        again = self.api.accounting_pnl(today, today)
        self.assertAlmostEqual(float(again["total_income"]), 250, places=2)
        self.assertAlmostEqual(float(again["total_cogs"]), 80, places=2)
        db = self.ac._db()
        try:
            known_cost = db.execute(
                "SELECT SUM(quantity * unit_cost) FROM cost_layer_uses WHERE sale_id=? AND COALESCE(reversed,0)=0",
                (known["sale_id"],),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(known_cost), 80, places=2)
        dash = self.api.accounting_dashboard()
        self.assertEqual(int(dash.get("sale_journals_posted") or 0), 0)
        self.assertAlmostEqual(float(dash["register_sales"]), 250, places=2)
        self.assertAlmostEqual(float(dash["month_revenue"]), 250, places=2)

    def test_short_cost_layers_do_not_block_the_sale(self):
        import threading
        from desktop.utils.stock_layers import add_layer
        from desktop.utils.financials import compute_financials

        def shelf(product_id, layers, layer_cost=100):
            created = self.api.create_product({
                "name": f"Bags {product_id}", "sku": f"BAG-{product_id}",
                "price": 200, "cost_price": 999, "stock": 0,
            })
            self.assertTrue(created.get("success"), created)
            db = self.ac._db()
            try:
                db.execute("UPDATE products SET stock=20 WHERE id=?", (created["id"],))
                added = add_layer(db, created["id"], layers, layer_cost, "purchase", f"b-{created['id']}")
                db.commit()
            finally:
                db.close()
            self.assertTrue(added.get("success"), added)
            return created["id"]

        desktop_id = shelf("desk", 10)
        sale = self.api.create_sale({
            "items": [{"product_id": desktop_id, "quantity": 15, "unit_price": 200, "total": 3000}],
            "subtotal": 3000, "discount": 0, "tax": 0, "total": 3000,
            "payment_method": "Cash", "amount_paid": 3000,
            "client_token": "short-desktop",
        })
        self.assertTrue(sale.get("success"), sale)
        self.assertNotIn("cost layer", str(sale.get("error", "")).lower())
        today = date.today().isoformat()
        db = self.ac._db()
        try:
            stock = db.execute("SELECT stock FROM products WHERE id=?", (desktop_id,)).fetchone()["stock"]
            covered = db.execute(
                "SELECT COALESCE(SUM(quantity),0), COALESCE(SUM(quantity*unit_cost),0) "
                "FROM cost_layer_uses WHERE sale_id=? AND COALESCE(reversed,0)=0",
                (sale["sale_id"],),
            ).fetchone()
            fake = db.execute(
                "SELECT COUNT(*) FROM cost_layers WHERE source_type IN ('product_card','reconciliation')"
            ).fetchone()[0]
            figures = compute_financials(db, today, today)
            item_id = db.execute(
                "SELECT id FROM sale_items WHERE sale_id=?", (sale["sale_id"],),
            ).fetchone()["id"]
        finally:
            db.close()
        self.assertAlmostEqual(float(stock), 5, places=2)
        self.assertAlmostEqual(float(covered[0]), 10, places=2)
        self.assertAlmostEqual(float(covered[1]), 1000, places=2)
        self.assertEqual(int(fake), 0)
        self.assertAlmostEqual(figures["cogs"], 1000, places=2)
        self.assertAlmostEqual(figures["gross_profit"], 1000, places=2)
        self.assertAlmostEqual(figures["uncosted_sales"], 1000, places=2)
        self.assertAlmostEqual(figures["uncosted_units"], 5, places=2)
        self.assertEqual(figures["uncosted_products"], 1)
        self.assertIsNone(figures["net_operating_result"])

        web_id = shelf("web", 10)
        headers = self._login("owner", "owner-pass")
        web = self.client.post("/api/sales", headers=headers, json={
            "items": [{"product_id": web_id, "quantity": 15, "unit_price": 200, "total": 3000}],
            "subtotal": 3000, "discount": 0, "tax": 0, "total": 3000,
            "payment_method": "cash", "amount_paid": 3000,
            "client_token": "short-web",
        })
        self.assertEqual(web.status_code, 200, web.get_json())
        db = self.ac._db()
        try:
            web_stock = db.execute("SELECT stock FROM products WHERE id=?", (web_id,)).fetchone()["stock"]
            web_sale = db.execute(
                "SELECT id FROM sales WHERE receipt_number=?",
                (web.get_json()["receipt_number"],),
            ).fetchone()["id"]
        finally:
            db.close()
        self.assertAlmostEqual(float(web_stock), 5, places=2)
        cashier = self._login("cashier", "cashier-pass")
        hidden = self.client.get(
            f"/api/reports/summary?start={today}&end={today}", headers=cashier,
        )
        self.assertNotIn("gross_profit", hidden.get_json().get("summary", {}))
        listed = self.client.get(
            f"/api/cost-reconciliation?start={today}&end={today}", headers=headers,
        ).get_json()
        self.assertGreaterEqual(listed["units"], 5)
        self.assertGreaterEqual(listed["products"], 1)

        voided = self.api.void_sale(int(web_sale), "Wrong bags")
        self.assertTrue(voided.get("success"), voided)
        db = self.ac._db()
        try:
            after_void = db.execute("SELECT stock FROM products WHERE id=?", (web_id,)).fetchone()["stock"]
            left = db.execute(
                "SELECT COALESCE(SUM(remaining_qty),0) FROM cost_layers WHERE product_id=?",
                (web_id,),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(after_void), 20, places=2)
        self.assertAlmostEqual(float(left), 10, places=2)

        returned = self.api.return_sale(
            int(sale["sale_id"]),
            [{"sale_item_id": item_id, "quantity": 5}],
            "Customer changed quantity",
        )
        self.assertTrue(returned.get("success"), returned)
        db = self.ac._db()
        try:
            after_return = db.execute(
                "SELECT stock FROM products WHERE id=?", (desktop_id,),
            ).fetchone()["stock"]
            still = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM cost_layer_uses "
                "WHERE sale_id=? AND COALESCE(reversed,0)=0",
                (sale["sale_id"],),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(after_return), 10, places=2)
        self.assertAlmostEqual(float(still), 5, places=2)

        supplier = self.api.create_supplier({"name": "QA Mill"})
        received = self.api.receive_delivery(
            supplier["id"],
            [{"product_id": desktop_id, "quantity": 10, "unit_cost": 110}],
        )
        self.assertTrue(received.get("success"), received)
        restarted = self.ac.APIClient()
        restarted._role = "superadmin"
        restarted._username = "owner"
        restarted._user_id = 1
        again = restarted.create_sale({
            "items": [{"product_id": desktop_id, "quantity": 1, "unit_price": 200, "total": 200}],
            "subtotal": 200, "discount": 0, "tax": 0, "total": 200,
            "payment_method": "Cash", "amount_paid": 200,
            "client_token": "short-restart",
        })
        self.assertTrue(again.get("success"), again)

        race_id = shelf("race", 10)
        results = []

        def sell(token):
            client = self.ac.APIClient()
            client._role = "superadmin"
            client._username = "owner"
            client._user_id = 1
            results.append(client.create_sale({
                "items": [{"product_id": race_id, "quantity": 8, "unit_price": 200, "total": 1600}],
                "subtotal": 1600, "discount": 0, "tax": 0, "total": 1600,
                "payment_method": "Cash", "amount_paid": 1600,
                "client_token": token,
            }))

        threads = [
            threading.Thread(target=sell, args=("race-a",)),
            threading.Thread(target=sell, args=("race-b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item.get("success") for item in results), results)
        db = self.ac._db()
        try:
            race_stock = db.execute("SELECT stock FROM products WHERE id=?", (race_id,)).fetchone()["stock"]
            race_cost = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM cost_layer_uses u "
                "JOIN sales s ON s.id=u.sale_id WHERE u.product_id=? "
                "AND COALESCE(u.reversed,0)=0 AND COALESCE(s.status,'completed')='completed'",
                (race_id,),
            ).fetchone()[0]
        finally:
            db.close()
        self.assertAlmostEqual(float(race_stock), 4, places=2)
        self.assertAlmostEqual(float(race_cost), 10, places=2)

    def test_backup_round_trip_keeps_the_sale_and_its_cost(self):
        from backend.cloud_backup.encryption import decrypt_file, encrypt_file
        src = os.path.join(self._tmpdir.name, "shop.db")
        db = sqlite3.connect(src)
        db.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, total REAL)")
        db.execute("CREATE TABLE cost_layer_uses (sale_id INTEGER, unit_cost REAL)")
        db.execute("INSERT INTO sales VALUES (1, 300)")
        db.execute("INSERT INTO cost_layer_uses VALUES (1, 65)")
        db.commit()
        db.close()
        folder = os.path.join(self._tmpdir.name, "zip")
        os.makedirs(folder)
        archive = os.path.join(folder, "backup.zip")
        with zipfile.ZipFile(archive, "w") as handle:
            handle.write(src, "mbt_pos.db")
        key = b"0123456789abcdef0123456789abcdef"
        sealed = os.path.join(folder, "backup.mbtenc")
        encrypt_file(archive, sealed, key)
        opened = os.path.join(folder, "opened.zip")
        decrypt_file(sealed, opened, key)
        restored = os.path.join(self._tmpdir.name, "restored.db")
        with zipfile.ZipFile(opened) as handle:
            handle.extract("mbt_pos.db", self._tmpdir.name)
        os.replace(os.path.join(self._tmpdir.name, "mbt_pos.db"), restored)
        check = sqlite3.connect(restored)
        sale = check.execute("SELECT total FROM sales").fetchone()
        cost = check.execute("SELECT unit_cost FROM cost_layer_uses").fetchone()
        check.close()
        self.assertEqual(sale[0], 300)
        self.assertEqual(cost[0], 65)


if __name__ == "__main__":
    unittest.main()
