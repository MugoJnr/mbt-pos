"""Deterministic checks for the 26 Nov 2026 shop-facing fixes."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QA = Path(os.environ.get("MBT_DATA_ROOT") or r"C:\MBT_Build\qa-final-20261126")
os.environ.setdefault("MBT_DATA_ROOT", str(QA))
os.environ.setdefault("MBT_TEST_INSTANCE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", str(QA / "local"))
os.environ.setdefault("APPDATA", str(QA / "appdata"))
os.environ.setdefault("PROGRAMDATA", str(QA / "programdata"))


class ReceiptMoneyTests(unittest.TestCase):
    def test_discount_is_shown_before_the_net_subtotal(self):
        from printing.sale_documents import receipt_total_rows
        rows = receipt_total_rows(100, 15, 0, 85)
        labels = [label for label, _amount in rows]
        self.assertLess(labels.index("Discount"), labels.index("Subtotal"))
        self.assertEqual(dict(rows)["Subtotal"], 85.0)
        self.assertNotEqual(dict(rows)["Subtotal"], 100.0)

    def test_already_net_subtotal_is_not_reduced_twice(self):
        from printing.sale_documents import receipt_total_rows
        rows = receipt_total_rows(85, 15, 0, 85)
        self.assertEqual(dict(rows)["Subtotal"], 85.0)


class GreetingTests(unittest.TestCase):
    def test_shop_and_owner_are_not_a_persons_name(self):
        from desktop.utils.ui_polish import time_greeting
        for name in ("Shop", "Shop Owner", "Owner"):
            headline, _sub = time_greeting(name)
            self.assertIn("there", headline)
            self.assertNotIn("Shop", headline.split(",")[-1])
            self.assertNotIn("Owner", headline.split(",")[-1])


class ReportGateTests(unittest.TestCase):
    def test_empty_daily_and_monthly_reports_are_not_sent(self):
        from backend.cloud.report_engine import ReportEngine
        engine = ReportEngine(":memory:", config_getter=lambda: {})
        published = []
        engine.generate_report = lambda kind: {
            "summary": {"transactions": 0, "revenue": 0},
            "currency": "KES",
            "period_start": "2026-11-26",
            "period_end": "2026-11-26",
        }
        engine._record_delivery = lambda *args, **kwargs: published.append(args)
        for kind in ("daily", "monthly"):
            ok, message = engine.send_report_now(kind)
            self.assertFalse(ok)
            self.assertIn("No sales", message)
        self.assertEqual(published, [])


class VersionDateTests(unittest.TestCase):
    def test_build_date_comes_from_version_json_released(self):
        from web.web_routes import _app_version_info
        released = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["released"][:10]
        info = _app_version_info()
        self.assertEqual(info["build_date"], released)
        self.assertNotEqual(info["build_date"], "2026-07-21")


class StatusLabelTests(unittest.TestCase):
    def test_missing_printer_and_backup_are_not_ready(self):
        from desktop.tabs.dashboard_tab import backup_status_label, printer_status_label
        self.assertFalse(printer_status_label({})[1])
        self.assertNotIn("Ready", printer_status_label({})[0])
        self.assertTrue(printer_status_label({"printer_name": "Till"})[1])
        self.assertFalse(backup_status_label("")[1])
        self.assertNotIn("OK", backup_status_label("")[0])
        self.assertTrue(backup_status_label("2026-11-26T08:00:00")[1])


class ActivationSeatTests(unittest.TestCase):
    def _server(self, reserved):
        from backend.cloud.license_server import CloudLicenseServer

        class Fake(CloudLicenseServer):
            def __init__(self):
                self.inserted = False

            def _rows(self, table, query):
                return [{
                    "id": "lic1",
                    "status": "issued",
                    "max_devices": 1,
                    "reserved_device_id": reserved,
                    "license_key": "MBT-TEST",
                    "plan": "shop",
                    "expires_at": None,
                    "assigned_email": "",
                }]

            def _activation_device_ids(self, device_id, aliases):
                return [device_id, "MBT-PC-THIS"]

            def _expand_device_aliases(self, ids):
                return list(ids)

            def _find_active_activation(self, *args, **kwargs):
                return None

            def _find_activation(self, *args, **kwargs):
                return None

            def _count_active_seats(self, *args, **kwargs):
                return 1

            def _sync_activated_devices(self, *args, **kwargs):
                return 1

            def _pick_canonical_device_id(self, ids):
                return ids[0]

            def _insert(self, *args, **kwargs):
                self.inserted = True
                return {"id": 1}

            def _update(self, *args, **kwargs):
                return None

            def _log_history(self, *args, **kwargs):
                return None

        return Fake()

    def test_reserved_computer_is_not_told_the_device_limit_is_full(self):
        server = self._server("MBT-PC-THIS")
        ok, message, _payload = server.activate("MBT-TEST", "dev-1", "org")
        self.assertTrue(ok, message)
        self.assertNotIn("Device limit", message)
        self.assertTrue(server.inserted)

    def test_a_different_computer_is_still_limited(self):
        server = self._server("")
        ok, message, _payload = server.activate("MBT-TEST", "dev-other", "org")
        self.assertFalse(ok)
        self.assertIn("Device limit", message)


class ShopDataTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True, dir=str(QA),
        )
        self._db_path = os.path.join(self._tmpdir.name, "pos.db")
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
        db = self.ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active) "
            "VALUES (1,'owner','x','superadmin','Owner',1)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS sync_outbox ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "event_id TEXT NOT NULL UNIQUE,"
            "entity_type TEXT NOT NULL,"
            "row_id TEXT NOT NULL,"
            "operation TEXT NOT NULL,"
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "attempts INTEGER NOT NULL DEFAULT 0,"
            "last_error TEXT,"
            "processed_at TEXT)"
        )
        db.commit()
        db.close()

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self.ac._SCHEMA_READY = False
        self._tmpdir.cleanup()

    def test_unapproved_rows_are_not_waiting_and_real_failures_stay_visible(self):
        db = self.ac._db()
        try:
            db.execute(
                "INSERT INTO sync_outbox (event_id, entity_type, row_id, operation, last_error) "
                "VALUES ('e1','sale','1','upsert','Device is not approved')"
            )
            db.execute(
                "INSERT INTO sync_outbox (event_id, entity_type, row_id, operation, last_error) "
                "VALUES ('e2','sale','2','upsert','portal timeout')"
            )
            db.commit()
        finally:
            db.close()
        status = self.api.sync_status()
        self.assertEqual(status["held_for_approval"], 1)
        self.assertEqual(status["failed"], 1)
        self.assertEqual(status["pending_upload"], 1)

    def test_debt_customer_name_comes_from_the_customer(self):
        db = self.ac._db()
        try:
            db.execute(
                "INSERT INTO customers (name, phone) VALUES ('Ada', '0700')"
            )
            customer_id = db.execute("SELECT id FROM customers WHERE name='Ada'").fetchone()[0]
            db.execute(
                "INSERT INTO debt_invoices "
                "(invoice_number, customer_id, customer_name, total_amount, balance, status) "
                "VALUES ('INV-ADA', ?, '', 100, 100, 'open')",
                (customer_id,),
            )
            db.commit()
        finally:
            db.close()
        rows = self.api.get_debt_invoices()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["customer_name"], "Ada")

    def test_new_approval_refund_reference_is_short(self):
        done = self.api.apply_owner_action("refund", "Refund", "Counter refund", 25)
        self.assertTrue(done.get("success") or done.get("executed"), done)
        number = done.get("receipt_number") or ""
        if not number:
            db = self.ac._db()
            try:
                row = db.execute(
                    "SELECT receipt_number FROM sales ORDER BY id DESC LIMIT 1"
                ).fetchone()
                number = row[0] if row else ""
            finally:
                db.close()
        self.assertRegex(number, r"^RET-\d{8}-\d{4}$")
        self.assertLess(len(number), 24)
        self.assertIsNone(re.search(r"RET-\d{14,}", number))
