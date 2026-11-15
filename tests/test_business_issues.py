"""Issues Centre rules: bad records are found, clean records are not."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest

os.environ["MBT_DATA_ROOT"] = tempfile.mkdtemp(prefix="mbt-issues-")
os.environ["MBT_TEST_INSTANCE"] = "1"

from desktop.utils.business_issues import (  # noqa: E402
    dismiss_issue,
    list_issues,
    scan,
    set_rule_mode,
    snooze_issue,
    summary,
)


def _db():
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE products (
            id INTEGER PRIMARY KEY, name TEXT, sku TEXT, price REAL, cost_price REAL,
            stock REAL, unit TEXT, is_active INTEGER DEFAULT 1)"""
    )
    conn.execute(
        """CREATE TABLE sales (
            id INTEGER PRIMARY KEY, receipt_number TEXT, total REAL, amount_paid REAL,
            payment_method TEXT, status TEXT, sale_date TEXT, created_at TEXT, mpesa_ref TEXT)"""
    )
    conn.execute(
        """CREATE TABLE sale_items (
            id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER,
            product_name TEXT, quantity REAL, total REAL)"""
    )
    conn.execute(
        """CREATE TABLE cost_layer_uses (
            id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER,
            quantity REAL, unit_cost REAL, reversed INTEGER DEFAULT 0)"""
    )
    conn.execute(
        """CREATE TABLE cost_layers (
            id INTEGER PRIMARY KEY, product_id INTEGER, remaining_qty REAL, unit_cost REAL)"""
    )
    conn.execute(
        """CREATE TABLE debt_invoices (
            id INTEGER PRIMARY KEY, invoice_number TEXT, sale_id INTEGER,
            customer_name TEXT, total_amount REAL, amount_paid REAL, balance REAL, status TEXT)"""
    )
    conn.execute(
        """CREATE TABLE journal_entries (
            id INTEGER PRIMARY KEY, entry_number TEXT, status TEXT, deleted_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE journal_lines (
            id INTEGER PRIMARY KEY, journal_id INTEGER, debit REAL, credit REAL)"""
    )
    conn.execute(
        """CREATE TABLE stock_consumptions (
            id INTEGER PRIMARY KEY, reference_no TEXT, voided INTEGER DEFAULT 0)"""
    )
    conn.execute(
        """CREATE TABLE stock_consumption_items (
            id INTEGER PRIMARY KEY, consumption_id INTEGER, product_name TEXT, quantity REAL)"""
    )
    conn.execute(
        """CREATE TABLE stocktakes (
            id INTEGER PRIMARY KEY, name TEXT, status TEXT, created_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE stock_receipts (
            id INTEGER PRIMARY KEY, receipt_number TEXT, reference_note TEXT)"""
    )
    conn.execute(
        """CREATE TABLE stock_receipt_lines (
            id INTEGER PRIMARY KEY, receipt_id INTEGER, product_name TEXT, quantity REAL)"""
    )
    conn.execute(
        """CREATE TABLE sync_queue (
            id INTEGER PRIMARY KEY, action_type TEXT, payload TEXT, status TEXT, created_at TEXT)"""
    )
    return conn


CASHIER = {"id": 2, "username": "cashier", "role": "cashier", "permission_grants": [], "permission_denials": []}
ADMIN = {"id": 1, "username": "admin", "role": "admin", "permission_grants": [], "permission_denials": []}
SUPER = {"id": 3, "username": "owner", "role": "superadmin", "permission_grants": [], "permission_denials": []}


