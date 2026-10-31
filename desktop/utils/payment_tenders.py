"""Split-tender helpers for POS checkout (cash + M-Pesa/card in one sale)."""
from __future__ import annotations

import json
from typing import Any, Iterable, List, Optional


def _r2(value: Any) -> float:
    return round(float(value or 0), 2)


def remainder_electronic(due: float, cash_paid: float, elec_paid: float = 0.0) -> float:
    """If electronic amount is empty, remaining due after cash is the other tender."""
    elec = _r2(elec_paid)
    if elec > 0.009:
        return elec
    rem = _r2(_r2(due) - _r2(cash_paid))
    return rem if rem > 0.009 else 0.0


def collected_and_balance(
    *,
    due: float,
    cash_paid: float = 0.0,
    electronic_paid: float = 0.0,
    credit_applied: float = 0.0,
) -> tuple:
    """Till collected vs leftover (used for Split + Part pay)."""
    collected = _r2(_r2(cash_paid) + _r2(electronic_paid) + _r2(credit_applied))
    balance = _r2(max(0.0, _r2(due) - collected))
    return collected, balance


def build_tenders(
    *,
    cash_paid: float = 0.0,
    electronic_paid: float = 0.0,
    electronic_method: str = '',
    store_credit: float = 0.0,
) -> List[dict]:
    rows: List[dict] = []
    elec = _r2(electronic_paid)
    cash = _r2(cash_paid)
    credit = _r2(store_credit)
    em = (electronic_method or 'M-Pesa').strip() or 'M-Pesa'
    if elec > 0.009:
        rows.append({'method': em, 'amount': elec})
    if cash > 0.009:
        rows.append({'method': 'Cash', 'amount': cash})
    if credit > 0.009:
        rows.append({'method': 'Store Credit', 'amount': credit})
    return rows


_CREDIT_METHODS = {
    'credit', 'credit sale', 'on account', 'customer credit', 'part credit',
}
_UNCONFIRMED = {'pending', 'failed', 'cancelled', 'initiated'}


def is_credit_method(name: str) -> bool:
    """Customer credit is an unpaid balance, not money taken at the till."""
    return str(name or '').strip().lower().replace('_', ' ') in _CREDIT_METHODS


def collected_buckets(lines: Iterable[dict]) -> dict:
    """Confirmed money by method. Credit and unconfirmed lines are not collected."""
    totals = {'cash': 0.0, 'mpesa': 0.0, 'card': 0.0, 'bank': 0.0, 'other': 0.0}
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        status = str(line.get('status') or 'confirmed').strip().lower()
        if status in _UNCONFIRMED:
            continue
        name = str(line.get('method') or '').strip().lower().replace('_', ' ')
        if is_credit_method(name):
            continue
        amount = _r2(line.get('amount'))
        if amount <= 0:
            continue
        if name == 'cash':
            key = 'cash'
        elif name in ('m-pesa', 'mpesa', 'mobile money'):
            key = 'mpesa'
        elif name == 'card':
            key = 'card'
        elif name in ('bank transfer', 'bank', 'bank payment', 'cheque', 'check'):
            key = 'bank'
        else:
            key = 'other'
        totals[key] = _r2(totals[key] + amount)
    return totals


def _net_cash_kept(amount_paid: Any, total: Any, change: Any) -> float:
    paid = _r2(amount_paid)
    if paid > _r2(total) + 0.02:
        return _r2(paid - _r2(change))
    return paid


def _cash_kept_on_split(buckets: dict, sale: dict) -> float:
    """Net cash on a mixed sale.

    The cash line is what the customer handed over. Change is given from cash
    only, and only when those lines still add up to more than the money kept.
    """
    cash_part = _r2(buckets.get('cash'))
    non_cash = _r2(
        float(buckets.get('mpesa') or 0)
        + float(buckets.get('card') or 0)
        + float(buckets.get('bank') or 0)
        + float(buckets.get('other') or 0)
    )
    change = _r2(sale.get('change_amount'))
    kept = sale.get('amount_paid')
    if kept is None:
        kept = sale.get('total')
    if change > 0.009 and _r2(cash_part + non_cash) > _r2(kept) + 0.02:
        cash_part = _r2(max(0.0, cash_part - change))
    return cash_part


