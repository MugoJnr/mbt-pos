# MBT Platform v3.0 — Production Readiness Report

**Date:** 2026-07-21
**Scope:** Portal + Fly monolith + Desktop onboarding + licensing + sync + installer upgrade path

## Overall: CONDITIONAL PASS (automatable core complete; external blockers remain)

| Gate | Status | Evidence |
|------|--------|----------|
| Portal builds | PASS | `web/mugobyte-platform` Vite build; route-split chunks |
| Live Dashboard builds | PASS | `web/dashboard-ui` Vite build |
| Desktop builds | NOT RUN | Full PyInstaller/NSIS packaging not executed in this loop |
| Installer builds | NOT RUN | NSIS compile not executed; `installer.nsi` reviewed |
| Fresh installation | NOT RUN | Requires signed installer + customer VM |
| Upgrade installation | PASS (simulated) | TEMP upgrade sim preserved DB/WAL/SHM/settings/license while replacing binary |
| Existing customer data preserved | PASS (design + sim) | `installer.nsi` backups under `$LOCALAPPDATA` |
| Portal-first onboarding | PASS (code) | Wizard order: Portal Account → License → Shop → Admin → Printer → Live Dashboard |
| Device registration | PASS (code + API) | `register_or_refresh_device` + `/api/cloud/devices/register` |
| License activation | PASS (code) | Cloud activation paths; no trial auto-seed |
| Device transfer | PASS (code) | Existing transfer APIs retained |
| Offline grace | NOT RUN | Requires desktop runtime exercise |
| Synchronization | PASS (code + contract tests) | Outbox + `/api/cloud/sync/batch` + approved-device gate |
| Reports | PARTIAL | Report engine present; email delivery not end-to-end verified |
| Downloads | NOT RUN | Portal downloads UI exists; artifact hosting not certified |
| Updates | NOT RUN | Update publish path requires platform admin + signed artifacts |
| Backups / Restore | PARTIAL | Code paths exist; cloud restore offered in wizard after login |
| Email notifications | PASS | Resend on Fly + Supabase Auth SMTP; `mugobyte.com` verified; branded confirm/reset from `noreply@mugobyte.com` delivered |
| Telegram runtime = 0 | PASS | `tests/test_no_telegram_runtime.py` |
| Security review | PASS (with notes) | See `SECURITY_AUDIT.md` |
| Performance review | PASS (baseline improved) | See `PERFORMANCE_REPORT.md` |
| Documentation | PASS | This set of reports |
| Critical production hosting | PASS | `portal.mugobyte.com` health 200 via Cloudflare → Fly |

## Architecture verification

```
portal.mugobyte.com → Cloudflare → Fly `mbt-portal` → Supabase
Desktop POS SQLite = operational source of truth
Live Dashboard = live shop ops only (tunnel)
Portal = synchronized cloud data only
```

## Remediation for FAIL / BLOCKED / NOT RUN

1. Run full desktop + NSIS build; upload to Portal Download Center with checksums/signatures.
2. Obtain code-signing certificate and sign installer/exe.
3. ~~Confirm Supabase Auth email (verify/reset) uses desired provider/templates alongside Portal Resend.~~ **DONE** 2026-07-21.
4. Execute full E2E on a clean Windows VM (fresh + upgrade).
