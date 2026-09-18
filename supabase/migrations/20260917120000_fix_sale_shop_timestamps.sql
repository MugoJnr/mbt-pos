-- Fix Portal sale hours: naive POS created_at is Africa/Nairobi, not UTC.
-- Live-safe: no drops, no POS client change, no shop DB writes.
-- Idempotent backfill from sync_entities payloads.

begin;

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


-- Recompute existing sale instants from stored payloads (idempotent).
-- Does not touch other projection tables: their created_at is SQLite UTC.
update public.cloud_sales cs
set source_created_at = coalesce(
      public._cloud_shop_ts(se.payload, 'created_at'),
      cs.source_created_at
    )
from public.sync_entities se
where se.org_id = cs.org_id
  and se.device_id is not distinct from cs.device_id
  and se.entity_type = 'sale'
  and se.source_id = cs.source_id
  and se.payload ? 'created_at'
  and nullif(btrim(se.payload ->> 'created_at'), '') is not null;

commit;
