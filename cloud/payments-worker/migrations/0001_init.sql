-- MugoByte Payments D1 schema (sandbox → production)
CREATE TABLE IF NOT EXISTS merchant_profiles (
  id TEXT PRIMARY KEY,
  shop_id TEXT NOT NULL UNIQUE,
  business_name TEXT NOT NULL DEFAULT '',
  shortcode TEXT NOT NULL DEFAULT '',
  till_number TEXT NOT NULL DEFAULT '',
  paybill_number TEXT NOT NULL DEFAULT '',
  stk_enabled INTEGER NOT NULL DEFAULT 0,
  c2b_enabled INTEGER NOT NULL DEFAULT 0,
  environment TEXT NOT NULL DEFAULT 'sandbox',
  account_reference_label TEXT NOT NULL DEFAULT 'Invoice',
  -- Secrets NEVER returned to POS: stored encrypted / via wrangler secrets per env
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_intents (
  id TEXT PRIMARY KEY,
  shop_id TEXT NOT NULL,
  device_id TEXT NOT NULL DEFAULT '',
  pos_payment_id TEXT NOT NULL,
  amount REAL NOT NULL,
  phone_masked TEXT NOT NULL DEFAULT '',
  account_reference TEXT NOT NULL DEFAULT '',
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'submitted',
  checkout_request_id TEXT NOT NULL DEFAULT '',
  merchant_request_id TEXT NOT NULL DEFAULT '',
  provider_reference TEXT,
  amount_received REAL NOT NULL DEFAULT 0,
  result_code TEXT NOT NULL DEFAULT '',
  result_desc TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_intents_idem
  ON payment_intents(shop_id, idempotency_key);

CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_intents_provider_ref
  ON payment_intents(provider_reference)
  WHERE provider_reference IS NOT NULL AND provider_reference != '';

CREATE TABLE IF NOT EXISTS incoming_payments (
  id TEXT PRIMARY KEY,
  shop_id TEXT NOT NULL,
  provider_reference TEXT NOT NULL,
  amount REAL NOT NULL,
  phone_masked TEXT NOT NULL DEFAULT '',
  till_number TEXT NOT NULL DEFAULT '',
  paybill_number TEXT NOT NULL DEFAULT '',
  bill_ref TEXT NOT NULL DEFAULT '',
  trans_time TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'unmatched',
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_incoming_shop_ref
  ON incoming_payments(shop_id, provider_reference);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  shop_id TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
