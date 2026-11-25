"""Shop quantities.

Measured goods keep the decimals the cashier typed.
Piece goods stay whole units. 0.5 pieces is refused, not rounded to 1 or 0.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_TOKEN = re.compile(r"-?\d+(?:\.\d+)?")
_QTY = Decimal("0.0001")
_MONEY = Decimal("0.01")

MEASURED_UNITS = {
    "kg", "kgs", "kilogram", "kilograms",
    "g", "gram", "grams",
    "l", "lt", "ltr", "litre", "liter", "litres", "liters",
    "ml", "millilitre", "milliliter", "millilitres", "milliliters",
    "m", "metre", "meter", "metres", "meters",
    "cm", "centimetre", "centimeter", "centimetres", "centimeters",
}

PIECE_UNITS = {
    "pcs", "pc", "piece", "pieces", "unit", "units",
    "item", "items", "each", "ea", "nos", "no",
}


class QuantityError(ValueError):
    pass


def unit_key(unit) -> str:
    return str(unit or "").strip().lower()


def decimal_choice(value):
    """None follows the unit. True allows fractions. False keeps whole quantities."""
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "allow"):
        return True
    if text in ("0", "false", "no", "whole"):
        return False
    return None


def allows_fraction(unit, decimal_qty=None) -> bool:
    """Piece goods are whole units unless the product allows decimals.

    Kilograms, litres, and other measured units keep the decimals typed.
    A product can override that rule without changing its unit.
    """
    choice = decimal_choice(decimal_qty)
    if choice is True:
        return True
    if choice is False:
        return False
    return unit_key(unit) not in PIECE_UNITS


def qty_step(unit, fallback=None, decimal_qty=None) -> float:
    if not allows_fraction(unit, decimal_qty):
        return 1.0
    name = unit_key(unit)
    measured = name in MEASURED_UNITS or decimal_choice(decimal_qty) is True
    default = 0.25 if measured else 0.01
    try:
        step = float(default if fallback is None else fallback)
    except (TypeError, ValueError):
        step = default
    return step if step > 0 else default


def money_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        raise QuantityError("Enter a valid amount.") from None
    if not amount.is_finite():
        raise QuantityError("Enter a valid amount.")
    return amount.quantize(_MONEY, rounding=ROUND_HALF_UP)


def parse_quantity(raw, unit=None, *, allow_zero=False, maximum=999999, decimal_qty=None):
    """Return the quantity as a float rounded to 4 places, or raise QuantityError.

    The float is only the storage form. The value is decided with Decimal and
    is never snapped to a whole number.
    """
    if isinstance(raw, bool) or raw is None:
        raise QuantityError("Enter a valid quantity.")
    # A spin box hands back a binary float. 0.01 stepped up to 0.5 is not a
    # typed string, so that noise is rounded to 4 places instead of rejected.
    if isinstance(raw, (int, float)):
        try:
            number = Decimal(str(raw)).quantize(_QTY, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise QuantityError("Enter a valid quantity.") from None
        text = format(number, "f")
    else:
        text = str(raw).strip().replace(",", "")
        if not text or not _TOKEN.fullmatch(text):
            raise QuantityError("Enter a valid quantity.")
        if "." in text and len(text.split(".", 1)[1]) > 4:
            raise QuantityError("Too many decimal places in the quantity.")
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise QuantityError("Enter a valid quantity.") from None
    if not number.is_finite():
        raise QuantityError("Enter a valid quantity.")
    number = number.quantize(_QTY, rounding=ROUND_HALF_UP)
    if not allows_fraction(unit, decimal_qty) and number != number.to_integral_value():
        raise QuantityError("Quantity must be in whole units.")
    if number < 0:
        raise QuantityError("Quantity cannot be negative.")
    if number == 0 and not allow_zero:
        raise QuantityError("Quantity must be greater than zero.")
    if number > Decimal(str(maximum)):
        raise QuantityError("Quantity is outside the allowed range.")
    return float(number)


def format_quantity(value) -> str:
    try:
        number = Decimal(str(value)).quantize(_QTY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return "0"
    text = format(number, "f").rstrip("0").rstrip(".")
    return text or "0"
