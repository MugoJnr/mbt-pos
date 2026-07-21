# End-to-End Test Report — MBT Platform v3.0

**Date:** 2026-07-21
**Overall:** PARTIAL PASS

| Scenario | Status | Evidence |
|----------|--------|----------|
| Portal health (Fly) | PASS | `mbt-portal.fly.dev/api/health` 200 |
| Portal health (custom domain + CF) | PASS | `portal.mugobyte.com/api/health` 200 + `CF-RAY` |
| Portal login page | PASS | Browser snapshot |
| Portal register page | PASS | Browser snapshot; no-trial copy visible |
| Automated pytest suite | PASS | 55 tests passed |
| Telegram runtime contract | PASS | `test_no_telegram_runtime` |
| Incremental sync contracts | PASS | `test_incremental_sync` |
| Upgrade data preservation sim | PASS | TEMP simulation |
| Portal SPA build | PASS | Vite |
| Live Dashboard SPA build | PASS | Vite (`dashboard-ui`) |
| Fresh install on clean PC | NOT RUN | Needs built installer |
| Email verification delivery | BLOCKED (External) / NOT RUN | Depends on Supabase mail + provider |
| Full sales → sync → Portal report | NOT RUN | Requires approved device + desktop session |
| Device approve in Portal UI | PASS (code) | Devices page approve/reject wired |
| Offline grace | NOT RUN | Desktop runtime |
| Role isolation | PARTIAL | Admin gate code present; full matrix NOT RUN |
| Live Dashboard separation | PASS (architecture) | Tunnel path distinct from Portal |

## Remediation

Execute a scripted VM certification pack covering fresh install, upgrade, portal login, device approve, sale, sync, and restore.
