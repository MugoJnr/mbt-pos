"""
Shop calendar helpers — Africa/Nairobi when available, else fixed UTC+3.

Business day for sales reporting matches cloud analytics day bounds.
Windows installs may lack the IANA tz database; Nairobi is permanently UTC+3,
so we never fall through to a wrong machine-local calendar day.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


# Permanent Nairobi offset when zoneinfo/tzdata is unavailable.
_NAIROBI_FIXED = timezone(timedelta(hours=3), name='Africa/Nairobi')


def shop_tzinfo():
    """Return Africa/Nairobi tzinfo (ZoneInfo, pytz, or fixed UTC+3)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('Africa/Nairobi')
    except Exception:
        pass
    try:
        import pytz
        return pytz.timezone('Africa/Nairobi')
    except Exception:
        return _NAIROBI_FIXED


def shop_now() -> datetime:
    """Current wall clock in shop timezone (always Africa/Nairobi or UTC+3)."""
    tz = shop_tzinfo()
    try:
        return datetime.now(tz)
    except Exception:
        return datetime.now(_NAIROBI_FIXED)


def shop_today() -> date:
    """Today's business calendar day for the shop."""
    return shop_now().date()


def parse_sale_date(value) -> date | None:
    """Parse YYYY-MM-DD (or ISO datetime prefix) to date, or None."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def business_day_iso(value=None) -> str:
    """Normalize to YYYY-MM-DD; default shop today."""
    d = parse_sale_date(value) if value is not None else None
    return (d or shop_today()).isoformat()


def sale_created_at_for_day(sale_day: date | str) -> str:
    """
    Timestamp stored on sales.created_at for a business day.

    Same calendar day → real now (local/Nairobi).
    Other day → that date + current clock time so date(created_at) reports correctly.
    """
    day = parse_sale_date(sale_day) or shop_today()
    now = shop_now()
    clock = now.time().replace(microsecond=0)
    if day == shop_today():
        naive = now.replace(microsecond=0)
        if naive.tzinfo is not None:
            naive = naive.replace(tzinfo=None)
        return naive.strftime('%Y-%m-%d %H:%M:%S')
    # Keep naive ISO-like string consistent with SQLite CURRENT_TIMESTAMP style
    combined = datetime.combine(day, clock)
    return combined.strftime('%Y-%m-%d %H:%M:%S')


def sale_day_sql(alias: str = '') -> str:
    """
    SQL expression for the reporting/business day of a sale row.

    Prefers sale_date column; falls back to date(created_at).
    """
    prefix = f'{alias}.' if alias else ''
    return (
        f"COALESCE(NULLIF({prefix}sale_date,''), date({prefix}created_at))"
    )


def receipt_date_label(sale_data: dict, *, today: date | None = None) -> tuple[str, bool]:
    """
    Human date line for receipts.

    Returns (display_string, is_not_today).
    Prefer sale_date; show entered time when backdated.
    """
    today = today or shop_today()
    sale_date = parse_sale_date(
        sale_data.get('sale_date') or sale_data.get('business_day')
    )
    created = str(sale_data.get('created_at') or '')
    if sale_date is None and created:
        sale_date = parse_sale_date(created)
    if sale_date is None:
        sale_date = today
    is_other = sale_date != today
    # Primary: business day; secondary: entry timestamp when different day
    if is_other:
        entered = created[:19] if created else ''
        if entered and entered[:10] != sale_date.isoformat():
            label = f"{sale_date.isoformat()} (entered {entered})"
        else:
            # created_at already stamped on that day — still flag sale date
            label = f"{sale_date.isoformat()}  {created[11:19] if len(created) >= 19 else ''}".rstrip()
            label = f"{label} *BACKDATED*"
        return label.strip(), True
    # Today — show normal datetime
    if created:
        return created[:19], False
    return datetime.combine(sale_date, time.min).strftime('%Y-%m-%d %H:%M:%S'), False
