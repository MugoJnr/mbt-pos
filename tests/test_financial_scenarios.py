"""The fifteen shop cases, then the portal overview on the same rows."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FinancialScenarioTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "scenarios.db")
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
            "VALUES (1,'owner','x','superadmin','Owner',1)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _figures(self, start, end):
        from desktop.utils.financials import compute_financials
        db = self.ac._db()
        try:
            return compute_financials(db, start, end)
        finally:
            db.close()

    def _sell(self, product_id, name, qty, price, method, paid, discount=0):
        total = round(qty * price - discount, 2)
        return self.api.create_sale({
            "items": [{
                "product_id": product_id, "product_name": name, "sku": "S",
                "quantity": qty, "unit_price": price, "discount": discount, "total": total,
            }],
            "subtotal": round(qty * price, 2), "discount": discount, "tax": 0, "total": total,
            "payment_method": method, "amount_paid": paid, "change_amount": 0,
            "customer_id": getattr(self, "customer", None),
        })

    def test_sales_credit_refunds_voids_cost_and_dates(self):
        from desktop.utils.shop_time import shop_today
        today = shop_today().isoformat()
        supplier = self.api.create_supplier({"name": "Scenario Supplier", "phone": "0700000001"})
        self.assertTrue(supplier.get("success"), supplier)
        costed = self.api.create_product({
            "name": "Costed Soap", "price": 100, "stock": 0, "unit": "pcs", "cost_price": 999,
        })
        self.assertTrue(costed.get("success"), costed)
        bare = self.api.create_product({
            "name": "No Cost Oil", "price": 70, "stock": 5, "unit": "pcs", "cost_price": 0,
        })
        self.assertTrue(bare.get("success"), bare)
        received = self.api.receive_delivery(supplier["id"], [{
            "product_id": costed["id"], "quantity": 10, "ordered_qty": 10,
            "rejected_qty": 0, "unit_cost": 40,
        }], reference="FIFO-1", client_token="scenario-fifo")
        self.assertTrue(received.get("success"), received)
        customer = self.api.create_customer({"name": "Scenario Customer", "phone": "0711000001"})
        self.assertTrue(customer.get("success"), customer)
        self.customer = customer["customer_id"]

        cash = self._sell(costed["id"], "Costed Soap", 2, 100, "Cash", 200)
        self.assertTrue(cash.get("success"), cash)
        after_cash = self._figures(today, today)
        self.assertEqual(after_cash["cash_collected"], 200)
        self.assertEqual(after_cash["cogs"], 80)
        self.assertNotEqual(after_cash["cogs"], 999)

        mpesa = self._sell(costed["id"], "Costed Soap", 1, 80, "M-Pesa", 80)
        self.assertTrue(mpesa.get("success"), mpesa)
        after_mpesa = self._figures(today, today)
        self.assertEqual(after_mpesa["mpesa_collected"], 80)
        self.assertEqual(after_mpesa["cash_collected"], 200)

        unpaid = self._sell(costed["id"], "Costed Soap", 1, 50, "Credit", 0)
        self.assertTrue(unpaid.get("success"), unpaid)
        after_credit = self._figures(today, today)
        self.assertEqual(after_credit["new_credit"], 50)
        self.assertEqual(after_credit["paid_sales"], after_mpesa["paid_sales"])

        partial = self._sell(costed["id"], "Costed Soap", 1, 100, "Credit", 30)
        self.assertTrue(partial.get("success"), partial)
        after_partial = self._figures(today, today)
        self.assertEqual(after_partial["paid_sales"], after_credit["paid_sales"] + 30)
        self.assertEqual(after_partial["new_credit"], after_credit["new_credit"] + 70)

        db = self.ac._db()
        invoice = db.execute(
            "SELECT id, balance FROM debt_invoices WHERE sale_id=?",
            (partial["sale_id"],),
        ).fetchone()
        db.close()
        self.assertIsNotNone(invoice)
        before_repay = self._figures(today, today)
        first = self.api.record_debt_payment(int(invoice["id"]), 20, "Cash", "First repayment")
        second = self.api.record_debt_payment(int(invoice["id"]), 15, "M-Pesa", "Second repayment")
        self.assertTrue(first.get("success"), first)
        self.assertTrue(second.get("success"), second)
        after_repay = self._figures(today, today)
        self.assertEqual(after_repay["total_sales"], before_repay["total_sales"])
        self.assertEqual(after_repay["debt_repayments"], before_repay["debt_repayments"] + 35)
        self.assertEqual(after_repay["cash_collected"], before_repay["cash_collected"] + 20)
        self.assertEqual(after_repay["mpesa_collected"], before_repay["mpesa_collected"] + 15)

        discounted = self._sell(costed["id"], "Costed Soap", 1, 100, "Cash", 90, discount=10)
        self.assertTrue(discounted.get("success"), discounted)
        after_discount = self._figures(today, today)
        self.assertEqual(after_discount["discounts"], before_repay["discounts"] + 10)
        self.assertEqual(after_discount["paid_sales"], after_repay["paid_sales"] + 90)

        line = self.ac._db().execute(
            "SELECT id, quantity FROM sale_items WHERE sale_id=?", (cash["sale_id"],)
        ).fetchone()
        self.ac._db().close()
        part_return = self.api.return_sale(
            int(cash["sale_id"]),
            [{"sale_item_id": int(line["id"]), "quantity": 1}],
            "One bar returned",
        )
        self.assertTrue(part_return.get("success"), part_return)
        after_part = self._figures(today, today)
        self.assertEqual(after_part["paid_sales"], after_discount["paid_sales"] - 100)

        full_line = self.ac._db().execute(
            "SELECT id FROM sale_items WHERE sale_id=?", (mpesa["sale_id"],)
        ).fetchone()
        self.ac._db().close()
        full_return = self.api.return_sale(
            int(mpesa["sale_id"]),
            [{"sale_item_id": int(full_line["id"]), "quantity": 1}],
            "Full M-Pesa refund",
            refund_method="M-Pesa",
        )
        self.assertTrue(full_return.get("success"), full_return)
        after_full = self._figures(today, today)
        self.assertEqual(after_full["mpesa_collected"], after_part["mpesa_collected"] - 80)

        doomed = self._sell(costed["id"], "Costed Soap", 1, 15, "Cash", 15)
        self.assertTrue(doomed.get("success"), doomed)
        with_void_sale = self._figures(today, today)
        voided = self.api.void_sale(int(doomed["sale_id"]), "Wrong item")
        self.assertTrue(voided.get("success"), voided)
        after_void = self._figures(today, today)
        self.assertEqual(after_void["total_sales"], with_void_sale["total_sales"] - 15)
        self.assertEqual(after_void["void_count"], 1)
        self.assertEqual(after_void["void_total"], 15)

        missing = self._sell(bare["id"], "No Cost Oil", 1, 70, "Cash", 70)
        self.assertTrue(missing.get("success"), missing)
        after_missing = self._figures(today, today)
        self.assertGreaterEqual(after_missing["uncosted_lines"], 1)
        self.assertGreaterEqual(after_missing["uncosted_sales"], 70)
        self.assertEqual(after_missing["cogs"], after_void["cogs"])
        self.assertIsNone(after_missing["net_operating_result"])

        expense = self.api.accounting_create_expense({
            "amount": 25, "description": "Scenario transport",
            "account_code": "6000", "pay_from_code": "1000",
        })
        self.assertTrue(expense.get("success"), expense)
        after_expense = self._figures(today, today)
        self.assertEqual(after_expense["expenses"], 25)

        other_day = "2026-01-15"
        other = self._sell(costed["id"], "Costed Soap", 1, 10, "Cash", 10)
        self.assertTrue(other.get("success"), other)
        db = self.ac._db()
        db.execute(
            "UPDATE sales SET sale_date=?, created_at=? WHERE id=?",
            (other_day, "2026-01-15 09:00:00", other["sale_id"]),
        )
        midnight_id = int(cash["sale_id"])
        db.execute(
            "UPDATE sales SET sale_date=?, created_at=? WHERE id=?",
            ("2026-11-25", "2026-11-26 00:10:00", midnight_id),
        )
        db.commit()
        db.close()
        today_after = self._figures(today, today)
        other_figures = self._figures(other_day, other_day)
        midnight = self._figures("2026-11-25", "2026-11-25")
        self.assertEqual(other_figures["paid_sales"], 10)
        self.assertEqual(
            today_after["completed_sale_count"],
            after_expense["completed_sale_count"] - 1,
        )
        self.assertEqual(midnight["completed_sale_count"], 1)
        self.assertNotEqual(midnight["total_sales"], today_after["total_sales"])

    def test_portal_overview_matches_the_till_on_the_same_rows(self):
        self.test_sales_credit_refunds_voids_cost_and_dates()
        from desktop.utils.financials import compute_financials
        from desktop.utils.shop_time import shop_today
        from backend.cloud import platform_service as ps
        today = shop_today().isoformat()
        db = self.ac._db()
        till = compute_financials(db, today, today)
        sales = []
        for row in db.execute("SELECT * FROM sales"):
            item = dict(row)
            day = str(item.get("sale_date") or "")[:10]
            item["device_id"] = "qa-device"
            item["source_id"] = str(item["id"])
            item["source_created_at"] = f"{day}T12:00:00+03:00" if len(day) == 10 else item.get("created_at")
            sales.append(item)
        items = []
        for row in db.execute("SELECT * FROM sale_items"):
            item = dict(row)
            item["device_id"] = "qa-device"
            item["sale_source_id"] = str(item["sale_id"])
            item["source_id"] = str(item["id"])
            items.append(item)
        payments = []
        for row in db.execute("SELECT * FROM debt_payments"):
            item = dict(row)
            item["source_id"] = str(item["id"])
            item["source_created_at"] = f"{today}T12:00:00+03:00"
            payments.append(item)
        debts = [dict(row) for row in db.execute("SELECT * FROM debt_invoices")]
        products = []
        for row in db.execute("SELECT * FROM products"):
            item = dict(row)
            item["source_id"] = str(item["id"])
            products.append(item)
        db.close()

        def fake_fetch(table, query, *, max_rows=10000, page_size=1000):
            rows = {
                "cloud_sales": sales,
                "cloud_debt_payments": payments,
                "cloud_debt_invoices": debts,
                "cloud_products": products,
                "cloud_sale_items": items,
            }.get(table, [])
            if table in ("cloud_sales", "cloud_debt_payments") and "source_created_at=gte." in query:
                rows = [row for row in rows if str(row.get("source_created_at") or "")[:10] == today]
            return rows

        with patch.object(ps, "analytics_fetch_all", side_effect=fake_fetch), \
             patch.object(ps, "analytics_last_sync_at", return_value="2026-11-26T12:00:00+03:00"):
            summary = ps.analytics_overview("org-qa", start=today, end=today)["summary"]
        self.assertEqual(summary["paid_sales"], till["paid_sales"])
        self.assertEqual(summary["new_credit"], till["new_credit"])
        self.assertEqual(summary["debt_collected"], till["debt_repayments"])
        self.assertEqual(summary["discounts"], till["discounts"])
        self.assertEqual(summary["void_transactions"], till["void_count"])
        self.assertEqual(summary["void_revenue"], till["void_total"])
        self.assertEqual(summary["gross_profit"], till["gross_profit"])
        self.assertEqual(summary["cost_of_goods"], till["cogs"])
        self.assertIsNone(summary["inventory_value"])
        self.assertGreater(till["inventory_cost_value"], 0)
        self.assertIn("label", summary.get("sync") or {})

    def test_opening_tender_is_not_a_second_collection(self):
        from backend.cloud_backup.sync_manager import debt_payment_is_opening_or_reversed
        self.assertTrue(debt_payment_is_opening_or_reversed({"notes": "Initial payment on invoice 1"}))
        self.assertTrue(debt_payment_is_opening_or_reversed({"reversed": 1}))
        self.assertFalse(debt_payment_is_opening_or_reversed({"notes": "First repayment", "reversed": 0}))

    def test_sale_date_is_the_timestamp_sent_to_the_portal(self):
        from backend.cloud_backup.sync_manager import serialize_entity_payload
        payload = serialize_entity_payload("sale", {
            "id": 1, "receipt_number": "R-1", "total": 10, "status": "completed",
            "sale_date": "2026-11-25", "created_at": "2026-11-26 00:10:00",
        })
        self.assertEqual(payload["sale_date"], "2026-11-25")
        self.assertEqual(payload["created_at"], "2026-11-25T12:00:00+03:00")