def collected_from_sales(sales: Iterable[dict]) -> dict:
    """Dashboard tiles for a list of sales.

    A split sale stores one combined method name. Its M-Pesa, card, and bank
    amounts come from the saved tender lines. A cash sale keeps the net money
    retained, so change is not subtracted twice. Credit is not collected.
    """
    cash = mpesa = card = bank = other = 0.0
    for sale in sales or []:
        if not isinstance(sale, dict):
            continue
        method = str(sale.get('payment_method') or '').strip().lower()
        raw = sale.get('payment_tenders')
        lines: List[dict] = []
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, list):
                lines = parsed
        elif isinstance(raw, list):
            lines = raw
        buckets = collected_buckets(lines) if lines else None
        split_money = 0.0
        if buckets:
            split_money = (
                buckets['mpesa'] + buckets['card'] + buckets['bank'] + buckets['other']
            )
        if buckets and split_money > 0.009:
            mpesa = _r2(mpesa + buckets['mpesa'])
            card = _r2(card + buckets['card'])
            bank = _r2(bank + buckets['bank'])
            other = _r2(other + buckets['other'])
            cash = _r2(cash + _cash_kept_on_split(buckets, sale))
            continue
        if method == 'cash':
            cash = _r2(cash + _net_cash_kept(
                sale.get('amount_paid'), sale.get('total'), sale.get('change_amount'),
            ))
        elif method in ('m-pesa', 'mpesa', 'mobile money'):
            mpesa = _r2(mpesa + _r2(sale.get('amount_paid') if sale.get('amount_paid') is not None else sale.get('total')))
        elif method == 'card':
            card = _r2(card + _r2(sale.get('amount_paid') if sale.get('amount_paid') is not None else sale.get('total')))
        elif method in ('bank transfer', 'bank', 'bank payment'):
            bank = _r2(bank + _r2(sale.get('amount_paid') if sale.get('amount_paid') is not None else sale.get('total')))
    collected = _r2(cash + mpesa + card + bank + other)
    return {
        'cash_collected': cash,
        'mpesa_collected': mpesa,
        'card_collected': card,
        'bank_collected': bank,
        'other_collected': other,
        'collected': collected,
    }


def credit_issued_from_sales(sales: Iterable[dict]) -> float:
    """Unpaid part of a sale. Missing amount_paid is not treated as credit."""
    issued = 0.0
    for sale in sales or []:
        if not isinstance(sale, dict):
            continue
        if sale.get('amount_paid') is None:
            continue
        gap = _r2(_r2(sale.get('total')) - _r2(sale.get('amount_paid')))
        if gap > 0.009:
            issued = _r2(issued + gap)
    return issued


def collection_by_method(sales: Iterable[dict]) -> list:
    """Collected money by method. A split sale adds each part once, not the whole total.

    Credit is listed separately and is not included in collected.
    """
    labels = (
        ('cash', 'Cash'),
        ('mpesa', 'M-Pesa'),
        ('card', 'Card'),
        ('bank', 'Bank'),
        ('other', 'Other'),
    )
    totals = {label: 0.0 for _key, label in labels}
    counts = {label: 0 for _key, label in labels}
    credit_total = 0.0
    credit_count = 0
    for sale in sales or []:
        if not isinstance(sale, dict):
            continue
        one = collected_from_sales([sale])
        for key, label in labels:
            amount = float(one.get(f'{key}_collected') or 0)
            if amount > 0.009:
                totals[label] = _r2(totals[label] + amount)
                counts[label] += 1
        issued = credit_issued_from_sales([sale])
        if issued > 0.009:
            credit_total = _r2(credit_total + issued)
            credit_count += 1
    rows = [
        {'method': label, 'count': counts[label], 'collected': totals[label]}
        for _key, label in labels
        if counts[label] or totals[label] > 0.009
    ]
    if credit_count:
        rows.append({
            'method': 'Credit issued',
            'count': credit_count,
            'collected': credit_total,
        })
    return rows


def stock_value_at_cost(cost, quantity) -> float:
    """Stock value from the recorded cost. A missing cost is not estimated."""
    cost_n = _r2(cost)
    qty_n = float(quantity or 0)
    if cost_n <= 0 or qty_n <= 0:
        return 0.0
    return _r2(cost_n * qty_n)


