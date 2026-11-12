"""New Backdated Sale must reach Point of Sale when opened from Receipts."""
import unittest

from desktop.tabs.backdate_dialog import open_backdated_sale


class _Node:
    def __init__(self, parent=None):
        self._parent = parent

    def parent(self):
        return self._parent


class _Sales:
    def __init__(self, calls):
        self.calls = calls

    def begin_backdated_sale(self):
        self.calls.append('begin')


class _Host:
    def __init__(self, calls):
        self.calls = calls
        self._tabs = {}

    def parent(self):
        return None

    def _goto(self, tab_id):
        self.calls.append(tab_id)
        self._tabs['sales'] = _Sales(self.calls)


class BackdateDialogHostTests(unittest.TestCase):
    def test_receipts_parent_opens_the_sales_cart(self):
        calls = []
        host = _Host(calls)
        receipts = _Node(host)
        self.assertTrue(open_backdated_sale(receipts))
        self.assertEqual(calls, ['sales', 'begin'])

    def test_missing_sales_tab_does_not_invent_a_cart(self):
        class _Empty:
            def parent(self):
                return None

        self.assertFalse(open_backdated_sale(_Empty()))


if __name__ == '__main__':
    unittest.main()
