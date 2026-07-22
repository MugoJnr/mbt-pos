# MBT Portal — Always-on Fly.io Deployment

Target architecture:

```
portal.mugobyte.com
  → Cloudflare (HTTPS / orange-cloud proxy)
  → Fly.io app `mbt-portal` (Flask API + Portal SPA)
  → Supabase (Auth + Postgres + Storage)
```

Live Dashboard remains on per-shop Cloudflare tunnels (`{shop}.mugobyte.com`) and continues to read live SQLite from Desktop POS. The Portal never reads shop SQLite.

## Current production status (verified)

| Check | Result | Evidence |
|-------|--------|----------|
| Fly health | PASS | `https://mbt-portal.fly.dev/api/health` → 200 |
| Custom domain health | PASS | `https://portal.mugobyte.com/api/health` → 200 via Cloudflare (`CF-RAY`) |
| Portal SPA login | PASS | `https://portal.mugobyte.com/login` renders Sign in |
| Fly TLS cert | PASS | `portal.mugobyte.com` Issued (Let's Encrypt) |
| Cloudflare SSL settings API | BLOCKED (External) | Token lacks Zone Settings write; proxy works with existing zone SSL mode |
| GitHub `FLY_API_TOKEN` | PASS | Deploy token created and set as repo secret on `MugoJnr/mbt-pos` |

## Prerequisites

1. Fly CLI authenticated (`flyctl auth login`)
2. Secrets available as Fly secrets (never baked into the image):
   - `MBT_JWT_SECRET`
   - `MBT_ACTIVATION_HMAC_SECRET`
   - `MBT_SUPABASE_URL`
   - `MBT_SUPABASE_ANON_KEY`
   - `MBT_SUPABASE_SERVICE_KEY`
3. Portal SPA and Live Dashboard SPA built into `web/*/dist`
4. GitHub Actions deployment secrets listed below

## First-time create

```powershell
$env:Path += ";$env:USERPROFILE\.fly\bin"
flyctl apps create mbt-portal --org personal
flyctl volumes create mbt_data --region jnb --size 1 --app mbt-portal
flyctl secrets set `
  MBT_ENV=production `
  MBT_JWT_SECRET="<32+ chars>" `
  MBT_ACTIVATION_HMAC_SECRET="<32+ chars>" `
  MBT_SUPABASE_URL="https://<project>.supabase.co" `
  MBT_SUPABASE_ANON_KEY="<anon>" `
  MBT_SUPABASE_SERVICE_KEY="<service>" `
  MBT_CORS_ORIGINS="https://portal.mugobyte.com,https://www.portal.mugobyte.com" `
  --app mbt-portal
```

## Deploy

OneDrive trees can break Fly's Docker context (`archive/tar: unknown file mode`). Deploy from a clean staging copy:

```powershell
cd extracted\mbt_pos
.\build_web.bat
$dst = "$env:TEMP\mbt-portal-deploy"
robocopy . $dst /MIR /XD .git node_modules __pycache__ .venv venv dist build .pytest_cache
Copy-Item .\web\mugobyte-platform\dist $dst\web\mugobyte-platform\dist -Recurse -Force
Set-Location $dst
flyctl deploy --remote-only --config fly.toml --app mbt-portal
flyctl status --app mbt-portal
flyctl checks list --app mbt-portal
```

Health check path: `/api/health`

## Cloudflare cutover (verified sequence)

1. Deploy and verify `https://mbt-portal.fly.dev/api/health`
2. Point `portal` A/AAAA at Fly IPs (DNS-only first) and issue Fly certs
3. Confirm direct HTTPS works on `portal.mugobyte.com`
4. Enable Cloudflare proxy (orange cloud) once certs are Issued
5. Verify `CF-RAY` header + `/api/health` 200
6. Keep the old local portal tunnel only as emergency rollback for 24h

## GitHub Actions

Workflow: `.github/workflows/portal-production.yml`

The production workflow validates migration hygiene, links the Supabase project,
previews and applies every pending migration, then deploys Fly. A migration
failure stops the job before `flyctl deploy`. After deploy it retries
`https://portal.mugobyte.com/api/health` and requires an HTTP 2xx response.

Required GitHub repository secrets:

- `SUPABASE_ACCESS_TOKEN`: Supabase personal access token used only by the CLI.
  Create it under Supabase Account → Access Tokens.
- `SUPABASE_PROJECT_ID`: project reference from Project Settings → General
  (the short value used in `<project-ref>.supabase.co`).
- `SUPABASE_DB_PASSWORD`: database password from Project Settings → Database.
- `FLY_API_TOKEN`: app-scoped Fly deploy token. Create with
  `flyctl tokens create deploy --app mbt-portal`.

These CI credentials are distinct from the Fly runtime secrets
`MBT_SUPABASE_URL`, `MBT_SUPABASE_ANON_KEY`, and
`MBT_SUPABASE_SERVICE_KEY`. Never put a service-role key, database password, or
access token in source, `supabase/config.toml`, workflow YAML, or build args.

### Migration adoption

The timestamped migration history is in `supabase/migrations`. The four
baseline migrations are deliberately idempotent so the first CI run can adopt
either a fresh database or the existing manually provisioned production
schema. `--include-all` ensures an existing project with no migration-history
rows receives the baseline migrations; later runs apply only new migrations.

Before enabling automatic deployment, preview from a trusted workstation:

```powershell
$env:SUPABASE_ACCESS_TOKEN = '<personal-access-token>'
$env:SUPABASE_DB_PASSWORD = '<database-password>'
supabase link --project-ref '<project-ref>' --password $env:SUPABASE_DB_PASSWORD
python deploy/validate_supabase_migrations.py
supabase db push --linked --include-all --dry-run --password $env:SUPABASE_DB_PASSWORD
```

Do not use `supabase db reset` against a linked production project. New schema
changes must be added as a later timestamped migration; do not edit a migration
after it has reached production.

## Rollback

```powershell
flyctl releases --app mbt-portal
flyctl deploy --image <previous-image> --app mbt-portal
```

Or restore Cloudflare DNS to the previous tunnel origin.
