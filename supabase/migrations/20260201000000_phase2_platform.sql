-- MBT Cloud Phase 2 — Extended Supabase Schema
-- Run after schema.sql. Adds orgs, branches, licenses, notifications, audit, commands, updates.
begin;

-- ── organizations (replaces single-business model) ───────────────────────────
create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text unique,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  plan text not null default 'trial',
  status text not null default 'active',
  settings jsonb default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_orgs_owner on public.organizations(owner_user_id);
create index if not exists idx_orgs_slug on public.organizations(slug);

-- ── org_members (multi-user per org) ─────────────────────────────────────────
create table if not exists public.org_members (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'cashier',
  is_active boolean not null default true,
  invited_at timestamptz default now(),
  joined_at timestamptz,
  unique (org_id, user_id)
);

create index if not exists idx_org_members_org on public.org_members(org_id);
create index if not exists idx_org_members_user on public.org_members(user_id);

-- ── branches ─────────────────────────────────────────────────────────────────
create table if not exists public.branches (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  address text,
  phone text,
  is_primary boolean not null default false,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists idx_branches_org on public.branches(org_id);

-- ── Extend devices table ─────────────────────────────────────────────────────
alter table public.devices add column if not exists org_id uuid references public.organizations(id) on delete cascade;
alter table public.devices add column if not exists branch_id uuid references public.branches(id) on delete set null;
alter table public.devices add column if not exists computer_name text;
alter table public.devices add column if not exists hardware_fingerprint text;
alter table public.devices add column if not exists os_info text;
alter table public.devices add column if not exists display_name text;
alter table public.devices add column if not exists is_disabled boolean not null default false;

-- ── licenses ─────────────────────────────────────────────────────────────────
create table if not exists public.licenses (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  license_key text unique not null,
  plan text not null default 'trial',
  status text not null default 'active',
  max_devices integer not null default 1,
  activated_devices integer not null default 0,
  issued_at timestamptz not null default now(),
  expires_at timestamptz,
  activated_at timestamptz,
  revoked_at timestamptz,
  notes text,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create index if not exists idx_licenses_org on public.licenses(org_id);
create index if not exists idx_licenses_key on public.licenses(license_key);
create index if not exists idx_licenses_status on public.licenses(status);

-- ── license_activations (device ↔ license binding) ─────────────────────────
create table if not exists public.license_activations (
  id uuid primary key default gen_random_uuid(),
  license_id uuid not null references public.licenses(id) on delete cascade,
  device_id text not null,
  org_id uuid not null references public.organizations(id) on delete cascade,
  activation_token text,
  activated_at timestamptz not null default now(),
  last_validated_at timestamptz,
  is_active boolean not null default true,
  unique (license_id, device_id)
);

create index if not exists idx_license_act_license on public.license_activations(license_id);
create index if not exists idx_license_act_device on public.license_activations(device_id);

-- ── license_history ──────────────────────────────────────────────────────────
create table if not exists public.license_history (
  id uuid primary key default gen_random_uuid(),
  license_id uuid not null references public.licenses(id) on delete cascade,
  action text not null,
  actor_user_id uuid references auth.users(id),
  details jsonb,
  created_at timestamptz not null default now()
);

-- ── notifications ────────────────────────────────────────────────────────────
create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references public.organizations(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  type text not null,
  title text not null,
  body text,
  severity text not null default 'info',
  channel text not null default 'dashboard',
  is_read boolean not null default false,
  link text,
  meta jsonb default '{}',
  created_at timestamptz not null default now()
);

create index if not exists idx_notifications_org on public.notifications(org_id, created_at desc);
create index if not exists idx_notifications_user on public.notifications(user_id, is_read, created_at desc);

-- ── notification_preferences ─────────────────────────────────────────────────
create table if not exists public.notification_preferences (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  org_id uuid references public.organizations(id) on delete cascade,
  event_type text not null,
  dashboard boolean not null default true,
  email boolean not null default false,
  push boolean not null default false,
  unique (user_id, org_id, event_type)
);

-- ── reports (stored generated reports) ───────────────────────────────────────
create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  branch_id uuid references public.branches(id) on delete set null,
  report_type text not null,
  period_start date,
  period_end date,
  title text not null,
  storage_path text,
  format text not null default 'json',
  size_bytes bigint default 0,
  summary jsonb default '{}',
  generated_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create index if not exists idx_reports_org on public.reports(org_id, created_at desc);

-- ── audit_logs ───────────────────────────────────────────────────────────────
create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references public.organizations(id) on delete set null,
  user_id uuid references auth.users(id) on delete set null,
  device_id text,
  action text not null,
  module text,
  details text,
  ip_address text,
  status text not null default 'success',
  meta jsonb default '{}',
  created_at timestamptz not null default now()
);

create index if not exists idx_audit_org on public.audit_logs(org_id, created_at desc);
create index if not exists idx_audit_action on public.audit_logs(action, created_at desc);

-- ── remote_commands ──────────────────────────────────────────────────────────
create table if not exists public.remote_commands (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  device_id text not null,
  command text not null,
  params jsonb default '{}',
  status text not null default 'pending',
  result jsonb,
  error text,
  issued_by uuid references auth.users(id),
  issued_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create index if not exists idx_remote_cmd_device on public.remote_commands(device_id, status);
create index if not exists idx_remote_cmd_pending on public.remote_commands(status) where status = 'pending';

-- ── app_updates ──────────────────────────────────────────────────────────────
create table if not exists public.app_updates (
  id uuid primary key default gen_random_uuid(),
  version text not null unique,
  release_notes text,
  download_url text,
  checksum_sha256 text,
  file_size_bytes bigint,
  is_mandatory boolean not null default false,
  min_version text,
  published_at timestamptz not null default now(),
  published_by uuid references auth.users(id),
  is_active boolean not null default true
);

-- ── update_history (per device) ──────────────────────────────────────────────
create table if not exists public.update_history (
  id uuid primary key default gen_random_uuid(),
  device_id text not null,
  org_id uuid references public.organizations(id) on delete set null,
  from_version text,
  to_version text not null,
  status text not null default 'pending',
  error text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

-- ── system_health_snapshots ──────────────────────────────────────────────────
create table if not exists public.system_health_snapshots (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references public.organizations(id) on delete cascade,
  device_id text,
  score integer,
  overall text,
  checks jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_health_org on public.system_health_snapshots(org_id, created_at desc);

-- ── RLS for new tables ───────────────────────────────────────────────────────
alter table public.organizations enable row level security;
alter table public.org_members enable row level security;
alter table public.branches enable row level security;
alter table public.licenses enable row level security;
alter table public.license_activations enable row level security;
alter table public.license_history enable row level security;
alter table public.notifications enable row level security;
alter table public.notification_preferences enable row level security;
alter table public.reports enable row level security;
alter table public.audit_logs enable row level security;
alter table public.remote_commands enable row level security;
alter table public.app_updates enable row level security;
alter table public.update_history enable row level security;
alter table public.system_health_snapshots enable row level security;

-- Helper: check org membership
create or replace function public.is_org_member(p_org_id uuid)
returns boolean language sql security definer stable
set search_path = public, pg_temp as $$
  select exists (
    select 1 from public.org_members
    where org_id = p_org_id and user_id = auth.uid() and is_active = true
  ) or exists (
    select 1 from public.organizations
    where id = p_org_id and owner_user_id = auth.uid()
  );
$$;

create or replace function public.is_org_admin(p_org_id uuid)
returns boolean language sql security definer stable
set search_path = public, pg_temp as $$
  select exists (
    select 1 from public.org_members
    where org_id = p_org_id and user_id = auth.uid()
      and role in ('superadmin', 'admin', 'owner') and is_active = true
  ) or exists (
    select 1 from public.organizations
    where id = p_org_id and owner_user_id = auth.uid()
  );
$$;

-- Organizations: owner + members
drop policy if exists orgs_member_select on public.organizations;
create policy orgs_member_select on public.organizations
  for select using (public.is_org_member(id) or owner_user_id = auth.uid());
drop policy if exists orgs_owner_all on public.organizations;
create policy orgs_owner_all on public.organizations
  for all using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());

-- Org members
drop policy if exists org_members_select on public.org_members;
create policy org_members_select on public.org_members
  for select using (public.is_org_member(org_id));
drop policy if exists org_members_admin on public.org_members;
create policy org_members_admin on public.org_members
  for all using (public.is_org_admin(org_id));

-- Branches
drop policy if exists branches_member on public.branches;
create policy branches_member on public.branches
  for all using (public.is_org_member(org_id));

-- Licenses
drop policy if exists licenses_member on public.licenses;
create policy licenses_member on public.licenses
  for select using (public.is_org_member(org_id));
drop policy if exists licenses_admin on public.licenses;
create policy licenses_admin on public.licenses
  for all using (public.is_org_admin(org_id));

-- License activations
drop policy if exists license_act_member on public.license_activations;
create policy license_act_member on public.license_activations
  for select using (public.is_org_member(org_id));
drop policy if exists license_act_admin on public.license_activations;
create policy license_act_admin on public.license_activations
  for all using (public.is_org_admin(org_id));

-- Notifications
drop policy if exists notifications_own on public.notifications;
create policy notifications_own on public.notifications
  for select using (user_id = auth.uid() or public.is_org_member(org_id));
drop policy if exists notifications_update on public.notifications;
create policy notifications_update on public.notifications
  for update using (user_id = auth.uid());

-- Notification preferences
drop policy if exists notif_prefs_own on public.notification_preferences;
create policy notif_prefs_own on public.notification_preferences
  for all using (user_id = auth.uid());

-- Reports
drop policy if exists reports_member on public.reports;
create policy reports_member on public.reports
  for select using (public.is_org_member(org_id));
drop policy if exists reports_admin on public.reports;
create policy reports_admin on public.reports
  for insert with check (public.is_org_admin(org_id));

-- Audit logs
drop policy if exists audit_member on public.audit_logs;
create policy audit_member on public.audit_logs
  for select using (public.is_org_member(org_id));

-- Remote commands
drop policy if exists remote_cmd_member on public.remote_commands;
create policy remote_cmd_member on public.remote_commands
  for select using (public.is_org_member(org_id));
drop policy if exists remote_cmd_admin on public.remote_commands;
create policy remote_cmd_admin on public.remote_commands
  for insert with check (public.is_org_admin(org_id));
drop policy if exists remote_cmd_device on public.remote_commands;
create policy remote_cmd_device on public.remote_commands
  for update using (true);

-- App updates (public read for authenticated users)
drop policy if exists app_updates_read on public.app_updates;
create policy app_updates_read on public.app_updates
  for select using (auth.uid() is not null and is_active = true);

-- Update history
drop policy if exists update_hist_member on public.update_history;
create policy update_hist_member on public.update_history
  for select using (public.is_org_member(org_id));

-- System health
drop policy if exists health_member on public.system_health_snapshots;
create policy health_member on public.system_health_snapshots
  for select using (public.is_org_member(org_id));

-- Link businesses → organizations (migration helper)
alter table public.businesses add column if not exists org_id uuid references public.organizations(id) on delete set null;

revoke all on function public.is_org_member(uuid) from public;
revoke all on function public.is_org_admin(uuid) from public;
grant execute on function public.is_org_member(uuid) to authenticated, service_role;
grant execute on function public.is_org_admin(uuid) to authenticated, service_role;

commit;
