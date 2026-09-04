"""Canonical POS payment-method names and Mixed tender validation.

Server-side gate for create_sale: unknown methods are rejected; aliases such as
``Credit`` / ``part_payment`` normalize to ``Credit Sale`` / ``Part Payment``.
Mixed sales require ≥2 validated tender rows that sum to the sale total.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Optional, Sequence

from desktop.utils.option_lists import POS_PAYMENT_METHODS
from desktop.utils.payment_tenders import build_tenders, parse_tenders

# Currency rounding tolerance for tender vs sale total checks.
TENDER_TOTAL_TOLERANCE = 0.02

CANONICAL_PAYMENT_METHODS = frozenset(POS_PAYMENT_METHODS)

DEBT_PAYMENT_METHODS = frozenset({
    'Credit Sale',
    'Part Payment',
})

ELECTRONIC_PAYMENT_METHODS = frozenset({
    'M-Pesa',
    'Airtel Money',
    'Card',
    'Bank Transfer',
    'Cheque',
})

# Keys are lowercased with underscores/hyphens collapsed to spaces, then
# spaces removed for the secondary lookup.
_PAYMENT_ALIASES: dict[str, str] = {
    'cash': 'Cash',
    'mpesa': 'M-Pesa',
    'm-pesa': 'M-Pesa',
    'm pesa': 'M-Pesa',
    'airtel money': 'Airtel Money',
    'airtel': 'Airtel Money',
    'card': 'Card',
    'bank transfer': 'Bank Transfer',
    'bank': 'Bank Transfer',
    'cheque': 'Cheque',
    'check': 'Cheque',
    'mixed': 'Mixed',
    'split': 'Mixed',
    'split pay': 'Mixed',
    'splitpay': 'Mixed',
    'part payment': 'Part Payment',
    'part pay': 'Part Payment',
    'partpay': 'Part Payment',
    'credit sale': 'Credit Sale',
    'credit': 'Credit Sale',
    'credit account': 'Credit Sale',
    'on account': 'Credit Sale',
    'store credit': 'Store Credit',  # tender-only row, not a sale method
}


def _alias_key(raw: str) -> str:
    s = str(raw or '').strip().lower()
    s = s.replace('_', ' ').replace('-', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _alias_compact(raw: str) -> str:
    return _alias_key(raw).replace(' ', '')


def normalize_payment_method(
    raw: Any,
    *,
    reject_unknown: bool = True,
    allow_tender_only: bool = False,
) -> str:
    """Return canonical payment method name.

    Raises ValueError when ``reject_unknown`` and the value is not a known
    sale method (or tender-only name when ``allow_tender_only``).
    """
    text = str(raw or '').strip()
    if not text:
        if reject_unknown:
            raise ValueError('Payment method is required.')
        return ''

    for canon in CANONICAL_PAYMENT_METHODS:
        if text == canon:
            return canon
    if allow_tender_only and text == 'Store Credit':
        return 'Store Credit'

    key = _alias_key(text)
    compact = key.replace(' ', '')
    mapped = _PAYMENT_ALIASES.get(key) or _PAYMENT_ALIASES.get(compact)
    if mapped:
        if mapped == 'Store Credit' and not allow_tender_only:
            if reject_unknown:
                raise ValueError(
                    f'Unknown payment method: {text!r}. '
                    'Store Credit is a tender row, not a sale payment method.'
                )
            return text
        return mapped

    # Title-case fallback only when it already matches a canonical label
    titled = ' '.join(p.capitalize() for p in key.split())
    if titled in CANONICAL_PAYMENT_METHODS:
        return titled
    if titled == 'M-Pesa' or key in ('m-pesa', 'mpesa'):
        return 'M-Pesa'

    if reject_unknown:
        allowed = ', '.join(POS_PAYMENT_METHODS)
        raise ValueError(
            f'Unknown payment method: {text!r}. '
            f'Allowed: {allowed}.'
        )
    return text


def is_debt_payment_method(method: Any) -> bool:
    try:
        canon = normalize_payment_method(method, reject_unknown=False)
    except Exception:
        return False
    return canon in DEBT_PAYMENT_METHODS


def normalize_tender_method(raw: Any) -> str:
    """Normalize a single Mixed tender row method (includes Store Credit)."""
    return normalize_payment_method(
        raw, reject_unknown=True, allow_tender_only=True,
    )


def _r2(value: Any) -> float:
    return round(float(value or 0), 2)


def _coerce_tender_rows(raw: Any) -> List[dict]:
    if isinstance(raw, dict):
        # Single object or method→amount map
        if 'method' in raw or 'amount' in raw:
            return [raw]
        rows = []
        for method, amount in raw.items():
            rows.append({'method': method, 'amount': amount})
        return rows
    return parse_tenders(raw)


def _normalize_tender_rows(rows: Sequence[dict]) -> List[dict]:
    out: List[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            amount = _r2(row.get('amount'))
            method = normalize_tender_method(row.get('method'))
        except (TypeError, ValueError) as e:
            raise ValueError(f'Invalid Mixed tender row: {e}') from e
        if amount <= 0.009:
            continue
        if method not in CANONICAL_PAYMENT_METHODS and method != 'Store Credit':
            raise ValueError(f'Invalid Mixed tender method: {method!r}')
        if method == 'Mixed':
            raise ValueError('Mixed tender rows cannot nest another Mixed method.')
        if method in DEBT_PAYMENT_METHODS:
            raise ValueError(
                f'{method} cannot appear as a Mixed tender row.'
            )
        out.append({'method': method, 'amount': amount})
    return out


def derive_split_from_tenders(tenders: Sequence[dict]) -> dict:
    """cash_paid / electronic_paid / electronic_method from validated rows."""
    cash = 0.0
    electronic = 0.0
    elec_method = ''
    store_credit = 0.0
    for row in tenders or []:
        method = str(row.get('method') or '')
        amount = _r2(row.get('amount'))
        if method == 'Cash':
            cash = _r2(cash + amount)
        elif method == 'Store Credit':
            store_credit = _r2(store_credit + amount)
        else:
            if not elec_method:
                elec_method = method
            electronic = _r2(electronic + amount)
    return {
        'cash_paid': cash,
        'electronic_paid': electronic,
        'electronic_method': elec_method,
        'store_credit': store_credit,
        'tender_total': _r2(cash + electronic + store_credit),
    }


def validate_and_normalize_mixed(
    *,
    payment_tenders: Any = None,
    sale_total: float,
    amount_paid: float = 0.0,
    cash_paid: float = 0.0,
    electronic_paid: float = 0.0,
    electronic_method: str = '',
    credit_applied: float = 0.0,
    tolerance: float = TENDER_TOTAL_TOLERANCE,
) -> dict:
    """Validate Mixed breakdown; return canonical tenders + derived columns.

    Does not invent historical splits: when tenders are absent it only rebuilds
    from explicit cash/electronic fields already supplied on the live request.
    """
    total = _r2(sale_total)
    paid = _r2(amount_paid)
    cash = _r2(cash_paid)
    elec = _r2(electronic_paid)
    credit = _r2(credit_applied)
    emethod = (electronic_method or '').strip()

    rows = _normalize_tender_rows(_coerce_tender_rows(payment_tenders))

    if len(rows) < 2:
        # Live checkout may send cash/electronic columns without a tenders list.
        rebuilt = build_tenders(
            cash_paid=cash if cash > 0.009 else max(0.0, _r2(paid - elec - credit)),
            electronic_paid=elec,
            electronic_method=emethod or 'M-Pesa',
            store_credit=credit,
        )
        rows = _normalize_tender_rows(rebuilt)

    if len(rows) < 2:
        raise ValueError(
            'Mixed payment requires at least two tender rows '
            '(e.g. Cash + M-Pesa) that cover the sale total.'
        )

    derived = derive_split_from_tenders(rows)
    tender_total = derived['tender_total']
    # If store credit was applied outside tender rows, count it toward coverage.
    if credit > 0.009 and derived['store_credit'] < 0.009:
        covered = _r2(tender_total + credit)
    else:
        covered = tender_total

    if abs(covered - total) > tolerance:
        raise ValueError(
            f'Mixed tender total {covered:,.2f} does not equal sale total '
            f'{total:,.2f} (tolerance {tolerance:.2f}).'
        )

    return {
        'tenders': rows,
        'tenders_json': json.dumps(rows),
        'cash_paid': derived['cash_paid'],
        'electronic_paid': derived['electronic_paid'],
        'electronic_method': derived['electronic_method'],
        'tender_total': tender_total,
        'covered_total': covered,
    }


def tender_rows_complete(raw: Any) -> bool:
    """True when Mixed already has ≥2 positive tender rows."""
    try:
        rows = _normalize_tender_rows(_coerce_tender_rows(raw))
    except ValueError:
        return False
    return len(rows) >= 2


MIXED_CORRECTION_FLAG = 'NEEDS_MIXED_TENDER_CORRECTION'


def notes_have_mixed_correction_flag(notes: Any) -> bool:
    return MIXED_CORRECTION_FLAG in str(notes or '')


def append_mixed_correction_flag(notes: Any) -> str:
    text = str(notes or '').strip()
    if MIXED_CORRECTION_FLAG in text:
        return text
    if text:
        return f'{text} | {MIXED_CORRECTION_FLAG}'
    return MIXED_CORRECTION_FLAG


def clear_mixed_correction_flag(notes: Any) -> str:
    text = str(notes or '')
    parts = [p.strip() for p in text.split('|')]
    kept = [p for p in parts if p and MIXED_CORRECTION_FLAG not in p]
    return ' | '.join(kept)
