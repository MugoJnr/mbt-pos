"""Device move must revoke the old computer once, and accept Pulse device ids."""
from __future__ import annotations

import unittest

from licensing.device_transfer import classify_device_transfer, classify_seat_validation, validation_http


class DeviceTransferTests(unittest.TestCase):
    def test_move_issues_one_revoke(self):
        ok, message, revoke = classify_device_transfer(
            "MBT-PC-52E6",
            "a" * 40,
            {"MBT-PC-52E6"},
        )
        self.assertTrue(ok)
        self.assertEqual(message, "Device transferred")
        self.assertTrue(revoke)

    def test_repeat_move_does_not_revoke_again(self):
        new_id = "b" * 40
        ok, message, revoke = classify_device_transfer("MBT-PC-52E6", new_id, {new_id})
        self.assertTrue(ok)
        self.assertEqual(message, "Already on this device")
        self.assertFalse(revoke)

    def test_same_device_is_not_a_move(self):
        ok, message, revoke = classify_device_transfer("PULSE-1", "PULSE-1", {"PULSE-1"})
        self.assertTrue(ok)
        self.assertFalse(revoke)
        self.assertIn("Already", message)

    def test_blank_device_rejected(self):
        ok, message, revoke = classify_device_transfer("", "abc", set())
        self.assertFalse(ok)
        self.assertFalse(revoke)
        self.assertIn("required", message)

    def test_pulse_seat_stays_on_the_holding_device(self):
        device = "a" * 40
        outcome, message = classify_seat_validation(
            device,
            [{"id": "lic-1", "status": "active", "product_id": "pulse", "reserved_device_id": device}],
            {"lic-1": [{"device_id": device, "is_active": True}]},
        )
        code, body = validation_http(outcome, message)
        self.assertEqual(outcome, "ok")
        self.assertEqual(code, 200)

    def test_moved_seat_locks_the_old_device(self):
        old, new = "a" * 40, "b" * 40
        outcome, message = classify_seat_validation(
            old,
            [{"id": "lic-1", "status": "active", "reserved_device_id": new}],
            {"lic-1": [
                {"device_id": old, "is_active": False},
                {"device_id": new, "is_active": True},
            ]},
        )
        code, body = validation_http(outcome, message)
        self.assertEqual(outcome, "moved")
        self.assertEqual(code, 403)
        self.assertIn("transferred", body["error"])

    def test_same_pc_alias_is_not_a_move(self):
        shop = "MBT-PC-52E6"
        hardware = "c" * 40
        outcome, _ = classify_seat_validation(
            hardware,
            [{"id": "lic-1", "status": "active", "reserved_device_id": shop}],
            {"lic-1": [{"device_id": shop, "is_active": True}]},
            aliases=[shop, hardware],
        )
        self.assertEqual(outcome, "ok")

    def test_no_paid_seat_stays_free(self):
        outcome, message = classify_seat_validation("a" * 40, [])
        code, body = validation_http(outcome, message)
        self.assertEqual(outcome, "free")
        self.assertEqual(code, 200)
        self.assertEqual(body["license_type"], "free")

    def test_suspended_seat_locks(self):
        outcome, message = classify_seat_validation(
            "MBT-PC-52E6",
            [{"id": "lic-1", "status": "suspended"}],
        )
        code, _ = validation_http(outcome, message)
        self.assertEqual(outcome, "suspended")
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
