-- MBT Platform v4 analytics migration
-- Safe to run repeatedly after schema.sql, schema_v2.sql, and schema_v3.sql.
-- Makes sync identity device-safe, adds debt/payment/stock entities, and
-- projects payloads into typed cloud analytics tables.

begin;

create extension if not exists "pgcrypto";

-- ── 1) Device-safe sync_entities identity ────────────────────────────────────
-- Drop legacy uniqueness (org, type, source) which collides across devices.
alter table public.sync_entities
  drop constraint if exists sync_entities_org_id_entity_type_source_id_key;

-- Rows without a device cannot participate in device-safe identity. Keep them
-- readable but exclude them from the new unique index until repaired.
-- Prefer preserving payload history over hard-delete.
update public.sync_entities se
set device_id = d.id,
    synced_at = now()
from public.devices d
where se.device_id is null
  and se.org_id = d.org_id
  and d.is_active is true
  and d.id = (
    select d2.id
    from public.devices d2
    where d2.org_id = se.org_id
      and d2.is_active is true
    order by d2.last_seen_at desc nulls last, d2.created_at desc
    limit 1
  );

-- Expand allowed entity types (drop/recreate check).
alter table public.sync_entities
  drop constraint if exists sync_entities_entity_type_check;

alter table public.sync_entities
  add constraint sync_entities_entity_type_check check (entity_type in (
    'sale','sale_item','inventory','product','customer','supplier','expense',
    'purchase','purchase_item','employee','user','branch','report',
    'notification','audit_log','setting',
    'debt_invoice','debt_payment','stock_movement'
  ));

-- New uniqueness includes device_id. Partial index skips unrepaired nulls.
create unique index if not exists uq_sync_entities_org_device_type_source
  on public.sync_entities(org_id, device_id, entity_type, source_id)
  where device_id is not null;

create index if not exists idx_sync_entities_org_device_type
  on public.sync_entities(org_id, device_id, entity_type, source_updated_at desc);

