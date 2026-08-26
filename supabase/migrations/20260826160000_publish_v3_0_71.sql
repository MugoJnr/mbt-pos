-- Publish the exact, tested MBT POS v3.0.71 GitHub artifact.
begin;

insert into public.app_updates (
  version,
  release_notes,
  download_url,
  checksum_sha256,
  file_size_bytes,
  is_mandatory,
  min_version,
  published_at,
  is_active
) values (
  '3.0.71',
  'MBT POS v3.0.71 production update: verified updater integrity, hardened recovery and credential packaging, reliable update helper, and responsive POS repairs.',
  'https://github.com/MugoJnr/mbt-pos/releases/download/v3.0.71/MBT_POS_Setup.exe',
  '9b9c29eb8c27ff43b1fc3e0516df3305c75f9962d86cff15d70285d9b95b368d',
  58783249,
  false,
  '3.0.70',
  now(),
  true
)
on conflict (version) do update set
  release_notes = excluded.release_notes,
  download_url = excluded.download_url,
  checksum_sha256 = excluded.checksum_sha256,
  file_size_bytes = excluded.file_size_bytes,
  is_mandatory = excluded.is_mandatory,
  min_version = excluded.min_version,
  published_at = excluded.published_at,
  is_active = excluded.is_active;

commit;
