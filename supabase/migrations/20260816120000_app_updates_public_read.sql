-- Allow shop POS installs (anon key, no portal login) to read active release rows.
-- Required for in-app update fallback when GitHub API is blocked or rate-limited.

begin;

drop policy if exists app_updates_read on public.app_updates;
create policy app_updates_read on public.app_updates
  for select using (is_active = true);

commit;
