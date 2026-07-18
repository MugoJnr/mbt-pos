# MBT Cloud Backup & Restore (Supabase)

Local-first disaster recovery for MBT POS. The shop keeps selling offline; internet is only used for scheduled encrypted backups and restore.

## What v1 does

1. **Encrypted full SQLite snapshot** → Supabase Storage (`mbt-backups` bucket)
2. **Metadata row** in `backups` (mbt_version, schema_version, size, hash, device)
3. **Device registration** (`MBT-PC-XXXX`) + **business auth** (email/password via Supabase Auth)
4. **Settings → MBT Cloud Backup** dashboard (status, Backup Now, history, restore, devices, frequency)
5. **Setup wizard** hooks: Create New Business | Login Existing | Continue offline
6. **Compatibility gate**: refuse restore if backup needs a newer schema/app
7. **Hooks** for future incremental sync (`cloud_change_log` table + `record_change()`)

Full row-level sync of every table is **not** in v1 — snapshot versioning covers disaster recovery.

## Architecture

```
POS (PyQt5 + SQLite)
  └─ backend/cloud_backup/
       paths.py            AppData cloud_config.json / cloud_identity.json
       device_manager.py   MBT-PC-XXXX
       encryption.py       AES-256-GCM (cryptography or Windows CNG)
       supabase_client.py  Auth + REST + Storage via requests
       auth_service.py     create business / login / skip
       sync_manager.py     5‑min scheduler + Backup Now + offline queue
       restore_manager.py  download → decrypt → replace DB
```

## Configure Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. SQL Editor → paste and run `supabase/schema.sql`
3. Storage → New bucket → name `mbt-backups` → **Private**
4. Add Storage policies from the comments at the bottom of `schema.sql`
5. Authentication → Providers → Email enabled
6. Copy **Project URL** + **anon public** key
7. On the POS PC, create:

`%LOCALAPPDATA%\MugoByte\MBT POS\config\cloud_config.json`

(from `config/cloud_config.example.json`):

```json
{
  "supabase_url": "https://xxxx.supabase.co",
  "anon_key": "eyJ...",
  "enabled": false,
  "backup_interval_minutes": 5,
  "bucket": "mbt-backups"
}
```

Or set env vars: `MBT_SUPABASE_URL`, `MBT_SUPABASE_ANON_KEY` (optional `MBT_SUPABASE_SERVICE_KEY`).

**Never commit real keys.** `cloud_config.json` and `cloud_identity.json` stay in AppData (gitignored patterns for `.env` / local config).

## First run

- Wizard / Settings: **Create New Business** or **Login Existing**
- If backups exist after login → offer restore
- **Continue offline** skips cloud; cashiers are never blocked

## Restore

Settings → MBT Cloud Backup → pick a backup → Restore.  
A copy of the current DB is saved as `mbt_pos.pre_restore_*.db` before replace. Restart POS after restore.

## Optional dependency

`cryptography` improves portability; on Windows, AES-GCM via `bcrypt.dll` works without it. Optional: `pip install cryptography`.
