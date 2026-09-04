"""
PaymentService — single orchestration path for STK + Till + manual.

Order (non-negotiable):
  pending checkout → payment created → VERIFIED paid → create_sale() ONCE
  → stock once → receipt from saved sale

Never treat Daraja request-accepted as paid.
Never duplicate sales / stock / debt / receipts.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from desktop.payments.cloud_client import PaymentsCloudClient, DEFAULT_BASE_URL
from desktop.payments.matching import classify_amount_variance, match_incoming_to_payment
from desktop.payments.models import (
    IncomingPayment,
    MatchConfidence,
    MerchantCapabilities,
    PaymentChannel,
    PaymentRecord,
    PaymentStatus,
    RECOVERABLE_STATUSES,
    new_idempotency_key,
    new_payment_id,
)
from desktop.payments.provider import MpesaProvider, NullProvider, PaymentProvider
from desktop.payments.repository import PaymentRepository
from desktop.payments.security import (
    assert_no_pin,
    cart_fingerprint,
    mask_phone,
    normalize_ke_phone,
    redact_for_log,
)

logger = logging.getLogger('payments.service')

_service_lock = threading.Lock()
_service_singleton: Optional['PaymentService'] = None


class PaymentService:
    def __init__(
        self,
        repo: PaymentRepository,
        provider: PaymentProvider,
        *,
        shop_id_getter: Callable[[], str],
        device_id_getter: Callable[[], str],
        create_sale: Optional[Callable[[dict], dict]] = None,
        settings_getter: Optional[Callable[[], dict]] = None,
    ):
        self.repo = repo
        self.provider = provider
        self.shop_id_getter = shop_id_getter
        self.device_id_getter = device_id_getter
        self.create_sale = create_sale
        self.settings_getter = settings_getter or (lambda: {})
        self._complete_lock = threading.Lock()

    # ── capabilities ──────────────────────────────────────────────
    def get_capabilities(self, *, force_refresh: bool = False) -> MerchantCapabilities:
        shop_id = self.shop_id_getter() or 'local'
        cached = self.repo.load_merchant_cache(shop_id)
        if cached and not force_refresh and (time.time() - cached.synced_at) < 300:
            return cached
        try:
            caps = self.provider.get_capabilities(shop_id)
            if caps.stk_enabled or caps.c2b_enabled or caps.till_number or caps.paybill_number:
                self.repo.save_merchant_cache(caps)
                return caps
        except Exception as e:
            logger.warning('capabilities refresh failed: %s', e)
        if cached:
            return cached
        # Fall back to local settings (manual till display — no secrets)
        cfg = self.settings_getter() or {}
        return MerchantCapabilities(
            shop_id=shop_id,
            stk_enabled=False,
            c2b_enabled=False,
            till_number=str(cfg.get('mpesa_till') or ''),
            paybill_number=str(cfg.get('mpesa_paybill') or ''),
            business_name=str(cfg.get('mpesa_business_name') or cfg.get('shop_name') or ''),
            environment=str(cfg.get('payments_environment') or 'sandbox'),
        )

    # ── create pending payment from checkout ──────────────────────
    def create_pending_payment(
        self,
        *,
        amount: float,
        cart: list,
        channel: str = PaymentChannel.STK.value,
        phone: str = '',
        customer_name: str = '',
        cashier_id: Optional[int] = None,
        cashier_name: str = '',
        account_reference: str = '',
        notes: str = '',
        idempotency_key: str = '',
        meta: Optional[dict] = None,
    ) -> PaymentRecord:
        assert_no_pin(notes)
        amount = round(float(amount), 2)
        if amount <= 0:
            raise ValueError('Payment amount must be positive.')
        key = idempotency_key or new_idempotency_key()
        existing = self.repo.get_by_idempotency(key)
        if existing:
            return existing  # idempotent create

        phone_e164 = normalize_ke_phone(phone) if phone else ''
        caps = self.get_capabilities()
        payment = PaymentRecord(
            id=new_payment_id(),
            shop_id=self.shop_id_getter() or 'local',
            device_id=self.device_id_getter() or '',
            amount_expected=amount,
            status=PaymentStatus.PENDING.value,
            channel=channel,
            phone_masked=mask_phone(phone_e164) if phone_e164 else '',
            phone_e164=phone_e164,
            customer_name=customer_name or '',
            cart_fingerprint=cart_fingerprint(cart, amount),
            cart_json=json.dumps({'items': cart, 'total': amount, **(meta or {})}),
            till_number=caps.till_number,
            paybill_number=caps.paybill_number,
            account_reference=(account_reference or '')[:12],
            idempotency_key=key,
            cashier_id=cashier_id,
            cashier_name=cashier_name or '',
            notes=notes or '',
            created_at=time.time(),
            updated_at=time.time(),
        )
        return self.repo.insert_payment(payment)

    # ── STK ───────────────────────────────────────────────────────
    def send_stk(self, payment_id: str, phone: str = '') -> PaymentRecord:
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        if payment.status in (
            PaymentStatus.VERIFIED.value,
            PaymentStatus.COMPLETED.value,
        ):
            return payment  # never re-STK a paid payment
        if payment.sale_id:
            return payment

        caps = self.get_capabilities()
        if not caps.can_send_prompt:
            payment.status = PaymentStatus.FAILED.value
            payment.error_code = 'STK_NOT_ENABLED'
            payment.error_message = 'STK Prompt not enabled for this merchant profile.'
            return self.repo.update_payment(payment, 'stk_blocked', payment.error_message)

        phone_e164 = normalize_ke_phone(phone) if phone else payment.phone_e164
        if not phone_e164:
            raise ValueError('Customer phone required for STK Prompt.')
        payment.phone_e164 = phone_e164
        payment.phone_masked = mask_phone(phone_e164)
        payment.channel = PaymentChannel.STK.value

        result = self.provider.initiate_stk(
            shop_id=payment.shop_id,
            device_id=payment.device_id,
            amount=payment.amount_expected,
            phone_e164=phone_e164,
            account_reference=payment.account_reference or payment.id[-12:],
            idempotency_key=payment.idempotency_key,
            payment_id=payment.id,
        )
        # CRITICAL: request_accepted ≠ paid
        if not result.ok:
            payment.status = PaymentStatus.FAILED.value
            payment.error_code = result.error_code
            payment.error_message = result.error_message
            return self.repo.update_payment(payment, 'stk_failed', result.error_message)

        payment.provider_checkout_id = result.provider_checkout_id
        payment.checkout_request_id = result.checkout_request_id
        payment.merchant_request_id = result.merchant_request_id
        payment.status = PaymentStatus.AWAITING_CUSTOMER.value
        payment.error_code = ''
        payment.error_message = ''
        return self.repo.update_payment(
            payment, 'stk_submitted',
            f'accepted={result.request_accepted} checkout={result.checkout_request_id}',
        )

    # ── query / timeout recovery (never double-STK) ───────────────
    def query_payment(self, payment_id: str) -> PaymentRecord:
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        if payment.status == PaymentStatus.COMPLETED.value:
            return payment

        payment.status = PaymentStatus.QUERYING.value
        self.repo.update_payment(payment, 'query_start')

        result = self.provider.query_status(
            shop_id=payment.shop_id,
            payment_id=payment.id,
            checkout_request_id=payment.checkout_request_id,
            provider_checkout_id=payment.provider_checkout_id,
        )
        return self._apply_status_result(payment, result)

    def _apply_status_result(self, payment: PaymentRecord, result) -> PaymentRecord:
        if result.provider_reference:
            # UNIQUE provider_reference — reject duplicates across payments
            other = self.repo.get_by_provider_reference(result.provider_reference)
            if other and other.id != payment.id:
                payment.status = PaymentStatus.NEEDS_CONFIRMATION.value
                payment.error_code = 'DUPLICATE_PROVIDER_REF'
                payment.error_message = (
                    f'Reference {result.provider_reference} already used by {other.id}'
                )
                return self.repo.update_payment(payment, 'duplicate_ref', payment.error_message)
            payment.provider_reference = result.provider_reference.upper()

        if result.amount_received:
            payment.amount_received = round(float(result.amount_received), 2)
            payment.variance = round(payment.amount_received - payment.amount_expected, 2)

        st = (result.status or '').lower()
        if st == PaymentStatus.VERIFIED.value or st in ('paid', 'success', 'completed'):
            return self._mark_verified_or_variance(payment)
        if st in (
            PaymentStatus.FAILED.value,
            PaymentStatus.CANCELLED.value,
            PaymentStatus.EXPIRED.value,
        ):
            payment.status = st
            payment.error_message = result.result_desc or st
            return self.repo.update_payment(payment, 'terminal', st)
        # Still waiting — do NOT mark paid
        payment.status = PaymentStatus.AWAITING_CUSTOMER.value
        return self.repo.update_payment(payment, 'still_pending', result.result_desc or '')

    def _mark_verified_or_variance(self, payment: PaymentRecord) -> PaymentRecord:
        received = payment.amount_received or payment.amount_expected
        payment.amount_received = round(float(received), 2)
        payment.variance = round(payment.amount_received - payment.amount_expected, 2)
        kind = classify_amount_variance(payment.amount_expected, payment.amount_received)
        if kind == 'underpaid':
            payment.status = PaymentStatus.UNDERPAID.value
            return self.repo.update_payment(payment, 'underpaid', f'var={payment.variance}')
        if kind == 'overpaid':
            cfg = self.settings_getter() or {}
            # Overpay never silent — needs cashier decision unless auto disabled
            payment.status = PaymentStatus.OVERPAID.value
            return self.repo.update_payment(payment, 'overpaid', f'var={payment.variance}')
        payment.status = PaymentStatus.VERIFIED.value
        payment.verified_at = time.time()
        payment.error_code = ''
        payment.error_message = ''
        return self.repo.update_payment(payment, 'verified', payment.provider_reference)

    # ── Till / C2B ingest + match ─────────────────────────────────
    def ingest_incoming(self, row: dict) -> IncomingPayment:
        shop_id = str(row.get('shop_id') or self.shop_id_getter() or 'local')
        # Hard multi-shop isolation
        local_shop = self.shop_id_getter() or 'local'
        if shop_id != local_shop and local_shop != 'local':
            raise ValueError('Cross-shop incoming payment rejected')
        ref = str(row.get('provider_reference') or row.get('TransID') or '').strip().upper()
        if not ref:
            raise ValueError('provider_reference required')
        phone = normalize_ke_phone(str(row.get('phone_e164') or row.get('MSISDN') or ''))
        incoming = IncomingPayment(
            id=str(row.get('id') or f'in_{ref}'),
            shop_id=shop_id,
            provider_reference=ref,
            amount=round(float(row.get('amount') or row.get('TransAmount') or 0), 2),
            phone_masked=mask_phone(phone) if phone else str(row.get('phone_masked') or ''),
            phone_e164=phone,
            till_number=str(row.get('till_number') or ''),
            paybill_number=str(row.get('paybill_number') or ''),
            bill_ref=str(row.get('bill_ref') or row.get('BillRefNumber') or ''),
            trans_time=str(row.get('trans_time') or ''),
            raw_json=json.dumps(redact_for_log(row)),
            created_at=float(row.get('created_at') or time.time()),
        )
        return self.repo.upsert_incoming(incoming)

    def sync_incoming_and_match(self, payment_id: str) -> PaymentRecord:
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        if payment.status == PaymentStatus.COMPLETED.value:
            return payment

        # Pull from cloud
        try:
            remote = self.provider.list_incoming(shop_id=payment.shop_id, unmatched_only=True)
            for row in remote:
                row = dict(row)
                row.setdefault('shop_id', payment.shop_id)
                try:
                    self.ingest_incoming(row)
                except Exception as e:
                    logger.debug('ingest skip: %s', e)
        except Exception as e:
            logger.warning('list_incoming failed: %s', e)

        cfg = self.settings_getter() or {}
        tol = float(cfg.get('mpesa_amount_tolerance') or 0.01)
        window = float(cfg.get('mpesa_match_window_sec') or 600)
        incoming = self.repo.list_unmatched_incoming(
            payment.shop_id, since_ts=payment.created_at - window
        )
        result = match_incoming_to_payment(
            payment, incoming, amount_tolerance=tol, window_sec=window
        )
        payment.match_confidence = result.confidence
        payment.match_candidates_json = json.dumps([
            {
                'incoming_id': c.incoming_id,
                'provider_reference': c.provider_reference,
                'amount': c.amount,
                'phone_masked': c.phone_masked,
                'score': c.score,
                'reasons': c.reasons,
            }
            for c in result.candidates
        ])

        if result.confidence == MatchConfidence.AMBIGUOUS.value:
            payment.status = PaymentStatus.NEEDS_CONFIRMATION.value
            return self.repo.update_payment(payment, 'ambiguous', result.reason)

        if result.confidence == MatchConfidence.NONE.value or not result.selected:
            return self.repo.update_payment(payment, 'no_match', result.reason)

        sel = result.selected
        # Duplicate ref guard
        other = self.repo.get_by_provider_reference(sel.provider_reference)
        if other and other.id != payment.id:
            payment.status = PaymentStatus.NEEDS_CONFIRMATION.value
            payment.error_code = 'DUPLICATE_PROVIDER_REF'
            return self.repo.update_payment(payment, 'duplicate_ref', other.id)

        payment.provider_reference = sel.provider_reference
        payment.amount_received = sel.amount
        payment.channel = (
            PaymentChannel.TILL.value if payment.till_number else PaymentChannel.PAYBILL.value
        )
        self.repo.mark_incoming_matched(sel.incoming_id, payment.id)
        return self._mark_verified_or_variance(payment)

    def confirm_match(
        self,
        payment_id: str,
        provider_reference: str,
        *,
        confirmed_by: str,
        amount_received: Optional[float] = None,
    ) -> PaymentRecord:
        """Cashier/manager confirmation for ambiguous matches — never auto-guess."""
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        ref = provider_reference.strip().upper()
        other = self.repo.get_by_provider_reference(ref)
        if other and other.id != payment.id:
            raise ValueError(f'Reference already linked to payment {other.id}')
        payment.provider_reference = ref
        if amount_received is not None:
            payment.amount_received = round(float(amount_received), 2)
        elif not payment.amount_received:
            payment.amount_received = payment.amount_expected
        payment.confirmed_by = confirmed_by
        payment.match_confidence = MatchConfidence.STRONG.value
        return self._mark_verified_or_variance(payment)

    # ── manual / offline fallback ─────────────────────────────────
    def register_manual_reference(
        self,
        payment_id: str,
        provider_reference: str,
        *,
        amount: Optional[float] = None,
        confirmed_by: str = '',
        notes: str = '',
        force_verify: bool = False,
    ) -> PaymentRecord:
        assert_no_pin(notes)
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        ref = provider_reference.strip().upper()
        if len(ref) < 6:
            raise ValueError('M-Pesa reference looks too short')
        other = self.repo.get_by_provider_reference(ref)
        if other and other.id != payment.id:
            raise ValueError(f'Reference already used by payment {other.id}')

        result = self.provider.register_manual_reference(
            shop_id=payment.shop_id,
            payment_id=payment.id,
            provider_reference=ref,
            amount=float(amount if amount is not None else payment.amount_expected),
            notes=notes,
        )
        payment.provider_reference = ref
        payment.channel = PaymentChannel.MANUAL.value
        payment.amount_received = round(
            float(result.amount_received or amount or payment.amount_expected), 2
        )
        payment.notes = (payment.notes + ' | ' + notes).strip(' |') if notes else payment.notes
        payment.confirmed_by = confirmed_by
        if force_verify or (result.status == PaymentStatus.VERIFIED.value):
            return self._mark_verified_or_variance(payment)
        payment.status = PaymentStatus.MANUAL_PENDING.value
        return self.repo.update_payment(payment, 'manual_pending', ref)

    # ── complete: VERIFIED → create_sale ONCE ─────────────────────
    def complete_sale_if_verified(
        self,
        payment_id: str,
        *,
        sale_payload_builder: Optional[Callable[[PaymentRecord], dict]] = None,
    ) -> dict:
        """Create sale exactly once for a VERIFIED payment. Idempotent."""
        with self._complete_lock:
            payment = self.repo.get_payment(payment_id)
            if not payment:
                return {'ok': False, 'error': 'Payment not found'}
            if payment.sale_id and payment.status == PaymentStatus.COMPLETED.value:
                return {
                    'ok': True,
                    'idempotent': True,
                    'sale_id': payment.sale_id,
                    'receipt_number': payment.receipt_number,
                    'payment': payment.to_dict(),
                }
            # Only VERIFIED may create a sale. OVERPAID/UNDERPAID require explicit accept.
            if payment.status != PaymentStatus.VERIFIED.value:
                return {
                    'ok': False,
                    'error': f'Payment not verified (status={payment.status})',
                    'payment': payment.to_dict(),
                }

            if not self.create_sale:
                return {'ok': False, 'error': 'create_sale not wired'}

            if sale_payload_builder:
                payload = sale_payload_builder(payment)
            else:
                payload = self._default_sale_payload(payment)

            # Stamp payment_id for traceability
            payload['payment_id'] = payment.id
            if payment.provider_reference and not payload.get('mpesa_ref'):
                payload['mpesa_ref'] = payment.provider_reference

            result = self.create_sale(payload)
            if not result or not result.get('success'):
                err = (result or {}).get('error') if isinstance(result, dict) else 'create_sale failed'
                payment.error_message = str(err)
                self.repo.update_payment(payment, 'create_sale_failed', str(err))
                return {'ok': False, 'error': err, 'payment': payment.to_dict()}

            payment.sale_id = result.get('sale_id')
            payment.receipt_number = result.get('receipt_number')
            payment.status = PaymentStatus.COMPLETED.value
            payment.completed_at = time.time()
            self.repo.update_payment(
                payment, 'completed',
                f"sale_id={payment.sale_id} receipt={payment.receipt_number}",
            )
            return {
                'ok': True,
                'idempotent': False,
                'sale_id': payment.sale_id,
                'receipt_number': payment.receipt_number,
                'payment': payment.to_dict(),
                'sale': result,
            }

    def _default_sale_payload(self, payment: PaymentRecord) -> dict:
        cart = {}
        try:
            cart = json.loads(payment.cart_json or '{}')
        except Exception:
            cart = {}
        items = cart.get('items') or []
        total = float(cart.get('total') or payment.amount_expected)
        paid = float(payment.amount_received or payment.amount_expected)
        return {
            'items': items,
            'total': total,
            'payment_method': 'mpesa',
            'amount_paid': paid,
            'mpesa_ref': payment.provider_reference,
            'notes': payment.notes,
            'electronic_paid': paid,
            'electronic_method': 'M-Pesa',
            'cash_paid': 0,
        }

    def accept_overpayment(self, payment_id: str, *, confirmed_by: str) -> PaymentRecord:
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        if payment.status != PaymentStatus.OVERPAID.value:
            raise ValueError('Payment is not overpaid')
        payment.confirmed_by = confirmed_by
        payment.status = PaymentStatus.VERIFIED.value
        payment.verified_at = time.time()
        return self.repo.update_payment(payment, 'overpay_accepted', confirmed_by)

    def accept_underpayment_as_part(
        self, payment_id: str, *, confirmed_by: str
    ) -> PaymentRecord:
        """Mark underpaid verified for part-payment / debt flows (caller builds sale)."""
        payment = self.repo.get_payment(payment_id)
        if not payment:
            raise ValueError('Payment not found')
        if payment.status != PaymentStatus.UNDERPAID.value:
            raise ValueError('Payment is not underpaid')
        payment.confirmed_by = confirmed_by
        payment.status = PaymentStatus.VERIFIED.value
        payment.verified_at = time.time()
        return self.repo.update_payment(payment, 'underpay_accepted', confirmed_by)

    # ── restart recovery ──────────────────────────────────────────
    def recover_pending_payments(self) -> list[PaymentRecord]:
        """On app start: query don't double-STK; resume matching."""
        shop_id = self.shop_id_getter() or ''
        statuses = [s.value for s in RECOVERABLE_STATUSES]
        pending = self.repo.list_by_status(statuses, shop_id=shop_id)
        recovered = []
        for payment in pending:
            try:
                if payment.channel == PaymentChannel.STK.value and payment.checkout_request_id:
                    recovered.append(self.query_payment(payment.id))
                else:
                    recovered.append(self.sync_incoming_and_match(payment.id))
            except Exception as e:
                logger.warning('recover %s failed: %s', payment.id, e)
                recovered.append(payment)
        return recovered

    def inbox(self, limit: int = 100) -> dict:
        return self.repo.list_inbox(self.shop_id_getter() or 'local', limit=limit)

    def get_payment(self, payment_id: str) -> Optional[PaymentRecord]:
        return self.repo.get_payment(payment_id)


