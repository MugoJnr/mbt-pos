"""Low-risk gap fixes: receipt address/phone + autofill reports preset."""
from printing.printer_engine import build_receipt, ReceiptBuilder
from printing.receipt_formatter import build_receipt_document, document_to_plain_text
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


def test_receipt_document_includes_sale_item_product_lines():
    """Completed-sale receipt must show product name, qty, unit price, line total."""
    doc = build_receipt_document(
        {
            'receipt_number': 'RCP-20260909-0001',
            'created_at': '2026-09-09T10:00:00',
            'cashier_name': 'Mercy',
            'payment_method': 'Cash',
            'subtotal': 350,
            'discount': 0,
            'tax': 0,
            'total': 350,
            'amount_paid': 500,
            'change_amount': 150,
            'items': [
                {
                    'product_name': 'Maize Flour 2kg',
                    'quantity': 2,
                    'unit_price': 125,
                    'discount': 0,
                    'total': 250,
                    'unit_cost': 80,
                },
                {
                    'name': 'Cooking Oil 1L',  # alternate key used by some payloads
                    'quantity': 1,
                    'unit_price': 100,
                    'total': 100,
                },
            ],
        },
        shop_name='Edmus',
        currency='KES',
    )
    text = document_to_plain_text(doc)
    assert 'ITEMS' in text
    assert 'Maize Flour 2kg' in text
    assert '2 x 125.00' in text
    assert '250.00' in text
    assert 'Cooking Oil 1L' in text
    assert '1 x 100.00' in text
    assert 'TOTAL:' in text
    assert 'Change:' in text


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
