"""Each Super Admin has their own PIN. A cashier cannot set one, and the PIN is not stored."""
import sqlite3
import unittest

from desktop.utils.security import _pin_hash
from desktop.utils.superadmin_pin import (
    gate_personal_pin, set_superadmin_user_pin, verify_superadmin_user_pin,
)


def _db():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, "
        "is_active INTEGER, full_name TEXT)"
    )
    db.execute("INSERT INTO users VALUES (1, 'edmus', 'superadmin', 1, 'Edmus')")
    db.execute("INSERT INTO users VALUES (2, 'ann', 'cashier', 1, 'Ann')")
    return db


class SuperAdminPinTests(unittest.TestCase):
    def test_each_super_admin_pin_is_hashed_and_locks(self):
        db = _db()
        denied = set_superadmin_user_pin(db, 2, "135790")
        self.assertIn("Super Admin", denied["error"])
        short = set_superadmin_user_pin(db, 1, "1234")
        self.assertIn("6 to 8", short["error"])
        saved = set_superadmin_user_pin(db, 1, "135790")
        self.assertTrue(saved.get("success"))
        stored = db.execute("SELECT pin_hash FROM users WHERE id=1").fetchone()[0]
        self.assertNotEqual(stored, "1234")
        self.assertNotIn("1234", stored)
        wrong = verify_superadmin_user_pin(db, "edmus", "999999")
        self.assertIn("not accepted", wrong["error"])
        ok = verify_superadmin_user_pin(db, "edmus", "135790")
        self.assertEqual(ok["authoriser_id"], 1)
        self.assertNotIn("pin_hash", ok)
        for _ in range(5):
            verify_superadmin_user_pin(db, "edmus", "0000")
        locked = verify_superadmin_user_pin(db, "edmus", "135790")
        self.assertTrue(locked.get("locked"))

    def test_the_old_shop_pin_does_not_approve_a_stock_reduction(self):
        db = _db()
        db.execute("CREATE TABLE system_settings (key TEXT, value TEXT)")
        db.execute(
            "INSERT INTO system_settings VALUES ('superadmin_pin_hash', ?)",
            (_pin_hash("246810"),),
        )
        set_superadmin_user_pin(db, 1, "135790")
        rejected = gate_personal_pin(db, "246810", "edmus")
        self.assertEqual(rejected["status"], 403)
        accepted = gate_personal_pin(db, "135790", "edmus")
        self.assertIsNone(accepted)
