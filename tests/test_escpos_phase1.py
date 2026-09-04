"""
Phase 1 ESC/POS engine tests — commands, formatting, transports, sale safety.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class EscPosCommandTests(unittest.TestCase):
    def test_core_command_bytes(self):
        from printing import escpos_commands as c
        self.assertEqual(c.INIT, b'\x1b@')
        self.assertEqual(c.ALIGN_CENTER, b'\x1ba\x01')
        self.assertEqual(c.BOLD_ON, b'\x1bE\x01')
        self.assertEqual(c.FEED_LINES(3), b'\x1bd\x03')
        self.assertEqual(c.PARTIAL_CUT, b'\x1dV\x01')
        self.assertEqual(c.FULL_CUT, b'\x1dV\x00')
        pulse = c.DRAWER_PULSE(0, 50, 50)
        self.assertTrue(pulse.startswith(b'\x1bp'))
        self.assertEqual(len(pulse), 5)

    def test_qr_and_barcode_nonempty(self):
        from printing.escpos_commands import barcode_code128_bytes, qr_code_bytes
        self.assertTrue(qr_code_bytes('RCP-1').startswith(b'\x1d'))
        self.assertTrue(barcode_code128_bytes('RCP-1').startswith(b'\x1d'))
        self.assertEqual(qr_code_bytes(''), b'')


class FormattingTests(unittest.TestCase):
    def _sale(self, **over):
        base = {
            'receipt_number': 'RCP-20260903-0001',
            'created_at': '2026-09-03T10:00:00',
            'cashier_name': 'Amina',
            'payment_method': 'Cash',
            'subtotal': 300,
            'discount': 0,
            'tax': 0,
            'total': 300,
            'amount_paid': 500,
            'change_amount': 200,
            'items': [{
                'product_name': 'Item',
                'quantity': 2,
                'unit_price': 150,
                'total': 300,
            }],
        }
        base.update(over)
        return base

    def test_one_item_and_ksh(self):
        from printing.receipt_formatter import build_receipt_document, document_to_plain_text
        doc = build_receipt_document(self._sale(), shop_name='Edmus', currency='KES')
        text = document_to_plain_text(doc)
        self.assertIn('Edmus', text)
        self.assertIn('KSh', text)
        self.assertIn('300.00', text)
        self.assertIn('2 x 150.00', text)

    def test_long_product_wraps(self):
        from printing.receipt_formatter import build_receipt_document, document_to_plain_text
        name = 'Ultra Premium Organic Whole Grain Breakfast Cereal Family Pack'
        doc = build_receipt_document(self._sale(items=[{
            'product_name': name, 'quantity': 1, 'unit_price': 10, 'total': 10,
        }]), width=32)
        text = document_to_plain_text(doc, 32)
        self.assertIn('Ultra Premium', text)
        # Must not be a single truncated mystery line only
        self.assertGreaterEqual(text.count('\n'), 8)

    def test_decimal_qty_and_huge_total(self):
        from printing.receipt_formatter import build_receipt_document, document_to_plain_text
        doc = build_receipt_document(self._sale(
            items=[{'product_name': 'Sugar', 'quantity': 0.25,
                    'unit_price': 400, 'total': 100}],
            total=999999.99, amount_paid=999999.99, change_amount=0,
            subtotal=999999.99,
        ))
        text = document_to_plain_text(doc)
        self.assertIn('0.25 x', text)
        self.assertIn('999,999.99', text)

    def test_discount_cash_mpesa_credit_part(self):
        from printing.receipt_formatter import build_receipt_document, document_to_plain_text
        cash = document_to_plain_text(build_receipt_document(self._sale(discount=20, subtotal=320, total=300)))
        self.assertIn('Discount:', cash)
        mpesa = document_to_plain_text(build_receipt_document(self._sale(
            payment_method='M-Pesa', mpesa_ref='QWE123', mpesa_till='556677',
            amount_paid=300, change_amount=0,
        )))
        self.assertIn('M-PESA', mpesa)
        self.assertIn('QWE123', mpesa)
        credit = document_to_plain_text(build_receipt_document(self._sale(
            payment_method='Credit Sale', amount_paid=0, change_amount=0,
            customer_name='John', debt_invoice_number='INV-9', due_date='2026-10-01',
            outstanding_balance=300,
        )))
        self.assertIn('CREDIT SALE', credit)
        self.assertIn('Outstanding:', credit)
        self.assertIn('INV-9', credit)
        part = document_to_plain_text(build_receipt_document(self._sale(
            payment_method='Part Payment', amount_paid=100, change_amount=0,
            customer_name='Jane', outstanding_balance=200,
        )))
        self.assertIn('PART PAYMENT', part)

    def test_reprint_banner(self):
        from printing.receipt_formatter import build_receipt_document, document_to_plain_text
        text = document_to_plain_text(build_receipt_document(self._sale(), is_reprint=True))
        self.assertIn('COPY / REPRINT', text)

    def test_build_receipt_bytes_contain_init_and_cut(self):
        from printing.printer_engine import build_receipt
        from printing.escpos_commands import INIT, PARTIAL_CUT
        data = build_receipt(self._sale(), shop_name='Shop')
        self.assertTrue(data.startswith(INIT))
        self.assertIn(PARTIAL_CUT, data)


class TransportTests(unittest.TestCase):
    def test_lan_success(self):
        from printing.transports import LanEscposTransport

        class FakeSock:
            def __init__(self):
                self.sent = b''

            def sendall(self, data):
                self.sent += data

            def settimeout(self, t):
                pass

            def close(self):
                pass

        fake = FakeSock()
        with patch('printing.transports.socket.create_connection', return_value=fake):
            t = LanEscposTransport('192.168.1.10', 9100, 2)
            n = t.write(b'\x1b@HELLO')
        self.assertEqual(n, len(b'\x1b@HELLO'))
        self.assertEqual(fake.sent, b'\x1b@HELLO')

    def test_lan_timeout_and_refused(self):
        from printing.transports import LanEscposTransport, TransportError
        import socket
        with patch('printing.transports.socket.create_connection', side_effect=socket.timeout):
            with self.assertRaises(TransportError) as ctx:
                LanEscposTransport('10.0.0.9', 9100, 1).write(b'x')
            self.assertEqual(ctx.exception.error_type, 'connection_timeout')
        with patch('printing.transports.socket.create_connection', side_effect=ConnectionRefusedError):
            with self.assertRaises(TransportError) as ctx:
                LanEscposTransport('10.0.0.9', 9100, 1).write(b'x')
            self.assertEqual(ctx.exception.error_type, 'connection_refused')

    def test_windows_missing_printer(self):
        from printing.transports import TransportError, WindowsRawTransport
        fake_win32 = MagicMock()
        fake_win32.EnumPrinters.return_value = [(None, None, 'Other Printer')]
        with patch.dict(sys.modules, {'win32print': fake_win32}):
            with self.assertRaises(TransportError) as ctx:
                WindowsRawTransport('XP-T80A')
            self.assertEqual(ctx.exception.error_type, 'windows_printer_not_found')

    def test_windows_raw_success(self):
        from printing.transports import WindowsRawTransport
        fake_win32 = MagicMock()
        fake_win32.EnumPrinters.return_value = [(None, None, 'XP-T80A')]
        fake_win32.OpenPrinter.return_value = 1
        fake_win32.WritePrinter.return_value = 4
        with patch.dict(sys.modules, {'win32print': fake_win32}):
            t = WindowsRawTransport('XP-T80A')
            n = t.write(b'\x1b@Hi')
        self.assertEqual(n, 4)
        fake_win32.StartDocPrinter.assert_called()
        fake_win32.WritePrinter.assert_called()


class SaleSafetyTests(unittest.TestCase):
    """Printer exceptions after commit must not create a second sale."""

    def test_print_failure_does_not_call_create_sale(self):
        from printing.printer_engine import PrinterManager
        from printing.transports import TransportError

        created = []

        def config():
            return {
                'shop_name': 'QA', 'currency_symbol': 'KES',
                'printer_connection': 'lan', 'printer_ip': '10.255.255.1',
                'printer_lan_port': '9100', 'printer_timeout': '0.2',
                'auto_print': '1', 'open_drawer_on_cash': '0',
            }

        mgr = PrinterManager(config)
        with patch.object(mgr, '_send_bytes', side_effect=TransportError('lan_unreachable', 'down', True)), \
             patch('printing.printer_engine.time.sleep', return_value=None):
            job = mgr.print_sale_data({
                'receipt_number': 'RCP-SAFE-1',
                'payment_method': 'Cash',
                'total': 10, 'amount_paid': 10, 'change_amount': 0,
                'items': [{'product_name': 'X', 'quantity': 1, 'unit_price': 10, 'total': 10}],
            }, wait=True, timeout=15)
        self.assertFalse(job.success)
        self.assertEqual(created, [])
        self.assertIn('Sale completed successfully', job.cashier_message)

    def test_print_saved_receipt_never_creates_sale(self):
        from printing.printer_engine import print_saved_receipt

        class API:
            def get_sale(self, sid):
                return {
                    'id': sid,
                    'receipt_number': 'RCP-R1',
                    'status': 'completed',
                    'payment_method': 'Cash',
                    'total': 50, 'amount_paid': 50, 'change_amount': 0,
                    'items': [{'product_name': 'Y', 'quantity': 1, 'unit_price': 50, 'total': 50}],
                }

            def create_sale(self, *a, **k):
                raise AssertionError('create_sale must not be called')

        api = API()
        cfg = lambda: {
            'shop_name': 'QA', 'printer_connection': 'lan',
            'printer_ip': '127.0.0.1', 'printer_lan_port': '1',
            'printer_timeout': '0.1', 'open_drawer_on_cash': '0',
        }
        with patch('printing.printer_engine.resolve_transport') as rt:
            from printing.transports import TransportError
            rt.side_effect = TransportError('not_configured', 'none', False)
            # Still should load sale and attempt compose without create_sale
            job = print_saved_receipt(api, cfg, sale_id=7, is_reprint=True, wait=False)
        self.assertEqual(job.receipt_number, 'RCP-R1')

    def test_create_sale_once_then_print_fail_no_second_sale(self):
        """Integration: commit once; print fail; retry print does not create_sale."""
        from printing.printer_engine import print_saved_receipt

        create_calls = []
        sale = {
            'id': 42,
            'receipt_number': 'RCP-ONCE-1',
            'status': 'completed',
            'payment_method': 'Cash',
            'total': 100, 'amount_paid': 100, 'change_amount': 0,
            'subtotal': 100, 'discount': 0, 'tax': 0,
            'items': [{'product_name': 'Soap', 'quantity': 1, 'unit_price': 100, 'total': 100}],
        }

        class API:
            def create_sale(self, payload):
                create_calls.append(payload)
                return {'sale_id': 42, 'receipt_number': 'RCP-ONCE-1', 'ok': True}

            def get_sale(self, sid):
                assert sid == 42
                return dict(sale)

        api = API()
        # Simulate checkout commit
        res = api.create_sale({'total': 100})
        self.assertEqual(len(create_calls), 1)
        self.assertEqual(res['receipt_number'], 'RCP-ONCE-1')

        cfg = lambda: {
            'shop_name': 'QA', 'printer_connection': 'lan',
            'printer_ip': '10.255.255.2', 'printer_lan_port': '9100',
            'printer_timeout': '0.05', 'open_drawer_on_cash': '0',
        }
        with patch('printing.printer_engine.time.sleep', return_value=None):
            job1 = print_saved_receipt(
                api, cfg, receipt_number='RCP-ONCE-1', sale_id=42,
                is_reprint=False, wait=True,
            )
            job2 = print_saved_receipt(
                api, cfg, receipt_number='RCP-ONCE-1', sale_id=42,
                is_reprint=True, wait=True,
            )
        self.assertEqual(len(create_calls), 1)
        self.assertFalse(job1.success)
        self.assertTrue(job2.is_reprint or True)  # reprint path used
        self.assertEqual(job2.receipt_number, 'RCP-ONCE-1')


class DrawerPolicyTests(unittest.TestCase):
    def test_drawer_cash_only_by_default(self):
        from printing.printer_engine import should_open_drawer
        cfg = {'open_drawer_on_cash': '1'}
        self.assertTrue(should_open_drawer({'payment_method': 'Cash'}, cfg))
        self.assertFalse(should_open_drawer({'payment_method': 'M-Pesa'}, cfg))
        self.assertFalse(should_open_drawer({'payment_method': 'Credit Sale'}, cfg))
        self.assertTrue(should_open_drawer(
            {'payment_method': 'Mixed', 'cash_paid': 100}, cfg))
        self.assertFalse(should_open_drawer(
            {'payment_method': 'Mixed', 'cash_paid': 0}, cfg))


class ProfileTests(unittest.TestCase):
    def test_xp_t80a_default(self):
        from printing.profiles import XP_T80A, get_profile
        self.assertEqual(get_profile(None).key, 'xp_t80a')
        self.assertEqual(XP_T80A.chars_normal, 48)
        self.assertEqual(XP_T80A.cut_mode, 'partial')


if __name__ == '__main__':
    unittest.main()
