"""A submitted backdate request must not leave its lines in the till cart."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Host:
    def __init__(self, cart, stash):
        self.cart = cart
        self._stashed_cart = stash
        self._backdate_request_mode = True
        self._backdate_reason = "QA sequence"
        self.reset_called = False
        self.refresh_called = False

    def _reset_business_day_today(self):
        self.reset_called = True

    def _refresh_cart(self):
        self.refresh_called = True


class BackdateCartRestoreTests(unittest.TestCase):
    def test_empty_stash_clears_the_request_lines(self):
        from desktop.tabs.sales_tab import SalesTab

        host = _Host(
            cart=[{"product_id": 10, "quantity": 2}],
            stash=[],
        )
        SalesTab._exit_backdate_mode(host, restore=True)
        self.assertEqual(host.cart, [])
        self.assertFalse(host._backdate_request_mode)
        self.assertEqual(host._backdate_reason, "")
        self.assertIsNone(host._stashed_cart)
        self.assertTrue(host.reset_called)
        self.assertTrue(host.refresh_called)

    def test_previous_cart_is_restored_without_the_request_lines(self):
        from desktop.tabs.sales_tab import SalesTab

        previous = [{"product_id": 2, "quantity": 1}]
        host = _Host(
            cart=[{"product_id": 10, "quantity": 2}],
            stash=previous,
        )
        SalesTab._exit_backdate_mode(host, restore=True)
        self.assertEqual(host.cart, previous)
        self.assertIsNot(host.cart, previous)


if __name__ == "__main__":
    unittest.main()
