begin;

alter table public.cloud_sales
  add column if not exists electronic_method text,
  add column if not exists cash_paid numeric(14,2) not null default 0,
  add column if not exists payment_tenders text;

-- Keep tender detail projection backward-compatible with already deployed
-- project_cloud_analytics_row versions. sync_entities is written immediately
-- before cloud_sales in the same transaction, so the payload is available.
create or replace function public.fill_cloud_sale_tender_details()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_payload jsonb;
begin
  select se.payload
    into v_payload
  from public.sync_entities se
  where se.org_id = new.org_id
    and se.device_id is not distinct from new.device_id
    and se.entity_type = 'sale'
    and se.source_id = new.source_id
  limit 1;

  if v_payload is not null then
    new.electronic_method := nullif(v_payload ->> 'electronic_method', '');
    new.cash_paid := coalesce(
      nullif(v_payload ->> 'cash_paid', '')::numeric,
      new.cash_paid,
      0
    );
    new.payment_tenders := nullif(v_payload ->> 'payment_tenders', '');
  end if;
  return new;
end;
$$;

drop trigger if exists trg_fill_cloud_sale_tender_details on public.cloud_sales;
create trigger trg_fill_cloud_sale_tender_details
before insert or update on public.cloud_sales
for each row execute function public.fill_cloud_sale_tender_details();

-- Idempotent backfill for any payloads already carrying these fields.
update public.cloud_sales cs
set electronic_method = nullif(se.payload ->> 'electronic_method', ''),
    cash_paid = coalesce(
      nullif(se.payload ->> 'cash_paid', '')::numeric,
      cs.cash_paid,
      0
    ),
    payment_tenders = nullif(se.payload ->> 'payment_tenders', '')
from public.sync_entities se
where se.org_id = cs.org_id
  and se.device_id is not distinct from cs.device_id
  and se.entity_type = 'sale'
  and se.source_id = cs.source_id
  and (
    se.payload ? 'electronic_method'
    or se.payload ? 'cash_paid'
    or se.payload ? 'payment_tenders'
  );

revoke all on function public.fill_cloud_sale_tender_details() from public;

commit;
