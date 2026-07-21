# Web Dashboard Gap Analysis

**Audited:** 2026-07-19
**Tip baseline:** 2.3.91 (not bumped this session)
**Scope:** `web/dashboard-ui` + `web/web_routes.py` + shared `/api/*` in `backend/app.py`

## Counts (post-session)

| Status | Count |
|--------|------:|
| DONE | 14 |
| PARTIAL | 5 |
| PLACEHOLDER | 0 |
| MISSING (cross-cutting features) | see remaining list |

---

## React pages (`web/dashboard-ui/src/routes/`)

| Route | File | Status | Notes |
|-------|------|--------|-------|
| `/` | `index.tsx` | **DONE** | Real KPIs, charts, AI insights, health ring |
| `/live` | `live.tsx` | **DONE** | `/api/live` polling |
| `/approvals` | `approvals.tsx` | **DONE** | Queue + create/approve/reject |
| `/pos` | `pos.tsx` | **DONE** | Web POS against live products/sales |
| `/inventory` | `inventory.tsx` | **DONE** | Search, sort, pagination, CSV/XLSX export |
| `/debt` | `debt.tsx` | **DONE** | Customers + invoices + payments |
| `/reports` | `reports.tsx` | **DONE** | Filters + Excel/CSV/PDF/Print |
| `/notifications` | `notifications.tsx` | **DONE** | Feed + mark read |
| `/health` | `health.tsx` | **DONE** | Scored checks |
| `/backup` | `backup.tsx` | **DONE** | Status + manual run |
| `/branches` | `branches.tsx` | **PARTIAL** | Single-DB; multi-branch revenue N/A |
| `/ai` | `ai.tsx` | **DONE** | Insights + chat with authorized context |
| `/notes` | `notes.tsx` | **DONE** | CRUD notes |
| `/users` | `users.tsx` | **PARTIAL** | List only; create/edit on desktop |
| `/settings` | `settings.tsx` | **DONE** | Shop + telegram settings |
| `/security` | `security.tsx` | **DONE** | Live audit + settings-backed policy |
| `/license` | `license.tsx` | **DONE** | Live `/api/license/status` |
| `/diagnostics` | `diagnostics.tsx` | **PARTIAL** | Health/sync; export/rotate desktop stubs |

## Nav

All sidebar items map to routes. Global search in topbar (`/` or Ctrl+K).

## New / extended APIs (`web/web_routes.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/reports/data` | Filtered sales report JSON |
| `GET /api/reports/export` | `format=xlsx\|csv\|pdf\|html`; `inventory=1` for stock workbook |
| `GET /api/search` | Global search (sales, products, customers, users) — RBAC filtered |
| `GET /api/license/status` | License engine status |
| AI insights/chat | Richer `_cc_today_snapshot` + `_authorized_context_text` + role gates |

## Exports verified (build + code paths)

| Format | Path | Notes |
|--------|------|-------|
| XLSX | `/api/reports/export?format=xlsx` | `export_engine` / `report_export_service` |
| CSV | `format=csv` | UTF-8 BOM |
| PDF | `format=pdf` | Valid PDF 1.4 text report |
| HTML/Print | `format=html` (+ print) | Branded printable |
| Inventory XLSX/CSV | `inventory=1` | Snapshot export |

UI build: `npm run build` **passed** (2026-07-19).

## AI data access / permission model

- Snapshot includes: today sales/revenue, profit, monthly revenue, inventory value, low-stock names, debt/overdue, by-payment, top products (fields omitted if role lacks tab access).
- Cashiers scoped to own sales (`cashier_id`).
- `_user_can(module)` uses `role` + `tab_permissions`.
- Factual Q&A answered from SQLite only; vendor AI gets ground-truth block and must not invent numbers.

## Remaining work

1. Multi-branch live revenue (multi-DB / cloud tenants).
2. Web user create/edit.
3. WebSockets (still polling).
4. Heatmaps / advanced analytics charts.
5. Diagnostics log export/rotate from web.
6. Persistable column visibility on all tables.
7. Expenses KPI without ledger tables stays 0.
8. License activate/renew from web UI.

## Version / Setup

- **Not bumped** — remains **2.3.91**
- **Setup not rebuilt** — source + docs + `dashboard-ui/dist` updated; ship tip when packaging next release
