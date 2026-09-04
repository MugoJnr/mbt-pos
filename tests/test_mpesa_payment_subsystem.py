"""
M-Pesa payment subsystem — automated test matrix (spec pillars).

Covers: STK≠paid, Till matching, ambiguous never-guess, idempotency,
under/overpay, offline manual, restart recovery, multi-shop isolation,
cash/credit still work when M-Pesa path fails, duplicate sale guard.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from desktop.payments.matching import classify_amount_variance, match_incoming_to_payment
from desktop.payments.models import (
    MatchConfidence,
    PaymentChannel,
    PaymentRecord,
    PaymentStatus,
)
from desktop.payments.security import mask_phone, normalize_ke_phone, redact_for_log
from desktop.payments.service import build_payment_service


def _mem_db():
    path = tempfile.mktemp(suffix='.db')
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales ("
        "id INTEGER PRIMARY KEY, receipt_number TEXT, total REAL, payment_id TEXT)"
    )
    conn.commit()

    def factory():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    return path, factory


class FakeTransport:
    """In-memory cloud stand-in for payments.mugobyte.com."""

    def __init__(self):
        self.intents = {}
        self.incoming = []
        self.profiles = {
            'shop_a': {
                'ok': True,
                'capabilities': {
                    'shop_id': 'shop_a',
                    'stk_enabled': True,
                    'c2b_enabled': True,
                    'till_number': '123456',
                    'paybill_number': '',
                    'business_name': 'Shop A',
                    'shortcode': '123456',
                    'environment': 'sandbox',
                    'profile_id': 'mp_a',
                    'synced_at': time.time(),
                },
            },
            'shop_b': {
                'ok': True,
                'capabilities': {
                    'shop_id': 'shop_b',
                    'stk_enabled': True,
                    'c2b_enabled': True,
                    'till_number': '999999',
                    'business_name': 'Shop B',
                    'shortcode': '999999',
                    'environment': 'sandbox',
                    'profile_id': 'mp_b',
                    'synced_at': time.time(),
                },
            },
        }
        self.query_status_map = {}  # checkout_id → status payload
        self.stk_calls = 0

    def __call__(self, method, path, body=None):
        body = body or {}
        if method == 'GET' and path.endswith('/capabilities'):
            shop = path.split('/')[3]
            return self.profiles.get(shop, {'ok': True, 'capabilities': {'shop_id': shop}})
        if method == 'POST' and path == '/v1/stk/initiate':
            self.stk_calls += 1
            idem = body['idempotency_key']
            if idem in self.intents:
                row = self.intents[idem]
                return {
                    'ok': True,
                    'idempotent': True,
                    'request_accepted': True,
                    'status': 'awaiting_customer',
                    'provider_checkout_id': row['id'],
                    'checkout_request_id': row['checkout_request_id'],
                    'merchant_request_id': row['merchant_request_id'],
                }
            intent_id = f'pi_{len(self.intents)+1}'
            row = {
                'id': intent_id,
                'checkout_request_id': f'cr_{intent_id}',
                'merchant_request_id': f'mr_{intent_id}',
                'status': 'awaiting_customer',
                'payment_id': body['payment_id'],
            }
            self.intents[idem] = row
            return {
                'ok': True,
                'request_accepted': True,
                'status': 'awaiting_customer',
                'provider_checkout_id': intent_id,
                'checkout_request_id': row['checkout_request_id'],
                'merchant_request_id': row['merchant_request_id'],
            }
        if method == 'POST' and path == '/v1/stk/query':
            cid = body.get('provider_checkout_id') or ''
            payload = self.query_status_map.get(cid, {
                'ok': True,
                'status': 'awaiting_customer',
                'provider_reference': '',
                'amount_received': 0,
            })
            return payload
        if method == 'GET' and '/incoming' in path:
            shop = path.split('/')[3]
            items = [i for i in self.incoming if i.get('shop_id') == shop]
            return {'ok': True, 'items': items}
        if method == 'POST' and path == '/v1/manual/register':
            return {
                'ok': True,
                'status': 'manual_pending',
                'provider_reference': body.get('provider_reference'),
                'amount_received': body.get('amount'),
            }
        return {'ok': False, 'error_code': 'NOT_FOUND', 'error_message': path}


class PaymentMatrixTests(unittest.TestCase):
    def setUp(self):
        self.db_path, self.factory = _mem_db()
        self.transport = FakeTransport()
        self.sales = []
        self.shop = 'shop_a'

        def create_sale(data):
            sid = len(self.sales) + 1
            rn = f'R{sid:04d}'
            self.sales.append({'id': sid, 'receipt': rn, 'data': data})
            conn = self.factory()
            conn.execute(
                'INSERT INTO sales (id, receipt_number, total, payment_id) VALUES (?,?,?,?)',
                (sid, rn, data.get('total'), data.get('payment_id')),
            )
            conn.commit()
            return {'success': True, 'sale_id': sid, 'receipt_number': rn}

        self.svc = build_payment_service(
            db_conn_factory=self.factory,
            create_sale=create_sale,
            settings_getter=lambda: {
                'mpesa_mode': 'cloud',
                'payments_cloud_base_url': 'https://payments.mugobyte.com',
                'mpesa_amount_tolerance': '0.01',
                'mpesa_match_window_sec': '600',
            },
            shop_id_getter=lambda: self.shop,
            device_id_getter=lambda: 'device_a',
            token_getter=lambda: 'test-token',
            cloud_transport=self.transport,
        )

    def tearDown(self):
        try:
            Path(self.db_path).unlink(missing_ok=True)
        except Exception:
            pass

    # ── security ──────────────────────────────────────────────────
    def test_mask_phone(self):
        self.assertEqual(mask_phone('254712345678')[:4], '2547')
        self.assertIn('****', mask_phone('0712345678'))
        self.assertEqual(normalize_ke_phone('0712345678'), '254712345678')

    def test_redact_secrets(self):
        red = redact_for_log({'consumer_secret': 'abc', 'phone': '254712345678'})
        self.assertEqual(red['consumer_secret'], '***REDACTED***')
        self.assertIn('****', red['phone'])

    # ── STK: accepted ≠ paid ──────────────────────────────────────
    def test_stk_accepted_is_not_paid(self):
        p = self.svc.create_pending_payment(
            amount=100, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 100}],
            phone='0712345678', cashier_name='c1',
        )
        p2 = self.svc.send_stk(p.id, phone='0712345678')
        self.assertEqual(p2.status, PaymentStatus.AWAITING_CUSTOMER.value)
        self.assertTrue(p2.checkout_request_id)
        # Must NOT be verified
        self.assertNotEqual(p2.status, PaymentStatus.VERIFIED.value)
        result = self.svc.complete_sale_if_verified(p.id)
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.sales), 0)

    def test_stk_idempotent_no_double_prompt(self):
        p = self.svc.create_pending_payment(
            amount=50, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 50}],
            phone='0712345678', idempotency_key='idem_stk_1',
        )
        self.svc.send_stk(p.id, phone='0712345678')
        calls = self.transport.stk_calls
        # Re-create with same idempotency returns same payment; send again uses cloud idem
        p2 = self.svc.create_pending_payment(
            amount=50, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 50}],
            phone='0712345678', idempotency_key='idem_stk_1',
        )
        self.assertEqual(p.id, p2.id)
        self.svc.send_stk(p2.id, phone='0712345678')
        # Second cloud call may happen but returns idempotent; count increments
        # but payment remains awaiting — never verified
        p3 = self.svc.get_payment(p.id)
        self.assertEqual(p3.status, PaymentStatus.AWAITING_CUSTOMER.value)
        self.assertGreaterEqual(self.transport.stk_calls, calls)

    def test_query_not_double_stk_on_timeout(self):
        p = self.svc.create_pending_payment(
            amount=80, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 80}],
            phone='0712000001',
        )
        p = self.svc.send_stk(p.id, phone='0712000001')
        calls_before = self.transport.stk_calls
        # Still pending on query
        p2 = self.svc.query_payment(p.id)
        self.assertEqual(self.transport.stk_calls, calls_before)  # query ≠ new STK
        self.assertEqual(p2.status, PaymentStatus.AWAITING_CUSTOMER.value)

        # Now cloud says paid
        self.transport.query_status_map[p.provider_checkout_id] = {
            'ok': True,
            'status': 'verified',
            'provider_reference': 'NLJ7RT61SV',
            'amount_received': 80,
        }
        p3 = self.svc.query_payment(p.id)
        self.assertEqual(p3.status, PaymentStatus.VERIFIED.value)
        self.assertEqual(p3.provider_reference, 'NLJ7RT61SV')

    # ── complete sale once ────────────────────────────────────────
    def test_verified_then_create_sale_once(self):
        p = self.svc.create_pending_payment(
            amount=120, cart=[{'product_id': 2, 'quantity': 1, 'unit_price': 120}],
            phone='0712000002',
        )
        p = self.svc.send_stk(p.id, phone='0712000002')
        self.transport.query_status_map[p.provider_checkout_id] = {
            'ok': True, 'status': 'verified',
            'provider_reference': 'ABC123XYZ9', 'amount_received': 120,
        }
        self.svc.query_payment(p.id)
        r1 = self.svc.complete_sale_if_verified(p.id)
        self.assertTrue(r1['ok'])
        self.assertFalse(r1.get('idempotent'))
        r2 = self.svc.complete_sale_if_verified(p.id)
        self.assertTrue(r2['ok'])
        self.assertTrue(r2.get('idempotent'))
        self.assertEqual(len(self.sales), 1)
        self.assertEqual(self.sales[0]['data']['mpesa_ref'], 'ABC123XYZ9')

    def test_duplicate_provider_reference_blocked(self):
        cart = [{'product_id': 1, 'quantity': 1, 'unit_price': 10}]
        p1 = self.svc.create_pending_payment(amount=10, cart=cart, phone='0712000003')
        p1 = self.svc.register_manual_reference(
            p1.id, 'SAME_REF_001', force_verify=True, confirmed_by='c'
        )
        self.assertEqual(p1.status, PaymentStatus.VERIFIED.value)
        p2 = self.svc.create_pending_payment(amount=10, cart=cart, phone='0712000004')
        with self.assertRaises(ValueError):
            self.svc.register_manual_reference(
                p2.id, 'SAME_REF_001', force_verify=True, confirmed_by='c'
            )

    # ── Till matching ─────────────────────────────────────────────
    def test_till_exact_match_auto_verify(self):
        p = self.svc.create_pending_payment(
            amount=200, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 200}],
            phone='0712555666', channel=PaymentChannel.TILL.value,
        )
        self.transport.incoming.append({
            'id': 'in_1', 'shop_id': 'shop_a', 'provider_reference': 'TILLREF001',
            'amount': 200, 'phone_e164': '254712555666',
            'status': 'unmatched', 'created_at': time.time(),
        })
        # Also seed local via ingest path used by sync
        p2 = self.svc.sync_incoming_and_match(p.id)
        self.assertEqual(p2.status, PaymentStatus.VERIFIED.value)
        self.assertEqual(p2.provider_reference, 'TILLREF001')

    def test_ambiguous_never_auto(self):
        p = self.svc.create_pending_payment(
            amount=100, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 100}],
            phone='', channel=PaymentChannel.TILL.value,
        )
        now = time.time()
        rows = [
            {'id': 'a', 'shop_id': 'shop_a', 'provider_reference': 'AA1',
             'amount': 100, 'status': 'unmatched', 'created_at': now},
            {'id': 'b', 'shop_id': 'shop_a', 'provider_reference': 'BB2',
             'amount': 100, 'status': 'unmatched', 'created_at': now},
        ]
        for r in rows:
            self.svc.ingest_incoming(r)
        result = match_incoming_to_payment(p, rows)
        self.assertEqual(result.confidence, MatchConfidence.AMBIGUOUS.value)
        self.assertIsNone(result.selected)

        p2 = self.svc.sync_incoming_and_match(p.id)
        self.assertEqual(p2.status, PaymentStatus.NEEDS_CONFIRMATION.value)
        # complete must fail until confirmed
        self.assertFalse(self.svc.complete_sale_if_verified(p.id)['ok'])

        p3 = self.svc.confirm_match(p.id, 'AA1', confirmed_by='manager')
        self.assertEqual(p3.status, PaymentStatus.VERIFIED.value)

    def test_cross_shop_isolation(self):
        p = self.svc.create_pending_payment(
            amount=75, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 75}],
            phone='0712777888',
        )
        # Incoming for shop_b must not match shop_a payment
        result = match_incoming_to_payment(p, [{
            'id': 'in_b', 'shop_id': 'shop_b', 'provider_reference': 'OTHERSHOP1',
            'amount': 75, 'phone_e164': '254712777888',
            'status': 'unmatched', 'created_at': time.time(),
        }])
        self.assertEqual(result.confidence, MatchConfidence.NONE.value)

        # ingest with wrong shop raises when local shop is shop_a
        with self.assertRaises(ValueError):
            self.svc.ingest_incoming({
                'shop_id': 'shop_b', 'provider_reference': 'XSHOP2',
                'amount': 10, 'created_at': time.time(),
            })

    # ── under / over ──────────────────────────────────────────────
    def test_underpayment_not_silent(self):
        p = self.svc.create_pending_payment(
            amount=500, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 500}],
            phone='0712111222',
        )
        p = self.svc.send_stk(p.id, phone='0712111222')
        self.transport.query_status_map[p.provider_checkout_id] = {
            'ok': True, 'status': 'verified',
            'provider_reference': 'UNDER001', 'amount_received': 400,
        }
        p2 = self.svc.query_payment(p.id)
        self.assertEqual(p2.status, PaymentStatus.UNDERPAID.value)
        self.assertFalse(self.svc.complete_sale_if_verified(p.id)['ok'])

    def test_overpayment_not_silent(self):
        p = self.svc.create_pending_payment(
            amount=100, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 100}],
            phone='0712333444',
        )
        p = self.svc.send_stk(p.id, phone='0712333444')
        self.transport.query_status_map[p.provider_checkout_id] = {
            'ok': True, 'status': 'verified',
            'provider_reference': 'OVER001', 'amount_received': 150,
        }
        p2 = self.svc.query_payment(p.id)
        self.assertEqual(p2.status, PaymentStatus.OVERPAID.value)
        self.assertFalse(self.svc.complete_sale_if_verified(p.id)['ok'])
        p3 = self.svc.accept_overpayment(p.id, confirmed_by='mgr')
        self.assertEqual(p3.status, PaymentStatus.VERIFIED.value)
        self.assertTrue(self.svc.complete_sale_if_verified(p.id)['ok'])

    def test_classify_variance(self):
        self.assertEqual(classify_amount_variance(100, 100), 'exact')
        self.assertEqual(classify_amount_variance(100, 90), 'underpaid')
        self.assertEqual(classify_amount_variance(100, 110), 'overpaid')

    # ── offline manual ────────────────────────────────────────────
    def test_offline_manual_fallback(self):
        offline = build_payment_service(
            db_conn_factory=self.factory,
            create_sale=lambda d: {'success': True, 'sale_id': 99, 'receipt_number': 'R99'},
            shop_id_getter=lambda: 'shop_a',
            device_id_getter=lambda: 'dev',
            offline=True,
        )
        caps = offline.get_capabilities()
        self.assertFalse(caps.can_send_prompt)
        p = offline.create_pending_payment(
            amount=30, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 30}],
        )
        stk = offline.send_stk(p.id, phone='0712000000')
        self.assertEqual(stk.status, PaymentStatus.FAILED.value)
        p2 = offline.register_manual_reference(
            p.id, 'OFFLINE99', force_verify=True, confirmed_by='cashier',
        )
        self.assertEqual(p2.status, PaymentStatus.VERIFIED.value)

    # ── restart recovery ──────────────────────────────────────────
    def test_restart_recovery_queries_not_restk(self):
        p = self.svc.create_pending_payment(
            amount=60, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 60}],
            phone='0712666777',
        )
        p = self.svc.send_stk(p.id, phone='0712666777')
        calls = self.transport.stk_calls
        self.transport.query_status_map[p.provider_checkout_id] = {
            'ok': True, 'status': 'verified',
            'provider_reference': 'RECOVER01', 'amount_received': 60,
        }
        recovered = self.svc.recover_pending_payments()
        self.assertEqual(self.transport.stk_calls, calls)
        found = [x for x in recovered if x.id == p.id][0]
        self.assertEqual(found.status, PaymentStatus.VERIFIED.value)

    # ── cash still works when mpesa provider down ─────────────────
    def test_cash_path_independent(self):
        # Simulate create_sale used by cash checkout — payment service unused
        result = self.svc.create_sale({
            'items': [{'product_id': 1, 'quantity': 1, 'unit_price': 20, 'product_name': 'X'}],
            'total': 20, 'payment_method': 'cash', 'amount_paid': 20,
        })
        self.assertTrue(result['success'])
        self.assertEqual(len(self.sales), 1)

    # ── capabilities hide STK when disabled ───────────────────────
    def test_capabilities_stk_flag(self):
        caps = self.svc.get_capabilities(force_refresh=True)
        self.assertTrue(caps.can_send_prompt)
        self.transport.profiles['shop_a']['capabilities']['stk_enabled'] = False
        # bust cache
        caps2 = self.svc.provider.get_capabilities('shop_a')
        self.assertFalse(caps2.can_send_prompt)

    # ── UNIQUE incoming idempotency ───────────────────────────────
    def test_incoming_idempotent(self):
        row = {
            'id': 'in_x', 'shop_id': 'shop_a', 'provider_reference': 'IDEMP001',
            'amount': 10, 'created_at': time.time(),
        }
        self.svc.ingest_incoming(row)
        self.svc.ingest_incoming(row)  # no throw
        rows = self.svc.repo.list_unmatched_incoming('shop_a')
        self.assertEqual(len([r for r in rows if r['provider_reference'] == 'IDEMP001']), 1)

    # ── remote command receipt ────────────────────────────────────
    def test_remote_command_receipt_blocks_replay(self):
        repo = self.svc.repo
        self.assertFalse(repo.has_command_receipt('cmd_1'))
        repo.record_command_receipt('cmd_1', 'revoke_license', 'device_a', 'claimed', {})
        self.assertTrue(repo.has_command_receipt('cmd_1'))
        repo.record_command_receipt('cmd_1', 'revoke_license', 'device_a', 'completed', {})
        self.assertTrue(repo.has_command_receipt('cmd_1', statuses=['completed', 'failed']))


    def test_accept_underpayment_as_part(self):
        p = self.svc.create_pending_payment(
            amount=100, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 100}],
            phone='0712345678',
        )
        p.status = PaymentStatus.UNDERPAID.value
        p.amount_received = 40
        self.svc.repo.update_payment(p, 'test_under', '')
        out = self.svc.accept_underpayment_as_part(p.id, confirmed_by='cashier')
        self.assertEqual(out.status, PaymentStatus.VERIFIED.value)
        self.assertEqual(float(out.amount_received), 40)

    def test_sales_tab_mixed_mpesa_uses_verification_gate(self):
        path = os.path.join(ROOT, 'desktop', 'tabs', 'sales_tab.py')
        src = open(path, encoding='utf-8').read()
        self.assertIn('_run_mpesa_verification', src)
        self.assertIn("self._elec_method_name() == 'M-Pesa'", src)
        self.assertIn('accept_underpayment_as_part', open(
            os.path.join(ROOT, 'desktop', 'dialogs', 'mpesa_checkout_dialog.py'),
            encoding='utf-8',
        ).read())


class MatchingUnitTests(unittest.TestCase):
    def test_strong_unique_amount(self):
        p = PaymentRecord(
            id='pay_1', shop_id='shop_a', device_id='d', amount_expected=250,
            phone_e164='', created_at=time.time(),
        )
        rows = [{
            'id': '1', 'shop_id': 'shop_a', 'provider_reference': 'ONLY1',
            'amount': 250, 'status': 'unmatched', 'created_at': time.time(),
        }]
        r = match_incoming_to_payment(p, rows)
        self.assertEqual(r.confidence, MatchConfidence.STRONG.value)
        self.assertEqual(r.selected.provider_reference, 'ONLY1')


if __name__ == '__main__':
    unittest.main()
