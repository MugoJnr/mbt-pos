"""
MBT POS — M-Pesa payment subsystem.

Two channels, one unified payment record:
  - STK Prompt (via MugoByte Payments cloud → Safaricom Daraja)
  - Manual Till / Paybill detection + matching

Never treat Daraja "request accepted" as paid.
Never create a sale until payment status is VERIFIED.
"""
from __future__ import annotations

from desktop.payments.models import (
    PaymentStatus,
    PaymentChannel,
    MatchConfidence,
    PaymentRecord,
)
from desktop.payments.service import PaymentService, get_payment_service
from desktop.payments.schema import ensure_payment_schema

__all__ = [
    'PaymentStatus',
    'PaymentChannel',
    'MatchConfidence',
    'PaymentRecord',
    'PaymentService',
    'get_payment_service',
    'ensure_payment_schema',
]