def allocate_sale(total: float, tenders: Optional[Iterable[dict]]) -> dict:
    """One sale, many confirmed tenders. Unconfirmed money is not collected.

    The credit line is customer debt, not cash. Confirmed amounts plus that
    debt must equal the sale total. Cash may exceed the total as change.
    """
    due = _r2(total)
    if due <= 0:
        return {'error': 'Sale total must be greater than zero'}
    rows_in = list(tenders or [])
    if not rows_in:
        return {'error': 'Add at least one payment'}
    cash = electronic = credit = 0.0
    rows: List[dict] = []
    for raw in rows_in:
        if not isinstance(raw, dict):
            return {'error': 'Each payment needs a method and an amount'}
        method = str(raw.get('method') or '').strip()
        if not method:
            return {'error': 'Each payment needs a method'}
        try:
            amount = _r2(raw.get('amount'))
        except (TypeError, ValueError):
            return {'error': 'Each payment needs an amount'}
        if amount <= 0:
            return {'error': 'Payment amounts must be greater than zero'}
        status = str(raw.get('status') or 'confirmed').strip().lower()
        key = method.lower().replace('_', ' ')
        if status in _UNCONFIRMED:
            rows.append({'method': method, 'amount': amount, 'status': status})
            continue
        if is_credit_method(method):
            credit = _r2(credit + amount)
            rows.append({'method': 'Credit', 'amount': amount, 'status': 'outstanding'})
            continue
        reference = str(raw.get('reference') or '').strip()
        if key == 'cash':
            cash = _r2(cash + amount)
            saved = {'method': 'Cash', 'amount': amount, 'status': 'confirmed'}
        else:
            electronic = _r2(electronic + amount)
            saved = {'method': method, 'amount': amount, 'status': 'confirmed'}
        if reference:
            saved['reference'] = reference
        rows.append(saved)
    collected = _r2(cash + electronic)
    change = 0.0
    if collected - due > 0.009:
        if credit > 0.009:
            return {'error': 'A credit balance cannot be combined with an overpayment'}
        change = _r2(collected - due)
        if cash + 0.009 < change:
            return {'error': 'Change can only come from cash'}
        net = due
    else:
        net = collected
        change = 0.0
    covered = _r2(net + credit)
    if abs(covered - due) > 0.02:
        return {
            'error': (
                f'Payments {covered:.2f} do not match the sale total {due:.2f}. '
                'Unconfirmed amounts are not collected.'
            )
        }
    return {
        'success': True,
        'cash': _r2(cash - change),
        'cash_tendered': cash,
        'electronic': electronic,
        'credit': credit,
        'collected': net,
        'change': change,
        'tenders': rows,
    }


def collected_method_label(tenders: Optional[Iterable[dict]], fallback: str = 'cash') -> str:
    """Name the money taken. An outstanding credit line is not a payment method."""
    names = []
    for tender in tenders or []:
        name = str(tender.get('method') or '').strip()
        key = name.lower()
        status = str(tender.get('status') or 'confirmed').lower()
        try:
            amount = _r2(tender.get('amount'))
        except Exception:
            continue
        if amount <= 0.009 or not name or status != 'confirmed' or is_credit_method(name):
            continue
        if name not in names:
            names.append(name)
    return ' + '.join(names) or fallback


def format_tenders(tenders: Optional[Iterable[dict]]) -> str:
    parts = []
    for t in tenders or []:
        try:
            amt = _r2(t.get('amount'))
            name = str(t.get('method') or '').strip()
        except Exception:
            continue
        if amt > 0.009 and name:
            parts.append(f'{name} {amt:,.2f}')
    return ' + '.join(parts)


def parse_tenders(raw: Any) -> List[dict]:
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if isinstance(data, list):
            return [t for t in data if isinstance(t, dict)]
    return []


