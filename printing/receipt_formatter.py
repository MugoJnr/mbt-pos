"""
Receipt model / text layout — NO hardware I/O.

Turns authoritative sale dict values into display lines.
Does not recalculate financial totals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


def currency_label(symbol: str | None) -> str:
    s = (symbol or 'KES').strip()
    if s.upper() in ('KES', 'KSH', 'KSHS'):
        return 'KSh'
    return s or 'KSh'


def format_money(amount, symbol: str = 'KES') -> str:
    try:
        val = float(amount or 0)
    except (TypeError, ValueError):
        val = 0.0
    return f"{currency_label(symbol)} {val:,.2f}"


def left_right(left: str, right: str, width: int) -> str:
    left = str(left or '')
    right = str(right or '')
    space = width - len(left) - len(right)
    if space < 1:
        # Prefer keeping the right (amount) visible
        keep = max(0, width - len(right) - 1)
        left = left[:keep]
        space = width - len(left) - len(right)
        if space < 1:
            return (left + right)[:width]
    return left + (' ' * space) + right


def wrap_text(text: str, width: int, max_lines: int = 3) -> List[str]:
    text = str(text or '')
    if width < 8:
        width = 8
    if not text:
        return ['']
    chunks = [text[i:i + width] for i in range(0, len(text), width)]
    return chunks[:max_lines]


@dataclass
class ReceiptLine:
    kind: str  # text | sep | blank
    text: str = ''
    align: str = 'left'  # left | center | right
    bold: bool = False
    double: bool = False


@dataclass
class ReceiptDocument:
    """Hardware-agnostic receipt representation."""
    lines: List[ReceiptLine] = field(default_factory=list)
    receipt_number: str = ''
    is_reprint: bool = False
    qr_payload: str = ''
    barcode_payload: str = ''
    open_drawer: bool = False
    cut: bool = True
    feed_before_cut: int = 3


def _sep(width: int, char: str = '-') -> ReceiptLine:
    return ReceiptLine(kind='sep', text=char * width)


def build_receipt_document(
    sale_data: dict,
    *,
    shop_name: str = 'My Shop',
    currency: str = 'KES',
    footer: str = 'Thank you for shopping with us!',
    shop_address: str = '',
    shop_phone: str = '',
    width: int = 48,
    is_reprint: bool = False,
    print_logo: bool = False,  # logo handled by builder; flag for future
    qr_enabled: bool = False,
) -> ReceiptDocument:
    """
    Map saved sale fields → receipt lines.
    Amounts are taken from sale_data as-is (no recalculation of TOTAL).
    Outstanding for credit/part uses stored total - amount_paid - credit_applied
    only for display of debt balance (same as prior text engine).
    """
    sale = sale_data or {}
    W = max(32, int(width or 48))
    doc = ReceiptDocument(
        receipt_number=str(sale.get('receipt_number') or ''),
        is_reprint=bool(is_reprint),
        feed_before_cut=3,
        cut=True,
    )
    lines = doc.lines

    def T(text='', *, align='left', bold=False, double=False):
        lines.append(ReceiptLine('text', str(text), align, bold, double))

    def B():
        lines.append(ReceiptLine('blank'))

    # Header
    T(shop_name[:W], align='center', bold=True, double=True)
    addr = (shop_address or '').strip()
    phone = (shop_phone or '').strip()
    if addr:
        for chunk in wrap_text(addr, W, 2):
            T(chunk, align='center')
    if phone:
        T(phone[:W], align='center')
    T('TAX INVOICE', align='center')
    lines.append(_sep(W, '='))

    if is_reprint:
        T('*** COPY / REPRINT ***', align='center', bold=True)
        T(f"Reprinted: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align='center')
        lines.append(_sep(W, '-'))

    inv = sale.get('receipt_number') or 'N/A'
    date_str = sale.get('created_at', datetime.now().isoformat())[:19]
    try:
        from desktop.utils.shop_time import receipt_date_label
        date_str, _ = receipt_date_label(sale)
    except Exception:
        pass
    cashier = sale.get('cashier_name') or 'Staff'
    pay = sale.get('payment_method') or 'Cash'

    T(f'Receipt: {inv}')
    T(f'Date:    {date_str}')
    T(f'Cashier: {cashier}')
    T(f'Payment: {pay}')
    cust = (sale.get('customer_name') or '').strip()
    if cust:
        T(f'Customer:{cust}'[:W])
    lines.append(_sep(W))

    # Items — name on its own line(s), then qty x price .... total
    T('ITEMS', bold=True)
    lines.append(_sep(W))
    for item in sale.get('items') or []:
        name = str(item.get('product_name') or '')
        for chunk in wrap_text(name, W, 3):
            T(chunk)
        try:
            qty_val = float(item.get('quantity', 1) or 1)
        except (TypeError, ValueError):
            qty_val = 1.0
        qty = f'{qty_val:g}' if qty_val % 1 else f'{int(qty_val)}'
        try:
            unit = float(item.get('unit_price', 0) or 0)
        except (TypeError, ValueError):
            unit = 0.0
        try:
            line_total = float(item.get('total', 0) or 0)
        except (TypeError, ValueError):
            line_total = 0.0
        left = f'{qty} x {unit:,.2f}'
        right = f'{line_total:,.2f}'
        T(left_right(left, right, W))
        try:
            disc = float(item.get('discount') or 0)
        except (TypeError, ValueError):
            disc = 0.0
        if disc > 0.009:
            T(left_right('  Disc:', f'-{disc:,.2f}', W))
    lines.append(_sep(W))

    # Totals — display stored values only
    try:
        discount = float(sale.get('discount') or 0)
    except (TypeError, ValueError):
        discount = 0.0
    try:
        tax = float(sale.get('tax') or 0)
    except (TypeError, ValueError):
        tax = 0.0
    try:
        subtotal = float(sale.get('subtotal') or sale.get('total') or 0)
    except (TypeError, ValueError):
        subtotal = 0.0
    try:
        total = float(sale.get('total') or 0)
    except (TypeError, ValueError):
        total = 0.0
    try:
        amount_paid = float(sale.get('amount_paid') or 0)
    except (TypeError, ValueError):
        amount_paid = 0.0
    try:
        change = float(sale.get('change_amount') or 0)
    except (TypeError, ValueError):
        change = 0.0
    try:
        credit_applied = float(sale.get('credit_applied') or 0)
    except (TypeError, ValueError):
        credit_applied = 0.0
    try:
        adj = float(sale.get('cash_rounding_adj') or 0)
    except (TypeError, ValueError):
        adj = 0.0
    orig = sale.get('original_total')
    try:
        elec = float(sale.get('electronic_paid') or 0)
    except (TypeError, ValueError):
        elec = 0.0
    try:
        cash_paid = float(sale.get('cash_paid') or 0)
    except (TypeError, ValueError):
        cash_paid = 0.0

    if discount > 0.009:
        T(left_right('Subtotal:', format_money(subtotal, currency), W))
        T(left_right('Discount:', f'-{format_money(discount, currency)}', W))
    if tax > 0.009:
        T(left_right('Tax:', format_money(tax, currency), W))
    pm_low = str(pay).lower()
    is_electronic = any(x in pm_low for x in ('mpesa', 'm-pesa', 'card', 'bank', 'cheque', 'eft'))
    is_mixed = 'mixed' in pm_low or elec > 0.009
    if abs(adj) > 0.009 and (not is_electronic or is_mixed):
        if orig is not None:
            T(left_right('Original:', format_money(orig, currency), W))
        sign = '+' if adj >= 0 else '-'
        T(left_right('Cash Rounding:', f'{sign}{format_money(abs(adj), currency)}', W))
    T(left_right('TOTAL:', format_money(total, currency), W), bold=True)
    if credit_applied > 0.009:
        T(left_right('Store Credit:', f'-{format_money(credit_applied, currency)}', W))

    if elec > 0.009:
        em = (sale.get('electronic_method') or 'Electronic').strip() or 'Electronic'
        if cash_paid < 0.009:
            cash_paid = max(0.0, round(amount_paid - elec, 2))
        T(left_right(f'{em}:', format_money(elec, currency), W))
        T(left_right('Cash:', format_money(cash_paid, currency), W))
    else:
        T(left_right(f'Amount Paid:', format_money(amount_paid, currency), W))
    if change > 0.009:
        T(left_right('Change:', format_money(change, currency), W))

    # M-Pesa refs — only when present
    if 'mpesa' in pm_low or 'm-pesa' in pm_low or (sale.get('mpesa_ref') or '').strip():
        till = (sale.get('mpesa_till') or '').strip()
        pb = (sale.get('mpesa_paybill') or '').strip()
        ref = (sale.get('mpesa_ref') or '').strip()
        if till or pb or ref:
            lines.append(_sep(W))
            T('M-PESA', bold=True, align='center')
            if till:
                T(left_right('Till:', till, W))
            if pb:
                T(left_right('Paybill:', pb, W))
            if ref:
                for i, chunk in enumerate(wrap_text(ref, max(8, W - 10), 2)):
                    T(left_right('Ref:' if i == 0 else '', chunk, W))

    # Variance (customer-facing tips/transport only — never additional_payment)
    var = sale.get('variance') or {}
    handling = (var.get('handling') or '').strip().lower()
    if handling != 'additional_payment':
        try:
            excess = float(var.get('excess_amount') or 0)
        except (TypeError, ValueError):
            excess = 0.0
        if excess > 0.009:
            lines.append(_sep(W))
            for key, label in (
                ('tip_amount', 'Tip'),
                ('transport_amount', 'Transport'),
                ('deposit_amount', 'Deposit'),
                ('advance_amount', 'Advance'),
            ):
                try:
                    amt = float(var.get(key) or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                if amt > 0.009:
                    T(left_right(f'{label}:', format_money(amt, currency), W))
            try:
                misc = float(var.get('misc_amount') or 0)
            except (TypeError, ValueError):
                misc = 0.0
            if misc > 0.009:
                cat = var.get('misc_category') or 'Misc'
                T(left_right(f'Misc ({cat}):', format_money(misc, currency), W))

    # Debt / part / credit — use stored amounts; balance from stored fields
    if pm_low in ('part payment', 'credit sale', 'credit', 'on account'):
        # Prefer authoritative outstanding from debt invoice if provided
        bal = sale.get('outstanding_balance')
        if bal is None:
            bal = round(total - amount_paid - credit_applied, 2)
        try:
            bal = float(bal)
        except (TypeError, ValueError):
            bal = 0.0
        if bal > 0.009:
            lines.append(_sep(W))
            title = 'PART PAYMENT' if 'part' in pm_low else 'CREDIT SALE'
            T(f'*** {title} ***', align='center', bold=True)
            if cust:
                T(left_right('Customer:', cust[: max(8, W - 12)], W))
            inv_n = (sale.get('debt_invoice_number') or '').strip()
            if inv_n:
                T(left_right('Debt Inv:', inv_n, W))
            due = (sale.get('due_date') or '').strip()
            if due:
                T(left_right('Due Date:', due[:16], W))
            T(left_right('Outstanding:', format_money(bal, currency), W), bold=True)

    lines.append(_sep(W, '='))
    foot = (footer or 'Thank you for shopping with us!').strip()
    for chunk in wrap_text(foot, W, 2):
        T(chunk, align='center')
    T('Powered by MugoByte', align='center')
    lines.append(_sep(W, '='))

    if qr_enabled and inv and inv != 'N/A':
        doc.qr_payload = str(inv)

    # Barcode of receipt number when printable ASCII
    if inv and inv != 'N/A' and all(32 <= ord(c) < 127 for c in str(inv)):
        doc.barcode_payload = str(inv)[:32]

    return doc


def document_to_plain_text(doc: ReceiptDocument, width: int = 48) -> str:
    W = max(32, int(width or 48))
    out = []
    for line in doc.lines:
        if line.kind == 'blank':
            out.append('')
        elif line.kind == 'sep':
            out.append((line.text or '-')[:W])
        else:
            text = line.text or ''
            if line.align == 'center':
                out.append(text.center(W)[:W])
            elif line.align == 'right':
                out.append(text.rjust(W)[:W])
            else:
                out.append(text[:W])
    return '\n'.join(out)
