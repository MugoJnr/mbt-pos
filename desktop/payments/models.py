"""Payment domain models — status machine and record shapes."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import time
import uuid


class PaymentStatus(str, Enum):
    """Authoritative local payment lifecycle.

    Daraja 'request accepted' is NEVER paid — only VERIFIED is paid.
    """
    DRAFT = 'draft'                 # checkout started, no provider call yet
    PENDING = 'pending'             # STK sent / awaiting Till match
    SUBMITTED = 'submitted'         # cloud accepted initiate (not paid)
    AWAITING_CUSTOMER = 'awaiting_customer'
    QUERYING = 'querying'           # timeout recovery / status poll
    MATCHED = 'matched'             # candidate match, may need confirm
    NEEDS_CONFIRMATION = 'needs_confirmation'  # ambiguous — never auto-guess
    UNDERPAID = 'underpaid'
    OVERPAID = 'overpaid'
    VERIFIED = 'verified'           # ONLY state that may create_sale()
    COMPLETED = 'completed'         # sale created once; receipt printed
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'
    MANUAL_PENDING = 'manual_pending'  # offline fallback awaiting audit


# States that may still recover after restart / network blip
RECOVERABLE_STATUSES = frozenset({
    PaymentStatus.PENDING,
    PaymentStatus.SUBMITTED,
    PaymentStatus.AWAITING_CUSTOMER,
    PaymentStatus.QUERYING,
    PaymentStatus.MATCHED,
    PaymentStatus.NEEDS_CONFIRMATION,
    PaymentStatus.UNDERPAID,
    PaymentStatus.OVERPAID,
    PaymentStatus.MANUAL_PENDING,
})

# Terminal — do not re-STK or auto-complete
TERMINAL_STATUSES = frozenset({
    PaymentStatus.COMPLETED,
    PaymentStatus.FAILED,
    PaymentStatus.CANCELLED,
    PaymentStatus.EXPIRED,
})

# Paid enough to create sale (exact or overpaid after cashier decision)
SALE_ELIGIBLE = frozenset({
    PaymentStatus.VERIFIED,
})


class PaymentChannel(str, Enum):
    STK = 'stk'
    TILL = 'till'
    PAYBILL = 'paybill'
    MANUAL = 'manual'       # cashier-entered reference (offline/online)
    SPLIT = 'split'         # schema-compatible split tender parent


class MatchConfidence(str, Enum):
    EXACT = 'exact'                 # amount + phone + time window unique
    STRONG = 'strong'               # amount + unique ref / checkout id
    AMBIGUOUS = 'ambiguous'         # multiple candidates — never auto
    NONE = 'none'


def new_payment_id() -> str:
    return f'pay_{uuid.uuid4().hex}'


def new_idempotency_key() -> str:
    return f'idem_{uuid.uuid4().hex}'


@dataclass
class PaymentRecord:
    """Unified payment record for STK + Till/Paybill + manual."""
    id: str
    shop_id: str
    device_id: str
    amount_expected: float
    currency: str = 'KES'
    status: str = PaymentStatus.DRAFT.value
    channel: str = PaymentChannel.STK.value
    phone_masked: str = ''
    phone_e164: str = ''           # stored encrypted/local only; never logged raw in full
    customer_name: str = ''
    cart_fingerprint: str = ''
    cart_json: str = ''            # frozen checkout cart for post-verify create_sale
    sale_id: Optional[int] = None
    receipt_number: Optional[str] = None
    provider_checkout_id: str = ''  # our cloud id
    provider_reference: str = ''    # M-Pesa receipt / CheckoutRequestID (UNIQUE)
    merchant_request_id: str = ''
    checkout_request_id: str = ''
    till_number: str = ''
    paybill_number: str = ''
    account_reference: str = ''
    amount_received: float = 0.0
    variance: float = 0.0
    match_confidence: str = MatchConfidence.NONE.value
    match_candidates_json: str = '[]'
    idempotency_key: str = ''
    error_code: str = ''
    error_message: str = ''
    notes: str = ''
    cashier_id: Optional[int] = None
    cashier_name: str = ''
    confirmed_by: str = ''
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    verified_at: float = 0.0
    completed_at: float = 0.0
    meta_json: str = '{}'

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> 'PaymentRecord':
        data = dict(row) if not isinstance(row, dict) else row
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: data[k] for k in known if k in data})


@dataclass
class IncomingPayment:
    """C2B / Till / Paybill notification normalized from cloud."""
    id: str
    shop_id: str
    provider_reference: str
    amount: float
    phone_masked: str = ''
    phone_e164: str = ''
    till_number: str = ''
    paybill_number: str = ''
    bill_ref: str = ''
    trans_time: str = ''
    raw_json: str = '{}'
    matched_payment_id: str = ''
    status: str = 'unmatched'  # unmatched | matched | ignored | disputed
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MerchantCapabilities:
    """What this shop's cloud merchant profile can do — drives UI."""
    shop_id: str
    stk_enabled: bool = False
    c2b_enabled: bool = False
    till_number: str = ''
    paybill_number: str = ''
    business_name: str = ''
    shortcode: str = ''
    environment: str = 'sandbox'  # sandbox | production
    account_reference_label: str = 'Invoice'
    profile_id: str = ''
    synced_at: float = 0.0

    @property
    def can_send_prompt(self) -> bool:
        return bool(self.stk_enabled and self.shortcode)

    @property
    def can_detect_till(self) -> bool:
        return bool(self.c2b_enabled and (self.till_number or self.paybill_number))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InitiateResult:
    ok: bool
    status: str = PaymentStatus.SUBMITTED.value
    provider_checkout_id: str = ''
    checkout_request_id: str = ''
    merchant_request_id: str = ''
    error_code: str = ''
    error_message: str = ''
    # CRITICAL: accepted=True means Daraja queued STK — NOT paid
    request_accepted: bool = False


@dataclass
class StatusResult:
    ok: bool
    status: str = ''
    provider_reference: str = ''
    amount_received: float = 0.0
    result_code: str = ''
    result_desc: str = ''
    raw: dict = field(default_factory=dict)
