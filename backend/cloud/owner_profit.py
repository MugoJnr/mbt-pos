"""Owner-portal profit splits built from synced sale lines.

The till copies FIFO cost onto each sale line at the time of the sale
(``unit_cost``). The portal uses that snapshot. It does not recompute
batches, and a later debt repayment does not create a new sale or a
second profit.

Allocation for one sale
-----------------------
* Gross profit is line revenue minus line cost. A sale with no synced
  lines contributes zero profit (the same rule as the existing overview).
* The sale is one of: fully paid, credit, or part-payment. Those three
  buckets add up to gross profit. Voids are excluded.
* Collected versus outstanding uses the invoice balance when a debt
  invoice is linked, because that balance already includes repayments.
  Otherwise it uses the tender taken on the sale.
* Profit is split in proportion to money: collected profit plus
  outstanding profit equals that sale's gross profit.
* Stock value elsewhere is quantity times the product's current cost.
  This module does not value remaining FIFO batches.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

_CREDIT = frozenset({'credit sale', 'credit'})
_PART = frozenset({'part payment', 'part-payment', 'part_payment'})
_VOID = frozenset({'void', 'voided'})
_CLOSED_DEBT = frozenset({'paid', 'cancelled', 'canceled', 'written_off'})

REPORT_SECTIONS = (
    ('sales_overview', 'Sales overview'),
    ('collections', 'Revenue and collections'),
    ('discounts', 'Discounts'),
    ('tax', 'Tax'),
    ('voids', 'Voided transactions'),
    ('debt', 'Debt issued and collected'),
    ('outstanding', 'Outstanding debt'),
    ('gross_profit', 'Gross profit'),
    ('cogs', 'FIFO cost of goods sold'),
    ('top_products', 'Top-selling products'),
    ('categories', 'Product categories'),
    ('payment_methods', 'Payment methods'),
    ('staff', 'Staff performance'),
    ('inventory', 'Inventory and low stock'),
    ('deliveries', 'Supplier deliveries'),
)
FINANCE_SECTIONS = frozenset({'gross_profit', 'cogs'})
SECTION_IDS = frozenset(key for key, _label in REPORT_SECTIONS)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _round2(value: float) -> float:
    return round(float(value) + 0.0, 2)


def sale_is_void(sale: dict) -> bool:
    return str(sale.get('status') or '').lower() in _VOID


def tender_collected(sale: dict) -> float:
    """Money taken on the sale itself. Unpaid credit contributes nothing."""
    if sale_is_void(sale):
        return 0.0
    method = str(sale.get('payment_method') or '').strip().lower()
    paid = _num(sale.get('amount_paid'))
    change = _num(sale.get('change_amount'))
    if method in _CREDIT and paid < 0.01:
        return 0.0
    if method in _PART and paid < 0.01:
        return 0.0
    return max(0.0, _round2(paid - change))


def sale_kind(sale: dict) -> str:
    """paid, credit, part, or void. Repayments do not change the kind."""
    if sale_is_void(sale):
        return 'void'
    method = str(sale.get('payment_method') or '').strip().lower()
    total = _num(sale.get('total'))
    collected = tender_collected(sale)
    if method in _CREDIT and collected < 0.01:
        return 'credit'
    if method in _PART or (method in _CREDIT and collected + 0.009 < total):
        return 'part'
    if 0.009 < collected + 0.001 < total - 0.009 and method in _CREDIT | _PART:
        return 'part'
    return 'paid'


def _invoice_for(sale: dict, invoices: list[dict]) -> dict | None:
    device = str(sale.get('device_id') or '')
    source = str(sale.get('source_id') or '')
    for invoice in invoices:
        if str(invoice.get('device_id') or '') not in ('', device):
            continue
        linked = str(invoice.get('sale_source_id') or invoice.get('sale_id') or '')
        if linked and linked == source:
            return invoice
    return None


def collected_and_outstanding(sale: dict, invoice: dict | None) -> tuple[float, float]:
    """Money already in hand versus still owed, for this sale only.

    A linked invoice balance is the till's remaining debt after every
    repayment. Collected is the original total minus that balance, so the
    two sides always add back to the sale total.
    """
    total = max(0.0, _num(sale.get('total')))
    if invoice and str(invoice.get('status') or '').lower() not in _CLOSED_DEBT:
        outstanding = min(total, max(0.0, _num(invoice.get('balance'))))
        if str(invoice.get('status') or '').lower() in ('paid',):
            outstanding = 0.0
        collected = max(0.0, _round2(total - outstanding))
        return collected, outstanding
    if invoice and str(invoice.get('status') or '').lower() == 'paid':
        return total, 0.0
    collected = min(total, tender_collected(sale))
    return collected, max(0.0, _round2(total - collected))


def _lines_for(sale: dict, items: list[dict]) -> list[dict]:
    device = str(sale.get('device_id') or '')
    source = str(sale.get('source_id') or '')
    out = []
    for item in items:
        if str(item.get('device_id') or '') not in ('', device):
            continue
        linked = str(item.get('sale_source_id') or item.get('sale_id') or '')
        if linked == source:
            out.append(item)
    return out


def line_profit(item: dict) -> tuple[float, float, float]:
    revenue = _num(item.get('total'))
    cost = _num(item.get('quantity')) * _num(item.get('unit_cost', item.get('cost_price')))
    return _round2(revenue), _round2(cost), _round2(revenue - cost)


def allocate_sale_profits(
    sales: list[dict],
    items: list[dict],
    invoices: list[dict] | None = None,
) -> dict:
    """Split gross profit without counting a repayment as a new sale."""
    invoices = invoices or []
    buckets = {
        'gross_profit': 0.0,
        'cost_of_goods': 0.0,
        'gross_profit_fully_paid': 0.0,
        'gross_profit_credit': 0.0,
        'gross_profit_part_payment': 0.0,
        'gross_profit_collected': 0.0,
        'gross_profit_outstanding': 0.0,
        'profit_sales': 0,
    }
    by_day: dict[str, float] = {}
    details = []
    for sale in sales:
        if sale_is_void(sale) or str(sale.get('deleted') or '').lower() in ('1', 'true'):
            continue
        lines = _lines_for(sale, items)
        revenue = 0.0
        cost = 0.0
        for line in lines:
            line_revenue, line_cost, _gp = line_profit(line)
            revenue += line_revenue
            cost += line_cost
        profit = _round2(revenue - cost)
        kind = sale_kind(sale)
        invoice = _invoice_for(sale, invoices)
        collected, outstanding = collected_and_outstanding(sale, invoice)
        total = _num(sale.get('total'))
        if total > 0.009:
            collected_profit = _round2(profit * (collected / total))
            outstanding_profit = _round2(profit - collected_profit)
        else:
            collected_profit, outstanding_profit = profit, 0.0
        buckets['gross_profit'] = _round2(buckets['gross_profit'] + profit)
        buckets['cost_of_goods'] = _round2(buckets['cost_of_goods'] + cost)
        buckets['profit_sales'] += 1 if lines else 0
        if kind == 'paid':
            buckets['gross_profit_fully_paid'] = _round2(
                buckets['gross_profit_fully_paid'] + profit
            )
        elif kind == 'credit':
            buckets['gross_profit_credit'] = _round2(
                buckets['gross_profit_credit'] + profit
            )
        else:
            buckets['gross_profit_part_payment'] = _round2(
                buckets['gross_profit_part_payment'] + profit
            )
        buckets['gross_profit_collected'] = _round2(
            buckets['gross_profit_collected'] + collected_profit
        )
        buckets['gross_profit_outstanding'] = _round2(
            buckets['gross_profit_outstanding'] + outstanding_profit
        )
        created = str(sale.get('source_created_at') or sale.get('created_at') or '')
        day = created[:10]
        if len(day) == 10:
            by_day[day] = _round2(by_day.get(day, 0.0) + profit)
        details.append({
            'source_id': sale.get('source_id'),
            'kind': kind,
            'gross_profit': profit,
            'collected': collected,
            'outstanding': outstanding,
            'profit_collected': collected_profit,
            'profit_outstanding': outstanding_profit,
        })
    buckets['gross_profit_credit_and_part'] = _round2(
        buckets['gross_profit_credit'] + buckets['gross_profit_part_payment']
    )
    buckets['by_day'] = by_day
    buckets['sales'] = details
    return buckets


def previous_window(start: str, end: str) -> tuple[str, str]:
    """The equal-length window immediately before ``start``."""
    start_d = date.fromisoformat(start[:10])
    end_d = date.fromisoformat(end[:10])
    if end_d < start_d:
        start_d, end_d = end_d, start_d
    days = (end_d - start_d).days + 1
    prev_end = start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return prev_start.isoformat(), prev_end.isoformat()


_AGE_KEYS = ('current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_90_plus')


def debt_age_key(invoice: dict, *, today: date | None = None) -> str | None:
    """Which ageing bucket an open invoice belongs to. Closed invoices return None.

    Current means not yet due, including invoices with no due date.
    The day cuts are 1–30, 31–60, 61–90, and over 90.
    """
    today = today or date.today()
    if str(invoice.get('status') or '').lower() in _CLOSED_DEBT:
        return None
    if _num(invoice.get('balance')) <= 0.009:
        return None
    due_raw = str(invoice.get('due_date') or '')[:10]
    try:
        due = date.fromisoformat(due_raw) if due_raw else None
    except ValueError:
        due = None
    late = (today - due).days if due and due < today else 0
    if late <= 0:
        return 'current'
    if late <= 30:
        return 'days_1_30'
    if late <= 60:
        return 'days_31_60'
    if late <= 90:
        return 'days_61_90'
    return 'days_90_plus'


def debt_ageing(invoices: list[dict], *, today: date | None = None) -> dict:
    """Open balances grouped by how late they are. Current means not yet due."""
    today = today or date.today()
    buckets = {key: 0.0 for key in _AGE_KEYS}
    buckets['count'] = 0
    invoice_counts = {key: 0 for key in _AGE_KEYS}
    customers = {key: set() for key in _AGE_KEYS}
    for invoice in invoices:
        key = debt_age_key(invoice, today=today)
        if not key:
            continue
        balance = _num(invoice.get('balance'))
        buckets['count'] += 1
        buckets[key] = _round2(buckets[key] + balance)
        invoice_counts[key] += 1
        party = str(
            invoice.get('customer_source_id')
            or invoice.get('customer_name')
            or invoice.get('source_id')
            or ''
        )
        customers[key].add(party)
    total = _round2(sum(buckets[key] for key in _AGE_KEYS))
    buckets['total_outstanding'] = total
    buckets['detail'] = {
        key: {
            'amount': buckets[key],
            'invoices': invoice_counts[key],
            'customers': len(customers[key]),
            'share': round((buckets[key] / total) * 100, 1) if total else 0.0,
        }
        for key in _AGE_KEYS
    }
    return buckets


def sync_freshness(last_sync_at: str | None, *, now: datetime | None = None) -> dict:
    """Tell an owner whether the copy on screen is recent, old, or missing."""
    if not last_sync_at:
        return {
            'state': 'never',
            'stale': True,
            'label': 'No successful sync has been reported',
        }
    text = str(last_sync_at).replace('Z', '+00:00')
    try:
        seen = datetime.fromisoformat(text)
    except ValueError:
        return {
            'state': 'unknown',
            'stale': True,
            'label': 'Sync time could not be read',
            'last_sync_at': last_sync_at,
        }
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=datetime.now().astimezone().tzinfo)
    current = now or datetime.now(seen.tzinfo)
    age_hours = (current - seen).total_seconds() / 3600.0
    stale = age_hours > 26
    return {
        'state': 'stale' if stale else 'ok',
        'stale': stale,
        'age_hours': round(age_hours, 1),
        'last_sync_at': last_sync_at,
        'label': (
            'Delayed. Last sync is more than a day old, so these figures may be behind the till.'
            if stale else
            'Up to date. The last sync succeeded.'
        ),
    }


def logical_debt_status(invoice: dict, *, today: date | None = None) -> str:
    today = today or date.today()
    status = str(invoice.get('status') or '').lower()
    balance = _num(invoice.get('balance'))
    paid = _num(invoice.get('amount_paid'))
    if status in ('paid',) or balance <= 0.009:
        return 'paid'
    if status in ('cancelled', 'canceled', 'written_off'):
        return status
    due_raw = str(invoice.get('due_date') or '')[:10]
    try:
        due = date.fromisoformat(due_raw) if due_raw else None
    except ValueError:
        due = None
    if due and due < today and balance > 0.009:
        return 'overdue'
    if paid > 0.009 and balance > 0.009:
        return 'partial'
    return 'open'


def supplier_name_from_reason(reason: str) -> str:
    text = str(reason or '')
    marker = 'Received from Supplier:'
    if marker not in text:
        return ''
    rest = text.split(marker, 1)[1].strip()
    return rest.split('—', 1)[0].split(' - ', 1)[0].strip()


def movement_is_delivery(row: dict) -> bool:
    kind = str(row.get('movement_type') or '').lower()
    if kind in ('receive', 'receipt', 'purchase', 'supplier', 'stock_in'):
        return True
    if 'receiv' in kind:
        return True
    reason = str(row.get('reason') or '')
    return 'Received from Supplier:' in reason and _num(row.get('qty_change')) > 0


def normalize_sections(requested: list[str] | None) -> list[str]:
    wanted = []
    for item in requested or []:
        key = str(item or '').strip().lower().replace(' ', '_').replace('-', '_')
        if key in SECTION_IDS and key not in wanted:
            wanted.append(key)
    return wanted


def report_lines(summary: dict, extras: dict, sections: list[str]) -> list[tuple[str, list[str]]]:
    """Plain lines for the sections the owner ticked. Nothing else."""
    labels = dict(REPORT_SECTIONS)
    blocks: list[tuple[str, list[str]]] = []

    def add(key: str, lines: list[str]) -> None:
        if key in sections:
            blocks.append((labels[key], lines))

    money = lambda n: f"{_num(n):,.2f}"
    add('sales_overview', [
        f"Gross sales: {money(summary.get('gross_sales'))}",
        f"Transactions: {int(_num(summary.get('transactions')))}",
        f"Average sale: {money(summary.get('avg_sale'))}",
    ])
    add('collections', [
        f"Collected from sales: {money(summary.get('collected_from_sales'))}",
        f"Debt collected: {money(summary.get('debt_collected'))}",
        f"Collected revenue: {money(summary.get('collected_revenue'))}",
    ])
    add('discounts', [f"Discounts: {money(summary.get('discounts'))}"])
    add('tax', [f"Tax: {money(summary.get('tax'))}"])
    add('voids', [
        f"Voided sales: {int(_num(summary.get('void_transactions')))}",
        f"Voided total (excluded from sales): {money(summary.get('void_revenue'))}",
    ])
    add('debt', [
        f"Debt issued: {money(summary.get('debt_issued'))}",
        f"Debt collected: {money(summary.get('debt_collected'))}",
    ])
    add('outstanding', [
        f"Outstanding debt: {money(summary.get('debt_outstanding'))}",
        f"Overdue: {money(summary.get('debt_overdue'))}",
    ])
    add('gross_profit', [
        f"Gross profit: {money(summary.get('gross_profit'))}",
        f"Fully paid sales: {money(summary.get('gross_profit_fully_paid'))}",
        f"Credit sales: {money(summary.get('gross_profit_credit'))}",
        f"Part-payment sales: {money(summary.get('gross_profit_part_payment'))}",
        f"Profit on money already collected: {money(summary.get('gross_profit_collected'))}",
        f"Profit still tied to outstanding debt: {money(summary.get('gross_profit_outstanding'))}",
        'A repayment moves profit from outstanding to collected. It does not add a sale.',
    ])
    add('cogs', [
        f"FIFO cost of goods sold (sale-time snapshot): {money(summary.get('cost_of_goods'))}",
    ])
    products = extras.get('top_products') or []
    add('top_products', [
        f"{row.get('name')}: qty {row.get('qty')} revenue {money(row.get('revenue'))}"
        for row in products
    ] or ['No product lines in this period.'])
    categories = extras.get('by_category') or extras.get('top_categories') or []
    add('categories', [
        f"{row.get('category')}: qty {row.get('qty')} revenue {money(row.get('revenue'))}"
        for row in categories
    ] or ['No categories in this period.'])
    methods = extras.get('payment_methods') or []
    add('payment_methods', [
        f"{row.get('payment_method')}: {row.get('count')} collected {money(row.get('total'))}"
        for row in methods
    ] or ['No payments in this period.'])
    staff = extras.get('staff') or []
    add('staff', [
        f"{row.get('cashier_name')}: {row.get('transactions')} sales, {money(row.get('revenue'))}"
        for row in staff
    ] or ['No staff sales in this period.'])
    stock = extras.get('low_stock') or []
    add('inventory', [
        f"{row.get('name')}: stock {row.get('stock')} minimum {row.get('min_stock')}"
        for row in stock
    ] or ['No low or out-of-stock products in the latest sync.'])
    deliveries = extras.get('deliveries') or []
    add('deliveries', [
        f"{row.get('supplier_name') or 'Supplier'}: {row.get('product_name')} "
        f"+{row.get('qty_change')} (before {row.get('qty_before')}, after {row.get('qty_after')})"
        for row in deliveries
    ] or ['No supplier deliveries in the latest sync.'])
    return blocks


def build_text_pdf(lines: list[str]) -> bytes:
    """A text PDF with no extra libraries. Callers encrypt it afterwards."""
    safe = [str(line or '').replace('\r', ' ').replace('\n', ' ') for line in lines] or [' ']
    page_size = 42
    groups = [safe[i:i + page_size] for i in range(0, len(safe), page_size)]
    font_id = 3
    objects: list[bytes] = [b'']  # 1-based
    page_ids = []
    content_ids = []
    next_id = 4
    for group in groups:
        content_ids.append(next_id)
        page_ids.append(next_id + 1)
        next_id += 2
    objects = [''] * (next_id - 1)
    kids = ' '.join(f'{pid} 0 R' for pid in page_ids)
    objects[0] = f'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = f'<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>'
    objects[2] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'

    def esc(text: str) -> str:
        return (
            text.replace('\\', '\\\\')
            .replace('(', '\\(')
            .replace(')', '\\)')
            .encode('latin-1', 'replace')
            .decode('latin-1')
        )

    for group, content_id, page_id in zip(groups, content_ids, page_ids):
        commands = ['BT', '/F1 11 Tf', '50 800 Td', '14 TL']
        for index, line in enumerate(group):
            if index:
                commands.append('T*')
            commands.append(f'({esc(line[:110])}) Tj')
        commands.append('ET')
        stream = '\n'.join(commands).encode('latin-1', 'replace')
        objects[content_id - 1] = (
            f'<< /Length {len(stream)} >>\nstream\n'.encode('ascii')
            + stream
            + b'\nendstream'
        )
        objects[page_id - 1] = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
            f'/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>'
        )
    out = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        if isinstance(body, str):
            payload = body.encode('latin-1', 'replace')
        else:
            payload = body
        out.extend(f'{number} 0 obj\n'.encode('ascii'))
        out.extend(payload)
        out.extend(b'\nendobj\n')
    xref = len(out)
    out.extend(f'xref\n0 {len(objects) + 1}\n'.encode('ascii'))
    out.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        out.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    out.extend(
        f'trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode('ascii')
    )
    return bytes(out)


def flatten_report_text(blocks: list[tuple[str, list[str]]], *, title: str, period: str) -> list[str]:
    lines = [
        title,
        period,
        'Read-only copy of synced till figures. Not a live sale.',
        '',
    ]
    for heading, body in blocks:
        lines.append(heading.upper())
        lines.extend(body or ['Nothing in this section.'])
        lines.append('')
    if not blocks:
        lines.append('No sections were selected.')
    return lines
