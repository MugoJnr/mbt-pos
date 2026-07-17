"""
MBT POS — Central option catalogs for standardized selects.
MugoByte Technologies | mugobyte.com

Single source of truth for predefined dropdown values.
Free-text is reserved for optional notes and ReasonSelect "Other → Please specify".
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Optional, Tuple

# ── Void / Consumption / Stock ────────────────────────────────────────────────

VOID_REASONS = (
    'Customer Request',
    'Wrong Item Sold',
    'Wrong Price / Amount',
    'Duplicate Sale',
    'Payment Failed',
    'Cashier Error',
    'Manager Override',
    'Fraud / Suspicion',
    'Other',
)

CONSUMPTION_REASONS = (
    'Production',
    'Staff Consumption',
    'Office Use',
    'Cleaning',
    'Sampling',
    'Damaged During Production',
    'Donation',
    'Promotion',
    'Other',
)

# Map legacy stored values → current catalog labels (history display / filters)
CONSUMPTION_REASON_ALIASES = {
    'Staff Use': 'Staff Consumption',
    'Free Samples': 'Sampling',
    'Testing': 'Sampling',
    'Charity': 'Donation',
}

STOCK_ADJUSTMENT_TYPES = (
    'Increase',
    'Decrease',
    'Set Quantity',
    'Stock Count Correction',
)

STOCK_ADJUSTMENT_REASONS = (
    'Received from Supplier',
    'Stock Count Correction',
    'Damaged / Spoiled',
    'Theft / Loss',
    'Return to Supplier',
    'Transfer In',
    'Transfer Out',
    'Opening Balance',
    'System Correction',
    'Other',
)

# ── Payments ──────────────────────────────────────────────────────────────────

PAYMENT_METHODS = (
    'Cash',
    'M-Pesa',
    'Airtel Money',
    'Card',
    'Bank Transfer',
    'Credit Account',
    'Mixed',
)

# Checkout / debt flows keep Part Payment + Credit Sale (Credit Account alias)
POS_PAYMENT_METHODS = (
    'Cash',
    'M-Pesa',
    'Airtel Money',
    'Card',
    'Bank Transfer',
    'Cheque',
    'Part Payment',
    'Credit Sale',
    'Mixed',
)

DEBT_PAYMENT_METHODS = (
    'Cash',
    'M-Pesa',
    'Airtel Money',
    'Card',
    'Bank Transfer',
    'Cheque',
    'Mixed',
)

# ── Entities / status ─────────────────────────────────────────────────────────

CUSTOMER_TYPES = (
    'Retail',
    'Wholesale',
    'Walk-in',
    'Corporate',
    'VIP',
    'Other',
)

USER_ROLES = (
    'superadmin',
    'admin',
    'manager',
    'cashier',
    'viewer',
)

USER_ROLE_LABELS = {
    'superadmin': 'Super Admin (shop owner)',
    'admin': 'Admin (manager)',
    'manager': 'Manager',
    'cashier': 'Cashier',
    'viewer': 'Viewer',
}

PRODUCT_STATUSES = (
    'Active',
    'Inactive',
    'Discontinued',
    'Out of Stock',
)

SUPPLIER_STATUSES = (
    'Active',
    'Inactive',
    'On Hold',
    'Blocked',
)

PURCHASE_STATUSES = (
    'Draft',
    'Ordered',
    'Partial',
    'Received',
    'Cancelled',
)

TRANSFER_STATUSES = (
    'Draft',
    'In Transit',
    'Received',
    'Cancelled',
)

INVOICE_STATUSES = (
    'Pending',
    'Partial',
    'Paid',
    'Overdue',
    'Cancelled',
)

EXPENSE_CATEGORIES = (
    'Rent',
    'Utilities',
    'Salaries',
    'Transport',
    'Supplies',
    'Maintenance',
    'Marketing',
    'Licenses & Fees',
    'Bank Charges',
    'Miscellaneous',
    'Other',
)

# ── Date presets ──────────────────────────────────────────────────────────────

DATE_PRESETS = (
    ('Today', 'today'),
    ('Yesterday', 'yesterday'),
    ('This Week', 'week'),
    ('This Month', 'month'),
    ('Last Month', 'last_month'),
    ('Custom Range', 'custom'),
)

DATE_PRESET_LABELS = tuple(lbl for lbl, _ in DATE_PRESETS)


def normalize_consumption_reason(reason: str) -> str:
    r = (reason or '').strip()
    return CONSUMPTION_REASON_ALIASES.get(r, r)


def role_label(role: str) -> str:
    key = (role or '').strip().lower()
    return USER_ROLE_LABELS.get(key, role or 'User')


def date_range_for_preset(preset_key: str,
                          today: Optional[date] = None) -> Tuple[date, date]:
    """
    Return (start, end) inclusive dates for a DATE_PRESETS key.
    'custom' returns today..today (caller shows date pickers).
    """
    today = today or date.today()
    key = (preset_key or 'today').strip().lower()
    if key == 'yesterday':
        d = today - timedelta(days=1)
        return d, d
    if key in ('week', 'this_week'):
        start = today - timedelta(days=today.weekday())  # Monday
        return start, today
    if key in ('month', 'this_month'):
        return today.replace(day=1), today
    if key == 'last_month':
        first_this = today.replace(day=1)
        last_end = first_this - timedelta(days=1)
        return last_end.replace(day=1), last_end
    # today / custom / unknown
    return today, today


def labels(items: Iterable[str]) -> List[str]:
    return [str(x) for x in items]


def with_all(items: Iterable[str], all_label: str = 'All') -> List[str]:
    return [all_label] + labels(items)
