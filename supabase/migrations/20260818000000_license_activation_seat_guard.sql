-- Enforce the device-seat entitlement in the database, not only in the
-- application process. This closes the concurrent-activation race where two
-- different devices could both observe the final free seat before either
-- activation was committed.

create or replace function public.enforce_license_activation_seat_limit()
returns trigger
language plpgsql
as $$
declare
  allowed_seats integer;
  used_seats integer;
begin
  -- Inactive history rows do not consume a seat.
  if new.is_active is not true then
    return new;
  end if;

  -- Lock the parent license so concurrent activation attempts serialize.
  select max_devices
    into allowed_seats
    from public.licenses
   where id = new.license_id
   for update;

  if allowed_seats is null then
    raise exception 'License not found for activation';
  end if;

  select count(distinct device_id)
    into used_seats
    from public.license_activations
   where license_id = new.license_id
     and is_active = true
     and (tg_op = 'INSERT' or id <> new.id);

  if used_seats >= allowed_seats then
    raise exception 'Device limit reached (%)', allowed_seats
      using errcode = 'P0001';
  end if;

  return new;
end;
$$;

drop trigger if exists license_activation_seat_guard on public.license_activations;
create trigger license_activation_seat_guard
before insert or update of license_id, device_id, is_active
on public.license_activations
for each row execute function public.enforce_license_activation_seat_limit();
