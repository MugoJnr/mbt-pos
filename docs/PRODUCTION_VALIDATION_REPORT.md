# MBT POS — Production Validation Report

**Date:** 2026-07-19  
**Validator:** Lead QA / Security / Performance / Release (automated session)  
**Workspace tip:** `extracted/mbt_pos` @ `2.3.94` (`PROD-2026-07-19-v2.3.94`)  
**Evidence:** `C:\Users\mugoj\OneDrive\Desktop\QA_PROD_VALIDATION\`  

---

## Overall readiness: **Not Ready**

Critical path mostly works in tip source, but production cutover is blocked by install skew, mid-flight UI shipping, a still-running stale `:5050` process, and incomplete hardware/cloud checks. Authz leaks found in tip code were **fixed and retested** on a tip Flask instance (`:5055`); they are **not** in the currently installed Program Files build until the next Setup is installed.

### Top blockers

1. **Installed vs tip skew:** Program Files `version.json` = **2.3.73**, `_internal/version.json` = **2.3.91**, Desktop Setup tip file = **v2.3.93**, source `version.json` = **2.3.94**. Runtime `:5050` (build-python long-lived) reported **2.3.87**.
2. **Authz regressions were live on stale server** — cashiers could read shop `inventory_value` / profit / debt summary / backup status / unscoped command-center. Fixed in tip (see Fixes); requires Setup rebuild + install + process restart to land in production.
3. **Mid-flight ship:** Current Sale premium UI (`2.3.94`) landed during validation; avoid treating Desktop `MBT_POS_Setup_v2.3.93.exe` as matching tip.
4. **Cloud backup not logged in** on this machine (`logged_in: false`) — local backup PASS; cloud restore path PARTIAL.
5. **Figma / approved visual baseline missing** (`Desktop/QA_VISUAL_POS` absent) — visual sign-off BLOCKED.
6. **Printer + live M-Pesa** not exercised — BLOCKED by environment.

---

## Inventory (Phase 1)

| Item | Result |
|------|--------|
| Git HEAD at start | `cf603a7` (v2.3.93) — tip moved to `c25cd76` (v2.3.94) during run |
| `version.json` (end) | **2.3.94** |
| Desktop Setup | `MBT_POS_Setup_v2.3.93.exe` present (~52 MB, 01:53) — tip Setup for **2.3.94** not verified on Desktop |
| Web `npm run build` | **PASS** (Vite, ~18s) — chunk size warning only |
| Python import smoke | **PASS** after wizard fix; `desktop.main` loads `APP_VERSION=2.3.93` then tip `2.3.94` |
| Packaged `_internal` | **PASS** — `cloudflared.exe` + `web/dashboard-ui/dist` present in dist and Program Files |

---

## Modules tested

| Module | Result | Notes |
|--------|--------|-------|
| SQLite integrity / FK | **PASS** | `integrity_check=ok`, `foreign_key_check=0`, 0 orphan `sale_items`, 1433 sales |
| Auth login (admin) | **PASS** | `admin` / `admin123` → `superadmin` |
| Authz (cashier) tip | **PASS** (after fix) | Retest on `:5055` — see below |
| Authz (cashier) live `:5050` | **FAIL** (stale process) | Pre-fix leaks observed |
| API health / version / live / search | **PASS** | On `:5050` |
| Reports export csv/xlsx/pdf | **PASS** | Evidence files saved under QA folder |
| AI insights (admin) | **PASS** | Authorized snapshot + alerts; vendor key seeded |
| AI insights (cashier scope) | **PASS** (after fix) | `scope=own_sales`, `inventory_value=None`, `profit=None` |
| License status | **PASS** | Valid ~363 days remaining |
| Local auto-backup | **PASS** | `create_local_backup` + `/api/backup/run` |
| Cloud backup | **PARTIAL** | Configured path present; not logged in |
| Desktop login / MainWindow | **PASS** | Offscreen smoke |
| Desktop Sales / Inventory tabs | **PARTIAL** | Tab navigation OK; cart-add harness BLOCKED; edit dialog PARTIAL |
| PaymentVarianceDialog | **PASS** | Default handling = **Return Change** |
| Web dashboard / POS / Reports / AI | **PASS** (Vite `:5173`) | Real pages, not placeholders; POS 3-panel loads products |
| Web SPA deep links via stale `:5050` | **FAIL** | `/pos` etc. 404 on long-lived 2.3.87 process (client router OK on Vite) |
| Installer silent abort UX | **PARTIAL** | `installer.nsi` abort warning disabled; `installer_staged.nsi` still has `MUI_ABORTWARNING` |
| Figma visual | **BLOCKED** | No Figma URL; no `QA_VISUAL_POS` |
| Hardware printer | **BLOCKED** | No printer exercised |
| Live M-Pesa STK | **BLOCKED** | Manual mode / no live gateway test |

---

## Tests performed

### Backend / API / DB

- PRAGMA integrity + foreign_key_check on AppData SQLite.
- Login + bearer probes: `/api/version`, `/health`, `/health/detail`, `/search`, `/license/status`, `/backup/status`, `/backup/run`, `/ai/insights`, `/reports/export` (csv/xlsx/pdf), `/command-center/summary`, `/live`.
- Unauth probes → **401** on reports export, backup/run, insights, users.
- Injection spot-check on `/api/search` (`' OR '1'='1`, XSS string, `" OR 1=1 --`) → **200**, no 500.
- Cashier (`Eugene` / `cashier123`) matrix before/after fix.
- Tip Flask `:5055` retest of authz after code change.

