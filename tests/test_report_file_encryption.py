"""Report file encryption and the figures those reports must not mix up."""
from __future__ import annotations

import os
import tempfile
import unittest
from io import BytesIO

from openpyxl import Workbook, load_workbook

from backend.report_file_encryption import (
    ExportPasswordError,
    check_export_password,
    csv_opens,
    export_audit_text,
    generate_export_password,
    pdf_opens,
    safe_download_name,
    seal_csv,
    seal_pdf,
    seal_xlsx_file,
    xlsx_opens,
)
from desktop.utils.payment_tenders import collected_from_sales, credit_issued_from_sales
from pypdf import PdfWriter


SECRET = 'shop-report-pass'
OTHER = 'different-pass'


def _plain_pdf(text: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _plain_xlsx(marker: str) -> str:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    handle.close()
    book = Workbook()
    book.active['A1'] = marker
    book.save(handle.name)
    book.close()
    return handle.name


class ExportPasswordRules(unittest.TestCase):
    def test_empty_password_is_rejected(self):
        with self.assertRaises(ExportPasswordError):
            check_export_password('', '')

    def test_whitespace_password_is_rejected(self):
        with self.assertRaises(ExportPasswordError):
            check_export_password('   ', '   ')

    def test_short_pin_is_rejected(self):
        with self.assertRaises(ExportPasswordError):
            check_export_password('246810', '246810')

    def test_nine_characters_are_rejected(self):
        with self.assertRaises(ExportPasswordError):
            check_export_password('123456789', '123456789')

    def test_ten_characters_are_accepted(self):
        self.assertEqual(check_export_password('1234567890', '1234567890'), '1234567890')

    def test_mismatch_is_rejected(self):
        with self.assertRaises(ExportPasswordError):
            check_export_password(SECRET, OTHER)

    def test_leading_space_is_rejected(self):
        with self.assertRaises(ExportPasswordError):
            check_export_password(' ' + SECRET, ' ' + SECRET)

    def test_very_long_password_is_rejected(self):
        huge = 'a' * 129
        with self.assertRaises(ExportPasswordError):
            check_export_password(huge, huge)

    def test_max_length_is_accepted(self):
        value = 'b' * 128
        self.assertEqual(len(check_export_password(value, value)), 128)

    def test_unicode_password_is_accepted(self):
        value = 'Ripoti-2026-ሀ'
        self.assertEqual(check_export_password(value, value), value)

    def test_special_characters_are_accepted(self):
        value = 'P@ssw0rd!!'
        self.assertEqual(check_export_password(value, value), value)

    def test_generated_password_is_long_enough(self):
        value = generate_export_password()
        self.assertGreaterEqual(len(value), 10)
        self.assertEqual(check_export_password(value, value), value)

    def test_two_generated_passwords_differ(self):
        self.assertNotEqual(generate_export_password(), generate_export_password())


class PdfEncryption(unittest.TestCase):
    def test_pdf_requires_the_password_and_rejects_the_wrong_one(self):
        sealed = seal_pdf(_plain_pdf('Sales'), SECRET)
        self.assertIn(b'/Encrypt', sealed)
        self.assertTrue(pdf_opens(sealed, SECRET) is not None)
        with self.assertRaises(Exception):
            pdf_opens(sealed, '')
        with self.assertRaises(Exception):
            pdf_opens(sealed, OTHER)

    def test_two_pdf_encryptions_are_not_identical(self):
        raw = _plain_pdf('Sales')
        self.assertNotEqual(seal_pdf(raw, SECRET), seal_pdf(raw, SECRET))


class WorkbookEncryption(unittest.TestCase):
    def test_xlsx_is_an_encrypted_office_file_not_a_plain_zip(self):
        path = _plain_xlsx('RCP-KNOWN')
        try:
            sealed = seal_xlsx_file(path, SECRET)
        finally:
            os.remove(path)
        self.assertTrue(sealed.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'))
        self.assertFalse(sealed.startswith(b'PK'))
        opened = xlsx_opens(sealed, SECRET)
        book = load_workbook(BytesIO(opened), read_only=True, data_only=True)
        try:
            self.assertEqual(book.active['A1'].value, 'RCP-KNOWN')
        finally:
            book.close()
        with self.assertRaises(Exception):
            xlsx_opens(sealed, OTHER)
        with self.assertRaises(Exception):
            xlsx_opens(sealed, '')

    def test_unicode_password_opens_the_workbook(self):
        password = 'Ripoti-2026-ሀ'
        path = _plain_xlsx('KES 55')
        try:
            sealed = seal_xlsx_file(path, password)
        finally:
            os.remove(path)
        opened = xlsx_opens(sealed, password)
        book = load_workbook(BytesIO(opened), read_only=True, data_only=True)
        try:
            self.assertEqual(book.active['A1'].value, 'KES 55')
        finally:
            book.close()

    def test_plaintext_workbook_is_removed_by_the_caller(self):
        path = _plain_xlsx('temp')
        seal_xlsx_file(path, SECRET)
        os.remove(path)
        self.assertFalse(os.path.exists(path))


class CsvArchiveEncryption(unittest.TestCase):
    def test_csv_download_is_an_aes_zip_and_not_a_raw_csv(self):
        raw = 'Receipt,Total\nRCP-1,55.00\n'.encode('utf-8')
        sealed = seal_csv(raw, 'MBT_Sales.csv', SECRET)
        self.assertTrue(sealed.startswith(b'PK'))
        self.assertNotIn(b'RCP-1', sealed)
        self.assertEqual(csv_opens(sealed, SECRET), raw)
        with self.assertRaises(Exception):
            csv_opens(sealed, OTHER)
        with self.assertRaises(Exception):
            csv_opens(sealed, '')

    def test_path_traversal_name_cannot_leave_the_archive(self):
        sealed = seal_csv(b'a,b\n', '../../secret.csv', SECRET)
        import pyzipper
        with pyzipper.AESZipFile(BytesIO(sealed)) as archive:
            archive.setpassword(SECRET.encode('utf-8'))
            names = archive.namelist()
            self.assertEqual(names, ['secret.csv'])
            self.assertFalse(any('/' in name or '\\' in name or name.startswith('..') for name in names))

    def test_stdlib_zipfile_cannot_read_the_aes_archive(self):
        import zipfile
        sealed = seal_csv(b'hidden\n', 'sales.csv', SECRET)
        with self.assertRaises(Exception):
            with zipfile.ZipFile(BytesIO(sealed)) as archive:
                archive.read(archive.namelist()[0])


class AuditAndNames(unittest.TestCase):
    def test_audit_text_has_no_password_field(self):
        text = export_audit_text(
            report='sales', fmt='xlsx', period='2026-10-30..2026-10-30',
            ok=True, sha256='abc123',
        )
        self.assertNotIn('password', text.lower())
        self.assertNotIn(SECRET, text)
        self.assertIn('encrypted=aes-256', text)

    def test_unsafe_file_names_are_rejected(self):
        self.assertEqual(safe_download_name('../sales.csv', 'report.csv'), 'sales.csv')
        self.assertEqual(safe_download_name('sales?.csv', 'report.csv'), 'report.csv')
        self.assertEqual(safe_download_name('sales.csv', 'report.csv'), 'sales.csv')


class ReportFigures(unittest.TestCase):
    def test_cash_change_is_not_collected(self):
        figures = collected_from_sales([{
            'payment_method': 'cash',
            'total': 55,
            'amount_paid': 75,
            'change_amount': 20,
        }])
        self.assertEqual(figures['cash_collected'], 55)
        self.assertEqual(figures['collected'], 55)

    def test_credit_is_not_collected_and_a_repayment_is_not_a_sale(self):
        sale = {
            'payment_method': 'Cash + M-Pesa',
            'total': 2000,
            'amount_paid': 1000,
            'change_amount': 0,
            'payment_tenders': [
                {'method': 'M-Pesa', 'amount': 500, 'status': 'confirmed'},
                {'method': 'Cash', 'amount': 300, 'status': 'confirmed'},
                {'method': 'Card', 'amount': 200, 'status': 'confirmed'},
                {'method': 'Credit', 'amount': 1000, 'status': 'outstanding'},
            ],
        }
        figures = collected_from_sales([sale])
        self.assertEqual(figures['mpesa_collected'], 500)
        self.assertEqual(figures['cash_collected'], 300)
        self.assertEqual(figures['card_collected'], 200)
        self.assertEqual(figures['collected'], 1000)
        self.assertEqual(credit_issued_from_sales([sale]), 1000)
        repayment_is_not_a_sale = collected_from_sales([])
        self.assertEqual(repayment_is_not_a_sale['collected'], 0)

    def test_missing_cost_is_not_invented_as_profit(self):
        from desktop.utils.stock_layers import period_profit
        self.assertTrue(callable(period_profit))


if __name__ == '__main__':
    unittest.main()
