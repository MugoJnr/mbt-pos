# portal.mugobyte.com — Live Configuration

**Status:** LIVE (2026-07-21)
**URL:** https://portal.mugobyte.com/login

## What was wrong
DNS `portal.mugobyte.com` pointed at the **edmus shop tunnel** (`mbt-pos-edmus`), whose ingress only allowed `edmus.mugobyte.com` → Cloudflare returned **404**.

## What was configured

### Cloudflare
| Item | Value |
|------|--------|
| Tunnel | `mbt-portal` (`b8a6442b-b035-4d72-bc27-1fdd8c643dc5`) |
| Ingress | `portal.mugobyte.com` → `http://127.0.0.1:5050` (Host header forced) |
| DNS | CNAME `portal` → `b8a6442b-….cfargotunnel.com` (proxied) |
| DNS | CNAME `www.portal` → same tunnel |

### Local connector
- Token: `%LOCALAPPDATA%\MugoByte\MBT Portal\tunnel_token.txt`
- Autostart: Startup folder shortcut `MugoByte Portal Tunnel.lnk`
- Requires MBT POS / Flask listening on `127.0.0.1:5050` (Host-based SPA serves Portal)

### Supabase (`mbt-pos` / `uynfglgttkaibyeglsrt`)
- Site URL: `https://portal.mugobyte.com`
- Redirect URLs: `https://portal.mugobyte.com/**`

### Separation preserved
- Live shop: `{shop}.mugobyte.com` (e.g. edmus) → shop tunnels → Live Dashboard
- Portal: `portal.mugobyte.com` → `mbt-portal` tunnel → Portal Workspace SPA

## Ops note (next hardening)
This PC must stay online for Portal to respond. For always-on production, migrate origin to Fly.io / Cloudflare Pages + API and keep the same DNS hostname.
