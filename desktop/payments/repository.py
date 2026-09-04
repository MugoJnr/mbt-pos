"""SQLite persistence for mpesa_payments / incoming / events."""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, List, Optional

from desktop.payments.models import IncomingPayment, PaymentRecord
from desktop.payments.schema import ensure_payment_schema


class PaymentRepository:
    def __init__(self, conn_factory):
        """conn_factory: callable returning sqlite3.Connection (row_factory Row)."""
        self._conn_factory = conn_factory

    def _conn(self) -> sqlite3.Connection:
        conn = self._conn_factory()
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        ensure_payment_schema(conn)
        return conn

    def insert_payment(self, payment: PaymentRecord) -> PaymentRecord:
        conn = self._conn()
        cols = list(payment.to_dict().keys())
        placeholders = ','.join('?' for _ in cols)
        conn.execute(
            f"INSERT INTO mpesa_payments ({','.join(cols)}) VALUES ({placeholders})",
            [getattr(payment, c) for c in cols],
        )
        self._event(conn, payment.id, 'created', f'status={payment.status}', payment.cashier_name)
        conn.commit()
        return payment

    def update_payment(self, payment: PaymentRecord, event: str = '', detail: str = '') -> PaymentRecord:
        payment.updated_at = time.time()
        conn = self._conn()
        data = payment.to_dict()
        sets = ', '.join(f'{k}=?' for k in data if k != 'id')
        vals = [data[k] for k in data if k != 'id'] + [payment.id]
        conn.execute(f'UPDATE mpesa_payments SET {sets} WHERE id=?', vals)
        if event:
            self._event(conn, payment.id, event, detail, payment.cashier_name)
        conn.commit()
        return payment

    def get_payment(self, payment_id: str) -> Optional[PaymentRecord]:
        conn = self._conn()
        row = conn.execute(
            'SELECT * FROM mpesa_payments WHERE id=?', (payment_id,)
        ).fetchone()
        return PaymentRecord.from_row(row) if row else None

    def get_by_provider_reference(self, provider_reference: str) -> Optional[PaymentRecord]:
        ref = (provider_reference or '').strip().upper()
        if not ref:
            return None
        conn = self._conn()
        row = conn.execute(
            'SELECT * FROM mpesa_payments WHERE upper(provider_reference)=?', (ref,)
        ).fetchone()
        return PaymentRecord.from_row(row) if row else None

    def get_by_idempotency(self, key: str) -> Optional[PaymentRecord]:
        if not key:
            return None
        conn = self._conn()
        row = conn.execute(
            'SELECT * FROM mpesa_payments WHERE idempotency_key=?', (key,)
        ).fetchone()
        return PaymentRecord.from_row(row) if row else None

    def list_by_status(self, statuses: List[str], shop_id: str = '') -> List[PaymentRecord]:
        conn = self._conn()
        if not statuses:
            return []
        placeholders = ','.join('?' for _ in statuses)
        sql = f'SELECT * FROM mpesa_payments WHERE status IN ({placeholders})'
        params: list[Any] = list(statuses)
        if shop_id:
            sql += ' AND shop_id=?'
            params.append(shop_id)
        sql += ' ORDER BY created_at DESC'
        return [PaymentRecord.from_row(r) for r in conn.execute(sql, params).fetchall()]

    def list_inbox(self, shop_id: str, limit: int = 100) -> List[dict]:
        """Unmatched incoming + payments needing confirmation."""
        conn = self._conn()
        incoming = conn.execute(
            "SELECT * FROM mpesa_incoming WHERE shop_id=? AND status='unmatched' "
            "ORDER BY created_at DESC LIMIT ?",
            (shop_id, limit),
        ).fetchall()
        needs = conn.execute(
            "SELECT * FROM mpesa_payments WHERE shop_id=? AND status IN "
            "('needs_confirmation','underpaid','overpaid','matched','manual_pending') "
            "ORDER BY updated_at DESC LIMIT ?",
            (shop_id, limit),
        ).fetchall()
        return {
            'incoming': [dict(r) for r in incoming],
            'payments': [dict(r) for r in needs],
        }

    def upsert_incoming(self, row: IncomingPayment) -> IncomingPayment:
        conn = self._conn()
        existing = conn.execute(
            'SELECT id FROM mpesa_incoming WHERE shop_id=? AND provider_reference=?',
            (row.shop_id, row.provider_reference),
        ).fetchone()
        if existing:
            return row  # idempotent — UNIQUE provider_reference
        cols = list(row.to_dict().keys())
        conn.execute(
            f"INSERT INTO mpesa_incoming ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            [getattr(row, c) for c in cols],
        )
        conn.commit()
        return row

    def mark_incoming_matched(self, incoming_id: str, payment_id: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE mpesa_incoming SET status='matched', matched_payment_id=? WHERE id=?",
            (payment_id, incoming_id),
        )
        conn.commit()

    def list_unmatched_incoming(self, shop_id: str, since_ts: float = 0.0) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM mpesa_incoming WHERE shop_id=? AND status='unmatched' "
            "AND created_at>=? ORDER BY created_at DESC",
            (shop_id, since_ts),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_merchant_cache(self, caps) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO mpesa_merchant_cache
            (shop_id, profile_id, stk_enabled, c2b_enabled, till_number, paybill_number,
             business_name, shortcode, environment, account_reference_label,
             capabilities_json, synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(shop_id) DO UPDATE SET
             profile_id=excluded.profile_id,
             stk_enabled=excluded.stk_enabled,
             c2b_enabled=excluded.c2b_enabled,
             till_number=excluded.till_number,
             paybill_number=excluded.paybill_number,
             business_name=excluded.business_name,
             shortcode=excluded.shortcode,
             environment=excluded.environment,
             account_reference_label=excluded.account_reference_label,
             capabilities_json=excluded.capabilities_json,
             synced_at=excluded.synced_at
            """,
            (
                caps.shop_id, caps.profile_id, int(caps.stk_enabled), int(caps.c2b_enabled),
                caps.till_number, caps.paybill_number, caps.business_name, caps.shortcode,
                caps.environment, caps.account_reference_label,
                json.dumps(caps.to_dict()), caps.synced_at,
            ),
        )
        conn.commit()

    def load_merchant_cache(self, shop_id: str):
        from desktop.payments.models import MerchantCapabilities
        conn = self._conn()
        row = conn.execute(
            'SELECT * FROM mpesa_merchant_cache WHERE shop_id=?', (shop_id,)
        ).fetchone()
        if not row:
            return None
        return MerchantCapabilities(
            shop_id=row['shop_id'],
            stk_enabled=bool(row['stk_enabled']),
            c2b_enabled=bool(row['c2b_enabled']),
            till_number=row['till_number'] or '',
            paybill_number=row['paybill_number'] or '',
            business_name=row['business_name'] or '',
            shortcode=row['shortcode'] or '',
            environment=row['environment'] or 'sandbox',
            account_reference_label=row['account_reference_label'] or 'Invoice',
            profile_id=row['profile_id'] or '',
            synced_at=float(row['synced_at'] or 0),
        )

    def _event(self, conn, payment_id: str, event_type: str, detail: str, actor: str) -> None:
        conn.execute(
            'INSERT INTO mpesa_payment_events (payment_id, event_type, detail, actor, created_at) '
            'VALUES (?,?,?,?,?)',
            (payment_id, event_type, detail or '', actor or '', time.time()),
        )

    def has_command_receipt(self, command_id: str, *, statuses: list | None = None) -> bool:
        conn = self._conn()
        if statuses:
            placeholders = ','.join('?' for _ in statuses)
            row = conn.execute(
                f'SELECT 1 FROM remote_command_receipts WHERE command_id=? '
                f'AND status IN ({placeholders})',
                [command_id, *statuses],
            ).fetchone()
        else:
            row = conn.execute(
                'SELECT 1 FROM remote_command_receipts WHERE command_id=?', (command_id,)
            ).fetchone()
        return bool(row)

    def get_command_receipt(self, command_id: str):
        conn = self._conn()
        row = conn.execute(
            'SELECT * FROM remote_command_receipts WHERE command_id=?', (command_id,)
        ).fetchone()
        return dict(row) if row else None

    def record_command_receipt(
        self, command_id: str, command: str, device_id: str, status: str, result: dict | None = None
    ) -> None:
        """Durable receipt BEFORE destructive effects should already exist;
        this upserts completion state."""
        import json as _json
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO remote_command_receipts
            (command_id, command, device_id, status, result_json, executed_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(command_id) DO UPDATE SET
              status=excluded.status,
              result_json=excluded.result_json,
              executed_at=excluded.executed_at
            """,
            (
                command_id, command, device_id or '', status,
                _json.dumps(result or {}), time.time(),
            ),
        )
        conn.commit()