def explain_sale_payments(sale: Optional[dict]) -> dict:
    """Receipt figures from the saved sale. Tender lines are not rewritten.

    A cash line is the amount handed over. ``change_amount`` is the change
    given back, and ``amount_paid`` is the money kept. Credit is not collected.
    """
    sale = sale or {}
    total = _r2(sale.get('total'))
    change = _r2(sale.get('change_amount'))
    paid_raw = sale.get('amount_paid')
    collected = None if paid_raw is None else _r2(paid_raw)
    lines = []
    tendered = 0.0
    credit = 0.0
    cash_tendered = 0.0
    for raw in parse_tenders(sale.get('payment_tenders')):
        method = str(raw.get('method') or '').strip() or 'Payment'
        try:
            amount = _r2(raw.get('amount'))
        except (TypeError, ValueError):
            continue
        status = str(raw.get('status') or 'confirmed').strip().lower() or 'confirmed'
        reference = str(raw.get('reference') or '').strip()
        if is_credit_method(method) or status == 'outstanding':
            kind = 'credit'
            credit = _r2(credit + amount)
        elif status in _UNCONFIRMED:
            kind = 'unconfirmed'
        elif method.lower() == 'cash' and change > 0.009:
            kind = 'tendered'
            tendered = _r2(tendered + amount)
            cash_tendered = _r2(cash_tendered + amount)
        else:
            kind = 'allocated'
            if status == 'confirmed':
                tendered = _r2(tendered + amount)
        row = {
            'method': 'Credit' if kind == 'credit' else method,
            'amount': amount,
            'status': 'outstanding' if kind == 'credit' else status,
            'kind': kind,
        }
        if reference:
            row['reference'] = reference
        lines.append(row)
    if collected is None:
        outstanding = None
    elif credit > 0.009:
        outstanding = credit
    else:
        outstanding = _r2(max(0.0, total - collected))
    issues = []
    if lines and collected is not None:
        expected = _r2(tendered - change)
        if abs(expected - collected) > 0.02:
            issues.append(
                f'Saved payments of {tendered:.2f} less change of {change:.2f} '
                f'equal {expected:.2f}, but the amount collected is {collected:.2f}.'
            )
    if collected is not None and _r2(collected + credit) > total + 0.02:
        issues.append(
            f'Amount collected {collected:.2f} plus credit {credit:.2f} '
            f'is more than the sale total {total:.2f}.'
        )
    if change > 0.009 and cash_tendered + 0.009 < change:
        issues.append(
            f'Change of {change:.2f} is larger than the cash tendered, {cash_tendered:.2f}.'
        )
    note = ''
    if change > 0.009 and not issues:
        note = (
            f'KES {change:,.2f} was returned as change. '
            f'The amount collected is KES {collected if collected is not None else 0:,.2f}, '
            f'not the sum of the tendered lines.'
        )
    return {
        'lines': lines,
        'sale_total': total,
        'amount_tendered': tendered,
        'amount_collected': collected,
        'change': change,
        'credit': credit,
        'outstanding': outstanding,
        'cash_kept': None if sale.get('cash_paid') is None else _r2(sale.get('cash_paid')),
        'consistent': not issues,
        'warning': ' '.join(issues),
        'note': note,
    }


def payment_slip_text(slip: Optional[dict]) -> str:
    """Same words on the till and on a printed copy."""
    slip = slip or {}
    rows = ['Payment breakdown']
    lines = slip.get('lines') or []
    if not lines:
        rows.append('  No separate payment lines are stored on this sale.')
    for line in lines:
        ref = f"  ref {line.get('reference')}" if line.get('reference') else ''
        kind = {
            'tendered': 'tendered',
            'allocated': 'allocated',
            'credit': 'credit',
            'unconfirmed': 'not collected',
        }.get(str(line.get('kind') or ''), '')
        rows.append(
            f"  {line.get('method') or 'Payment'}  "
            f"{_r2(line.get('amount')):,.2f}  "
            f"{line.get('status') or ''}  {kind}{ref}".rstrip()
        )
    collected = slip.get('amount_collected')
    outstanding = slip.get('outstanding')
    rows.extend([
        f"Sale total: {_r2(slip.get('sale_total')):,.2f}",
        f"Amount tendered: {_r2(slip.get('amount_tendered')):,.2f}",
        'Amount collected: —' if collected is None else f"Amount collected: {_r2(collected):,.2f}",
        f"Change: {_r2(slip.get('change')):,.2f}",
        f"Credit: {_r2(slip.get('credit')):,.2f}",
        'Outstanding: —' if outstanding is None else f"Outstanding: {_r2(outstanding):,.2f}",
    ])
    if slip.get('note'):
        rows.append(str(slip['note']))
    if slip.get('warning'):
        rows.append(str(slip['warning']))
    return '\n'.join(rows)


def format_sale_payment(sale: Optional[dict]) -> str:
    """History / receipt label: Mixed (Cash 500.00 + M-Pesa 300.00)."""
    sale = sale or {}
    tenders = parse_tenders(sale.get('payment_tenders'))
    if not tenders:
        elec = _r2(sale.get('electronic_paid'))
        method = str(sale.get('payment_method') or '').strip()
        if elec > 0.009 or method.lower() in ('mixed', 'split'):
            cash = _r2(sale.get('cash_paid'))
            if cash < 0.009:
                cash = max(0.0, _r2(sale.get('amount_paid')) - elec)
            tenders = build_tenders(
                cash_paid=cash,
                electronic_paid=elec,
                electronic_method=str(sale.get('electronic_method') or '').strip(),
                store_credit=_r2(sale.get('credit_applied')),
            )
    label = format_tenders(tenders)
    method = str(sale.get('payment_method') or 'cash').replace('_', ' ').strip()
    method_l = method.lower()
    if label and len(tenders) > 1:
        mixed = f'Mixed ({label})'
        if method_l in ('part payment', 'part pay'):
            return f'Part pay · {mixed}'
        return mixed
    if label:
        if method_l in ('part payment', 'part pay'):
            return f'Part pay · {label}'
        return label
    return method.title() if method else 'Cash'
