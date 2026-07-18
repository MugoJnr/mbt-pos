# MBT Business Command Center - Implementation Report

**Version:** **2.3.88** (shipped)  
**Ship date:** 2026-07-18  
**Setup:** `MBT_POS_Setup_v2.3.88.exe` (GitHub release `v2.3.88`)

## Patch 2.3.88 (AI chat sales)

AI Command Center chat returned **0 sales** while Insights showed real totals because chat used `api=None`. Fixed with `_WebPosApi` shim, `_cc_today_snapshot` from SQLite, and factual sales answers grounded in the same totals as Insights.

---

## Prior: 2.3.87

**Version:** **2.3.87**  
**Setup:** `MBT_POS_Setup_v2.3.87.exe`

## Ship status

| Check | Result |
|-------|--------|
| Code + routes implemented | **Yes** |
| Dashboard `dist` in Setup package | **Yes** (BUILD.bat step 2e) |
| Version bump 2.3.87 | **Yes** |
| Setup.exe / GitHub release | **In progress / published with this ship** |
| Hot-deploy required for shops | **No** — durable installer release |

## What was added

### App shell
- Desktop sidebar retained (lg+), nav grouped: Overview / Operations / Command / Admin
- Branding subtitle: **COMMAND CENTER**
- Mobile bottom nav (lg:hidden): Dashboard Â· Live Â· Approvals Â· Inventory Â· More
- More opens the full drawer; main content has bottom padding so it is not obscured
- Notification bell in topbar â†’ `/notifications` (unread badge)
- Online status via lightweight `/api/health` ping (~30s)
- Footer version from `/api/version` (reads `version.json`)
- Keyboard: `/` or `g` then `d` â†’ Dashboard

### New pages (TanStack file routes)
| Route | Purpose |
|-------|---------|
| `/approvals` | Remote approvals queue (void, refund, discount, override, stock, expense, credit) |
| `/live` | Live monitoring (sales, cashiers, sync, backup, AI) â€” 20s refresh |
| `/health` | Scored system health ring + check cards |
| `/notifications` | Polling feed (low stock, large sale, sync, backup, â€¦) |
| `/backup` | Backup status, cloud hint, manual run, history |
| `/branches` | Branch list + context switch (localStorage + SQLite) |
| `/ai` | Insights panel + chat (AI when configured, else heuristics) |

### Executive dashboard (`/`)
- Extra KPIs: profit, monthly revenue, expenses, inventory value, debts, cash-flow proxy
- AI Insights card, health score ring â†’ `/health`, recent activity, mobile-friendly sales list
- Summary refetch every 60s

### Backend (`web/web_routes.py`)
New SQLite tables (auto-created): `cc_approvals`, `cc_notifications`, `cc_backup_history`, `cc_branches`

| Endpoint | Auth | Notes |
|----------|------|-------|
| `GET /api/version` | no | From `version.json` |
| `GET /api/command-center/summary` | yes | KPI aggregates |
| `GET/POST /api/approvals` | yes | List / create |
| `POST /api/approvals/<id>/approve\|reject` | yes | Manager+ |
| `GET /api/notifications` | yes | Seeds situational alerts |
| `POST /api/notifications/<id>/read` | yes | |
| `POST /api/notifications/read-all` | yes | |
| `GET /api/health/detail` | yes | Scored checks |
| `GET /api/live` | yes | Live monitor payload |
| `GET /api/backup/status` | yes | |
| `POST /api/backup/run` | yes | Cloud if available, else local DB copy |
| `GET /api/branches` | yes | |
| `POST /api/branches/<id>/select` | yes | |
| `GET /api/ai/insights` | yes | |
| `POST /api/ai/chat` | yes | |

Existing `GET /api/health` unchanged (ping).

## How to open / verify

1. Build UI:
   ```bash
   cd extracted/mbt_pos/web/dashboard-ui
   npm install
   npm run build
   ```
   Dist is served from `web/dashboard-ui/dist` by Flask (`web_routes.py`).

2. Start POS / web service as usual (desktop â€œAccess POS through web dashboardâ€ or Flask on port 5050).

3. Open the dashboard URL, log in, then visit:
   - `/` Dashboard KPIs + health ring
   - `/approvals` create â†’ approve/reject
   - `/live` watch auto-refresh
   - `/health`, `/notifications`, `/backup`, `/branches`, `/ai`
   - Resize to phone width: bottom nav + card layouts

## Known gaps vs full master prompt

- No heatmap / advanced chart suite on executive dashboard (kept KPI + lists)
- Multi-branch revenue comparison is placeholder (single local DB)
- Cloud backup run requires desktop cloud login; otherwise local SQLite snapshot only
- AI chat uses vendor AI only when configured/online; otherwise heuristics
- Expenses KPI is 0 unless accounting ledger tables exist
- Diagnostics â€œExport / Rotate logsâ€ remain desktop-oriented stubs
- Real-time websockets not used â€” polling intervals instead

## Files touched (summary)

- `web/web_routes.py` â€” Command Center APIs
- `web/dashboard-ui/src/components/app-shell.tsx`, `ui-kit.tsx`
- `web/dashboard-ui/src/routes/` â€” index + new pages + diagnostics
- `docs/COMMAND_CENTER_REPORT.md` â€” this file