def build_payment_service(
    *,
    db_conn_factory: Callable,
    create_sale: Optional[Callable[[dict], dict]] = None,
    settings_getter: Optional[Callable[[], dict]] = None,
    shop_id_getter: Optional[Callable[[], str]] = None,
    device_id_getter: Optional[Callable[[], str]] = None,
    token_getter: Optional[Callable[[], str]] = None,
    cloud_transport=None,
    offline: bool = False,
) -> PaymentService:
    settings_getter = settings_getter or (lambda: {})
    shop_id_getter = shop_id_getter or _default_shop_id
    device_id_getter = device_id_getter or _default_device_id
    token_getter = token_getter or _default_token

    repo = PaymentRepository(db_conn_factory)
    if offline:
        provider: PaymentProvider = NullProvider()
    else:
        cfg = settings_getter() or {}
        mode = str(cfg.get('mpesa_mode') or 'manual').strip().lower()
        # Cloud mode uses MugoByte Payments → Daraja. Manual keeps NullProvider
        # (cashier reference / offline fallback) while still using local till display.
        if mode not in ('cloud', 'stk', 'auto'):
            provider = NullProvider()
        else:
            base = str(cfg.get('payments_cloud_base_url') or DEFAULT_BASE_URL)
            client = PaymentsCloudClient(
                base,
                token_getter=token_getter,
                shop_id_getter=shop_id_getter,
                device_id_getter=device_id_getter,
                transport=cloud_transport,
            )
            provider = MpesaProvider(client)
    return PaymentService(
        repo,
        provider,
        shop_id_getter=shop_id_getter,
        device_id_getter=device_id_getter,
        create_sale=create_sale,
        settings_getter=settings_getter,
    )


def get_payment_service(**kwargs) -> PaymentService:
    global _service_singleton
    with _service_lock:
        if _service_singleton is None or kwargs:
            _service_singleton = build_payment_service(**kwargs)
        return _service_singleton


def _default_shop_id() -> str:
    try:
        from backend.cloud_backup.paths import load_identity
        ident = load_identity() or {}
        return str(ident.get('org_id') or ident.get('shop_id') or 'local')
    except Exception:
        return 'local'


def _default_device_id() -> str:
    try:
        from backend.cloud_backup.device_manager import get_or_create_device_id
        return get_or_create_device_id() or ''
    except Exception:
        return ''


def _default_token() -> str:
    try:
        from backend.cloud_backup.paths import load_identity
        ident = load_identity() or {}
        return str(ident.get('access_token') or '')
    except Exception:
        return ''
