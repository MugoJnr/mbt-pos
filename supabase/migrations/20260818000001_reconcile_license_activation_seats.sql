-- Repair historical over-capacity licenses without deleting audit history.
-- For each license retain the most recently validated activation(s), up to the
-- purchased seat limit, and deactivate only surplus rows. Then mirror the
-- denormalized activated_devices counter from the retained active seats.

with ranked_active as (
  select
    a.id,
    a.license_id,
    l.max_devices,
    row_number() over (
      partition by a.license_id
      order by a.last_validated_at desc nulls last,
               a.activated_at desc nulls last,
               a.id desc
    ) as seat_rank
  from public.license_activations a
  join public.licenses l on l.id = a.license_id
  where a.is_active = true
),
surplus as (
  select id
  from ranked_active
  where seat_rank > max_devices
)
update public.license_activations
   set is_active = false
 where id in (select id from surplus);

with active_counts as (
  select license_id, count(distinct device_id)::integer as seat_count
  from public.license_activations
  where is_active = true
  group by license_id
)
update public.licenses l
   set activated_devices = coalesce(c.seat_count, 0),
       claim_status = case
         when coalesce(c.seat_count, 0) > 0 then 'claimed'
         when coalesce(l.assigned_email, '') <> ''
           or coalesce(l.reserved_device_id, '') <> '' then 'reserved'
         else 'unassigned'
       end
  from active_counts c
 where l.id = c.license_id
   and (l.activated_devices is distinct from c.seat_count
        or l.claim_status is distinct from case
          when c.seat_count > 0 then 'claimed'
          when coalesce(l.assigned_email, '') <> ''
            or coalesce(l.reserved_device_id, '') <> '' then 'reserved'
          else 'unassigned'
        end);

update public.licenses l
   set activated_devices = 0,
       claim_status = case
         when coalesce(l.assigned_email, '') <> ''
           or coalesce(l.reserved_device_id, '') <> '' then 'reserved'
         else 'unassigned'
       end
 where not exists (
   select 1 from public.license_activations a
   where a.license_id = l.id and a.is_active = true
 )
   and (l.activated_devices <> 0 or l.claim_status = 'claimed');
