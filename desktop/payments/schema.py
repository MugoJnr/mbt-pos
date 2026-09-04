"""Additive payment schema migrations — never wipe mbt_pos.db."""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger('payments.schema')

PAYMENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mpesa_payments (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT '',
    amount_expected REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KES',
    status TEXT NOT NULL DEFAULT 'draft',
    channel TEXT NOT NULL DEFAULT 'stk',
    phone_masked TEXT NOT NULL DEFAULT '',
    phone_e164 TEXT NOT NULL DEFAULT '',
    customer_name TEXT NOT NULL DEFAULT '',
    cart_fingerprint TEXT NOT NULL DEFAULT '',
    cart_json TEXT NOT NULL DEFAULT '',
    sale_id INTEGER,
    receipt_number TEXT,
    provider_checkout_id TEXT NOT NULL DEFAULT '',
    provider_reference TEXT,
    merchant_request_id TEXT NOT NULL DEFAULT '',
    checkout_request_id TEXT NOT NULL DEFAULT '',
    till_number TEXT NOT NULL DEFAULT '',
    paybill_number TEXT NOT NULL DEFAULT '',
    account_reference TEXT NOT NULL DEFAULT '',
    amount_received REAL NOT NULL DEFAULT 0,
    variance REAL NOT NULL DEFAULT 0,
    match_confidence TEXT NOT NULL DEFAULT 'none',
    match_candidates_json TEXT NOT NULL DEFAULT '[]',
    idempotency_key TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    cashier_id INTEGER,
    cashier_name TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    verified_at REAL NOT NULL DEFAULT 0,
    completed_at REAL NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_mpesa_payments_provider_reference
    ON mpesa_payments(provider_reference)
    WHERE provider_reference IS NOT NULL AND provider_reference != '';

CREATE UNIQUE INDEX IF NOT EXISTS ux_mpesa_payments_idempotency
    ON mpesa_payments(idempotency_key)
    WHERE idempotency_key IS NOT NULL AND idempotency_key != '';

CREATE INDEX IF NOT EXISTS ix_mpesa_payments_status
    ON mpesa_payments(status);

CREATE INDEX IF NOT EXISTS ix_mpesa_payments_shop_created
    ON mpesa_payments(shop_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_mpesa_payments_sale
    ON mpesa_payments(sale_id);

CREATE TABLE IF NOT EXISTS mpesa_incoming (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    provider_reference TEXT NOT NULL,
    amount REAL NOT NULL,
    phone_masked TEXT NOT NULL DEFAULT '',
    phone_e164 TEXT NOT NULL DEFAULT '',
    till_number TEXT NOT NULL DEFAULT '',
    paybill_number TEXT NOT NULL DEFAULT '',
    bill_ref TEXT NOT NULL DEFAULT '',
    trans_time TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    matched_payment_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unmatched',
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_mpesa_incoming_provider_reference
    ON mpesa_incoming(shop_id, provider_reference);

CREATE INDEX IF NOT EXISTS ix_mpesa_incoming_unmatched
    ON mpesa_incoming(shop_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS mpesa_payment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_mpesa_payment_events_payment
    ON mpesa_payment_events(payment_id, created_at);

CREATE TABLE IF NOT EXISTS mpesa_merchant_cache (
    shop_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT '',
    stk_enabled INTEGER NOT NULL DEFAULT 0,
    c2b_enabled INTEGER NOT NULL DEFAULT 0,
    till_number TEXT NOT NULL DEFAULT '',
    paybill_number TEXT NOT NULL DEFAULT '',
    business_name TEXT NOT NULL DEFAULT '',
    shortcode TEXT NOT NULL DEFAULT '',
    environment TEXT NOT NULL DEFAULT 'sandbox',
    account_reference_label TEXT NOT NULL DEFAULT 'Invoice',
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    synced_at REAL NOT NULL DEFAULT 0
);

-- Durable local receipts for remote cloud commands (licensing safety).
CREATE TABLE IF NOT EXISTS remote_command_receipts (
    command_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    device_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    executed_at REAL NOT NULL
);
"""


def ensure_payment_schema(conn: sqlite3.Connection) -> None:
    """Apply additive payment tables/indexes. Safe to call repeatedly."""
    try:
        conn.executescript(PAYMENT_SCHEMA_SQL)
        # Link sales → payment when present (additive column only)
        sales_cols = {r[1] for r in conn.execute('PRAGMA table_info(sales)').fetchall()}
        if 'payment_id' not in sales_cols:
            conn.execute('ALTER TABLE sales ADD COLUMN payment_id TEXT')
        # Settings keys for cloud payments (seed if missing; keep cloud URL fresh)
        for key, value in (
            ('payments_cloud_base_url', 'https://payments.mugobyte.com'),
            ('payments_environment', 'sandbox'),
            ('mpesa_stk_timeout_sec', '90'),
            ('mpesa_match_window_sec', '600'),
            ('mpesa_amount_tolerance', '0.01'),
            ('mpesa_auto_complete_exact', '1'),
            ('mpesa_require_confirm_ambiguous', '1'),
        ):
            exists = conn.execute(
                "SELECT 1 FROM system_settings WHERE key=?", (key,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO system_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            elif key == 'payments_cloud_base_url':
                # Always keep canonical payments host (never leave blank/stale).
                cur = conn.execute(
                    "SELECT value FROM system_settings WHERE key=?", (key,)
                ).fetchone()
                if not (cur and str(cur[0] or '').strip()):
                    conn.execute(
                        "UPDATE system_settings SET value=? WHERE key=?",
                        (value, key),
                    )
        # Prefer cloud collection when mode unset; do not clobber an explicit manual choice.
        mode_row = conn.execute(
            "SELECT value FROM system_settings WHERE key='mpesa_mode'"
        ).fetchone()
        if not mode_row:
            conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ('mpesa_mode', 'cloud')"
            )
        conn.commit()
    except Exception:
        logger.exception('ensure_payment_schema failed')
        raise
