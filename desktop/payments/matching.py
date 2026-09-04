"""Payment matching engine — never guess on ambiguous matches."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from desktop.payments.models import MatchConfidence, PaymentRecord
from desktop.payments.security import normalize_ke_phone


@dataclass
class MatchCandidate:
    incoming_id: str
    provider_reference: str
    amount: float
    phone_masked: str
    score: float
    reasons: List[str]


@dataclass
class MatchResult:
    confidence: str
    selected: Optional[MatchCandidate]
    candidates: List[MatchCandidate]
    reason: str = ''


def _amount_close(a: float, b: float, tol: float) -> bool:
    return abs(round(float(a), 2) - round(float(b), 2)) <= float(tol)


def match_incoming_to_payment(
    payment: PaymentRecord,
    incoming_rows: Iterable[dict],
    *,
    amount_tolerance: float = 0.01,
    window_sec: float = 600.0,
    now_ts: Optional[float] = None,
) -> MatchResult:
    """Score unmatched incoming payments against one pending checkout payment.

    Rules:
    - Cross-shop rows must already be filtered out by caller (shop_id).
    - Exact unique amount+phone in window → EXACT (auto-eligible).
    - Unique provider ref / bill ref hit → STRONG.
    - Multiple plausible candidates → AMBIGUOUS (never auto).
    - Under/over amount alone never silent-complete.
    """
    import time
    now = float(now_ts if now_ts is not None else time.time())
    expected = float(payment.amount_expected)
    pay_phone = normalize_ke_phone(payment.phone_e164)
    created = float(payment.created_at or 0)

    candidates: List[MatchCandidate] = []
    for row in incoming_rows:
        if str(row.get('shop_id') or '') and str(row.get('shop_id')) != str(payment.shop_id):
            # Hard isolation — never match cross-shop
            continue
        if str(row.get('status') or 'unmatched') not in ('unmatched', 'pending', ''):
            continue
        if row.get('matched_payment_id'):
            continue
        amount = float(row.get('amount') or 0)
        ref = str(row.get('provider_reference') or '').strip().upper()
        if not ref:
            continue
        inc_phone = normalize_ke_phone(str(row.get('phone_e164') or row.get('phone') or ''))
        ts = float(row.get('created_at') or 0)
        if created and ts and abs(ts - created) > float(window_sec):
            # Still allow if bill_ref matches payment id
            bill = str(row.get('bill_ref') or '').strip()
            if payment.id not in bill and payment.account_reference not in bill:
                continue

        score = 0.0
        reasons: List[str] = []
        if _amount_close(amount, expected, amount_tolerance):
            score += 50
            reasons.append('amount_exact')
        elif amount > 0:
            # Partial credit for near amounts — never auto
            diff = abs(amount - expected)
            if diff <= max(1.0, expected * 0.05):
                score += 15
                reasons.append('amount_near')
            else:
                reasons.append('amount_mismatch')

        if pay_phone and inc_phone and pay_phone == inc_phone:
            score += 40
            reasons.append('phone_exact')

        bill = str(row.get('bill_ref') or '').strip()
        if bill and (
            bill == payment.account_reference
            or bill == payment.id
            or payment.id in bill
        ):
            score += 35
            reasons.append('bill_ref')

        if payment.provider_reference and ref == payment.provider_reference.upper():
            score += 100
            reasons.append('provider_ref')

        if score >= 40:
            candidates.append(MatchCandidate(
                incoming_id=str(row.get('id') or ref),
                provider_reference=ref,
                amount=amount,
                phone_masked=str(row.get('phone_masked') or ''),
                score=score,
                reasons=reasons,
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)

    if not candidates:
        return MatchResult(
            confidence=MatchConfidence.NONE.value,
            selected=None,
            candidates=[],
            reason='no_candidates',
        )

    top = candidates[0]
    # Ambiguous if two strong candidates within 10 points
    if len(candidates) > 1 and (candidates[0].score - candidates[1].score) < 10:
        return MatchResult(
            confidence=MatchConfidence.AMBIGUOUS.value,
            selected=None,
            candidates=candidates[:5],
            reason='multiple_strong_candidates',
        )

    if 'provider_ref' in top.reasons or (
        'amount_exact' in top.reasons and 'phone_exact' in top.reasons
    ):
        conf = MatchConfidence.EXACT.value
    elif 'amount_exact' in top.reasons and (
        'bill_ref' in top.reasons or 'phone_exact' in top.reasons
    ):
        conf = MatchConfidence.STRONG.value
    elif 'amount_exact' in top.reasons and len(candidates) == 1:
        conf = MatchConfidence.STRONG.value
    else:
        conf = MatchConfidence.AMBIGUOUS.value
        return MatchResult(
            confidence=conf,
            selected=None,
            candidates=candidates[:5],
            reason='insufficient_uniqueness',
        )

    # Under/over never silent auto — surface variance
    if not _amount_close(top.amount, expected, amount_tolerance):
        return MatchResult(
            confidence=MatchConfidence.AMBIGUOUS.value,
            selected=top,
            candidates=candidates[:5],
            reason='amount_variance_requires_confirm',
        )

    return MatchResult(
        confidence=conf,
        selected=top,
        candidates=candidates[:5],
        reason='matched',
    )


def classify_amount_variance(expected: float, received: float, tol: float = 0.01) -> str:
    """Return 'exact' | 'underpaid' | 'overpaid'."""
    e = round(float(expected), 2)
    r = round(float(received), 2)
    if abs(e - r) <= float(tol):
        return 'exact'
    if r < e:
        return 'underpaid'
    return 'overpaid'
