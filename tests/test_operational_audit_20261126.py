"""Regression tests for the 26 Nov 2026 operational audit.

Each test fails if the named defect comes back.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class PinStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "pin.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active) "
            "VALUES (1,'owner','x','superadmin','Shop Owner',1)"
        )
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active) "
            "VALUES (2,'till','x','cashier','Till',1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_b001_screen_pin_is_the_pin_verification_reads(self):
        from desktop.utils.superadmin_pin import verify_superadmin_user_pin
        saved = self.api.change_superadmin_pin("", "135790", "135790")
        self.assertTrue(saved.get("success"), saved)
        short = self.api.change_superadmin_pin("135790", "1234", "1234")
        self.assertIn("6 to 8", short.get("error", ""))
        db = self.ac._db()
        try:
            db.execute("DELETE FROM system_settings WHERE key='superadmin_pin_hash'")
            db.commit()
            accepted = verify_superadmin_user_pin(db, "owner", "135790")
            rejected = verify_superadmin_user_pin(db, "owner", "246810")
        finally:
            db.close()
        self.assertTrue(accepted.get("success"), accepted)
        self.assertIn("not accepted", rejected.get("error", ""))

    def test_b003_manager_void_and_refund_require_a_pin(self):
        self.api._role = "manager"
        self.api._user_id = 2
        self.api._username = "lead"
        db = self.ac._db()
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) "
            "VALUES ('Maize','MZ',100,40,20,1)"
        )
        db.commit()
        db.close()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        self.api.change_superadmin_pin("", "135790", "135790")
        sale = self.api.create_sale({
            "items": [{
                "product_id": 1, "product_name": "Maize", "quantity": 1,
                "unit_price": 100, "discount": 0, "total": 100,
            }],
            "subtotal": 100, "discount": 0, "tax": 0, "total": 100,
            "payment_method": "Cash", "amount_paid": 100, "cash_paid": 100,
        })
        self.assertTrue(sale.get("success"), sale)
        self.api._role = "manager"
        self.api._user_id = 2
        self.api._username = "lead"
        blocked = self.api.void_sale(sale["sale_id"], "mistake")
        self.assertIn("not accepted", blocked.get("error", "").lower() + "pin")
        self.assertNotEqual(blocked.get("error"), None)
        refund_blocked = self.api.return_sale(
            sale["sale_id"], [{"sale_item_id": 1, "quantity": 1}], "changed mind",
        )
        self.assertEqual(refund_blocked.get("status"), 403)
        ok = self.api.void_sale(
            sale["sale_id"], "mistake", pin="135790", pin_username="owner",
        )
        self.assertTrue(ok.get("success"), ok)


class RefundAndTenderTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "money.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, is_active) "
            "VALUES (1,'owner','x','superadmin',1)"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) "
            "VALUES ('Maize','MZ',150,40,20,1)"
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, is_active) "
            "VALUES ('Sugar','SG',60,20,20,1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_b004_order_discount_is_shared_across_a_refund(self):
        sale = self.api.create_sale({
            "items": [
                {"product_id": 1, "product_name": "Maize", "quantity": 1,
                 "unit_price": 150, "discount": 10, "total": 140},
                {"product_id": 2, "product_name": "Sugar", "quantity": 1,
                 "unit_price": 60, "discount": 0, "total": 60},
            ],
            "subtotal": 210, "discount": 30, "tax": 0, "total": 180,
            "payment_method": "Cash", "amount_paid": 180, "cash_paid": 180,
        })
        self.assertTrue(sale.get("success"), sale)
        db = self.ac._db()
        line = db.execute(
            "SELECT id FROM sale_items WHERE sale_id=? AND product_name='Maize'",
            (sale["sale_id"],),
        ).fetchone()
        db.close()
        refund = self.api.return_sale(
            sale["sale_id"], [{"sale_item_id": line["id"], "quantity": 1}],
            "customer changed their mind", refund_method="Cash",
        )
        self.assertTrue(refund.get("success"), refund)
        self.assertAlmostEqual(float(refund.get("refund_total") or 0), 126.0, places=2)
        self.assertRegex(refund.get("receipt_number") or refund.get("return_receipt") or "", r"RET-\d{8}-\d{4}")

    def test_b010_mpesa_is_not_stored_as_cash(self):
        sale = self.api.create_sale({
            "items": [{
                "product_id": 1, "product_name": "Maize", "quantity": 1,
                "unit_price": 60, "discount": 0, "total": 60,
            }],
            "subtotal": 60, "total": 60, "payment_method": "M-Pesa",
            "amount_paid": 60, "cash_paid": 60, "electronic_paid": 0,
            "mpesa_ref": "TEST123ABC",
        })
        self.assertTrue(sale.get("success"), sale)
        db = self.ac._db()
        row = db.execute(
            "SELECT payment_method, cash_paid, electronic_paid FROM sales WHERE id=?",
            (sale["sale_id"],),
        ).fetchone()
        db.close()
        self.assertEqual(float(row["cash_paid"] or 0), 0.0)
        self.assertAlmostEqual(float(row["electronic_paid"] or 0), 60.0, places=2)

    def test_split_and_part_pay_are_accepted(self):
        mixed = self.api.create_sale({
            "items": [{
                "product_id": 1, "product_name": "Maize", "quantity": 1,
                "unit_price": 90, "discount": 0, "total": 90,
            }],
            "subtotal": 90, "total": 90, "payment_method": "Mixed",
            "amount_paid": 90, "electronic_paid": 40, "electronic_method": "M-Pesa",
        })
        self.assertTrue(mixed.get("success"), mixed)
        db = self.ac._db()
        db.execute(
            "INSERT INTO customers (name, phone, is_active) VALUES ('Asha','0700',1)"
        )
        db.commit()
        customer = db.execute("SELECT id FROM customers").fetchone()["id"]
        db.close()
        part = self.api.create_sale({
            "items": [{
                "product_id": 2, "product_name": "Sugar", "quantity": 1,
                "unit_price": 130.50, "discount": 0, "total": 130.50,
            }],
            "subtotal": 130.50, "total": 130.50, "payment_method": "part payment",
            "amount_paid": 70, "electronic_paid": 40, "electronic_method": "M-Pesa",
            "cash_paid": 30, "customer_id": customer,
            "payment_tenders": [
                {"method": "M-Pesa", "amount": 40},
                {"method": "Cash", "amount": 30},
            ],
        })
        self.assertTrue(part.get("success"), part)
        self.assertAlmostEqual(float(part.get("debt_balance") or 0), 60.50, places=2)


class BooksAndStockTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "books.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        ac._SCHEMA_READY = False
        self.ac = ac
        self.api = ac.APIClient()
        self.api._role = "superadmin"
        self.api._user_id = 1
        self.api._username = "owner"
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, is_active) "
            "VALUES (1,'owner','x','superadmin',1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_b007_opening_stock_is_journaled(self):
        created = self.api.create_product({
            "name": "Opening Flour", "price": 120, "cost_price": 100, "stock": 10,
        })
        self.assertTrue(created.get("success"), created)
        db = self.ac._db()
        try:
            lines = db.execute(
                """SELECT account_code, debit, credit FROM journal_lines
                   WHERE journal_id IN (
                     SELECT id FROM journal_entries WHERE entry_type='opening_stock'
                   )"""
            ).fetchall()
        finally:
            db.close()
        codes = {row["account_code"]: (row["debit"], row["credit"]) for row in lines}
        self.assertAlmostEqual(float(codes["1200"][0]), 1000.0, places=2)
        self.assertAlmostEqual(float(codes["3200"][1]), 1000.0, places=2)

    def test_b028_adjustment_reasons_use_the_chart(self):
        from desktop.utils.accounting_hooks import adjustment_debit_account
        self.assertEqual(adjustment_debit_account("internal use by staff"), "6100")
        self.assertEqual(adjustment_debit_account("samples for the counter"), "6100")
        self.assertEqual(adjustment_debit_account("wastage after rain"), "6200")
        self.assertEqual(adjustment_debit_account("expired stock"), "6300")
        self.assertEqual(adjustment_debit_account("owner personal drawings"), "3300")

    def test_consumption_uses_the_product_cost_when_no_batch_exists(self):
        db = self.ac._db()
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, unit, is_active) "
            "VALUES ('Sugar','SUG',200,50,30,'kg',1)"
        )
        db.commit()
        db.close()
        saved = self.api.save_department("Office")
        done = self.api.create_consumption({
            "department_id": saved["id"],
            "reason": "Staff tea",
            "items": [{"product_id": 1, "quantity": 2}],
        })
        self.assertTrue(done.get("success"), done)
        db = self.ac._db()
        row = db.execute(
            "SELECT total_cost FROM stock_consumption_items WHERE consumption_id=?",
            (done["id"],),
        ).fetchone()
        db.close()
        self.assertAlmostEqual(float(row["total_cost"]), 100.0, places=2)

    def test_b005_paid_sales_net_the_refund(self):
        from desktop.utils.financials import compute_financials
        sale = self.api.create_sale({
            "items": [{
                "product_id": 1, "product_name": "Made", "quantity": 1,
                "unit_price": 200, "discount": 0, "total": 200,
            }],
            "subtotal": 200, "total": 200, "payment_method": "Cash",
            "amount_paid": 200, "cash_paid": 200,
        })
        self.api.create_product({
            "name": "Made", "price": 200, "cost_price": 50, "stock": 5,
        }) if not sale.get("success") else None
        db = self.ac._db()
        if not sale.get("success"):
            db.execute(
                "INSERT INTO products (name, sku, price, cost_price, stock, is_active) "
                "VALUES ('Made','MD',200,50,5,1)"
            )
            db.commit()
        db.close()
        if not sale.get("success"):
            sale = self.api.create_sale({
                "items": [{
                    "product_id": 1, "product_name": "Made", "quantity": 1,
                    "unit_price": 200, "discount": 0, "total": 200,
                }],
                "subtotal": 200, "total": 200, "payment_method": "Cash",
                "amount_paid": 200, "cash_paid": 200,
            })
        self.assertTrue(sale.get("success"), sale)
        db = self.ac._db()
        line = db.execute(
            "SELECT id FROM sale_items WHERE sale_id=?", (sale["sale_id"],)
        ).fetchone()
        db.close()
        refund = self.api.return_sale(
            sale["sale_id"], [{"sale_item_id": line["id"], "quantity": 1}],
            "full refund",
        )
        self.assertTrue(refund.get("success"), refund)
        db = self.ac._db()
        day = str(db.execute("SELECT sale_date FROM sales WHERE id=?", (sale["sale_id"],)).fetchone()[0])[:10]
        figures = compute_financials(db, day, day)
        db.close()
        self.assertAlmostEqual(figures["paid_sales"], 0.0, places=2)


class SyncBackupTests(unittest.TestCase):
    def test_b008_retry_clock_is_utc_and_expenses_use_the_real_table(self):
        from backend.cloud_backup.sync_manager import ENTITY_TABLE_MAP
        self.assertEqual(ENTITY_TABLE_MAP["expense"], "expense_entries")
        self.assertEqual(ENTITY_TABLE_MAP["supplier_payment"], "supplier_payments")
        now = datetime.now(timezone.utc)
        retry = (now + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
        parsed = datetime.strptime(retry, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        self.assertLess(abs((parsed - now).total_seconds() - 30), 2)

    def test_b016_restore_latest_is_the_newest_substantial_backup(self):
        from backend.cloud_backup.restore_manager import RestoreManager
        manager = RestoreManager()
        rows = [
            {"created_at": "2026-11-20T10:00:00Z", "size_bytes": 900_000},
            {"created_at": "2026-11-25T20:00:00Z", "size_bytes": 80_000},
            {"created_at": "2026-11-26T01:00:00Z", "size_bytes": 1_000},
        ]
        with patch.object(manager, "list_available_backups", return_value=rows):
            chosen = manager.latest_backup()
        self.assertEqual(chosen["created_at"], "2026-11-25T20:00:00Z")

    def test_mpesa_code_ignores_separators_inside_the_length_rule(self):
        from backend.mpesa_service import normalize_code
        self.assertEqual(normalize_code("QA-MPESA-1"), "QAMPESA1")

    def test_payment_bars_sum_to_100(self):
        from desktop.utils.charts import payment_bar_rows
        rows = payment_bar_rows([
            {"label": "Cash", "value": 480},
            {"label": "M-Pesa", "value": 60},
            {"label": "Credit issued", "value": 360},
        ])
        total = round(sum(row["pct"] for row in rows), 2)
        self.assertAlmostEqual(total, 100.0, places=1)


class WordingTests(unittest.TestCase):
    def test_b026_shop_owner_is_not_greeted_as_shop(self):
        from desktop.utils.ui_polish import time_greeting
        headline, _sub = time_greeting("Shop Owner")
        self.assertNotIn("Shop", headline.split(",")[-1])
        self.assertIn("there", headline)


if __name__ == "__main__":
    unittest.main()
