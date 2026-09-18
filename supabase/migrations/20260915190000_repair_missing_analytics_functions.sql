-- MBT Portal repair: restore the analytics functions that never landed.
--
-- Verified against mxfvbylmlynotvghnzqg on 2026-09-15 with the anon key:
--   cloud_sales / cloud_sale_items / cloud_products / cloud_customers /
--   cloud_debt_invoices / cloud_debt_payments / cloud_stock_movements   EXIST
--   _cloud_ts / _cloud_num / _cloud_text / _cloud_bool                  MISSING
--   project_cloud_analytics_row                                        MISSING
--   ingest_sync_batch                                                  MISSING (404 PGRST202)
--   uq_sync_entities_org_device_type_source                            MISSING (42P10)
--
-- So 20260401000000_cloud_analytics.sql applied its tables but not its
-- dollar-quoted function bodies -- the signature of a migration runner that
-- splits statements on ';'. Without ingest_sync_batch every POS analytics
-- push fails, which is why Portal > Reports shows KES 0.00 and 0 transactions.
--
-- Run this in the Supabase SQL Editor (it handles \$\$ bodies correctly).
-- Idempotent: create index if not exists + create or replace function only.
-- Creates no tables, drops nothing, deletes no rows.
--
-- PRE-CHECK -- the unique index below cannot be created while duplicates exist.
-- Run this first; it must return no rows:
--
--   select org_id, device_id, entity_type, source_id, count(*)
--   from public.sync_entities
--   where device_id is not null
--   group by 1,2,3,4 having count(*) > 1;
--
-- If it returns rows, stop and resolve them before running this script.

begin;

-- ── Section 1 leftover: device-safe uniqueness for sync_entities ─────────────
-- ingest_sync_batch relies on this exact ON CONFLICT target.
-- New uniqueness includes device_id. Partial index skips unrepaired nulls.
create unique index if not exists uq_sync_entities_org_device_type_source
  on public.sync_entities(org_id, device_id, entity_type, source_id)
  where device_id is not null;

create index if not exists idx_sync_entities_org_device_type
  on public.sync_entities(org_id, device_id, entity_type, source_updated_at desc);

alter table public.cloud_sales
  add column if not exists electronic_method text,
  add column if not exists cash_paid numeric(14,2) not null default 0,
  add column if not exists payment_tenders text;

-- ── 3) Projection helpers ────────────────────────────────────────────────────
create or replace function public._cloud_ts(p jsonb, p_key text)
returns timestamptz
language sql
immutable
as $$
  select nullif(p ->> p_key, '')::timestamptz;
$$;

-- POS sales.created_at is a naive Africa/Nairobi wall clock. Postgres
-- ::timestamptz would otherwise treat that string as UTC (+3h in the Portal).
-- Explicit offsets / Z are honoured as written. Other entity types keep _cloud_ts.
create or replace function public._cloud_shop_ts(p jsonb, p_key text)
returns timestamptz
language sql
stable
as $$
  select case
    when nullif(btrim(p ->> p_key), '') is null then null::timestamptz
    when btrim(p ->> p_key) ~* '(Z|[+-][0-9]{2}(:?[0-9]{2})?)$'
      then btrim(p ->> p_key)::timestamptz
    else (btrim(p ->> p_key)::timestamp at time zone 'Africa/Nairobi')
  end;
$$;

create or replace function public._cloud_num(p jsonb, p_key text, p_default numeric default 0)
returns numeric
language sql
immutable
as $$
  select coalesce(nullif(p ->> p_key, '')::numeric, p_default);
$$;

create or replace function public._cloud_text(p jsonb, p_key text)
returns text
language sql
immutable
as $$
  select nullif(p ->> p_key, '');
$$;

create or replace function public._cloud_bool(p jsonb, p_key text, p_default boolean default true)
returns boolean
language sql
immutable
as $$
  select case
    when lower(coalesce(p ->> p_key, '')) in ('1', 'true', 't', 'yes', 'y') then true
    when lower(coalesce(p ->> p_key, '')) in ('0', 'false', 'f', 'no', 'n') then false
    else p_default
  end;
