-- Shop-safe cloud backup authorization.
-- Backup blobs remain scoped by businesses.id (the first storage path segment),
-- while access follows either direct business ownership or active org membership.
begin;

create or replace function public.can_access_business(p_business_id uuid)
returns boolean
language sql
security definer
stable
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from public.businesses b
    where b.id = p_business_id
      and (
        b.owner_user_id = auth.uid()
        or (
          b.org_id is not null
          and public.is_org_member(b.org_id)
        )
      )
  );
$$;

revoke all on function public.can_access_business(uuid) from public;
grant execute on function public.can_access_business(uuid)
  to authenticated, service_role;

-- Makes metadata retries idempotent after an object upload succeeds.
delete from public.backups
where id in (
  select id
  from (
    select
      id,
      row_number() over (
        partition by storage_path
        order by created_at desc, id desc
      ) as duplicate_rank
    from public.backups
  ) ranked
  where duplicate_rank > 1
);
create unique index if not exists uq_backups_storage_path
  on public.backups(storage_path);

-- A Portal member may discover the legacy business row linked to their org.
drop policy if exists businesses_org_member_select on public.businesses;
create policy businesses_org_member_select on public.businesses
  for select to authenticated
  using (
    owner_user_id = auth.uid()
    or (org_id is not null and public.is_org_member(org_id))
  );

drop policy if exists backups_owner_all on public.backups;
drop policy if exists backups_shop_select on public.backups;
drop policy if exists backups_shop_insert on public.backups;
drop policy if exists backups_shop_update on public.backups;
drop policy if exists backups_shop_delete on public.backups;

create policy backups_shop_select on public.backups
  for select to authenticated
  using (public.can_access_business(business_id));
create policy backups_shop_insert on public.backups
  for insert to authenticated
  with check (public.can_access_business(business_id));
create policy backups_shop_update on public.backups
  for update to authenticated
  using (public.can_access_business(business_id))
  with check (public.can_access_business(business_id));
create policy backups_shop_delete on public.backups
  for delete to authenticated
  using (public.can_access_business(business_id));

-- Device registration used by backup history follows the same shop boundary.
drop policy if exists devices_owner_all on public.devices;
drop policy if exists devices_shop_all on public.devices;
create policy devices_shop_all on public.devices
  for all to authenticated
  using (public.can_access_business(business_id))
  with check (public.can_access_business(business_id));

drop policy if exists "mbt backups read" on storage.objects;
drop policy if exists "mbt backups write" on storage.objects;
drop policy if exists "mbt backups update" on storage.objects;
drop policy if exists "mbt backups delete" on storage.objects;

create policy "mbt backups read"
on storage.objects for select to authenticated
using (
  bucket_id = 'mbt-backups'
  and public.can_access_business(
    nullif((storage.foldername(name))[1], '')::uuid
  )
);

create policy "mbt backups write"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'mbt-backups'
  and public.can_access_business(
    nullif((storage.foldername(name))[1], '')::uuid
  )
);

create policy "mbt backups update"
on storage.objects for update to authenticated
using (
  bucket_id = 'mbt-backups'
  and public.can_access_business(
    nullif((storage.foldername(name))[1], '')::uuid
  )
)
with check (
  bucket_id = 'mbt-backups'
  and public.can_access_business(
    nullif((storage.foldername(name))[1], '')::uuid
  )
);

create policy "mbt backups delete"
on storage.objects for delete to authenticated
using (
  bucket_id = 'mbt-backups'
  and public.can_access_business(
    nullif((storage.foldername(name))[1], '')::uuid
  )
);

commit;