-- ── 2) Typed analytics projections ───────────────────────────────────────────
create table if not exists public.cloud_sales (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  receipt_number text,
  cashier_id text,
  cashier_name text,
  customer_source_id text,
  subtotal numeric(14,2) not null default 0,
  discount numeric(14,2) not null default 0,
  tax numeric(14,2) not null default 0,
  total numeric(14,2) not null default 0,
  amount_paid numeric(14,2) not null default 0,
  change_amount numeric(14,2) not null default 0,
  credit_applied numeric(14,2) not null default 0,
  electronic_paid numeric(14,2) not null default 0,
  original_total numeric(14,2),
  cash_rounding_adj numeric(14,2) not null default 0,
  payment_method text,
  status text not null default 'completed',
  variance_handling text,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

create table if not exists public.cloud_sale_items (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  sale_source_id text,
  product_source_id text,
  product_name text,
  sku text,
  category text,
  quantity numeric(14,4) not null default 0,
  unit_price numeric(14,4) not null default 0,
  unit_cost numeric(14,4),
  discount numeric(14,4) not null default 0,
  total numeric(14,4) not null default 0,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

create table if not exists public.cloud_products (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  name text,
  sku text,
  category text,
  price numeric(14,4) not null default 0,
  cost_price numeric(14,4) not null default 0,
  stock numeric(14,4) not null default 0,
  min_stock numeric(14,4) not null default 0,
  unit text,
  barcode text,
  is_active boolean not null default true,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

-- Restricted customer PII: name/phone/email only — never national_id/notes/address.
create table if not exists public.cloud_customers (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  name text,
  phone text,
  email text,
  credit_limit numeric(14,2) not null default 0,
  customer_type text,
  is_active boolean not null default true,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

create table if not exists public.cloud_debt_invoices (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  invoice_number text,
  sale_source_id text,
  receipt_number text,
  customer_source_id text,
  customer_name text,
  customer_phone text,
  total_amount numeric(14,2) not null default 0,
  amount_paid numeric(14,2) not null default 0,
  balance numeric(14,2) not null default 0,
  status text not null default 'pending',
  due_date date,
  cashier_id text,
  cashier_name text,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

create table if not exists public.cloud_debt_payments (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  payment_receipt text,
  invoice_source_id text,
  customer_source_id text,
  amount numeric(14,2) not null default 0,
  payment_method text,
  balance_before numeric(14,2) not null default 0,
  balance_after numeric(14,2) not null default 0,
  cashier_id text,
  cashier_name text,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

create table if not exists public.cloud_stock_movements (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  source_id text not null,
  product_source_id text,
  product_name text,
  movement_type text,
  qty_before numeric(14,4) not null default 0,
  qty_change numeric(14,4) not null default 0,
  qty_after numeric(14,4) not null default 0,
  reference text,
  reason text,
  user_id text,
  username text,
  source_created_at timestamptz,
  source_updated_at timestamptz,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, device_id, source_id)
);

-- Indexes for org-scoped analytics queries
create index if not exists idx_cloud_sales_org_created
  on public.cloud_sales(org_id, source_created_at desc);
create index if not exists idx_cloud_sales_org_status
  on public.cloud_sales(org_id, status, source_created_at desc);
create index if not exists idx_cloud_sales_org_receipt
  on public.cloud_sales(org_id, receipt_number);
create index if not exists idx_cloud_sales_org_cashier
  on public.cloud_sales(org_id, cashier_name);

create index if not exists idx_cloud_sale_items_org_sale
  on public.cloud_sale_items(org_id, sale_source_id);
create index if not exists idx_cloud_sale_items_org_product
  on public.cloud_sale_items(org_id, product_source_id);

create index if not exists idx_cloud_products_org_stock
  on public.cloud_products(org_id, stock, min_stock);
create index if not exists idx_cloud_products_org_active
  on public.cloud_products(org_id, is_active, name);
create index if not exists idx_cloud_products_org_category
  on public.cloud_products(org_id, category);

create index if not exists idx_cloud_customers_org_name
  on public.cloud_customers(org_id, name);
create index if not exists idx_cloud_customers_org_phone
  on public.cloud_customers(org_id, phone);

create index if not exists idx_cloud_debts_org_status
  on public.cloud_debt_invoices(org_id, status, due_date);
create index if not exists idx_cloud_debts_org_created
  on public.cloud_debt_invoices(org_id, source_created_at desc);
create index if not exists idx_cloud_debts_org_customer
  on public.cloud_debt_invoices(org_id, customer_source_id);

create index if not exists idx_cloud_debt_payments_org_created
  on public.cloud_debt_payments(org_id, source_created_at desc);
create index if not exists idx_cloud_debt_payments_org_invoice
  on public.cloud_debt_payments(org_id, invoice_source_id);

create index if not exists idx_cloud_stock_org_created
  on public.cloud_stock_movements(org_id, source_created_at desc);
create index if not exists idx_cloud_stock_org_product
  on public.cloud_stock_movements(org_id, product_source_id);

-- RLS: org members can read; writes are service-role only (no write policies).
alter table public.cloud_sales enable row level security;
alter table public.cloud_sale_items enable row level security;
alter table public.cloud_products enable row level security;
alter table public.cloud_customers enable row level security;
alter table public.cloud_debt_invoices enable row level security;
alter table public.cloud_debt_payments enable row level security;
alter table public.cloud_stock_movements enable row level security;

drop policy if exists cloud_sales_member on public.cloud_sales;
create policy cloud_sales_member on public.cloud_sales
  for select using (public.is_org_member(org_id));

drop policy if exists cloud_sale_items_member on public.cloud_sale_items;
create policy cloud_sale_items_member on public.cloud_sale_items
  for select using (public.is_org_member(org_id));

drop policy if exists cloud_products_member on public.cloud_products;
create policy cloud_products_member on public.cloud_products
  for select using (public.is_org_member(org_id));

drop policy if exists cloud_customers_member on public.cloud_customers;
create policy cloud_customers_member on public.cloud_customers
  for select using (public.is_org_member(org_id));

drop policy if exists cloud_debt_invoices_member on public.cloud_debt_invoices;
create policy cloud_debt_invoices_member on public.cloud_debt_invoices
  for select using (public.is_org_member(org_id));

drop policy if exists cloud_debt_payments_member on public.cloud_debt_payments;
create policy cloud_debt_payments_member on public.cloud_debt_payments
  for select using (public.is_org_member(org_id));

drop policy if exists cloud_stock_movements_member on public.cloud_stock_movements;
create policy cloud_stock_movements_member on public.cloud_stock_movements
  for select using (public.is_org_member(org_id));

-- ── 3) Projection helpers ────────────────────────────────────────────────────
create or replace function public._cloud_ts(p jsonb, p_key text)
returns timestamptz
language sql
immutable
as $$
  select nullif(p ->> p_key, '')::timestamptz;
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
grant execute on function public.ingest_sync_batch(uuid, uuid, text, jsonb) to service_role;

commit;