class IssueRuleTests(unittest.TestCase):
    def setUp(self):
        self.db = _db()

    def tearDown(self):
        self.db.close()

    def _codes(self, user=ADMIN, status="open"):
        return {item["rule_code"] for item in list_issues(self.db, user, status)}

    def test_clean_records_are_not_flagged(self):
        self.db.execute(
            "INSERT INTO products VALUES (1,'Sugar','QA',150,100,10,'kg',1)"
        )
        self.db.execute(
            """INSERT INTO sales VALUES (1,'RCP-1',150,150,'cash','completed','2026-11-15','2026-11-15T10:00:00','')"""
        )
        self.db.execute(
            "INSERT INTO sale_items VALUES (1,1,1,'Sugar',1,150)"
        )
        self.db.execute(
            "INSERT INTO cost_layer_uses VALUES (1,1,1,1,100,0)"
        )
        self.db.execute(
            "INSERT INTO journal_entries VALUES (1,'JE-1','posted',NULL)"
        )
        self.db.execute("INSERT INTO journal_lines VALUES (1,1,150,0)")
        self.db.execute("INSERT INTO journal_lines VALUES (2,1,0,150)")
        self.db.execute(
            "INSERT INTO debt_invoices VALUES (1,'INV-1',NULL,'Ada',100,40,60,'pending')"
        )
        self.db.commit()
        scan(self.db)
        self.assertEqual(self._codes(), set())
        self.assertEqual(summary(self.db, ADMIN)["open"], 0)

    def test_each_bad_record_is_found_once(self):
        self.db.execute("INSERT INTO products VALUES (1,'Bare','B',80,0,4,'kg',1)")
        self.db.execute("INSERT INTO products VALUES (2,'Minus','M',50,-5,1,'pcs',1)")
        self.db.execute("INSERT INTO products VALUES (3,'Loss','L',40,90,2,'pcs',1)")
        self.db.execute("INSERT INTO products VALUES (4,'Empty','E',10,5,-2,'pcs',1)")
        self.db.execute(
            "INSERT INTO sales VALUES (2,'RCP-U',80,80,'cash','completed','2026-11-15','2026-11-15T10:00:00','ABC')"
        )
        self.db.execute("INSERT INTO sale_items VALUES (2,2,1,'Bare',1,80)")
        self.db.execute(
            "INSERT INTO sales VALUES (3,'RCP-S',200,50,'cash','completed','2026-11-15','2026-11-15T10:00:00','ABC')"
        )
        self.db.execute(
            "INSERT INTO debt_invoices VALUES (2,'INV-BAD',NULL,'Bea',100,10,50,'pending')"
        )
        self.db.execute("INSERT INTO journal_entries VALUES (3,'JE-BAD','posted',NULL)")
        self.db.execute("INSERT INTO journal_lines VALUES (3,3,10,0)")
        self.db.execute("INSERT INTO journal_lines VALUES (4,3,0,4)")
        self.db.execute("INSERT INTO stock_consumptions VALUES (1,'AUTO-1',0)")
        self.db.execute("INSERT INTO stock_consumption_items VALUES (1,1,'Bare',0)")
        self.db.execute("INSERT INTO stock_receipts VALUES (1,'GRN-1','REF-1')")
        self.db.execute("INSERT INTO stock_receipts VALUES (2,'GRN-2','REF-1')")
        self.db.execute("INSERT INTO stock_receipt_lines VALUES (1,1,'Bare',0)")
        self.db.execute(
            "INSERT INTO sync_queue VALUES (1,'sale','{}','pending','2020-01-01T00:00:00')"
        )
        self.db.commit()
        first = scan(self.db)
        second = scan(self.db)
        codes = self._codes()
        self.assertIn("INV-NO-BUYING-PRICE", codes)
        self.assertIn("INV-NEGATIVE-COST", codes)
        self.assertIn("INV-SELL-BELOW-COST", codes)
        self.assertIn("INV-NEGATIVE-STOCK", codes)
        self.assertIn("SALE-UNCOSTED", codes)
        self.assertIn("SALE-PAY-SHORT", codes)
        self.assertIn("SALE-MPESA-DUP", codes)
        self.assertIn("DEBT-BALANCE", codes)
        self.assertIn("ACCT-UNBALANCED", codes)
        self.assertIn("CONSUME-BAD-QTY", codes)
        self.assertIn("DELIVERY-BAD-QTY", codes)
        self.assertIn("DELIVERY-DUP-REF", codes)
        self.assertIn("SYNC-WAITING", codes)
        self.assertNotIn("INV-LOW-MARGIN", codes)
        self.assertEqual(second["opened"], 0)
        self.assertGreater(first["detected"], 10)
        rows = self.db.execute(
            "SELECT fingerprint, COUNT(*) c FROM business_issues GROUP BY fingerprint HAVING c>1"
        ).fetchall()
        self.assertEqual(rows, [])

    def test_cashier_does_not_see_cost_or_dismiss_stock(self):
        self.db.execute("INSERT INTO products VALUES (1,'Bare','B',80,0,4,'kg',1)")
        self.db.execute("INSERT INTO products VALUES (4,'Empty','E',10,5,-2,'pcs',1)")
        self.db.commit()
        scan(self.db)
        cashier_codes = self._codes(CASHIER)
        self.assertNotIn("INV-NO-BUYING-PRICE", cashier_codes)
        self.assertIn("INV-NEGATIVE-STOCK", cashier_codes)
        issue = list_issues(self.db, CASHIER)[0]
        denied = dismiss_issue(self.db, CASHIER, issue["id"], "not my job")
        self.assertEqual(denied["status"], 403)
        self.assertEqual(self._codes(CASHIER), {"INV-NEGATIVE-STOCK"})

    def test_correction_resolves_and_dismiss_needs_a_reason(self):
        self.db.execute("INSERT INTO products VALUES (1,'Bare','B',80,0,4,'kg',1)")
        self.db.commit()
        scan(self.db)
        issue = list_issues(self.db, ADMIN)[0]
        self.assertEqual(dismiss_issue(self.db, ADMIN, issue["id"], "no")["status"], 400)
        saved = dismiss_issue(self.db, ADMIN, issue["id"], "Seasonal sample, price is intentional")
        self.assertEqual(saved["status"], "dismissed")
        scan(self.db)
        self.assertEqual(self._codes(ADMIN), set())
        self.assertEqual(self._codes(ADMIN, "dismissed"), {"INV-NO-BUYING-PRICE"})
        self.db.execute("UPDATE products SET cost_price=20 WHERE id=1")
        self.db.commit()
        scan(self.db)
        self.assertEqual(self._codes(ADMIN, "resolved"), {"INV-NO-BUYING-PRICE"})

    def test_critical_journal_cannot_be_snoozed_or_disabled(self):
        self.db.execute("INSERT INTO journal_entries VALUES (1,'JE-BAD','posted',NULL)")
        self.db.execute("INSERT INTO journal_lines VALUES (1,1,9,0)")
        self.db.commit()
        scan(self.db)
        issue = list_issues(self.db, SUPER)[0]
        self.assertEqual(issue["severity"], "critical")
        self.assertEqual(snooze_issue(self.db, SUPER, issue["id"], 1, "later")["status"], 403)
        self.assertEqual(dismiss_issue(self.db, ADMIN, issue["id"], "ignore it")["status"], 403)
        blocked = set_rule_mode(self.db, "ACCT-UNBALANCED", "disabled", "owner")
        self.assertEqual(blocked["status"], 403)

    def test_a_disabled_rule_stops_appearing(self):
        self.db.execute("INSERT INTO products VALUES (1,'Bare','B',80,0,4,'kg',1)")
        self.db.commit()
        scan(self.db)
        self.assertIn("INV-NO-BUYING-PRICE", self._codes())
        set_rule_mode(self.db, "INV-NO-BUYING-PRICE", "disabled", "owner")
        self.assertNotIn("INV-NO-BUYING-PRICE", self._codes())

    def test_shadow_margin_is_hidden_unless_requested(self):
        self.db.execute("INSERT INTO products VALUES (1,'Tight','T',100,96,3,'pcs',1)")
        self.db.commit()
        scan(self.db)
        self.assertEqual(self._codes(), set())
        shown = list_issues(self.db, SUPER, include_shadow=True)
        self.assertEqual({item["rule_code"] for item in shown}, {"INV-LOW-MARGIN"})

    def test_scan_of_three_hundred_products_stays_quick(self):
        for i in range(300):
            self.db.execute(
                "INSERT INTO products VALUES (?,?,?,?,?,?,?,1)",
                (i + 1, f"Item {i}", f"SKU-{i}", 100, 40, 5, "pcs"),
            )
        self.db.commit()
        started = time.perf_counter()
        scan(self.db)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertEqual(summary(self.db, ADMIN)["open"], 0)


if __name__ == "__main__":
    unittest.main()