$$;

create or replace function public.project_cloud_analytics_row(
  p_org_id uuid,
  p_device_id uuid,
  p_branch_id uuid,
  p_entity_type text,
  p_source_id text,
  p_payload jsonb,
  p_deleted boolean,
  p_source_updated_at timestamptz
)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_payload jsonb := coalesce(p_payload, '{}'::jsonb);
  v_deleted boolean := coalesce(p_deleted, false);
  v_created timestamptz;
  v_updated timestamptz;
begin
  v_created := coalesce(
    public._cloud_ts(v_payload, 'created_at'),
    p_source_updated_at
  );
  v_updated := coalesce(
    public._cloud_ts(v_payload, 'updated_at'),
    p_source_updated_at,
    v_created
  );
  if p_entity_type = 'sale' then
    v_created := coalesce(
      public._cloud_shop_ts(v_payload, 'created_at'),
      p_source_updated_at
    );
  end if;

  if p_entity_type = 'sale' then
    insert into public.cloud_sales(
      org_id, device_id, branch_id, source_id, receipt_number, cashier_id,
      cashier_name, customer_source_id, subtotal, discount, tax, total,
      amount_paid, change_amount, credit_applied, electronic_paid,
      electronic_method, cash_paid, payment_tenders,
      original_total, cash_rounding_adj, payment_method, status,
      variance_handling, source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'receipt_number'),
      public._cloud_text(v_payload, 'cashier_id'),
      public._cloud_text(v_payload, 'cashier_name'),
      public._cloud_text(v_payload, 'customer_id'),
      public._cloud_num(v_payload, 'subtotal'),
      public._cloud_num(v_payload, 'discount'),
      public._cloud_num(v_payload, 'tax'),
      public._cloud_num(v_payload, 'total'),
      public._cloud_num(v_payload, 'amount_paid'),
      public._cloud_num(v_payload, 'change_amount'),
      public._cloud_num(v_payload, 'credit_applied'),
      public._cloud_num(v_payload, 'electronic_paid'),
      public._cloud_text(v_payload, 'electronic_method'),
      public._cloud_num(v_payload, 'cash_paid'),
      public._cloud_text(v_payload, 'payment_tenders'),
      nullif(v_payload ->> 'original_total', '')::numeric,
      public._cloud_num(v_payload, 'cash_rounding_adj'),
      public._cloud_text(v_payload, 'payment_method'),
      coalesce(public._cloud_text(v_payload, 'status'), 'completed'),
      public._cloud_text(v_payload, 'variance_handling'),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      receipt_number = excluded.receipt_number,
      cashier_id = excluded.cashier_id,
      cashier_name = excluded.cashier_name,
      customer_source_id = excluded.customer_source_id,
      subtotal = excluded.subtotal,
      discount = excluded.discount,
      tax = excluded.tax,
      total = excluded.total,
      amount_paid = excluded.amount_paid,
      change_amount = excluded.change_amount,
      credit_applied = excluded.credit_applied,
      electronic_paid = excluded.electronic_paid,
      electronic_method = excluded.electronic_method,
      cash_paid = excluded.cash_paid,
      payment_tenders = excluded.payment_tenders,
      original_total = excluded.original_total,
      cash_rounding_adj = excluded.cash_rounding_adj,
      payment_method = excluded.payment_method,
      status = excluded.status,
      variance_handling = excluded.variance_handling,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();

  elsif p_entity_type = 'sale_item' then
    insert into public.cloud_sale_items(
      org_id, device_id, branch_id, source_id, sale_source_id, product_source_id,
      product_name, sku, category, quantity, unit_price, unit_cost, discount,
      total, source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'sale_id'),
      public._cloud_text(v_payload, 'product_id'),
      public._cloud_text(v_payload, 'product_name'),
      public._cloud_text(v_payload, 'sku'),
      public._cloud_text(v_payload, 'category'),
      public._cloud_num(v_payload, 'quantity'),
      public._cloud_num(v_payload, 'unit_price'),
      nullif(v_payload ->> 'unit_cost', '')::numeric,
      public._cloud_num(v_payload, 'discount'),
      public._cloud_num(v_payload, 'total'),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      sale_source_id = excluded.sale_source_id,
      product_source_id = excluded.product_source_id,
      product_name = excluded.product_name,
      sku = excluded.sku,
      category = excluded.category,
      quantity = excluded.quantity,
      unit_price = excluded.unit_price,
      unit_cost = excluded.unit_cost,
      discount = excluded.discount,
      total = excluded.total,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();

  elsif p_entity_type = 'product' then
    insert into public.cloud_products(
      org_id, device_id, branch_id, source_id, name, sku, category, price,
      cost_price, stock, min_stock, unit, barcode, is_active,
      source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'name'),
      public._cloud_text(v_payload, 'sku'),
      public._cloud_text(v_payload, 'category'),
      public._cloud_num(v_payload, 'price'),
      public._cloud_num(v_payload, 'cost_price'),
      public._cloud_num(v_payload, 'stock'),
      public._cloud_num(v_payload, 'min_stock'),
      public._cloud_text(v_payload, 'unit'),
      public._cloud_text(v_payload, 'barcode'),
      public._cloud_bool(v_payload, 'is_active', true),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      name = excluded.name,
      sku = excluded.sku,
      category = excluded.category,
      price = excluded.price,
      cost_price = excluded.cost_price,
      stock = excluded.stock,
      min_stock = excluded.min_stock,
      unit = excluded.unit,
      barcode = excluded.barcode,
      is_active = excluded.is_active,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();

  elsif p_entity_type = 'customer' then
    insert into public.cloud_customers(
      org_id, device_id, branch_id, source_id, name, phone, email, credit_limit,
      customer_type, is_active, source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'name'),
      public._cloud_text(v_payload, 'phone'),
      public._cloud_text(v_payload, 'email'),
      public._cloud_num(v_payload, 'credit_limit'),
      public._cloud_text(v_payload, 'customer_type'),
      public._cloud_bool(v_payload, 'is_active', true),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      name = excluded.name,
      phone = excluded.phone,
      email = excluded.email,
      credit_limit = excluded.credit_limit,
      customer_type = excluded.customer_type,
      is_active = excluded.is_active,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();

  elsif p_entity_type = 'debt_invoice' then
    insert into public.cloud_debt_invoices(
      org_id, device_id, branch_id, source_id, invoice_number, sale_source_id,
      receipt_number, customer_source_id, customer_name, customer_phone,
      total_amount, amount_paid, balance, status, due_date, cashier_id,
      cashier_name, source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'invoice_number'),
      public._cloud_text(v_payload, 'sale_id'),
      public._cloud_text(v_payload, 'receipt_number'),
      public._cloud_text(v_payload, 'customer_id'),
      public._cloud_text(v_payload, 'customer_name'),
      public._cloud_text(v_payload, 'customer_phone'),
      public._cloud_num(v_payload, 'total_amount'),
      public._cloud_num(v_payload, 'amount_paid'),
      public._cloud_num(v_payload, 'balance'),
      coalesce(public._cloud_text(v_payload, 'status'), 'pending'),
      nullif(v_payload ->> 'due_date', '')::date,
      public._cloud_text(v_payload, 'cashier_id'),
      public._cloud_text(v_payload, 'cashier_name'),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      invoice_number = excluded.invoice_number,
      sale_source_id = excluded.sale_source_id,
      receipt_number = excluded.receipt_number,
      customer_source_id = excluded.customer_source_id,
      customer_name = excluded.customer_name,
      customer_phone = excluded.customer_phone,
      total_amount = excluded.total_amount,
      amount_paid = excluded.amount_paid,
      balance = excluded.balance,
      status = excluded.status,
      due_date = excluded.due_date,
      cashier_id = excluded.cashier_id,
      cashier_name = excluded.cashier_name,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();

  elsif p_entity_type = 'debt_payment' then
    insert into public.cloud_debt_payments(
      org_id, device_id, branch_id, source_id, payment_receipt, invoice_source_id,
      customer_source_id, amount, payment_method, balance_before, balance_after,
      cashier_id, cashier_name, source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'payment_receipt'),
      public._cloud_text(v_payload, 'invoice_id'),
      public._cloud_text(v_payload, 'customer_id'),
      public._cloud_num(v_payload, 'amount'),
      public._cloud_text(v_payload, 'payment_method'),
      public._cloud_num(v_payload, 'balance_before'),
      public._cloud_num(v_payload, 'balance_after'),
      public._cloud_text(v_payload, 'cashier_id'),
      public._cloud_text(v_payload, 'cashier_name'),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      payment_receipt = excluded.payment_receipt,
      invoice_source_id = excluded.invoice_source_id,
      customer_source_id = excluded.customer_source_id,
      amount = excluded.amount,
      payment_method = excluded.payment_method,
      balance_before = excluded.balance_before,
      balance_after = excluded.balance_after,
      cashier_id = excluded.cashier_id,
      cashier_name = excluded.cashier_name,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();

  elsif p_entity_type = 'stock_movement' then
    insert into public.cloud_stock_movements(
      org_id, device_id, branch_id, source_id, product_source_id, product_name,
      movement_type, qty_before, qty_change, qty_after, reference, reason,
      user_id, username, source_created_at, source_updated_at, deleted, synced_at
    ) values (
      p_org_id, p_device_id, p_branch_id, p_source_id,
      public._cloud_text(v_payload, 'product_id'),
      public._cloud_text(v_payload, 'product_name'),
      public._cloud_text(v_payload, 'movement_type'),
      public._cloud_num(v_payload, 'qty_before'),
      public._cloud_num(v_payload, 'qty_change'),
      public._cloud_num(v_payload, 'qty_after'),
      public._cloud_text(v_payload, 'reference'),
      public._cloud_text(v_payload, 'reason'),
      public._cloud_text(v_payload, 'user_id'),
      public._cloud_text(v_payload, 'username'),
      v_created, v_updated, v_deleted, now()
    )
    on conflict (org_id, device_id, source_id) do update set
      branch_id = excluded.branch_id,
      product_source_id = excluded.product_source_id,
      product_name = excluded.product_name,
      movement_type = excluded.movement_type,
      qty_before = excluded.qty_before,
      qty_change = excluded.qty_change,
      qty_after = excluded.qty_after,
      reference = excluded.reference,
      reason = excluded.reason,
      user_id = excluded.user_id,
      username = excluded.username,
      source_created_at = excluded.source_created_at,
      source_updated_at = excluded.source_updated_at,
      deleted = excluded.deleted,
      synced_at = now();
  end if;
