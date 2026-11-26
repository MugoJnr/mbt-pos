"""Shared activity authorization: direct, admin PIN, or a request."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CapabilityModeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "cap.db")
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
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active, tab_permissions) "
            "VALUES (1,'owner','x','superadmin','Owner',1,'[]')"
        )
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active, tab_permissions) "
            "VALUES (2,'mercy','x','cashier','Mercy',1,?)",
            (json.dumps(["dashboard", "sales", "receipts", "inventory"]),),
        )
        db.commit()
        db.close()
        self.owner = ac.APIClient()
        self.owner._role = "superadmin"
        self.owner._user_id = 1
        self.owner._username = "owner"
        self.cashier = ac.APIClient()
        self.cashier._role = "cashier"
        self.cashier._user_id = 2
        self.cashier._username = "mercy"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_request_does_not_publish_and_direct_does(self):
        saved = self.owner.update_user(2, {"permission_modes": {"inventory.create": "request"}})
        self.assertTrue(saved.get("success"), saved)
        queued = self.cashier.create_product({"name": "Requested Soap", "price": 20, "unit": "pcs"})
        self.assertTrue(queued.get("pending_approval"), queued)
        self.assertFalse(queued.get("published", True) and queued.get("id"))
        db = self.ac._db()
        count = db.execute("SELECT COUNT(*) FROM products WHERE name='Requested Soap'").fetchone()[0]
        db.close()
        self.assertEqual(int(count), 0)
        opened = self.owner.update_user(2, {"permission_modes": {"inventory.create": "direct"}})
        self.assertTrue(opened.get("success"), opened)
        created = self.cashier.create_product({"name": "Direct Soap", "price": 25, "unit": "pcs", "stock": 0})
        self.assertTrue(created.get("success"), created)
        self.assertFalse(created.get("pending_approval"))
        self.assertTrue(created.get("id"))

    def test_hidden_inventory_tab_blocks_the_action(self):
        saved = self.owner.update_user(2, {
            "tab_permissions": ["dashboard", "sales", "receipts"],
            "permission_modes": {"inventory.create": "direct"},
        })
        self.assertTrue(saved.get("success"), saved)
        denied = self.cashier.create_product({"name": "Hidden Soap", "price": 10})
        self.assertEqual(denied.get("status"), 403)
        db = self.ac._db()
        count = db.execute("SELECT COUNT(*) FROM products WHERE name='Hidden Soap'").fetchone()[0]
        db.close()
        self.assertEqual(int(count), 0)

    def test_receive_request_does_not_change_stock(self):
        product = self.owner.create_product({"name": "Flour", "price": 100, "cost_price": 80, "stock": 5, "unit": "kg"})
        self.assertTrue(product.get("success"), product)
        supplier = self.owner.create_supplier({"name": "QA Sagana Supplies"})
        self.assertTrue(supplier.get("success") or supplier.get("id"), supplier)
        saved = self.owner.update_user(2, {"permission_modes": {"inventory.receive": "request"}})
        self.assertTrue(saved.get("success"), saved)
        asked = self.cashier.receive_delivery(
            supplier.get("id"),
            [{"product_id": product["id"], "quantity": 20, "unit_cost": 150}],
            reference="QA-1",
        )
        self.assertTrue(asked.get("pending_approval"), asked)
        self.assertFalse(asked.get("executed"))
        db = self.ac._db()
        stock = db.execute("SELECT stock FROM products WHERE id=?", (product["id"],)).fetchone()[0]
        receipts = db.execute("SELECT COUNT(*) FROM stock_receipts").fetchone()[0]
        db.close()
        self.assertEqual(float(stock), 5)
        self.assertEqual(int(receipts), 0)

    def test_role_default_is_inherited_and_an_override_is_kept(self):
        from desktop.utils.capability_modes import apply_role_default, save_role_default
        saved = save_role_default("superadmin", "cashier", ["dashboard", "sales", "inventory"], {
            "inventory.adjust_stock": "request",
            "inventory.view": "direct",
        })
        self.assertTrue(saved.get("success"), saved)
        created = self.owner.create_user({
            "username": "cashier-a", "password": "cashier-a", "role": "cashier", "full_name": "Cashier A",
        })
        self.assertTrue(created.get("success"), created)
        db = self.ac._db()
        row = db.execute(
            "SELECT id, permission_modes, tab_permissions FROM users WHERE username='cashier-a'"
        ).fetchone()
        product = db.execute("SELECT id, stock FROM products LIMIT 1").fetchone()
        db.close()
        modes = json.loads(row["permission_modes"] or "{}")
        self.assertEqual(modes.get("inventory.adjust_stock"), "request")
        self.assertIn("inventory", json.loads(row["tab_permissions"]))
        made = self.owner.create_product({"name": "Rice", "price": 100, "stock": 8, "unit": "kg"})
        self.assertTrue(made.get("success"), made)
        person = self.ac.APIClient()
        person._role = "cashier"
        person._user_id = int(row["id"])
        person._username = "cashier-a"
        asked = person.adjust_stock(made["id"], 4, "count was short")
        self.assertTrue(asked.get("pending_approval"), asked)
        db = self.ac._db()
        stock = db.execute("SELECT stock FROM products WHERE id=?", (made["id"],)).fetchone()[0]
        db.close()
        self.assertEqual(float(stock), 8)
        custom = self.owner.update_user(int(row["id"]), {"permission_modes": {"inventory.view": "direct"}})
        self.assertTrue(custom.get("success"), custom)
        kept = apply_role_default("superadmin", "cashier", [int(row["id"])], replace=False, confirm=False)
        self.assertIn(int(row["id"]), kept["skipped"])
        refused = apply_role_default("superadmin", "cashier", [int(row["id"])], replace=True, confirm=False)
        self.assertEqual(refused.get("status"), 400)
        replaced = apply_role_default("superadmin", "cashier", [int(row["id"])], replace=True, confirm=True)
        self.assertIn(int(row["id"]), replaced["updated"])

    def test_manager_and_viewer_defaults_and_a_lock_blocks_the_api(self):
        from desktop.utils.capability_modes import (
            apply_mode_change, save_direct_locks, save_role_default, screen_for,
        )
        manager = save_role_default("superadmin", "manager", ["dashboard", "sales", "inventory"], {
            "inventory.create": "request",
            "inventory.adjust_stock": "request",
        })
        viewer = save_role_default("superadmin", "viewer", ["dashboard", "receipts"], {
            "inventory.view": "direct",
        })
        self.assertTrue(manager.get("success"), manager)
        self.assertTrue(viewer.get("success"), viewer)
        self.assertTrue(self.owner.create_user({
            "username": "mgr", "password": "manager-1", "role": "manager", "full_name": "Manager",
        }).get("success"))
        self.assertTrue(self.owner.create_user({
            "username": "view", "password": "viewer-1", "role": "viewer", "full_name": "Viewer",
        }).get("success"))
        db = self.ac._db()
        mgr = db.execute("SELECT permission_modes, tab_permissions FROM users WHERE username='mgr'").fetchone()
        view = db.execute("SELECT tab_permissions FROM users WHERE username='view'").fetchone()
        db.close()
        self.assertEqual(json.loads(mgr["permission_modes"])["inventory.create"], "request")
        self.assertNotIn("inventory", json.loads(view["tab_permissions"]))
        denied = save_direct_locks("admin", {})
        self.assertEqual(denied.get("status"), 403)
        screen = screen_for({"role": "cashier", "tab_permissions": ["inventory"], "permission_modes": {}})
        stock = next(item for section in screen["tabs"] if section["tab"] == "inventory" for item in section["activities"] if item["key"] == "inventory.adjust_stock")
        self.assertTrue(stock["locked_direct"])
        self.assertIn("Stock quantity", stock["lock_reason"])
        blocked = apply_mode_change("cashier", [], [], {}, "inventory.adjust_stock", "direct")
        self.assertEqual(blocked.get("status"), 400)
        opened = save_direct_locks("superadmin", {"categories.delete": "Category delete stays off Direct."})
        self.assertTrue(opened.get("success"), opened)
        granted = self.owner.update_user(2, {"permission_modes": {"inventory.adjust_stock": "direct"}})
        self.assertTrue(granted.get("success"), granted)
        product = self.owner.create_product({"name": "Sugar", "price": 50, "stock": 10, "unit": "kg"})
        self.assertTrue(product.get("success"), product)
        changed = self.cashier.adjust_stock(product["id"], 7, "count")
        self.assertTrue(changed.get("success"), changed)
        db = self.ac._db()
        stock_qty = float(db.execute("SELECT stock FROM products WHERE id=?", (product["id"],)).fetchone()[0])
        audit = db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='CAPABILITY_LOCKS'"
        ).fetchone()[0]
        db.close()
        self.assertEqual(stock_qty, 7)
        self.assertGreaterEqual(int(audit), 1)
        restored = save_direct_locks("superadmin", {
            "inventory.adjust_stock": "Stock quantity changes default to a request.",
        })
        self.assertTrue(restored.get("success"), restored)
        again = self.cashier.adjust_stock(product["id"], 3, "count again")
        self.assertTrue(again.get("pending_approval"), again)
        db = self.ac._db()
        stock_qty = float(db.execute("SELECT stock FROM products WHERE id=?", (product["id"],)).fetchone()[0])
        db.close()
        self.assertEqual(stock_qty, 7)

    def test_locked_stock_adjustment_cannot_be_direct(self):
        from desktop.utils.capability_modes import apply_mode_change
        refused = apply_mode_change("cashier", [], [], {}, "inventory.adjust_stock", "direct")
        self.assertEqual(refused.get("status"), 400)
        allowed = apply_mode_change("cashier", [], [], {}, "inventory.adjust_stock", "request")
        self.assertEqual(allowed["permission_modes"]["inventory.adjust_stock"], "request")

    def _product(self, name, stock=10, price=40):
        created = self.owner.create_product({
            "name": name, "price": price, "stock": stock, "unit": "pcs",
        })
        self.assertTrue(created.get("success"), created)
        return int(created["id"])

    def _cash_sale(self, product_id, qty=2, price=40):
        total = qty * price
        sale = self.owner.create_sale({
            "items": [{
                "product_id": product_id, "product_name": "QA Item", "sku": "QA",
                "quantity": qty, "unit_price": price, "discount": 0, "total": total,
            }],
            "subtotal": total, "discount": 0, "tax": 0, "total": total,
            "payment_method": "Cash", "amount_paid": total, "change_amount": 0,
        })
        self.assertTrue(sale.get("success"), sale)
        db = self.ac._db()
        line_id = db.execute(
            "SELECT id FROM sale_items WHERE sale_id=?", (sale["sale_id"],)
        ).fetchone()[0]
        db.close()
        return int(sale["sale_id"]), int(line_id)

    def _stock(self, product_id):
        db = self.ac._db()
        qty = float(db.execute("SELECT stock FROM products WHERE id=?", (product_id,)).fetchone()[0])
        db.close()
        return qty

    def test_refund_request_executes_once_and_rejection_does_not(self):
        product_id = self._product("Refund Soap", stock=10)
        sale_id, line_id = self._cash_sale(product_id)
        self.assertEqual(self._stock(product_id), 8)
        saved = self.owner.update_user(2, {"permission_modes": {"sales.refund": "request"}})
        self.assertTrue(saved.get("success"), saved)
        too_many = self.cashier.return_sale(
            sale_id, [{"sale_item_id": line_id, "quantity": 5}], "too many",
        )
        self.assertEqual(too_many.get("status"), 400, too_many)
        self.assertEqual(self._stock(product_id), 8)
        queued = self.cashier.return_sale(
            sale_id, [{"sale_item_id": line_id, "quantity": 1}], "one back",
        )
        self.assertTrue(queued.get("pending_approval"), queued)
        self.assertFalse(queued.get("executed"))
        self.assertEqual(self._stock(product_id), 8)
        db = self.ac._db()
        status = db.execute("SELECT status FROM sales WHERE id=?", (sale_id,)).fetchone()[0]
        returns = db.execute("SELECT COUNT(*) FROM sales WHERE status='return'").fetchone()[0]
        db.close()
        self.assertEqual(status, "completed")
        self.assertEqual(int(returns), 0)
        rejected_sale, rejected_line = self._cash_sale(product_id, qty=1)
        rejected = self.cashier.return_sale(
            rejected_sale, [{"sale_item_id": rejected_line, "quantity": 1}], "do not refund",
        )
        held = self.owner.execute_approval(int(rejected["id"]), "reject", note="goods stayed with the customer")
        self.assertEqual(held.get("status"), "rejected", held)
        self.assertEqual(self._stock(product_id), 7)
        approved = self.owner.execute_approval(int(queued["id"]), "approve", note="checked the receipt")
        self.assertTrue(approved.get("success"), approved)
        self.assertEqual(self._stock(product_id), 8)
        again = self.owner.execute_approval(int(queued["id"]), "approve", note="again")
        self.assertTrue(again.get("duplicate"), again)
        self.assertEqual(self._stock(product_id), 8)
        db = self.ac._db()
        linked = db.execute(
            "SELECT COUNT(*) FROM sales WHERE status='return' AND original_sale_id=?",
            (sale_id,),
        ).fetchone()[0]
        audit = db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='RETURN_REQUEST'"
        ).fetchone()[0]
        db.close()
        self.assertEqual(int(linked), 1)
        self.assertGreaterEqual(int(audit), 1)

    def test_direct_refund_admin_pin_expense_credit_and_report(self):
        from desktop.utils.superadmin_pin import set_superadmin_user_pin
        db = self.ac._db()
        pinned = set_superadmin_user_pin(db, 1, "246810")
        db.commit()
        db.close()
        self.assertTrue(pinned.get("success"), pinned)
        direct_user = self.owner.create_user({
            "username": "qa-direct", "password": "secret1", "role": "cashier", "full_name": "Direct",
        })
        pin_user = self.owner.create_user({
            "username": "qa-pin", "password": "secret1", "role": "cashier", "full_name": "Pin",
        })
        request_user = self.owner.create_user({
            "username": "qa-request", "password": "secret1", "role": "cashier", "full_name": "Request",
        })
        quiet_user = self.owner.create_user({
            "username": "qa-quiet", "password": "secret1", "role": "cashier", "full_name": "Quiet",
        })
        self.assertTrue(direct_user.get("success"), direct_user)
        ids = {}
        db = self.ac._db()
        for name in ("qa-direct", "qa-pin", "qa-request", "qa-quiet"):
            ids[name] = int(db.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0])
        db.close()
        self.owner.update_user(ids["qa-direct"], {"permission_modes": {"sales.refund": "direct"}})
        self.owner.update_user(ids["qa-pin"], {"permission_modes": {"sales.refund": "admin_pin"}})
        self.owner.update_user(ids["qa-request"], {
            "tab_permissions": ["dashboard", "sales", "receipts", "consumption", "accounting", "debt"],
            "permission_modes": {
                "accounting.create_expenses": "request",
                "debt.create": "request",
                "debt.collect": "request",
            },
        })
        self.owner.update_user(ids["qa-quiet"], {
            "tab_permissions": ["dashboard", "sales", "receipts", "consumption", "reports"],
            "permission_modes": {"reports.view_all": "request"},
        })

        def client(name):
            person = self.ac.APIClient()
            person._role = "cashier"
            person._user_id = ids[name]
            person._username = name
            return person

        product_id = self._product("Mode Soap", stock=12)
        sale_id, line_id = self._cash_sale(product_id, qty=2)
        direct = client("qa-direct")
        done = direct.return_sale(sale_id, [{"sale_item_id": line_id, "quantity": 1}], "direct refund")
        self.assertTrue(done.get("executed"), done)
        self.assertEqual(self._stock(product_id), 11)
        self.owner.update_user(ids["qa-direct"], {"permission_modes": {"sales.refund": "request"}})
        second_sale, second_line = self._cash_sale(product_id, qty=1)
        changed = direct.return_sale(
            second_sale, [{"sale_item_id": second_line, "quantity": 1}], "now a request",
        )
        self.assertTrue(changed.get("pending_approval"), changed)
        self.assertEqual(self._stock(product_id), 10)

        pin_sale, pin_line = self._cash_sale(product_id, qty=1)
        pinned_cashier = client("qa-pin")
        wrong = pinned_cashier.return_sale(
            pin_sale, [{"sale_item_id": pin_line, "quantity": 1}], "wrong pin",
            pin="000000", pin_username="owner",
        )
        self.assertEqual(wrong.get("status"), 403, wrong)
        self.assertFalse(wrong.get("executed"))
        right = pinned_cashier.return_sale(
            pin_sale, [{"sale_item_id": pin_line, "quantity": 1}], "right pin",
            pin="246810", pin_username="owner",
        )
        self.assertTrue(right.get("executed"), right)

        requester = client("qa-request")
        expense = requester.accounting_create_expense({
            "amount": 80, "description": "Fare", "account_code": "6000", "pay_from_code": "1000",
        })
        self.assertTrue(expense.get("pending_approval"), expense)
        db = self.ac._db()
        expenses = int(db.execute("SELECT COUNT(*) FROM expense_entries").fetchone()[0])
        db.close()
        self.assertEqual(expenses, 0)
        posted = self.owner.execute_approval(int(expense["id"]), "approve", note="fare is real")
        self.assertTrue(posted.get("success"), posted)
        db = self.ac._db()
        expenses = int(db.execute("SELECT COUNT(*) FROM expense_entries").fetchone()[0])
        amount = float(db.execute("SELECT amount FROM expense_entries").fetchone()[0])
        db.close()
        self.assertEqual(expenses, 1)
        self.assertEqual(amount, 80.0)
        posted_again = self.owner.execute_approval(int(expense["id"]), "approve", note="again")
        self.assertTrue(posted_again.get("duplicate"), posted_again)
        db = self.ac._db()
        expenses = int(db.execute("SELECT COUNT(*) FROM expense_entries").fetchone()[0])
        db.close()
        self.assertEqual(expenses, 1)

        customer = self.owner.create_customer({"name": "QA Customer", "phone": "0712345678"})
        self.assertTrue(customer.get("success"), customer)
        credit = requester.create_sale({
            "items": [{
                "product_id": product_id, "product_name": "Mode Soap", "sku": "QA",
                "quantity": 1, "unit_price": 40, "discount": 0, "total": 40,
            }],
            "subtotal": 40, "discount": 0, "tax": 0, "total": 40,
            "payment_method": "Credit", "amount_paid": 0, "change_amount": 0,
            "customer_id": customer["customer_id"],
        })
        self.assertTrue(credit.get("pending_approval"), credit)
        stock_before_credit = self._stock(product_id)
        approved_credit = self.owner.execute_approval(int(credit["id"]), "approve", note="allow credit")
        self.assertTrue(approved_credit.get("success"), approved_credit)
        self.assertEqual(self._stock(product_id), stock_before_credit - 1)
        db = self.ac._db()
        invoice = db.execute(
            "SELECT id, balance FROM debt_invoices ORDER BY id DESC LIMIT 1"
        ).fetchone()
        db.close()
        self.assertIsNotNone(invoice)
        balance_before = float(invoice[1])
        payment = requester.record_debt_payment(int(invoice[0]), 10, "cash", "part")
        self.assertTrue(payment.get("pending_approval"), payment)
        db = self.ac._db()
        balance = float(db.execute("SELECT balance FROM debt_invoices WHERE id=?", (invoice[0],)).fetchone()[0])
        db.close()
        self.assertEqual(balance, balance_before)
        paid = self.owner.execute_approval(int(payment["id"]), "approve", note="take ten")
        self.assertTrue(paid.get("success"), paid)
        db = self.ac._db()
        balance = float(db.execute("SELECT balance FROM debt_invoices WHERE id=?", (invoice[0],)).fetchone()[0])
        db.close()
        self.assertAlmostEqual(balance, balance_before - 10, places=2)

        quiet = client("qa-quiet")
        hidden = quiet.get_report_summary("2026-01-01", "2026-12-31")
        self.assertEqual(hidden.get("status"), 403, hidden)
        visible = self.owner.get_report_summary("2026-01-01", "2026-12-31")
        self.assertNotIn("error", visible)
