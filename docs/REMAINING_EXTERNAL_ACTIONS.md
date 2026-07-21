# Remaining External Actions Checklist

**Date:** 2026-07-21

| Action | Owner | Status | Why blocked / needed |
|--------|-------|--------|----------------------|
| Code-signing certificate for Windows installer/exe | Business / cert authority | BLOCKED (External) | Required for trusted Download Center releases |
| Configure production email provider (Resend/SMTP) + Supabase Auth mail | Platform admin | PASS | Fly Resend OK; Supabase Auth Custom SMTP → Resend; branded Auth templates (confirm/reset/magic/invite/email-change) with MugoByte shell; Site URL + redirects (`/auth/callback`, `/reset-password`, `/verify-email`); email rate limit 100/hr; live delivery verified 2026-07-21 |
| Cloudflare SSL mode Full (strict) | Platform admin | PASS | Set via dashboard 2026-07-21; API token still DNS-only (Zone Settings write not required now) |
| Payment-provider activation | Business | BLOCKED (External) | Commercial billing not activated in this loop |
| Domain ownership changes | N/A | PASS | `portal.mugobyte.com` already on Fly via Cloudflare |
| GitHub `FLY_API_TOKEN` | Engineering | PASS | Set on `MugoJnr/mbt-pos` |
| Full desktop/NSIS release build on clean agent | Engineering CI | NOT RUN | OneDrive tar quirks; use staging agent |
| Publish signed installer + checksums to Download Center | Release manager | NOT RUN | Depends on signing |
| Customer pilot on production device approval queue | Ops | NOT RUN | Human approval workflow |

## Completed external ops this loop

- Fly app deploy + always-on volume
- Custom domain certificates
- Cloudflare DNS A/AAAA + proxy enablement
- GitHub Actions deploy secret
- Resend API key + verified `mugobyte.com` domain (DKIM/SPF DNS on Cloudflare)
- Cloudflare SSL/TLS → **Full (strict)**
- Branded transactional send from `noreply@mugobyte.com`
- Supabase Auth Custom SMTP → Resend (`smtp.resend.com`, sender `noreply@mugobyte.com`)
- Auth Site URL + redirect allowlist for `portal.mugobyte.com` (`/auth/callback`, `/reset-password`, `/verify-email`)
- Branded Supabase Auth email templates + email send rate limit raised to 100/hr
- Portal register + `/api/cloud/auth/resend-verification` wired; verification mail delivered via Resend

## Do not claim complete until

1. Signed installer published
2. One full VM fresh+upgrade certification green
