"""Shared shop-settings catalog for the till and the web dashboard.

One key has one meaning. Finance owns currency and tax. Secrets never appear here.
"""
from __future__ import annotations

CURRENCIES = ('KES', 'USD', 'EUR', 'GBP', 'TZS', 'UGX', 'ZAR')
ROUNDING_MODES = (
    'nearest', 'none', 'nearest_1', 'nearest_5', 'nearest_10', 'always_up', 'always_down',
)
ACCOUNTING_METHODS = ('accrual', 'cash')
COSTING_METHODS = ('weighted_avg', 'fifo')
CHECKOUT_LAYOUTS = ('retail_classic', 'product_explorer', 'checkout_pro')
PAYMENT_METHODS = (
    'Cash', 'M-Pesa', 'Airtel Money', 'Card', 'Bank Transfer',
    'Cheque', 'Part Payment', 'Credit Sale', 'Mixed',
)

# scope: shop (every till that shares this database), device (this computer only
# in intent — each installed till has its own database), protected (never via
# the ordinary save).
SECTIONS = (
    ('shop', 'Shop Information'),
    ('receipts', 'Receipt Printing'),
    ('mpesa', 'M-Pesa Payments'),
    ('variance', 'Payment Variance'),
    ('rounding', 'Cash Rounding'),
    ('finance', 'Finance'),
    ('checkout', 'POS Checkout'),
    ('reports', 'Automatic Reports'),
    ('dashboard', 'Live Dashboard'),
)

BOOL_KEYS = {
    'auto_print',
    'print_customer_copy',
    'print_duplicate_copy',
    'show_document_preview',
    'allow_cashier_doc_override',
    'auto_report_daily',
    'auto_report_weekly',
    'auto_db_backup',
    'variance_enabled',
    'variance_enable_deposits',
    'variance_enable_tips',
    'variance_enable_transport',
    'variance_require_customer_deposit',
    'cash_rounding_enabled',
    'cash_rounding_apply_cash',
    'cash_rounding_apply_mpesa',
    'cash_rounding_apply_card',
    'cash_rounding_apply_bank',
    'receipt_tax_enabled',
    'profit_use_inventory_cogs',
    'profit_include_tips',
    'finance_use_cash_rounding',
    'after_sale_focus_barcode',
    'after_sale_auto_clear_cart',
    'after_sale_reset_discounts',
    'after_sale_reset_notes',
    'autofill_cash_paid',
    'autofill_product_defaults',
    'autofill_reports_today',
    'autofill_clear_search_on_leave',
    'autofill_credit_customer_info',
}

SECTION_OF = {
    'shop_name': 'shop',
    'shop_address': 'shop',
    'shop_phone': 'shop',
    'shop_email': 'shop',
    'currency_symbol': 'finance',
    'currency_code': 'finance',
    'tax_rate': 'finance',
    'receipt_footer': 'receipts',
    'auto_print': 'receipts',
    'printer_port': 'receipts',
    'printer_name': 'receipts',
    'printer_connection': 'receipts',
    'printer_host': 'receipts',
    'paper_size': 'receipts',
    'document_policy': 'receipts',
    'print_customer_copy': 'receipts',
    'print_duplicate_copy': 'receipts',
    'show_document_preview': 'receipts',
    'allow_cashier_doc_override': 'receipts',
    'allow_reprint': 'receipts',
    'mpesa_mode': 'mpesa',
    'mpesa_till': 'mpesa',
    'mpesa_paybill': 'mpesa',
    'mpesa_business_name': 'mpesa',
    'daraja_gateway_url': 'mpesa',
    'daraja_environment': 'mpesa',
    'variance_enabled': 'variance',
    'variance_enable_deposits': 'variance',
    'variance_enable_tips': 'variance',
    'variance_enable_transport': 'variance',
    'variance_require_customer_deposit': 'variance',
    'variance_allow_refund_after_finalize': 'variance',
    'variance_max_cashier': 'variance',
    'cash_rounding_enabled': 'rounding',
    'cash_rounding_apply_cash': 'rounding',
    'cash_rounding_apply_mpesa': 'rounding',
    'cash_rounding_apply_card': 'rounding',
    'cash_rounding_apply_bank': 'rounding',
    'cash_rounding_mode': 'rounding',
    'cash_rounding_value': 'rounding',
    'receipt_tax_enabled': 'finance',
    'fiscal_year_start_month': 'finance',
    'accounting_method': 'finance',
    'inventory_costing': 'finance',
    'acct_cash_code': 'finance',
    'acct_mpesa_code': 'finance',
    'acct_bank_code': 'finance',
    'expense_category_codes': 'finance',
    'opening_balances_note': 'finance',
    'profit_use_inventory_cogs': 'finance',
    'profit_include_tips': 'finance',
    'finance_use_cash_rounding': 'finance',
    'after_sale_default_customer': 'checkout',
    'after_sale_default_payment': 'checkout',
    'after_sale_focus_barcode': 'checkout',
    'after_sale_auto_clear_cart': 'checkout',
    'after_sale_reset_discounts': 'checkout',
    'after_sale_reset_notes': 'checkout',
    'autofill_cash_paid': 'checkout',
    'autofill_product_defaults': 'checkout',
    'autofill_reports_today': 'checkout',
    'autofill_clear_search_on_leave': 'checkout',
    'autofill_credit_customer_info': 'checkout',
    'pos_checkout_layout': 'checkout',
    'auto_report_daily': 'reports',
    'auto_report_weekly': 'reports',
    'auto_db_backup': 'reports',
}

# Printer port is recorded as device-intent. Each installed till has its own
# database, so this value does not change another computer.
DEVICE_KEYS = frozenset({'printer_port'})

# Ordinary Save must not change these. They stay on their own actions.
FORCED = {
    'mpesa_mode': 'manual',
    'daraja_environment': 'sandbox',
    'variance_allow_refund_after_finalize': '0',
    'sync_interval': '30',
    'allow_reprint': '1',
}


def section_for(key: str) -> str:
    return SECTION_OF.get(key, 'other')


def scope_for(key: str) -> str:
    if key in DEVICE_KEYS:
        return 'device'
    return 'shop'
