# Security Audit — MBT Platform v3.0

**Date:** 2026-07-21
**Overall:** PASS (with residual external items)

| Control | Status | Notes |
|---------|--------|-------|
| JWT secret not hardcoded | PASS | `runtime_security.py` / env / AppData |
| Activation HMAC not baked | PASS | Env / runtime secret |
| bcrypt passwords | PASS | New hashes + legacy upgrade on login |
| CORS restricted | PASS | `MBT_CORS_ORIGINS` includes portal hosts |
| Login rate limiting | PASS | Implemented in Flask app |
| Security headers | PASS | Observed on production responses |
| Org-scoped cloud routes | PASS | `require_org_access` |
| Device approval gate for sync | PASS | `approval_status=eq.approved` |
| Supabase RLS / schema v3 | PASS | Applied live |
| Secrets in repo | PASS (guarded) | `deploy.local.json` gitignored; Telegram keys removed |
| Secrets in Docker image | PASS | `.dockerignore` + Fly secrets |
| Secrets in SPA bundles | PASS | No service keys in frontend |
| HTTPS / Cloudflare | PASS | Production portal via CF → Fly TLS |
| CSRF / XSS / SQLi | PARTIAL | Flask JSON APIs + parameterized SQL; SPA CSP present; dedicated CSRF not required for bearer APIs |
| Telegram purge | PASS | Contract test green |
| Code signing | BLOCKED (External) | Certificate required |
| Payment provider | BLOCKED (External) | Not in scope / not activated |

## Findings

1. **Resolved:** Hardcoded JWT / activation secrets removed from production paths.
2. **Resolved:** Device sync requires approved devices.
3. **Resolved:** Supabase Auth uses the verified Resend SMTP configuration and branded templates.
4. **Residual:** Rotate any historical tokens that appeared in local config or chat tooling.

## Remediation

- Keep Cloudflare SSL mode Full (strict) in dashboard (API token currently cannot change it).
- Sign desktop artifacts before public Download Center release.
