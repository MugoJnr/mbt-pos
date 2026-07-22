"""Low-risk gap fixes: receipt address/phone + autofill reports preset."""
from printing.printer_engine import build_receipt, ReceiptBuilder
from desktop.utils.auto_fill import AutoFillService, AUTOFILL_REPORTS_TODAY


def test_receipt_includes_shop_address_and_phone():
    data = build_receipt(
        {
            'receipt_number': 'R-1',
            'created_at': '2026-07-22T10:00:00',
            'cashier_name': 'Test',
            'subtotal': 100,
            'discount': 0,
            'tax': 0,
            'total': 100,
            'payment_method': 'Cash',
            'amount_paid': 100,
            'change_amount': 0,
            'items': [
                {
                    'product_name': 'Item',
                    'quantity': 1,
                    'unit_price': 100,
                    'total': 100,
                }
            ],
        },
        shop_name='Demo Shop',
        currency='KES',
        shop_address='123 Market St',
        shop_phone='0700 000 000',
    )
    text = data.decode('cp437', errors='replace')
    assert 'Demo Shop' in text
    assert '123 Market St' in text
    assert '0700 000 000' in text


def test_receipt_builder_header_skips_blank_contact():
    b = ReceiptBuilder(shop_name='Only Name', shop_address='  ', shop_phone='')
    b.header('INV', '2026-07-22', 'Cashier')
    text = bytes(b.build()).decode('cp437', errors='replace')
    assert 'Only Name' in text
    assert 'INV' in text


def test_reports_default_preset_respects_flag():
    assert AutoFillService.reports_default_preset(
        {AUTOFILL_REPORTS_TODAY: '1'}) == 'today'
    assert AutoFillService.reports_default_preset(
        {AUTOFILL_REPORTS_TODAY: '0'}) == ''
    assert AutoFillService.reports_default_preset({}) == 'today'
