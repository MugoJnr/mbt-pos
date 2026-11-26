"""Backup commands and a local encrypted snapshot that restores somewhere else."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class BackupRoundtripTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "shop.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
            patch("backend.cloud_backup.sync_manager.get_db_path", return_value=self._db_path),
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

    def test_expired_wrong_device_and_duplicate_commands_do_not_run(self):
        from backend.cloud.command_center import CommandCenter, dispatch_remote_command
        center = CommandCenter(self._db_path, config_getter=lambda: {})
        receipt = os.path.join(self._tmpdir.name, "receipts.json")
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        expired = dispatch_remote_command(
            center,
            {"id": "cmd-old", "command": "run_backup", "expires_at": past, "device_id": "till-a"},
            receipt,
            device_id="till-a",
            org_id="shop-a",
        )
        self.assertEqual(expired, "expired")
        wrong = dispatch_remote_command(
            center,
            {"id": "cmd-other", "command": "run_backup", "device_id": "till-b", "org_id": "shop-a"},
            receipt,
            device_id="till-a",
            org_id="shop-a",
        )
        self.assertEqual(wrong, "wrong_device")
        other_shop = dispatch_remote_command(
            center,
            {"id": "cmd-shop", "command": "run_backup", "device_id": "till-a", "org_id": "shop-b"},
            receipt,
            device_id="till-a",
            org_id="shop-a",
        )
        self.assertEqual(other_shop, "wrong_shop")
        with patch("backend.cloud.command_center.claim_pending_command", return_value=True), \
             patch.object(center, "report_result"), \
             patch.object(center, "execute_local", return_value=(True, "ran", {})) as ran:
            first = dispatch_remote_command(
                center,
                {"id": "cmd-once", "command": "run_backup", "device_id": "till-a", "org_id": "shop-a"},
                receipt,
                device_id="till-a",
                org_id="shop-a",
            )
            second = dispatch_remote_command(
                center,
                {"id": "cmd-once", "command": "run_backup", "device_id": "till-a", "org_id": "shop-a"},
                receipt,
                device_id="till-a",
                org_id="shop-a",
            )
        self.assertEqual(first, "executed")
        self.assertEqual(second, "skipped")
        self.assertEqual(ran.call_count, 1)

    def test_failed_upload_does_not_replace_the_current_backup(self):
        product = self.api.create_product({
            "name": "Backup Soap", "price": 10, "stock": 1, "unit": "pcs", "cost_price": 4,
        })
        self.assertTrue(product.get("success"), product)
        calls = []

        class FakeClient:
            def upload_file(self, path, *_args, **_kwargs):
                calls.append(path)
                if "/staging/" in path:
                    raise ConnectionError("upload interrupted")

            def rest_select(self, *_args, **_kwargs):
                return []

        from backend.cloud_backup.sync_manager import SyncManager
        with patch("backend.cloud_backup.sync_manager.is_cloud_configured", return_value=True), \
             patch("backend.cloud_backup.sync_manager.is_logged_in", return_value=True), \
             patch("backend.cloud_backup.sync_manager.load_identity", return_value={
                 "business_id": "qa-business", "user_id": "qa-user", "email": "qa@example.com",
             }), \
             patch("backend.cloud_backup.sync_manager.save_identity"), \
             patch("backend.cloud_backup.sync_manager.get_device_info", return_value={
                 "device_id": "qa-device", "hostname": "qa", "platform": "test",
             }), \
             patch("backend.cloud_backup.sync_manager.SupabaseClient", FakeClient), \
             patch("backend.cloud_backup.sync_manager.ensure_identity_key_material", return_value=(b"k" * 32, {
                 "business_id": "qa-business",
             })):
            result = SyncManager.instance().run_backup(reason="qa")
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("queued"))
        self.assertTrue(any("/staging/" in path for path in calls))
        self.assertFalse(any(path.endswith("/latest.mbtenc") for path in calls))

    def test_snapshot_restores_into_a_different_database(self):
        from backend.cloud_backup.encryption import decrypt_file, encrypt_file, sha256_file
        from backend.cloud_backup.sync_manager import create_sqlite_snapshot
        created = self.api.create_product({
            "name": "Restore Soap", "price": 12, "stock": 3, "unit": "pcs", "cost_price": 5,
        })
        self.assertTrue(created.get("success"), created)
        sale = self.api.create_sale({
            "items": [{
                "product_id": created["id"], "product_name": "Restore Soap", "sku": "R",
                "quantity": 1, "unit_price": 12, "discount": 0, "total": 12,
            }],
            "subtotal": 12, "discount": 0, "tax": 0, "total": 12,
            "payment_method": "Cash", "amount_paid": 12, "change_amount": 0,
        })
        self.assertTrue(sale.get("success"), sale)
        original = sqlite3.connect(self._db_path)
        original_sales = original.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        original_products = original.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        original.close()
        zip_path, tmp_dir = create_sqlite_snapshot(self._db_path)
        try:
            enc_path = zip_path + ".mbtenc"
            key = os.urandom(32)
            encrypt_file(zip_path, enc_path, key)
            digest = sha256_file(enc_path)
            self.assertEqual(digest, sha256_file(enc_path))
            broken = enc_path + ".partial"
            with open(enc_path, "rb") as src, open(broken, "wb") as dst:
                dst.write(src.read(40))
            with self.assertRaises(Exception):
                decrypt_file(broken, broken + ".zip", key)
            restored_zip = os.path.join(self._tmpdir.name, "restored.zip")
            decrypt_file(enc_path, restored_zip, key)
            out_dir = os.path.join(self._tmpdir.name, "restored")
            os.makedirs(out_dir)
            with zipfile.ZipFile(restored_zip) as archive:
                archive.extractall(out_dir)
            restored_db = os.path.join(out_dir, "mbt_pos.db")
            self.assertNotEqual(os.path.abspath(restored_db), os.path.abspath(self._db_path))
            check = sqlite3.connect(restored_db)
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(check.execute("SELECT COUNT(*) FROM sales").fetchone()[0], original_sales)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM products").fetchone()[0], original_products)
            self.assertEqual(
                check.execute("SELECT total FROM sales").fetchone()[0],
                12,
            )
            check.close()
            self.assertEqual(integrity, "ok")
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
