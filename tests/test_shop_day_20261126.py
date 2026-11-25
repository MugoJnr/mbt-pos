"""Shop-day defects found on the installed v3.1.93 till."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class GoodsReceiptVoidTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db_path = os.path.join(self._tmpdir.name, "rcv.db")
        self._patches = [
            patch("mbt_paths.get_db_path", return_value=self._db_path),
            patch("desktop.utils.api_client.get_db_path", return_value=self._db_path),
        ]
        for item in self._patches:
            item.start()
        import desktop.utils.api_client as ac
        from desktop.utils.security import _pin_hash
        ac._SCHEMA_READY = False
        self.ac = ac
        db = ac._db()
        db.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, is_active) "
            "VALUES (1,'owner','x','superadmin','Owner',1)"
        )
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('superadmin_pin_hash', ?)",
            (_pin_hash("135790"),),
        )
        db.commit()
        db.close()
        self.api = ac.APIClient()
        self.api._role = "admin"
        self.api._user_id = 1
        self.api._username = "owner"

    def tearDown(self):
        for item in self._patches:
            item.stop()
        self._tmpdir.cleanup()
        self.ac._SCHEMA_READY = False

    def test_voiding_a_receipt_reverses_its_journal_and_leaves_other_layers(self):
        from desktop.utils.stock_layers import add_layer
        created = self.api.create_product({
            "name": "Flour", "price": 200, "cost_price": 100, "stock": 0,
        })
        self.assertTrue(created.get("success"), created)
        pid = created["id"]
        supplier = self.api.create_supplier({"name": "Farm", "phone": "0700111222"})
        db = self.ac._db()
        try:
            add_layer(db, pid, 10, 80, "opening", "open-flour")
            add_layer(db, pid, 5, 90, "purchase", "RCV-OLD:flour")
            db.execute("UPDATE products SET stock=15 WHERE id=?", (pid,))
            db.commit()
        finally:
            db.close()
        saved = self.api.receive_delivery(
            supplier["id"],
            [{"product_id": pid, "quantity": 20, "unit_cost": 110}],
            client_token="rcv-void-1",
        )
        self.assertTrue(saved.get("success"), saved)
        denied = self.api.reverse_stock_receipt(saved["receipt_id"], pin="")
        self.assertEqual(denied.get("status"), 403)
        voided = self.api.reverse_stock_receipt(
            saved["receipt_id"], pin="135790", reason="Wrong delivery",
        )
        self.assertTrue(voided.get("success"), voided)
        db = self.ac._db()
        try:
            layers = {
                row["source_id"]: row["remaining_qty"]
                for row in db.execute(
                    "SELECT source_id, remaining_qty FROM cost_layers WHERE product_id=?",
                    (pid,),
                )
            }
            self.assertEqual(float(layers["open-flour"]), 10)
            self.assertEqual(float(layers["RCV-OLD:flour"]), 5)
            receipt_layer = [
                qty for key, qty in layers.items()
                if str(saved["receipt_number"]) in str(key)
            ]
            self.assertEqual(len(receipt_layer), 1)
            self.assertEqual(float(receipt_layer[0]), 0)
            net_1200 = db.execute(
                """SELECT COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0)
                   FROM journal_lines WHERE account_code='1200'
                     AND journal_id IN (
                       SELECT id FROM journal_entries
                       WHERE source_module='stock_receipts' AND source_id=?
                     )""",
                (str(saved["receipt_id"]),),
            ).fetchone()[0]
            net_2000 = db.execute(
                """SELECT COALESCE(SUM(credit),0) - COALESCE(SUM(debit),0)
                   FROM journal_lines WHERE account_code='2000'
                     AND journal_id IN (
                       SELECT id FROM journal_entries
                       WHERE source_module='stock_receipts' AND source_id=?
                     )""",
                (str(saved["receipt_id"]),),
            ).fetchone()[0]
            self.assertAlmostEqual(float(net_1200), 0.0, places=2)
            self.assertAlmostEqual(float(net_2000), 0.0, places=2)
            listed = self.api.list_stock_receipts(10)
        finally:
            db.close()
        match = next(row for row in listed if row["id"] == saved["receipt_id"])
        self.assertEqual(match["payment_status"], "VOIDED")
        self.assertAlmostEqual(float(match["outstanding"]), 0.0, places=2)


class SplitAndRoundingTests(unittest.TestCase):
    def test_part_pay_remainder_is_customer_credit(self):
        from desktop.utils.payment_tenders import allocate_sale
        covered = allocate_sale(7000, [
            {"method": "Cash", "amount": 3000, "status": "confirmed"},
            {"method": "Credit", "amount": 4000, "status": "outstanding"},
        ])
        self.assertTrue(covered.get("success"), covered)
        self.assertAlmostEqual(covered["cash"], 3000, places=2)
        self.assertAlmostEqual(covered["credit"], 4000, places=2)
        short = allocate_sale(7000, [
            {"method": "Cash", "amount": 3000, "status": "confirmed"},
        ])
        self.assertIn("do not match", short.get("error", ""))

    def test_credit_sale_is_not_cash_rounded(self):
        from desktop.utils.cash_rounding_service import CashRoundingService
        settings = {"enabled": True, "mode": "nearest", "value": 5, "apply_methods": {"cash"}}
        rounded = CashRoundingService.apply_to_total(
            732.50, 0, 0, "credit sale", settings,
        )
        self.assertEqual(rounded["adjustment"], 0.0)
        self.assertAlmostEqual(rounded["amount_due"], 732.50, places=2)
        cash = CashRoundingService.apply_to_total(732.50, 0, 0, "cash", settings)
        self.assertNotEqual(cash["adjustment"], 0.0)


class QuantityEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_decimal_point_does_not_reject_a_fractional_quantity(self):
        from PyQt5.QtCore import QLocale
        from desktop.utils.pos_components import QuantityControl
        box = QuantityControl(value=1, step=0.01, snap=False, decimals=2)
        self.assertEqual(box._spin.locale().decimalPoint(), QLocale.c().decimalPoint())
        box._spin.lineEdit().setText("2.5")
        box._spin.interpretText()
        self.assertAlmostEqual(box.value(), 2.5, places=2)

    def test_unfocused_line_edit_wheel_does_not_change_the_amount(self):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtGui import QWheelEvent
        from PyQt5.QtWidgets import QDoubleSpinBox
        from desktop.utils.no_wheel_controls import install_systemwide_no_wheel_protection
        install_systemwide_no_wheel_protection(self.app)
        spin = QDoubleSpinBox()
        spin.setRange(0, 1000)
        spin.setValue(10)
        editor = spin.lineEdit()
        event = QWheelEvent(
            editor.rect().center(), editor.rect().center(),
            QPoint(0, 0), QPoint(0, 120),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
        )
        self.app.sendEvent(editor, event)
        self.assertEqual(spin.value(), 10)


if __name__ == "__main__":
    unittest.main()
