"""Receipt wording, tender labels, stocktake cost repair, and the sale refresh path."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

_ISOLATION = tempfile.mkdtemp(prefix="mbt-close-iso-")
os.environ["MBT_DATA_ROOT"] = _ISOLATION
os.environ["APPDATA"] = _ISOLATION
os.environ["LOCALAPPDATA"] = _ISOLATION
os.environ["PROGRAMDATA"] = _ISOLATION
os.environ["MBT_TEST_INSTANCE"] = "1"
os.makedirs(os.path.join(_ISOLATION, "data"), exist_ok=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class CloseDefectTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "close.db")
        os.environ["MBT_DATA_ROOT"] = self._tmpdir.name
        os.environ["APPDATA"] = self._tmpdir.name
        os.environ["LOCALAPPDATA"] = self._tmpdir.name
        os.environ["PROGRAMDATA"] = self._tmpdir.name
        os.environ["MBT_TEST_INSTANCE"] = "1"
        os.environ["MBT_PRINTER_SIMULATE"] = "fail"
        os.makedirs(os.path.join(self._tmpdir.name, "data"), exist_ok=True)
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
            ("closer", ac._hash_pw("close-pass"), "superadmin", "Closer"),
        )
        db.execute(
            "INSERT INTO products (name, sku, price, cost_price, stock, unit, is_active) "
            "VALUES ('Sugar', 'SUGAR', 80, 100, 10, 'kg', 1)"
        )
        db.commit()
        self.user_id = db.execute("SELECT id FROM users").fetchone()["id"]
        self.product_id = db.execute("SELECT id FROM products").fetchone()["id"]
        db.close()

    def tearDown(self):
        os.environ.pop("MBT_PRINTER_SIMULATE", None)
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def _api(self):
        api = self.ac.APIClient()
        api._user_id = self.user_id
        api._username = "closer"
        api._role = "superadmin"
        return api

    def _sale(self, **extra):
        payload = {
            "items": [{
                "product_id": self.product_id,
                "product_name": "Sugar",
                "quantity": 1,
                "unit_price": 80,
                "discount": 0,
                "total": 80,
            }],
            "subtotal": 80,
            "discount": 0,
            "tax": 0,
            "total": 80,
            "payment_method": "Cash",
            "amount_paid": 80,
            "cash_paid": 80,
        }
        payload.update(extra)
        return self._api().create_sale(payload)

    def test_electronic_method_keeps_every_non_cash_tender(self):
        from desktop.utils.payment_tenders import electronic_method_label
        tenders = [
            {"method": "M-Pesa", "amount": 30, "status": "confirmed", "reference": "QASPLIT0002"},
            {"method": "Card", "amount": 20, "status": "confirmed"},
            {"method": "Cash", "amount": 30, "status": "confirmed"},
        ]
        self.assertEqual(electronic_method_label(tenders, "M-Pesa"), "M-Pesa + Card")
        created = self._sale(
            payment_method="Mixed",
            amount_paid=80,
            cash_paid=30,
            electronic_paid=50,
            electronic_method="M-Pesa",
            payment_tenders=tenders,
            client_token="split-methods",
        )
        self.assertTrue(created.get("success"), created)
        db = self.ac._db()
        row = db.execute(
            "SELECT electronic_method, electronic_paid, cash_paid, payment_tenders FROM sales WHERE id=?",
            (created["sale_id"],),
        ).fetchone()
        db.close()
        self.assertEqual(row["electronic_method"], "M-Pesa + Card")
        self.assertAlmostEqual(float(row["electronic_paid"]), 50.0, places=2)
        self.assertAlmostEqual(float(row["cash_paid"]), 30.0, places=2)
        stored = json.loads(row["payment_tenders"])
        self.assertEqual([item["method"] for item in stored], ["M-Pesa", "Card", "Cash"])
        self.assertEqual([item["amount"] for item in stored], [30, 20, 30])

    def test_first_receipt_is_not_a_reprint_and_viewing_does_not_sell_again(self):
        from printing.direct import render_text
        created = self._sale(client_token="receipt-once")
        self.assertTrue(created.get("success"), created)
        db = self.ac._db()
        before = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        first = render_text(db, "sale", created["sale_id"], {"role": "cashier"})
        again = render_text(db, "sale", created["sale_id"], {"role": "cashier"}, reprint=True)
        preview = self._api().preview_saved_document("sale", created["sale_id"])
        after = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        db.close()
        self.assertNotIn("REPRINT", first.get("text") or "")
        self.assertIn("REPRINT", again.get("text") or "")
        self.assertNotIn("REPRINT", preview.get("text") or "")
        self.assertEqual(before, after)

    def test_blank_shop_name_is_not_presented_as_a_real_shop(self):
        from printing.sale_documents import build_sale_document
        created = self._sale(client_token="shop-name")
        db = self.ac._db()
        blank = build_sale_document(db, created["sale_id"])
        self.assertIn("Shop name not set", blank.get("text") or "")
        self.assertNotIn("My Shop", blank.get("text") or "")
        long_name = "QA Disposable Grocer and Household Supplies Limited"
        db.execute(
            "INSERT INTO system_settings (key, value) VALUES ('shop_name', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (long_name,),
        )
        db.commit()
        named = build_sale_document(db, created["sale_id"])
        db.close()
        text = named.get("text") or ""
        self.assertIn("QA Disposable Grocer and Household Supplies", text)
        self.assertIn("Limited", text)
        self.assertNotIn("Shop name not set", text)

    def test_historical_stocktake_shortage_consumes_cost_once(self):
        from desktop.utils.stock_layers import add_layer
        from desktop.utils.stocktake import _REPAIRED_PATHS, repair_uncosted_stocktake_shortages
        db = self.ac._db()
        add_layer(db, self.product_id, 10, 100, "opening", "sugar-open")
        db.execute("UPDATE products SET stock=9.75 WHERE id=?", (self.product_id,))
        db.execute(
            "INSERT INTO stock_movements "
            "(product_id, product_name, movement_type, qty_before, qty_change, qty_after, reference, reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.product_id, "Sugar", "STOCKTAKE", 10, -0.25, 9.75, f"STK:9:{self.product_id}", "Stocktake 9"),
        )
        db.commit()
        _REPAIRED_PATHS.clear()
        first = repair_uncosted_stocktake_shortages(db)
        stock = db.execute("SELECT stock FROM products WHERE id=?", (self.product_id,)).fetchone()[0]
        remaining = db.execute(
            "SELECT COALESCE(SUM(remaining_qty), 0) FROM cost_layers WHERE product_id=?",
            (self.product_id,),
        ).fetchone()[0]
        used = db.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM cost_layer_uses WHERE reference=? AND COALESCE(reversed,0)=0",
            (f"STK:9:{self.product_id}",),
        ).fetchone()[0]
        audit = db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='REPAIR_STOCKTAKE_COST'"
        ).fetchone()[0]
        _REPAIRED_PATHS.clear()
        second = repair_uncosted_stocktake_shortages(db)
        db.close()
        self.assertTrue(first.get("success"), first)
        self.assertEqual(len(first.get("repaired") or []), 1)
        self.assertAlmostEqual(float(stock), 9.75, places=2)
        self.assertAlmostEqual(float(remaining), 9.75, places=2)
        self.assertAlmostEqual(float(used), 0.25, places=2)
        self.assertGreaterEqual(int(audit), 1)
        self.assertEqual(second.get("repaired"), [])

    def test_sale_confirmation_does_not_rebuild_the_catalog_before_returning(self):
        path = os.path.join(ROOT, "desktop", "tabs", "sales_tab.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("self._refresh_sold_stock(", text)
        self.assertIn("defer_grid=True", text)
        self.assertNotIn("self.refresh(force=True)\n", text)

    def test_printer_probe_does_not_scan_when_no_printer_is_configured(self):
        from printing.printer_engine import probe_printer
        started = time.perf_counter()
        result = probe_printer({"printer_connection": "USB", "printer_port": "USB", "printer_name": ""})
        elapsed = time.perf_counter() - started
        self.assertFalse(result.get("available"))
        self.assertLess(elapsed, 0.5)

    def test_release_file_version_matches_runtime(self):
        with open(os.path.join(ROOT, "file_version_info.txt"), encoding="utf-8") as handle:
            info = handle.read()
        with open(os.path.join(ROOT, "version.json"), encoding="utf-8") as handle:
            version = json.load(handle)
        self.assertIn("3.1.92.0", info)
        self.assertNotIn("3.1.91.0", info)
        self.assertEqual(version["version"], "3.1.92")
