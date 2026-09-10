# MBT POS 3.0.89 — rolling cloud backups

## Desktop changes

- Migrates retired `uynfglgttkaibyeglsrt` shop configs to the current
  MugoByte Cloud project on first config load.
- Changes the default schedule from 5 minutes to 24 hours and enforces a
  one-hour minimum.
- Uploads fixed rolling objects:
  - `{business}/{device}/latest.mbtenc`
  - `{business}/{device}/daily/YYYYMMDD.mbtenc`
- Keeps seven daily slots by default and prunes older daily objects plus
  legacy timestamp-named cloud objects.
- Upserts backup metadata by storage path so metadata does not grow forever.
- Retires legacy timestamp queue references without uploading them. Their
  encrypted local payloads remain until a new rolling backup succeeds.
- Displays and stores backup frequency in hours in the desktop Settings UI.

No portal files or repo-local `config/cloud_config.json` are part of this
desktop release.

## Safety

- `%LOCALAPPDATA%\MugoByte\MBT POS\data\mbt_pos.db` remains installer-owned
  user data and is not replaced during upgrade.
- The ProgramData machine license store and LocalAppData identity/config are
  preserved.
- Remote-command durable receipts and destructive-command replay guards from
  3.0.88 remain included.
