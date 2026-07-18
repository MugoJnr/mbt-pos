"""
Cash Rounding Service — nearest KSh 5 (and configurable modes).

Rounds the final payable amount only; never mutates product unit prices.
Electronic methods (M-Pesa, Card, Bank, etc.) never round unless explicitly
enabled in settings. Mixed tender: only the cash portion is rounded.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Optional, Sequence, Union


# Canonical mode keys stored in settings
MODE_NONE = 'none'
MODE_NEAREST = 'nearest'
MODE_NEAREST_1 = 'nearest_1'
MODE_NEAREST_5 = 'nearest_5'
MODE_NEAREST_10 = 'nearest_10'
MODE_ALWAYS_UP = 'always_up'
MODE_ALWAYS_DOWN = 'always_down'

MODE_LABELS = (
    ('nearest', 'Nearest'),
    ('none', 'No Rounding'),
    ('nearest_1', 'Nearest 1'),
    ('nearest_5', 'Nearest 5'),
    ('nearest_10', 'Nearest 10'),
    ('always_up', 'Always Up'),
    ('always_down', 'Always Down'),
)

# Methods that are electronic by default (never round unless checkbox on)
ELECTRONIC_METHODS = frozenset({
    'm-pesa', 'mpesa', 'card', 'bank', 'cheque', 'check',
    'electronic', 'transfer', 'eft',
})

DEFAULT_STEP = 5.0


def _d(value: Union[int, float, str, Decimal]) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


class CashRoundingService:
    """Reusable cash-rounding math for desktop POS and API."""

    STEP = DEFAULT_STEP

    @staticmethod
    def settings_from_config(cfg: Optional[dict] = None) -> dict:
        cfg = cfg or {}
        enabled = str(cfg.get('cash_rounding_enabled', '1')).strip() in ('1', 'true', 'True', 'yes')
        mode = (cfg.get('cash_rounding_mode') or MODE_NEAREST).strip().lower()
        try:
            value = float(cfg.get('cash_rounding_value', DEFAULT_STEP) or DEFAULT_STEP)
        except (TypeError, ValueError):
            value = DEFAULT_STEP
        if value <= 0:
            value = DEFAULT_STEP
        # Mode shortcuts force step
        if mode == MODE_NEAREST_1:
            value = 1.0
        elif mode in (MODE_NEAREST_5, MODE_NEAREST):
            if mode == MODE_NEAREST_5:
                value = 5.0
        elif mode == MODE_NEAREST_10:
            value = 10.0

        apply = set()
        # Prefer explicit checkboxes; fall back to CSV list
        if str(cfg.get('cash_rounding_apply_cash', '1')).strip() in ('1', 'true', 'True', 'yes'):
            apply.add('cash')
        if str(cfg.get('cash_rounding_apply_mpesa', '0')).strip() in ('1', 'true', 'True', 'yes'):
            apply.update({'m-pesa', 'mpesa'})
        if str(cfg.get('cash_rounding_apply_card', '0')).strip() in ('1', 'true', 'True', 'yes'):
            apply.add('card')
        if str(cfg.get('cash_rounding_apply_bank', '0')).strip() in ('1', 'true', 'True', 'yes'):
            apply.update({'bank', 'cheque', 'check', 'transfer', 'eft'})
        csv = (cfg.get('cash_rounding_methods') or '').strip()
        if csv and not any(k.startswith('cash_rounding_apply_') for k in cfg):
            apply = {m.strip().lower() for m in csv.split(',') if m.strip()}
        if not apply:
            apply = {'cash'}
        return {
            'enabled': enabled,
            'mode': mode,
            'value': value,
            'apply_methods': apply,
        }

    @staticmethod
    def normalize_method(payment_method: Optional[str]) -> str:
        return (payment_method or 'cash').strip().lower().replace('_', ' ')

    @classmethod
    def should_apply(cls, payment_method: Optional[str], settings: Optional[dict] = None) -> bool:
        st = settings if settings and 'enabled' in settings else cls.settings_from_config(settings)
        if not st.get('enabled'):
            return False
        mode = st.get('mode') or MODE_NEAREST
        if mode in (MODE_NONE, 'no_rounding', 'off'):
            return False
        method = cls.normalize_method(payment_method)
        apply = st.get('apply_methods') or {'cash'}
        # Aliases
        if method in apply:
            return True
        if method == 'm-pesa' and 'mpesa' in apply:
            return True
        if method == 'mpesa' and 'm-pesa' in apply:
            return True
        return False

    @staticmethod
    def round_amount(amount: float, mode: str = MODE_NEAREST, value: float = DEFAULT_STEP) -> float:
        """Round *amount* using mode + step. Never changes line-item prices."""
        amt = _d(amount)
        step = _d(value if value and float(value) > 0 else DEFAULT_STEP)
        mode = (mode or MODE_NEAREST).strip().lower()

        if mode in (MODE_NONE, 'no_rounding', 'off') or step <= 0:
            return _money(amt)

        if mode == MODE_NEAREST_1:
            step = _d(1)
            mode = MODE_NEAREST
        elif mode == MODE_NEAREST_5:
            step = _d(5)
            mode = MODE_NEAREST
        elif mode == MODE_NEAREST_10:
            step = _d(10)
            mode = MODE_NEAREST

        if mode in (MODE_NEAREST, 'nearest'):
            units = (amt / step).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            return _money(units * step)

        if mode in (MODE_ALWAYS_UP, 'up', 'ceil'):
            units = (amt / step).to_integral_value(rounding=ROUND_CEILING)
            # Exact multiples stay
            if amt % step == 0:
                return _money(amt)
            return _money(units * step)

        if mode in (MODE_ALWAYS_DOWN, 'down', 'floor'):
            units = (amt / step).to_integral_value(rounding=ROUND_FLOOR)
            return _money(units * step)

        # Unknown mode → nearest
        units = (amt / step).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return _money(units * step)

    @classmethod
    def adjustment(cls, original: float, rounded: float) -> float:
        return round(float(rounded) - float(original), 2)

    @classmethod
    def apply(
        cls,
        original_amount: float,
        payment_method: Optional[str] = 'cash',
        settings: Optional[dict] = None,
        *,
        electronic_portion: float = 0.0,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Apply cash rounding to a final payable amount.

        For mixed payments: pass electronic_portion (M-Pesa/Card already paid).
        Only the remaining cash portion is rounded; electronic is never rounded.

        Returns dict:
          original, electronic, cash_original, cash_rounded,
          rounded_total (final due), adjustment, applied (bool), mode, value
        """
        st = settings if settings and 'enabled' in settings else cls.settings_from_config(settings)
        original = round(float(original_amount or 0), 2)
        electronic = max(0.0, round(float(electronic_portion or 0), 2))
        if electronic > original:
            electronic = original
        cash_original = round(original - electronic, 2)

        result = {
            'original': original,
            'electronic': electronic,
            'cash_original': cash_original,
            'cash_rounded': cash_original,
            'rounded_total': original,
            'adjustment': 0.0,
            'applied': False,
            'show_on_receipt': False,
            'mode': st.get('mode', MODE_NEAREST),
            'value': float(st.get('value', DEFAULT_STEP)),
        }

        method = cls.normalize_method(payment_method)
        # Mixed tender always rounds cash portion when cash rounding enabled + cash apply
        is_mixed = electronic > 0.009
        apply_ok = force or cls.should_apply(
            'cash' if is_mixed else method, st)

        if not apply_ok or cash_original <= 0:
            return result

        cash_rounded = cls.round_amount(
            cash_original, mode=st.get('mode', MODE_NEAREST), value=st.get('value', DEFAULT_STEP))
        rounded_total = round(electronic + cash_rounded, 2)
        adj = cls.adjustment(original, rounded_total)
        result.update({
            'cash_rounded': cash_rounded,
            'rounded_total': rounded_total,
            'adjustment': adj,
            # Applied only when delta is real (UI / receipt gate on this)
            'applied': abs(adj) > 0.009,
            'show_on_receipt': abs(adj) > 0.009,
        })
        return result

    @classmethod
    def apply_to_total(
        cls,
        subtotal: float,
        discount: float,
        tax: float,
        payment_method: str,
        settings: Optional[dict] = None,
        *,
        credit_applied: float = 0.0,
        electronic_portion: float = 0.0,
    ) -> Dict[str, Any]:
        """Round the final amount due (after tax/discount/credit), not unit prices."""
        cart_total = round(max(0.0, float(subtotal) - float(discount)) + float(tax), 2)
        credit = max(0.0, round(float(credit_applied or 0), 2))
        due_raw = round(max(0.0, cart_total - credit), 2)
        out = cls.apply(
            due_raw,
            payment_method=payment_method,
            settings=settings,
            electronic_portion=electronic_portion,
        )
        out['cart_total'] = cart_total
        out['credit_applied'] = credit
        out['amount_due'] = out['rounded_total']
        out['original_due'] = due_raw
        return out


def example_cases() -> Sequence[tuple]:
    """Documented edge cases from product spec (nearest 5)."""
    svc = CashRoundingService
    cases = [
        (37.50, 40.0),
        (38.0, 40.0),
        (42.0, 40.0),
        (43.0, 45.0),
        (47.50, 50.0),
        (40.0, 40.0),
        (35.0, 35.0),
        (0.0, 0.0),
    ]
    return [(a, svc.round_amount(a, MODE_NEAREST, 5), b) for a, b in cases]
