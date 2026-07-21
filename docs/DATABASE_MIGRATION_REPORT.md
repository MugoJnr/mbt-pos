# Database Migration Report — MBT Platform v3.0

**Date:** 2026-07-21
**Overall:** PASS

| Item | Status | Evidence |
|------|--------|----------|
| `supabase/schema_v3.sql` additive | PASS | `IF NOT EXISTS` / safe defaults |
| Applied to live Supabase | PASS | Project `uynfglgttkaibyeglsrt` |
| Existing devices backfilled approved | PASS | Migration updates legacy rows |
| New devices default `pending` | PASS | Column default |
| `device_events` / `sync_batches` / `sync_entities` | PASS | Tables present |
| `ingest_sync_batch` RPC | PASS | Service-role ingest path |
| Desktop SQLite destructive migration | PASS (none introduced) | Upgrade sim preserves customer DB |
| Trial plan defaults removed | PASS | Org plan default `unlicensed` |

## Customer safety

- No DROP of customer sales/inventory tables.
- Installer upgrade backs up DB + WAL/SHM before binary replace.
- Portal schema changes are cloud-side only and do not rewrite shop SQLite.

## Remediation

- Keep future migrations additive.
- Re-run schema_v3 on any secondary/staging Supabase projects.