### Desktop

- Import: `desktop.main`, tabs, `PaymentVarianceDialog`, AI config, `backend.local_db_backup`.
- Offscreen harness `scripts/qa_prod_desktop_smoke.py`: login, dashboard, sales/inventory navigate, variance dialog screenshot, settings/reports shot_only.
- Process exit code `3221226505` after PASS results (Qt teardown crash) — functional asserts still recorded.

### Web

- `npm run build` clean.
- Browser: login → Point of Sale (3-panel, products, cart chrome) → Reports (export buttons present) → AI Center (insights/chat shell).
- Responsive resize snapshot not saved as separate mobile evidence (desktop viewport exercised; mark PARTIAL).

### AI / Backup / Install assets

- `ensure_vendor_ai_seeded()` → True; `is_ai_configured` True (key **redacted** in evidence logs).
- Local zip backup created under AppData `backups\`.
- Confirmed `cloudflared.exe` in Program Files `_internal` and dist.

---

## Issues found + fixes applied

| Severity | Issue | Fix | Status |
|----------|-------|-----|--------|
| **Critical** | Cashier could read shop `inventory_value`, profit, debt, backup status, unscoped CC summary (`_user_can` aliases + ungated routes) | Tightened aliases; added `inventory_value` gate; gated `debt/summary`, `backup/status`; scoped `cc_summary` + `_sales_where` | **Fixed in tip** — commit below |
| **High** | `setup_wizard.py` literal `\n` corruption → `SyntaxError` blocking `desktop.main` import | Restored real newlines in settings dict | **Fixed** |
| **Medium** | JWT HMAC key 28 bytes (`InsecureKeyLengthWarning`) | Not changed this session (coordinate with secret rotation) | Open |
| **Medium** | Stale `:5050` / PF install skew vs tip | Operational: restart source server + install latest Setup | Open |
| **Low** | `installer_staged.nsi` still defines `MUI_ABORTWARNING` | Not changed (ship uses `installer.nsi` which is soft) | Open |
| **Info** | Search `/api/search?q=a` returned empty for admin (indexing/UX) | Not treated as blocker | Observe |

### Commit

- **Message:** `fix cashier finance data leaks and setup_wizard SyntaxError.`
- **Files:** `web/web_routes.py`, `desktop/wizard/setup_wizard.py`, `scripts/qa_prod_desktop_smoke.py`
- Version **not** bumped (left to ship agents; tip already at 2.3.94).

### Authz retest (tip `:5055`, post-fix)

| Endpoint | Admin | Cashier |
|----------|-------|---------|
| `/api/ai/insights` | 200 | 200 — `inv=None`, `profit=None`, `scope=own_sales` |
| `/api/command-center/summary` | 200 | 200 — `inv=None`, `debts=None`, `scope=own_sales` |
| `/api/backup/status` | 200 | **403** |
| `/api/backup/run` | 200 | **403** |
| `/api/debt/summary` | 200 | **403** |
| `/api/users` | 200 | **403** |
| `/api/license/status` | 200 | **403** |
| `/api/customers` | 200 | 200 — **no** `total_outstanding` |
| `/api/reports/export` | 200 | 200 — own-sales scoped via `_sales_where` |

---

## Remaining risks

- Production machines on older Setup will still serve pre-fix authz until Upgrade.
- Long-lived Python `:5050` in this workspace was **not** restarted (avoid disrupting other agents) — still old code.
- Cloud backup login / remote restore untested.
- Desktop offscreen screenshots for some tabs appear minimal/blank (~30 KB) — visual desktop QA incomplete vs on-screen UAT.
- Mid-flight Current Sale UI (`2.3.94`) needs its own focused regression before calling the latest tip “frozen.”
- Short JWT secret length.
- No live till printer / STK M-Pesa proof.

---

## Evidence index

`C:\Users\mugoj\OneDrive\Desktop\QA_PROD_VALIDATION\`

- `web_dashboard_build.log`
- `import_smoke.log`, `desktop_import_backup_ai.log` (secrets redacted)
- `phase2_api_complete.log`, `phase2_api_results.json`
- `authz_cashier.log` (stale `:5050`), `authz_cashier_tip5055.log` (post-fix)
- `export_sales.csv` / `.xlsx` / `.pdf`
- `desktop_smoke_results.json`, `desktop_smoke.log`, `desktop_shots\*.png`
- `phase6_install_assets.log`

---

## Verdict

**Not Ready** for declaring production-ready cutover on customer machines.

Tip source after this session’s authz/wizard fixes is in good shape for a **follow-up Setup rebuild + install verification**, but the **currently installed** Program Files tree and the **stale** runtime process do not match that tip, visual/Figma sign-off is missing, and cloud/hardware paths remain PARTIAL/BLOCKED.
