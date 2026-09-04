"""HTTPS client for payments.mugobyte.com — never stores Daraja secrets locally."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from desktop.payments.models import (
    InitiateResult,
    MerchantCapabilities,
    PaymentStatus,
    StatusResult,
)
from desktop.payments.security import mask_phone, redact_for_log

logger = logging.getLogger('payments.cloud')

DEFAULT_BASE_URL = 'https://payments.mugobyte.com'
CONNECT_TIMEOUT = 12
READ_TIMEOUT = 30


class PaymentsCloudClient:
    """Thin HTTPS client. Auth uses shop/device tokens from existing cloud identity."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        token_getter: Optional[Callable[[], str]] = None,
        shop_id_getter: Optional[Callable[[], str]] = None,
        device_id_getter: Optional[Callable[[], str]] = None,
        transport: Optional[Callable[..., dict]] = None,
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip('/')
        self.token_getter = token_getter or (lambda: '')
        self.shop_id_getter = shop_id_getter or (lambda: '')
        self.device_id_getter = device_id_getter or (lambda: '')
        self._transport = transport  # injectable for tests

    def _headers(self) -> dict:
        token = (self.token_getter() or '').strip()
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-MBT-Shop-Id': self.shop_id_getter() or '',
            'X-MBT-Device-Id': self.device_id_getter() or '',
            'User-Agent': 'MBT-POS/3.0 (Windows; payments-client)',
        }
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        if self._transport:
            return self._transport(method, path, body)
        # Skip hostname DNS when offline — Windows can stall 30s+ on
        # payments.mugobyte.com even with urllib timeouts (CloudBoot recovery).
        try:
            from backend.cloud.net_gate import network_up, mark_network_down
            if not network_up(1.0):
                mark_network_down()
                return {
                    'ok': False,
                    'error_code': 'NETWORK',
                    'error_message': 'Offline — payments cloud unreachable',
                }
        except Exception:
            pass
        url = f'{self.base_url}{path}'
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as resp:
                raw = resp.read().decode('utf-8') or '{}'
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode('utf-8')
                parsed = json.loads(err_body) if err_body else {}
            except Exception:
                parsed = {'error': str(e)}
            logger.warning(
                'payments cloud HTTP %s %s → %s %s',
                method, path, e.code, redact_for_log(parsed),
            )
            parsed.setdefault('ok', False)
            parsed.setdefault('error_code', f'HTTP_{e.code}')
            parsed.setdefault('error_message', parsed.get('error') or e.reason)
            return parsed
        except Exception as e:
            logger.warning('payments cloud error %s %s: %s', method, path, e)
            try:
                from backend.cloud.net_gate import mark_network_down
                mark_network_down()
            except Exception:
                pass
            return {
                'ok': False,
                'error_code': 'NETWORK',
                'error_message': str(e) or 'Network error',
            }

    def health(self) -> dict:
        return self._request('GET', '/health')

    def fetch_capabilities(self, shop_id: str) -> MerchantCapabilities:
        data = self._request('GET', f'/v1/shops/{shop_id}/capabilities')
        if not data.get('ok', True) and data.get('error_code'):
            return MerchantCapabilities(shop_id=shop_id, environment='sandbox')
        caps = data.get('capabilities') or data
        return MerchantCapabilities(
            shop_id=shop_id,
            stk_enabled=bool(caps.get('stk_enabled')),
            c2b_enabled=bool(caps.get('c2b_enabled')),
            till_number=str(caps.get('till_number') or ''),
            paybill_number=str(caps.get('paybill_number') or ''),
            business_name=str(caps.get('business_name') or ''),
            shortcode=str(caps.get('shortcode') or ''),
            environment=str(caps.get('environment') or 'sandbox'),
            account_reference_label=str(caps.get('account_reference_label') or 'Invoice'),
            profile_id=str(caps.get('profile_id') or ''),
            synced_at=float(caps.get('synced_at') or time.time()),
        )

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
        payload = {
            'shop_id': shop_id,
            'device_id': device_id,
            'payment_id': payment_id,
            'amount': round(float(amount), 2),
            'phone': phone_e164,
            'account_reference': account_reference[:12],
            'description': (description or 'POS Payment')[:20],
            'idempotency_key': idempotency_key,
        }
        logger.info(
            'STK initiate payment_id=%s amount=%s phone=%s',
            payment_id, payload['amount'], mask_phone(phone_e164),
        )
        data = self._request('POST', '/v1/stk/initiate', payload)
        if not data.get('ok'):
            return InitiateResult(
                ok=False,
                status=PaymentStatus.FAILED.value,
                error_code=str(data.get('error_code') or 'STK_FAILED'),
                error_message=str(data.get('error_message') or 'STK initiate failed'),
                request_accepted=False,
            )
        # request_accepted True ≠ paid
        return InitiateResult(
            ok=True,
            status=PaymentStatus.AWAITING_CUSTOMER.value,
            provider_checkout_id=str(data.get('provider_checkout_id') or ''),
            checkout_request_id=str(data.get('checkout_request_id') or ''),
            merchant_request_id=str(data.get('merchant_request_id') or ''),
            request_accepted=bool(data.get('request_accepted', True)),
        )

    def query_status(
        self,
        *,
        shop_id: str,
        payment_id: str,
        checkout_request_id: str = '',
        provider_checkout_id: str = '',
    ) -> StatusResult:
        payload = {
            'shop_id': shop_id,
            'payment_id': payment_id,
            'checkout_request_id': checkout_request_id,
            'provider_checkout_id': provider_checkout_id,
        }
        data = self._request('POST', '/v1/stk/query', payload)
        status = str(data.get('status') or '').lower()
        # Map cloud statuses — never promote 'accepted'/'pending' to verified
        if status in ('paid', 'completed', 'success', 'verified'):
            mapped = PaymentStatus.VERIFIED.value
        elif status in ('failed', 'cancelled', 'expired'):
            mapped = status
        elif status in ('pending', 'awaiting_customer', 'submitted', 'accepted'):
            mapped = PaymentStatus.AWAITING_CUSTOMER.value
        else:
            mapped = status or PaymentStatus.QUERYING.value
        return StatusResult(
            ok=bool(data.get('ok', True)),
            status=mapped,
            provider_reference=str(data.get('provider_reference') or data.get('mpesa_receipt') or ''),
            amount_received=float(data.get('amount_received') or data.get('amount') or 0),
            result_code=str(data.get('result_code') or ''),
            result_desc=str(data.get('result_desc') or data.get('error_message') or ''),
            raw=data if isinstance(data, dict) else {},
        )

    def list_incoming(
        self,
        *,
        shop_id: str,
        since_ts: float = 0.0,
        unmatched_only: bool = True,
    ) -> list[dict]:
        q = f'/v1/shops/{shop_id}/incoming?since={since_ts:.0f}&unmatched={int(unmatched_only)}'
        data = self._request('GET', q)
        items = data.get('items') or data.get('incoming') or []
        return items if isinstance(items, list) else []

    def register_manual(self, **kwargs) -> StatusResult:
        payload = {
            'shop_id': kwargs.get('shop_id'),
            'payment_id': kwargs.get('payment_id'),
            'provider_reference': str(kwargs.get('provider_reference') or '').strip().upper(),
            'amount': float(kwargs.get('amount') or 0),
            'notes': kwargs.get('notes') or '',
        }
        data = self._request('POST', '/v1/manual/register', payload)
        if not data.get('ok'):
            return StatusResult(
                ok=False,
                status='failed',
                result_desc=str(data.get('error_message') or 'Manual register failed'),
            )
        st = str(data.get('status') or 'manual_pending')
        return StatusResult(
            ok=True,
            status=st,
            provider_reference=payload['provider_reference'],
            amount_received=float(data.get('amount_received') or payload['amount']),
            result_desc=str(data.get('result_desc') or ''),
        )
