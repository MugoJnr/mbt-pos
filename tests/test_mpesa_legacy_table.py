"""An older shop M-Pesa table must accept a manual code without a new database."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_SHOP = tempfile.mkdtemp(prefix="mbt-mpesa-legacy-")
os.environ["MBT_TEST_INSTANCE"] = "1"
os.environ["MBT_DATA_ROOT"] = _SHOP
os.environ["APPDATA"] = os.path.join(_SHOP, "appdata")
os.environ["LOCALAPPDATA"] = os.path.join(_SHOP, "localappdata")
os.environ["PROGRAMDATA"] = os.path.join(_SHOP, "programdata")

from backend.mpesa_service import (  # noqa: E402
    MpesaSaleError,
    _code_taken,
    _insert_payment,
    ensure_tables,
    prepare_sale_mpesa,
)


LEGACY = """
CREATE TABLE mpesa_payments (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT '',
    amount_expected REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KES',
    status TEXT NOT NULL DEFAULT 'draft',
    channel TEXT NOT NULL DEFAULT 'stk',
    phone_masked TEXT NOT NULL DEFAULT '',
    phone_e164 TEXT NOT NULL DEFAULT '',
    customer_name TEXT NOT NULL DEFAULT '',
    cart_fingerprint TEXT NOT NULL DEFAULT '',
    cart_json TEXT NOT NULL DEFAULT '',
    sale_id INTEGER,
    receipt_number TEXT,
    provider_checkout_id TEXT NOT NULL DEFAULT '',
    provider_reference TEXT,
    merchant_request_id TEXT NOT NULL DEFAULT '',
    checkout_request_id TEXT NOT NULL DEFAULT '',
    till_number TEXT NOT NULL DEFAULT '',
    paybill_number TEXT NOT NULL DEFAULT '',
    account_reference TEXT NOT NULL DEFAULT '',
    amount_received REAL NOT NULL DEFAULT 0,
    variance REAL NOT NULL DEFAULT 0,
    match_confidence TEXT NOT NULL DEFAULT 'none',
    match_candidates_json TEXT NOT NULL DEFAULT '[]',
    idempotency_key TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    cashier_id INTEGER,
    cashier_name TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    verified_at REAL NOT NULL DEFAULT 0,
    completed_at REAL NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}'
)
"""


class LegacyMpesaTableTests(unittest.TestCase):
    def test_manual_code_fits_the_existing_shop_table(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, mpesa_ref TEXT)")
        db.execute(LEGACY)
        db.execute(
            """INSERT INTO mpesa_payments
               (id, shop_id, amount_expected, created_at, updated_at, provider_reference)
               VALUES ('old', 'shop', 10, 1, 1, 'OLDCODE1')"""
        )
        ensure_tables(db)
        payment_id = _insert_payment(
            db,
            kind="manual",
            state="recorded",
            amount_text="30.00",
            receipt_code="QAMPESA0001",
            verification="manual",
            provider="manual",
            result_detail="Manually recorded. Not verified with Safaricom.",
        )
        db.commit()
        row = db.execute("SELECT * FROM mpesa_payments WHERE id=?", (payment_id,)).fetchone()
        self.assertEqual(row["receipt_code"], "QAMPESA0001")
        self.assertEqual(row["shop_id"], "local")
        self.assertEqual(row["amount_expected"], 30)
        self.assertTrue(_code_taken(db, "QAMPESA0001"))
        self.assertEqual(
            db.execute("SELECT provider_reference FROM mpesa_payments WHERE id='old'").fetchone()[0],
            "OLDCODE1",
        )
        ensure_tables(db)
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM mpesa_payments").fetchone()[0],
            2,
        )

    def test_card_and_cash_ignore_a_leftover_mpesa_code(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, mpesa_ref TEXT)")
        ensure_tables(db)
        _insert_payment(
            db,
            kind="manual",
            state="recorded",
            amount_text="30.00",
            receipt_code="QAMPESA0001",
            verification="manual",
            provider="manual",
        )
        for method in ("card", "cash", "Credit Sale"):
            prepared = prepare_sale_mpesa(
                db,
                {"payment_method": method, "mpesa_ref": "QAMPESA0001", "total": 60},
                method,
                0,
            )
            self.assertEqual(prepared, {})
        with self.assertRaises(MpesaSaleError):
            prepare_sale_mpesa(
                db,
                {"payment_method": "m-pesa", "mpesa_ref": "QAMPESA0001", "total": 30, "amount_paid": 30},
                "m-pesa",
                0,
            )
        split = prepare_sale_mpesa(
            db,
            {
                "payment_method": "Mixed",
                "payment_tenders": [
                    {"method": "Cash", "amount": 10},
                    {"method": "M-Pesa", "amount": 20, "reference": "QAMPESA0002"},
                ],
                "total": 30,
            },
            "Mixed",
            20,
        )
        self.assertEqual(split["mpesa_ref"], "QAMPESA0002")
        self.assertEqual(split["verification"], "manual")


if __name__ == "__main__":
    unittest.main()
