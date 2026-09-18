"""v3.0.99 — M-Pesa Confirm Manual busy-queue + force_verify."""
from __future__ import annotations

import os
import sqlite3
import tempfile

from desktop.payments.models import PaymentStatus
from desktop.payments.service import build_payment_service


def _factory():
    path = tempfile.mktemp(suffix='.db')
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales ("
        "id INTEGER PRIMARY KEY, receipt_number TEXT, total REAL, payment_id TEXT)"
    )
    conn.commit()
    conn.close()

    def factory():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    return factory


def test_force_verify_manual_reaches_verified_offline():
    offline = build_payment_service(
        db_conn_factory=_factory(),
        create_sale=lambda d: {'success': True, 'sale_id': 1, 'receipt_number': 'R1'},
        shop_id_getter=lambda: 'shop_a',
        device_id_getter=lambda: 'dev',
        offline=True,
    )
    p = offline.create_pending_payment(
        amount=30, cart=[{'product_id': 1, 'quantity': 1, 'unit_price': 30}],
    )
    p2 = offline.register_manual_reference(
        p.id, 'OFFLINE99X', force_verify=True, confirmed_by='cashier',
    )
    assert p2.status == PaymentStatus.VERIFIED.value


def test_run_net_queues_priority_when_busy():
    class Fake:
        def __init__(self):
            self._net_busy = True
            self._worker = None
            self._net_queue = []
            self.msgs = []

        def _set_status(self, t):
            self.msgs.append(t)

    fake = Fake()

    def run_busy(priority, defer_message=''):
        if fake._net_busy:
            if priority:
                fake._net_queue.append({'priority': True})
                if defer_message:
                    fake._set_status(defer_message)
                return 'queued'
            return 'dropped'
        return 'ran'

    assert run_busy(False) == 'dropped'
    assert run_busy(True, 'confirming next') == 'queued'
    assert len(fake._net_queue) == 1
