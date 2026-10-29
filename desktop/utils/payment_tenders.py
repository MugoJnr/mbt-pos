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


_CREDIT_METHODS = {'credit', 'on account', 'customer credit', 'part credit'}
_UNCONFIRMED = {'pending', 'failed', 'cancelled', 'initiated'}


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
        if key in _CREDIT_METHODS:
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


_CREDIT_METHODS = {'credit', 'on account', 'customer credit', 'part credit'}


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
        if amount <= 0.009 or not name or status != 'confirmed' or key in _CREDIT_METHODS:
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
