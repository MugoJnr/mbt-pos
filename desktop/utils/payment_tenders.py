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
