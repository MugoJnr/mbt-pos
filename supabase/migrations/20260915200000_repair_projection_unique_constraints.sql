-- Repair: restore the unique constraints the analytics projection upserts need.
--
-- WHY THIS IS MISSING
-- 20260401000000_cloud_analytics.sql declares uniqueness INLINE inside its
-- `create table if not exists public.cloud_* (... unique (org_id, device_id,
-- source_id))` statements. The cloud_* tables already existed from an earlier
-- schema, so every `create table if not exists` was a no-op and the inline
-- UNIQUE was silently skipped. Only the `id` primary keys exist today.
--
-- CONSEQUENCE
-- project_cloud_analytics_row() upserts with
--   on conflict (org_id, device_id, source_id) do update ...
-- ON CONFLICT can only infer a matching unique index, so every sale /
-- sale_item / product / customer / debt / stock projection fails with
--   42P10: there is no unique or exclusion constraint matching the
--          ON CONFLICT specification
-- The error propagates out of ingest_sync_batch, so the whole batch aborts and
-- the shop's outbox rows are retried forever. Restoring the functions in
-- 20260915190000 was necessary but not sufficient: entity types that do not
-- project (setting, user) succeeded while sales stayed stuck at 9 Sep.
--
-- PRE-CHECK (verified 2026-09-15 against the live Portal database)
--   duplicate (org_id, device_id, source_id) groups ....... 0 on all 7 tables
--   rows with device_id IS NULL ........................... 0 on all 7 tables
-- Existing rows already carry the correct device UUID, so these indexes match
-- history in place — the next projection UPDATES the existing row instead of
-- inserting a second copy. No sale is double counted.
--
-- A full (non-partial) unique index is required: ON CONFLICT cannot infer a
-- partial index unless the INSERT repeats its predicate, and the function's
-- INSERT has no WHERE clause.
--
-- Idempotent: `create unique index if not exists` only. Creates no tables,
-- drops nothing, deletes no rows, rewrites no function.
-- Index names match what the inline `unique (...)` would have produced.

begin;

create unique index if not exists cloud_sales_org_id_device_id_source_id_key
  on public.cloud_sales (org_id, device_id, source_id);

create unique index if not exists cloud_sale_items_org_id_device_id_source_id_key
  on public.cloud_sale_items (org_id, device_id, source_id);

create unique index if not exists cloud_products_org_id_device_id_source_id_key
  on public.cloud_products (org_id, device_id, source_id);

create unique index if not exists cloud_customers_org_id_device_id_source_id_key
  on public.cloud_customers (org_id, device_id, source_id);

create unique index if not exists cloud_debt_invoices_org_id_device_id_source_id_key
  on public.cloud_debt_invoices (org_id, device_id, source_id);

create unique index if not exists cloud_debt_payments_org_id_device_id_source_id_key
  on public.cloud_debt_payments (org_id, device_id, source_id);

create unique index if not exists cloud_stock_movements_org_id_device_id_source_id_key
  on public.cloud_stock_movements (org_id, device_id, source_id);

commit;
