-- MBT Platform v3 additive production migration
-- Safe to run repeatedly after schema.sql and schema_v2.sql.
begin;

create extension if not exists "pgcrypto";

alter table public.organizations alter column plan set default 'unlicensed';
alter table public.licenses alter column plan set default 'monthly';

alter table public.devices add column if not exists org_id uuid
  references public.organizations(id) on delete cascade;
alter table public.devices add column if not exists branch_id uuid
  references public.branches(id) on delete set null;
alter table public.devices add column if not exists hardware_fingerprint text;
alter table public.devices add column if not exists computer_name text;
alter table public.devices add column if not exists windows_version text;
alter table public.devices add column if not exists installation_id uuid;
alter table public.devices add column if not exists approval_status text
  not null default 'pending';
alter table public.devices add column if not exists approved_at timestamptz;
alter table public.devices add column if not exists approved_by uuid
  references auth.users(id) on delete set null;
alter table public.devices add column if not exists rejected_at timestamptz;
alter table public.devices add column if not exists deactivated_at timestamptz;
alter table public.devices add column if not exists last_sync_at timestamptz;
alter table public.devices add column if not exists sync_status text;
alter table public.devices add column if not exists updated_at timestamptz
  not null default now();

-- Existing customer devices were implicitly owner-approved in v1.
update public.devices d
set org_id = b.org_id,
    approval_status = 'approved',
    approved_at = coalesce(d.approved_at, d.created_at),
    updated_at = now()
from public.businesses b
where d.business_id = b.id
  and d.org_id is null
  and b.org_id is not null;

create unique index if not exists uq_devices_installation_id
  on public.devices(installation_id) where installation_id is not null;
create unique index if not exists uq_devices_org_fingerprint
  on public.devices(org_id, hardware_fingerprint)
  where org_id is not null and hardware_fingerprint is not null;
create index if not exists idx_devices_org_status
  on public.devices(org_id, approval_status, last_seen_at desc);

create table if not exists public.device_events (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid references public.devices(id) on delete set null,
  event_type text not null,
  actor_user_id uuid references auth.users(id) on delete set null,
  details jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index if not exists idx_device_events_org_created
  on public.device_events(org_id, created_at desc);

create table if not exists public.sync_batches (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id uuid references public.devices(id) on delete set null,
  idempotency_key text not null,
  entity_count integer not null default 0,
  status text not null default 'processing',
  error text,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (org_id, idempotency_key)
);
create index if not exists idx_sync_batches_org_started
  on public.sync_batches(org_id, started_at desc);

create table if not exists public.sync_entities (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  device_id uuid references public.devices(id) on delete set null,
  entity_type text not null check (entity_type in (
    'sale','sale_item','inventory','product','customer','supplier','expense',
    'purchase','purchase_item','employee','user','branch','report',
    'notification','audit_log','setting'
  )),
  source_id text not null,
  source_version bigint not null default 1,
  source_updated_at timestamptz not null,
  payload jsonb not null,
  payload_hash text not null,
  deleted boolean not null default false,
  synced_at timestamptz not null default now(),
  unique (org_id, entity_type, source_id)
);
create index if not exists idx_sync_entities_org_type_updated
  on public.sync_entities(org_id, entity_type, source_updated_at desc);
create index if not exists idx_sync_entities_branch_type
  on public.sync_entities(branch_id, entity_type, source_updated_at desc);
create index if not exists idx_sync_entities_payload
  on public.sync_entities using gin(payload);

alter table public.device_events enable row level security;
alter table public.sync_batches enable row level security;
alter table public.sync_entities enable row level security;

drop policy if exists device_events_member on public.device_events;
create policy device_events_member on public.device_events
  for select using (public.is_org_member(org_id));

drop policy if exists sync_batches_member on public.sync_batches;
create policy sync_batches_member on public.sync_batches
  for select using (public.is_org_member(org_id));

drop policy if exists sync_entities_member on public.sync_entities;
create policy sync_entities_member on public.sync_entities
  for select using (public.is_org_member(org_id));

-- Writes are accepted only by the server/service role. There are deliberately
-- no authenticated-client insert/update/delete policies for sync data.

create or replace function public.is_org_member(p_org_id uuid)
returns boolean
language sql
security definer
stable
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.org_members
    where org_id = p_org_id and user_id = auth.uid() and is_active = true
  ) or exists (
    select 1 from public.organizations
    where id = p_org_id and owner_user_id = auth.uid()
  );
$$;

create or replace function public.is_org_admin(p_org_id uuid)
returns boolean
language sql
security definer
stable
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.org_members
    where org_id = p_org_id and user_id = auth.uid()
      and role in ('superadmin', 'admin', 'owner', 'manager')
      and is_active = true
  ) or exists (
    select 1 from public.organizations
    where id = p_org_id and owner_user_id = auth.uid()
  );
$$;

revoke all on function public.is_org_member(uuid) from public;
revoke all on function public.is_org_admin(uuid) from public;
grant execute on function public.is_org_member(uuid) to authenticated, service_role;
grant execute on function public.is_org_admin(uuid) to authenticated, service_role;

-- The previous policy allowed any authenticated user to acknowledge any
-- remote command. Device acknowledgements now go through the authenticated API.
drop policy if exists remote_cmd_device on public.remote_commands;

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
  v_count integer;
begin
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

  insert into public.sync_entities(
    org_id, branch_id, device_id, entity_type, source_id, source_version,
    source_updated_at, payload, payload_hash, deleted, synced_at
  )
  select
    p_org_id,
    nullif(e.branch_id, '')::uuid,
    p_device_id,
    e.entity_type,
    e.source_id,
    greatest(coalesce(e.source_version, 1), 1),
    e.source_updated_at,
    e.payload,
    e.payload_hash,
    coalesce(e.deleted, false),
    now()
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
  on conflict (org_id, entity_type, source_id) do update set
    branch_id = excluded.branch_id,
    device_id = excluded.device_id,
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

  get diagnostics v_count = row_count;
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