end;
$$;

revoke all on function public.project_cloud_analytics_row(
  uuid, uuid, uuid, text, text, jsonb, boolean, timestamptz
) from public;
grant execute on function public.project_cloud_analytics_row(
  uuid, uuid, uuid, text, text, jsonb, boolean, timestamptz
) to service_role;

-- ── 4) ingest_sync_batch: device-safe upsert + transactional projection ──────
create or replace function public.ingest_sync_batch(
  p_org_id uuid,
  p_device_id uuid,
  p_idempotency_key text,
  p_entities jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_batch_id uuid;
  v_count integer := 0;
  v_row record;
  v_touched integer;
begin
  if p_org_id is null or p_device_id is null then
    raise exception 'org_id and device_id are required';
  end if;
  if p_idempotency_key is null or length(p_idempotency_key) < 8 then
    raise exception 'invalid idempotency key';
  end if;
  if jsonb_typeof(p_entities) <> 'array' or jsonb_array_length(p_entities) > 500 then
    raise exception 'entities must be an array of at most 500 items';
  end if;

  insert into public.sync_batches(
    org_id, device_id, idempotency_key, entity_count, status
  ) values (
    p_org_id, p_device_id, p_idempotency_key, jsonb_array_length(p_entities), 'processing'
  )
  on conflict (org_id, idempotency_key) do nothing
  returning id into v_batch_id;

  if v_batch_id is null then
    return jsonb_build_object('ok', true, 'duplicate', true, 'processed', 0);
  end if;

  for v_row in
    select
      nullif(e.branch_id, '')::uuid as branch_id,
      e.entity_type,
      e.source_id,
      greatest(coalesce(e.source_version, 1), 1) as source_version,
      e.source_updated_at,
      e.payload,
      e.payload_hash,
      coalesce(e.deleted, false) as deleted
    from jsonb_to_recordset(p_entities) as e(
      branch_id text,
      entity_type text,
      source_id text,
      source_version bigint,
      source_updated_at timestamptz,
      payload jsonb,
      payload_hash text,
      deleted boolean
    )
  loop
    if v_row.entity_type is null or v_row.source_id is null or v_row.payload_hash is null then
      raise exception 'entity_type, source_id and payload_hash are required';
    end if;
    if v_row.source_updated_at is null then
      raise exception 'source_updated_at is required';
    end if;

    insert into public.sync_entities(
      org_id, branch_id, device_id, entity_type, source_id, source_version,
      source_updated_at, payload, payload_hash, deleted, synced_at
    ) values (
      p_org_id,
      v_row.branch_id,
      p_device_id,
      v_row.entity_type,
      v_row.source_id,
      v_row.source_version,
      v_row.source_updated_at,
      coalesce(v_row.payload, '{}'::jsonb),
      v_row.payload_hash,
      v_row.deleted,
      now()
    )
    on conflict (org_id, device_id, entity_type, source_id)
      where device_id is not null
    do update set
      branch_id = excluded.branch_id,
      source_version = excluded.source_version,
      source_updated_at = excluded.source_updated_at,
      payload = excluded.payload,
      payload_hash = excluded.payload_hash,
      deleted = excluded.deleted,
      synced_at = now()
    where excluded.source_version > public.sync_entities.source_version
       or (
         excluded.source_version = public.sync_entities.source_version
         and excluded.source_updated_at >= public.sync_entities.source_updated_at
         and excluded.payload_hash <> public.sync_entities.payload_hash
       );

    get diagnostics v_touched = row_count;
    if v_touched > 0 then
      v_count := v_count + 1;
      perform public.project_cloud_analytics_row(
        p_org_id,
        p_device_id,
        v_row.branch_id,
        v_row.entity_type,
        v_row.source_id,
        coalesce(v_row.payload, '{}'::jsonb),
        v_row.deleted,
        v_row.source_updated_at
      );
    end if;
  end loop;

  update public.sync_batches
    set status = 'complete', completed_at = now()
    where id = v_batch_id;
  update public.devices
    set last_sync_at = now(), sync_status = 'healthy', updated_at = now()
    where id = p_device_id and org_id = p_org_id;
  return jsonb_build_object(
    'ok', true, 'duplicate', false, 'processed', v_count, 'batch_id', v_batch_id
  );
exception when others then
  if v_batch_id is not null then
    update public.sync_batches
      set status = 'failed', error = left(sqlerrm, 500), completed_at = now()
      where id = v_batch_id;
  end if;
  raise;
end;
$$;

revoke all on function public.ingest_sync_batch(uuid, uuid, text, jsonb) from public;
revoke all on function public.ingest_sync_batch(uuid, uuid, text, jsonb) from authenticated;
revoke all on function public.ingest_sync_batch(uuid, uuid, text, jsonb) from anon;
grant execute on function public.ingest_sync_batch(uuid, uuid, text, jsonb) to service_role;

-- ingest_sync_batch does ON CONFLICT (org_id, idempotency_key) on sync_batches.
create unique index if not exists sync_batches_org_id_idempotency_key_key
  on public.sync_batches(org_id, idempotency_key);

commit;
