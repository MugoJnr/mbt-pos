-- MBT POS Cloud Backup — baseline migration.
-- Intentionally repeatable so an existing manually provisioned project can be
-- adopted by Supabase migrations without destructive changes.
begin;

-- Extensions
create extension if not exists "pgcrypto";

-- ── businesses ───────────────────────────────────────────────────────────────
create table if not exists public.businesses (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_businesses_owner on public.businesses(owner_user_id);

-- ── devices ──────────────────────────────────────────────────────────────────
create table if not exists public.devices (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  device_id text not null,
  hostname text,
  platform text,
  mbt_version text,
  is_active boolean not null default true,
  last_seen_at timestamptz default now(),
  created_at timestamptz not null default now(),
  unique (business_id, device_id)
);

create index if not exists idx_devices_business on public.devices(business_id);

-- ── backups (metadata; blobs live in Storage) ────────────────────────────────
create table if not exists public.backups (
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  device_id text not null,
  storage_path text not null,
  size_bytes bigint default 0,
  content_hash text,
  mbt_version text,
  schema_version integer not null default 1,
  backup_type text not null default 'full_snapshot',
  reason text,
  created_at timestamptz not null default now()
);

create index if not exists idx_backups_business_created
  on public.backups(business_id, created_at desc);

-- ── sync_logs ────────────────────────────────────────────────────────────────
create table if not exists public.sync_logs (
  id uuid primary key default gen_random_uuid(),
  business_id uuid references public.businesses(id) on delete cascade,
  device_id text,
  event_type text,
  status text,
  message text,
  detail jsonb,
  created_at timestamptz not null default now()
);

-- ── restore_history ──────────────────────────────────────────────────────────
create table if not exists public.restore_history (
  id uuid primary key default gen_random_uuid(),
  business_id uuid references public.businesses(id) on delete cascade,
  device_id text,
  backup_id uuid references public.backups(id) on delete set null,
  status text,
  message text,
  restored_at timestamptz not null default now()
);

-- ── RLS ──────────────────────────────────────────────────────────────────────
alter table public.businesses enable row level security;
alter table public.devices enable row level security;
alter table public.backups enable row level security;
alter table public.sync_logs enable row level security;
alter table public.restore_history enable row level security;

-- Owner can manage their business
drop policy if exists businesses_owner_all on public.businesses;
create policy businesses_owner_all on public.businesses
  for all using (auth.uid() = owner_user_id)
  with check (auth.uid() = owner_user_id);

drop policy if exists devices_owner_all on public.devices;
create policy devices_owner_all on public.devices
  for all using (
    exists (
      select 1 from public.businesses b
      where b.id = devices.business_id and b.owner_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.businesses b
      where b.id = devices.business_id and b.owner_user_id = auth.uid()
    )
  );

drop policy if exists backups_owner_all on public.backups;
create policy backups_owner_all on public.backups
  for all using (
    exists (
      select 1 from public.businesses b
      where b.id = backups.business_id and b.owner_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.businesses b
      where b.id = backups.business_id and b.owner_user_id = auth.uid()
    )
  );

drop policy if exists sync_logs_owner_all on public.sync_logs;
create policy sync_logs_owner_all on public.sync_logs
  for all using (
    business_id is null or exists (
      select 1 from public.businesses b
      where b.id = sync_logs.business_id and b.owner_user_id = auth.uid()
    )
  )
  with check (
    business_id is null or exists (
      select 1 from public.businesses b
      where b.id = sync_logs.business_id and b.owner_user_id = auth.uid()
    )
  );

drop policy if exists restore_history_owner_all on public.restore_history;
create policy restore_history_owner_all on public.restore_history
  for all using (
    business_id is null or exists (
      select 1 from public.businesses b
      where b.id = restore_history.business_id and b.owner_user_id = auth.uid()
    )
  )
  with check (
    business_id is null or exists (
      select 1 from public.businesses b
      where b.id = restore_history.business_id and b.owner_user_id = auth.uid()
    )
  );

-- Upsert support for devices (unique business_id + device_id)
-- PostgREST needs a unique constraint (already defined above).

-- Private backup bucket. ON CONFLICT preserves production bucket settings.
insert into storage.buckets (id, name, public)
values ('mbt-backups', 'mbt-backups', false)
on conflict (id) do nothing;

drop policy if exists "mbt backups read" on storage.objects;
create policy "mbt backups read"
on storage.objects for select to authenticated
using (
  bucket_id = 'mbt-backups'
  and exists (
    select 1 from public.businesses b
    where b.id::text = (storage.foldername(name))[1]
      and b.owner_user_id = auth.uid()
  )
);

drop policy if exists "mbt backups write" on storage.objects;
create policy "mbt backups write"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'mbt-backups'
  and exists (
    select 1 from public.businesses b
    where b.id::text = (storage.foldername(name))[1]
      and b.owner_user_id = auth.uid()
  )
);

drop policy if exists "mbt backups update" on storage.objects;
create policy "mbt backups update"
on storage.objects for update to authenticated
using (
  bucket_id = 'mbt-backups'
  and exists (
    select 1 from public.businesses b
    where b.id::text = (storage.foldername(name))[1]
      and b.owner_user_id = auth.uid()
  )
)
with check (
  bucket_id = 'mbt-backups'
  and exists (
    select 1 from public.businesses b
    where b.id::text = (storage.foldername(name))[1]
      and b.owner_user_id = auth.uid()
  )
);

commit;
