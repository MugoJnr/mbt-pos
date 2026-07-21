# Synchronization Architecture — MBT Platform v3.0

**Date:** 2026-07-21
**Overall:** PASS (contract-tested; full multi-entity E2E NOT RUN)

## Authority model

1. **Desktop POS SQLite** is the operational source of truth.
2. Local writes enqueue rows into `sync_outbox` (transactional triggers).
3. `SyncManager.flush_entity_outbox()` posts batches to Portal.
4. Portal `/api/cloud/sync/batch` authorizes org membership + **approved device**.
5. Supabase RPC `ingest_sync_batch` upserts `sync_entities` idempotently.
6. Portal UI reads synchronized cloud tables only — never shop SQLite.
7. Live Dashboard remains on shop tunnel and reads live local ops data.

## Guarantees

| Guarantee | Mechanism | Status |
|-----------|-----------|--------|
| Incremental | Outbox of changed entities | PASS |
| Idempotent | `idempotency_key` per batch | PASS |
| Duplicate prevention | Unique `(org_id, idempotency_key)` + entity hashes | PASS |
| Retries | Attempt counter + delayed `available_at` | PASS |
| Offline queue | Unprocessed outbox remains local | PASS |
| Conflict | Source version / updated_at fields | PASS (basic) |
| Approved device only | `approval_status=eq.approved` | PASS |

## Contract tests

- `tests/test_incremental_sync.py` — PASS
- Device approval gate asserted in source

## Remediation

- Run a multi-sale / inventory E2E against a staging org and confirm Portal report counts.
- Extend entity coverage if any POS module still lacks outbox triggers.
