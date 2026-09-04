"""Payment provider abstraction — checkout UI never talks to Daraja directly."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from desktop.payments.models import (
    InitiateResult,
    MerchantCapabilities,
    StatusResult,
)


class PaymentProvider(ABC):
    """Channel-agnostic payment provider."""

    @abstractmethod
    def get_capabilities(self, shop_id: str) -> MerchantCapabilities:
        ...

    @abstractmethod
    def initiate_stk(
        self,
        *,
        shop_id: str,
        device_id: str,
        amount: float,
        phone_e164: str,
        account_reference: str,
        idempotency_key: str,
        payment_id: str,
        description: str = 'POS Payment',
    ) -> InitiateResult:
        """Start STK. Success here means request accepted — NOT paid."""
        ...

    @abstractmethod
    def query_status(
        self,
        *,
        shop_id: str,
        payment_id: str,
        checkout_request_id: str = '',
        provider_checkout_id: str = '',
    ) -> StatusResult:
        """Query provider — preferred over double-STK on timeout."""
        ...

    @abstractmethod
    def list_incoming(
        self,
        *,
        shop_id: str,
        since_ts: float = 0.0,
        unmatched_only: bool = True,
    ) -> list[dict]:
        ...

    @abstractmethod
    def register_manual_reference(
        self,
        *,
        shop_id: str,
        payment_id: str,
        provider_reference: str,
        amount: float,
        notes: str = '',
    ) -> StatusResult:
        """Offline/manual fallback — still requires verification path."""
        ...


class NullProvider(PaymentProvider):
    """Offline / unconfigured provider — capabilities empty, manual only."""

    def get_capabilities(self, shop_id: str) -> MerchantCapabilities:
        return MerchantCapabilities(shop_id=shop_id, environment='sandbox')

    def initiate_stk(self, **kwargs) -> InitiateResult:
        return InitiateResult(
            ok=False,
            status='failed',
            error_code='PROVIDER_UNAVAILABLE',
            error_message='MugoByte Payments cloud unavailable. Use Manual Till / reference.',
            request_accepted=False,
        )

    def query_status(self, **kwargs) -> StatusResult:
        return StatusResult(ok=False, status='unknown', result_desc='Provider unavailable')

    def list_incoming(self, **kwargs) -> list[dict]:
        return []

    def register_manual_reference(self, **kwargs) -> StatusResult:
        ref = str(kwargs.get('provider_reference') or '').strip().upper()
        if not ref:
            return StatusResult(ok=False, status='failed', result_desc='Reference required')
        return StatusResult(
            ok=True,
            status='manual_pending',
            provider_reference=ref,
            amount_received=float(kwargs.get('amount') or 0),
            result_desc='Manual reference recorded — awaiting confirmation',
        )


class MpesaProvider(PaymentProvider):
    """M-Pesa via MugoByte Payments cloud (never embeds Daraja secrets)."""

    def __init__(self, cloud_client):
        self.cloud = cloud_client

    def get_capabilities(self, shop_id: str) -> MerchantCapabilities:
        return self.cloud.fetch_capabilities(shop_id)

    def initiate_stk(self, **kwargs) -> InitiateResult:
        return self.cloud.initiate_stk(**kwargs)

    def query_status(self, **kwargs) -> StatusResult:
        return self.cloud.query_status(**kwargs)

    def list_incoming(self, **kwargs) -> list[dict]:
        return self.cloud.list_incoming(**kwargs)

    def register_manual_reference(self, **kwargs) -> StatusResult:
        # Prefer cloud attestation when online; else local pending
        try:
            return self.cloud.register_manual(**kwargs)
        except Exception:
            ref = str(kwargs.get('provider_reference') or '').strip().upper()
            return StatusResult(
                ok=True,
                status='manual_pending',
                provider_reference=ref,
                amount_received=float(kwargs.get('amount') or 0),
                result_desc='Offline manual reference — confirm when online',
            )
