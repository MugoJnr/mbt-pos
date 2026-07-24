# MBT POS v3 — Final Production Acceptance Report

**Gate date:** 2026-07-24 (EAT)  
**Auditor posture:** Brand-new commercial customer / release gate (evidence-only)  
**Evidence root:** `extracted/mbt_pos/_qa_acceptance_final/`  
**Rule:** PASS only if verified in this session. Otherwise PARTIAL / FAIL / **NOT VERIFIED**.

---

## 1. Executive Summary

MBT POS tip source and local `dist\MBT_POS_Setup.exe` are labeled **3.0.11** (`RC-2026-07-23-v3.0.11`) with matching Setup SHA-256. Core commerce APIs remain strong (**235 passed / 9 failed** pytest). Portal login, cloud KPIs, licenses, devices, downloads UI, and Live Dashboard (`testshop.mugobyte.com`) all respond.

**However, this build is not customer-ready as a release cut.** The machine customers would actually run is still **Program Files 3.0.9**; GitHub / Download Center “latest” still points at **v3.0.4**; packaged `_internal/version.json` carries a **stale checksum**; UI polish gates remain below the stated ≥98% bars (ChatGPT checkout peak **97%**, Claude system peak **90%**); Live Dashboard shows **Backup ERROR**; 100k-product / multi-day supermarket simulation was **not** executed.

**Verdict:** **NOT READY FOR PRODUCTION**  
**Production readiness score:** **64 / 100**

---

## 2. Production Readiness Score (0–100%)

| Area | Weight | Score | Notes |
|------|-------:|------:|-------|
| Core POS / inventory / debt / reports (API gates) | 25 | 20 | Strong pytest coverage; 9 failures incl. snappy cache |
| Installer / upgrade / version hygiene | 20 | 8 | Setup 3.0.11 OK locally; PF=3.0.9; GH=v3.0.4; checksum skew |
| Portal / cloud / live | 15 | 11 | Login + modules work; billing Soon; `/licenses` deep-link 404 |
| Offline / license grace | 10 | 7 | Unit/offline gate PASS; full NIC-down UAT NOT VERIFIED |
| UI/UX polish | 15 | 7 | Claude 90%; ChatGPT not all ≥98% |
| Performance / stress | 10 | 3 | ~650 products only; 100k NOT VERIFIED |
| Security / authz | 5 | 4 | Login lockout/session/PIN gates present; field authz matrix not re-run full |
| Hardware / printing / STK | — | 0 contrib | NOT VERIFIED (blocks absolute 100) |
| **Total** | **100** | **64** | |

---

## 3. Version Under Test (mandatory clarity)

| Artifact | Version | Evidence |
|----------|---------|----------|
| Source `version.json` | **3.0.11** / `RC-2026-07-23-v3.0.11` | `version.json` |
| `desktop/main.py` `APP_VERSION` | **3.0.11** | version probe |
| `dist\MBT_POS_Setup.exe` FileVersion | **3.0.11** | PE version + size 60,196,285 (2026-07-23 21:54) |
| Setup SHA-256 (measured) | `8761cf5705760078b8c8faf34a306ba34cf3496c971a40b910bb029618bc372e` | matches root `version.json` + `.sha256` sidecar |
| `dist\MBT_POS\_internal\version.json` checksum | **MISMATCH** `57704eef…` | `logs/checksum_skew.txt` |
| Installed Program Files | **3.0.9** | `C:\Program Files\MugoByte\MBT POS\` + Desktop shortcut target |
| Portal “This device / App version” | **v3.0.9** | `screenshots/portal_license_page.png`, `portal_devices.png` |
| GitHub `releases/latest` | **v3.0.4** (2026-07-22) | `gh api` |
| Portal Download Center | Links to Setup + “Open latest GitHub release asset” | `screenshots/portal_downloads.png` |

**Implication:** A brand-new customer using Download Center / GitHub today does **not** get tip 3.0.11. Even this QA PC’s “installed” POS is **two patches behind** local Setup.

---

## 4. Final Acceptance Checklist (every item)

Legend: ✅ PASS · ⚠ PARTIAL · ❌ FAIL · ◌ NOT VERIFIED

### Installation
| Item | Status | Evidence |
|------|--------|----------|
| Installer | ⚠ PARTIAL | Setup 3.0.11 present + PE version OK; **full silent customer install of 3.0.11 onto Program Files not executed this gate** (shop data protection). Upgrade sim **PASS** (`logs/qa_upgrade_sim.txt`). |
| Upgrade | ⚠ PARTIAL | `qa_upgrade_sim` PASS; live PF still on 3.0.9 → upgrade to tip **not field-verified**. |
| First launch | ⚠ PARTIAL | Portable `dist\MBT_POS\MBT_POS.exe` launched under `MBT_DATA_ROOT=…\MBT POS QA`, stayed alive ~10s (~95 MB WS), then killed (`logs/portable_launch.txt`). Wizard/first-run UX **not** fully walked on clean profile. |
| Activation | ⚠ PARTIAL | Portal licenses list 10 MBT POS keys; org has claimed/bound + unassigned keys. Desktop activation of **3.0.11** on clean PC **NOT VERIFIED**. Portal “This device” shows Not valid / fallback (browser context). |
| Licensing | ⚠ PARTIAL | Offline grace unit tests PASS (`test_license_offline_grace` in offline subset). Portal license UI works at `/license`. Deep link `/licenses` → **404**. |

### Portal
| Item | Status | Evidence |
|------|--------|----------|
| Account | ✅ PASS | Login as prior QA account → dashboard “Welcome back, Amina Otieno”, org **testshop**. |
| Devices | ✅ PASS | Devices page: 4 cloud devices, approve/rename/deactivate controls visible. |
| Licensing | ⚠ PARTIAL | `/license` lists 10 keys; header still “Not activated yet” for browser engine mirror; `/licenses` 404. |
| Updates | ❌ FAIL | Downloads → GitHub latest = **v3.0.4** while tip Setup is **3.0.11**. Customers cannot get current build via published channel. |
| Remote management | ⚠ PARTIAL | Devices/approvals UI present; command-center end-to-end approve from desktop **NOT VERIFIED** this session. |
| Cloud sync | ⚠ PARTIAL | Dashboard KPIs (Gross 29.7K / Collected 26.3K / Debt 660 / 108 txns) + “Last sync”; Live shows Sync clear. Full conflict/offline-queue UAT **NOT VERIFIED**. |

### Shop Setup
| Item | Status | Evidence |
|------|--------|----------|
| Business creation | ⚠ PARTIAL | testshop exists in portal; wizard fresh-create journey **NOT VERIFIED** this gate. |
| Taxes | ◌ NOT VERIFIED | Code/settings exist; not exercised end-to-end here. |
| Receipt setup | ◌ NOT VERIFIED | — |
| Payment methods | ⚠ PARTIAL | API payment-method tests historically covered; UI cash/M-Pesa/card not re-walked on 3.0.11 UI this session. |

### Inventory
| Item | Status | Evidence |
|------|--------|----------|
| Products | ⚠ PARTIAL | DB: **651** products (prod + QA); Live Inventory Value ~KES 1.08M / 617 SKUs. CRUD gates in pytest historically; not re-UAT’d on 3.0.11 UI. |
| Categories | ⚠ PARTIAL | Code + category gates exist; UI **NOT VERIFIED**. |
| Stock | ⚠ PARTIAL | Live alert **362 low stock**; integrity_check=ok. |
| Purchases | ◌ NOT VERIFIED | Receiving/PO full UAT not run. |
| Suppliers | ⚠ PARTIAL | Code paths + prior gates; live UI **NOT VERIFIED**. |
| Customers | ⚠ PARTIAL | DB 10–16 customers; CRUD UI **NOT VERIFIED**. |
| Imports | ◌ NOT VERIFIED | — |
| Exports | ⚠ PARTIAL | Report export gates in pytest suite; large-file import/export **NOT VERIFIED**. |

### Checkout
| Item | Status | Evidence |
|------|--------|----------|
| Checkout Pro | ⚠ PARTIAL | Present in source/layouts; ChatGPT score **96%** (iter22) — below ≥98% gate. |
| Product Explorer | ⚠ PARTIAL | ChatGPT **97%** (iter22). |
| Retail Classic | ✅ PASS* | ChatGPT **98%** (iter22). *Valid score; not re-scored this session. |
| Barcode workflow | ⚠ PARTIAL | `P01SearchBarcodeGate` **FAILED** this run (`_show_empty_overlay` AttributeError). |
| Keyboard workflow | ◌ NOT VERIFIED | F9 etc. in code; not timed UAT. |
| Touch workflow | ◌ NOT VERIFIED | Touch-target gate **FAILED** (`test_u04…`). |
| Refunds | ⚠ PARTIAL | Return dialog wired in `panel_factory` (“Return / Exchange”); brittle test looking in `sales_tab.py` **FAILED**. |
| Returns | ⚠ PARTIAL | Same; `test_partial_return_restocks…` **FAILED** (400 vs 300). |
| Exchanges | ◌ NOT VERIFIED | Return/Exchange dialog exists; full exchange path not UAT’d. |
| Split payments | ⚠ PARTIAL | API payment tests in suite; UI **NOT VERIFIED**. |
| Credit sales | ⚠ PARTIAL | Debt/credit gates historically; Live outstanding KES 660. |
| Receipt printing | ◌ NOT VERIFIED | No physical printer exercised. |
| Receipt reprint | ⚠ PARTIAL | Code path present; hardware **NOT VERIFIED**. |
| Offline checkout | ⚠ PARTIAL | `test_offline_launch` + grace subset **PASS**; NIC-down sale UAT **NOT VERIFIED**. |

### Dashboard
| Item | Status | Evidence |
|------|--------|----------|
| KPIs | ✅ PASS | Live Dashboard KPIs load (monthly KES 11,570, inventory, debts). Portal cloud KPIs load. |
| Charts | ⚠ PARTIAL | Chart shells present; “No hourly data yet” for today. |
| Alerts | ⚠ PARTIAL | Low stock + credit + **Backup ERROR** shown. |
| Responsiveness | ◌ NOT VERIFIED | Mobile/tablet live dash resize not measured. |

### Reports
| Item | Status | Evidence |
|------|--------|----------|
| Accuracy | ⚠ PARTIAL | API report gates largely in green suite; full accountant UAT **NOT VERIFIED**. |
| Filters | ⚠ PARTIAL | Code-backed; UI **NOT VERIFIED**. |
| Export | ⚠ PARTIAL | xlsx/html export gates in suite; PDF via browser print path. |
| Printing | ◌ NOT VERIFIED | — |

### Users
| Item | Status | Evidence |
|------|--------|----------|
| Roles | ⚠ PARTIAL | `test_permissions_matrix` in suite (passed within 235). Live login admin works. |
| Permissions | ⚠ PARTIAL | Unit matrix OK; cashier live matrix **not re-run** this session. |
| Audit logs | ⚠ PARTIAL | Code/gates exist; UI Security tab **NOT VERIFIED** on 3.0.11. |
| Security | ⚠ PARTIAL | Lockout/session/PIN tests present; see Security section. |

### Settings
| Item | Status | Evidence |
|------|--------|----------|
| Every settings page | ◌ NOT VERIFIED | `test_settings_keys_wired` historically PASS; not re-audited page-by-page on UI. |
| Every toggle | ◌ NOT VERIFIED | — |
| Backup | ⚠ PARTIAL | Local backup gate in offline subset PASS; Live UI shows **Backup ERROR**. |
| Restore | ⚠ PARTIAL | `test_db_backup_restore_gate` in PASS subset; cloud restore UAT **NOT VERIFIED**. |
| Themes | ⚠ PARTIAL | Theme toggle present on Live; desktop persist gate in suite. |
| Integrations | ◌ NOT VERIFIED | — |

### Printing
| Item | Status | Evidence |
|------|--------|----------|
| Receipt printer | ◌ NOT VERIFIED | No hardware. |
| A4 | ◌ NOT VERIFIED | — |
| PDF | ⚠ PARTIAL | HTML→print path / prior exports; not re-proven. |
| Excel | ⚠ PARTIAL | Export gates. |
| CSV | ⚠ PARTIAL | Prior validation; not re-run. |

### Offline
| Item | Status | Evidence |
|------|--------|----------|
| Complete offline operation | ◌ NOT VERIFIED | Would require NIC block + hours of till use. |
| Sync after reconnect | ◌ NOT VERIFIED | — |
| Data integrity | ⚠ PARTIAL | SQLite integrity_check=ok on shop DBs; offline unit suite PASS. |

### Web Dashboard (Live)
| Item | Status | Evidence |
|------|--------|----------|
| Remote management | ⚠ PARTIAL | Login OK; modules listed; deep feature UAT limited. |
| Analytics | ⚠ PARTIAL | KPIs + activity feed visible. |
| Inventory | ⚠ PARTIAL | Link present; list page not fully walked. |
| Reports | ⚠ PARTIAL | Nav present. |
| Mobile | ◌ NOT VERIFIED | — |
| Desktop | ✅ PASS | Login + dashboard screenshot captured. |

### AI
| Item | Status | Evidence |
|------|--------|----------|
| AI assistant | ⚠ PARTIAL | Portal AI Insights Beta + Live AI Center nav; live chat UAT **NOT VERIFIED**. |
| Error handling | ⚠ PARTIAL | `test_ai_no_fabricate` in green suite historically. |
| Offline behaviour | ◌ NOT VERIFIED | — |

### Performance
| Item | Status | Evidence |
|------|--------|----------|
| Large database | ❌ FAIL / NOT VERIFIED | Only **~650 products / ~1.4–1.5k sales** — nowhere near 100k / millions. |
| Speed | ⚠ PARTIAL | Portable launch ~10s alive; POS snappy **tests FAILED** (catalog cache). |
| Memory | ⚠ PARTIAL | ~95 MB WS at early launch only. |
| Stability | ⚠ PARTIAL | No multi-day supermarket simulation. |

### UI/UX
| Item | Status | Evidence |
|------|--------|----------|
| Consistency | ⚠ PARTIAL | Portal polished; Claude system **90%**; Inventory historically weak (78%). |
| Accessibility | ⚠ PARTIAL | Live login contrast concerns on capture; no a11y audit. |
| Responsiveness | ◌ NOT VERIFIED | — |
| Polish | ❌ FAIL vs stated ≥98% bars | ChatGPT overall **97%** (not all layouts ≥98%); Claude **90%**. |

### Security
| Item | Status | Evidence |
|------|--------|----------|
| Authentication | ✅ PASS | Portal + Live login succeeded with known QA credentials. |
| Authorization | ⚠ PARTIAL | Role matrix unit tests in suite; live cashier retest **NOT VERIFIED** this gate. |
| Session handling | ⚠ PARTIAL | Session/idle tests exist; not field-timed. |
| Data protection | ⚠ PARTIAL | No Telegram runtime gate in suite; code signing **NOT VERIFIED**; secrets in capture scripts are a process risk (see defects). |

---

## 5. Defects

### Critical
1. **Published download channel is stale:** GitHub `latest` = **v3.0.4**; Portal Downloads points customers there — tip is **3.0.11**.
2. **Field install skew:** Program Files + Desktop shortcut still **3.0.9** while local Setup is **3.0.11** (offline 3.0.10 + snappy 3.0.11 not on installed tree).
3. **Packaged checksum skew:** `dist\MBT_POS\_internal\version.json` checksum ≠ actual Setup SHA-256 → unattended update risk.

### High
4. **pytest gate red:** 9 failed including POS snappy cache, barcode filter overlay, return restock math, touch targets, brand compliance (BOM/`utf-8` read and/or installer shortcut assertion).
5. **Live Dashboard Backup ERROR** badge while System Health 97 — operators will distrust backups.
6. **UI polish gates unmet:** Claude system **90%**; ChatGPT checkout not all ≥98%.
7. **SPA deep-link `/licenses` returns 404** (correct route is `/license`) — bookmark/share breakage.
8. **Business-day feature** exists in tip source/tests but **installed 3.0.9** cannot be claimed to include it; not proven in last customer Setup path.

### Medium
9. Portal license header “Not activated yet” / browser device “Not valid” while org has active claimed keys — confusing for owners.
10. Device roster shows duplicate EUGENE-LENOVO entries / `vunknown` versions — hygiene issue.
11. Return/Exchange label moved to `panel_factory.py` but gates still scrape `sales_tab.py` — false-negative CI.
12. `version.json` UTF-8 BOM breaks naive `utf-8` JSON loads (brand test).
13. Billing marked **Soon**; AI Insights **Beta** — OK if disclosed, not “complete product”.
14. 362 low-stock SKUs + Biz score 45 vs System 97 — operational/data quality signal.

### Low
15. Desktop littered with historical Setup EXEs (support confusion risk, not product bug).
16. Capture scripts store portal passwords in-repo (process/security hygiene).
17. Live login capture appeared very low-contrast before dashboard paint.
18. Dual uninstall registry leftovers (3.0.9 + older 3.0.3 entry observed earlier).

---

## 6. UI/UX Recommendations

1. Do not ship claiming “≥98% ChatGPT/Claude” until scores are re-measured on the **exact Setup** customers get.
2. Fix Inventory density/overflow (historical Claude 78%) before marketing polish.
3. Align portal license “engine status” copy so owners aren’t told “Not activated” when org seats are active.
4. Add redirect `/licenses` → `/license`.
5. Raise Live Dashboard login contrast; fix Backup ERROR badge semantics (error vs warn).
6. Finish Checkout Pro + Product Explorer to clear the 98% layout gate or lower the published bar honestly.

---

## 7. Performance Findings

| Finding | Result |
|---------|--------|
| Shop DB size | ~3.7 MB; integrity ok |
| Product count | **651** (not 100k) |
| Sales count | ~1.4k–1.5k (not millions) |
| Portable 3.0.11 launch | Process alive @ ~10s, ~95 MB WS (smoke only) |
| POS open snappy tests | **FAILED** (catalog cache expected skip not met) |
| 100k / millions stress | **NOT VERIFIED** |
| Long-session / multi-cashier | **NOT VERIFIED** |

---

## 8. Security Findings

| Finding | Severity | Notes |
|---------|----------|-------|
| Portal + Live auth work | Positive | Verified login |
| Role/permission unit coverage | Positive | In green majority of suite |
| Live cashier authz retest | Gap | NOT VERIFIED this gate |
| Capture-script plaintext password | Medium (process) | Rotate if repo shared |
| Code signing of Setup | NOT VERIFIED | No Authenticode check recorded |
| JWT secret length | Prior note | Not re-audited |

---

## 9. Stability Findings

- Upgrade simulation: **PASS**
- SQLite integrity: **ok** on production + QA DBs
- Portable exe: started without immediate crash
- Multi-day supermarket simulation / power-loss recovery: **NOT VERIFIED**
- Live Backup ERROR: active operator-visible failure
- pytest regressions on snappy/returns: indicate tip instability relative to advertised 3.0.11 notes

---

## 10. Missing Features (relative to Phase 1–24 ambitions)

- Gift cards / vouchers / layaway / coupons (as full commercial modules)
- Serial/batch/expiry as first-class verified workflows
- Live M-Pesa STK (manual till mode; STK previously N/A)
- Hardware cash drawer / multi-printer UAT
- Billing in Portal (explicitly **Soon**)
- Guaranteed ≥98% visual gate across all layouts
- Published 3.0.11 GitHub/Portal download artifact

---

## 11. Nice-to-Haves

- One-click Live Dashboard URL from Portal Settings (cue already shown)
- Cleaner device inventory (dedupe EUGENE-LENOVO)
- Cloud release listing inside Downloads (currently “No cloud releases listed yet”)
- Business-day picker called out in release notes only when present in Setup
- Automated “installed version == latest Setup” health check on desktop

---

## 12. Top 20 Issues Before Release

1. Publish **3.0.11** (or later green build) to GitHub `latest` + Portal Download Center with correct SHA-256.  
2. Upgrade field Program Files from **3.0.9 → tip** and re-verify.  
3. Fix `_internal/version.json` checksum to match Setup.  
4. Fix 9 failing pytest cases (esp. snappy cache, return restock, barcode overlay).  
5. Resolve Live **Backup ERROR** root cause.  
6. Re-run ChatGPT checkout gate; clear Pro + Explorer to ≥98% **or** change release criteria.  
7. Re-run Claude system gate; do not claim 98% at 90%.  
8. Redirect `/licenses` → `/license`.  
9. Strip UTF-8 BOM from `version.json` or make loaders use `utf-8-sig`.  
10. Update brittle Return/Exchange tests to `panel_factory.py`.  
11. Fresh clean-PC install of tip Setup (wizard → activate → first sale).  
12. Offline NIC-down UAT: sales + queue + reconnect sync.  
13. Physical receipt printer UAT.  
14. Cashier vs admin live authz matrix on tip.  
15. Confirm business-day in **shipped** Setup (or remove from marketing).  
16. Deduplicate/clarify portal device + license activation status.  
17. Inventory low-stock / overflow polish.  
18. Code-sign Setup.exe.  
19. Remove or sequester plaintext QA passwords from scripts.  
20. Honest stress test plan (or declare scale limits: e.g. certified to N products).

---

## 13. Automated Evidence Summary

| Run | Result | Log |
|-----|--------|-----|
| `pytest tests/` | **235 passed, 9 failed** (~49s) | `logs/pytest_full.txt` |
| Offline/backup/updater/business-day subset | **25 passed** | `logs/pytest_offline_backup.txt` |
| `qa_upgrade_sim.py` | **PASS** | `logs/qa_upgrade_sim.txt` |
| Portal `/api/health` | `{"status":"ok","system":"MBT POS",…}` | `logs/portal_api_health.json` |
| Portable 3.0.11 + QA data root | Alive smoke | `logs/portable_launch.txt` |
| Checksum skew | Documented | `logs/checksum_skew.txt` |
| Screenshots | Portal dashboard/license/devices/downloads + Live dashboard | `screenshots/` |

**Failed tests (this gate):**
- `test_u04_sales_footer_settings_debt_touch_targets`
- `test_sales_return_wired`
- `test_app_version_matches_version_json`
- `test_installer_workspace_shortcut`
- `test_filter_substring_sku_and_difflib`
- `test_fab_and_settings_clean`
- `test_on_show_skips_db_when_catalog_fresh`
- `test_second_refresh_is_noop_without_force`
- `test_partial_return_restocks_and_nets_revenue`

---

## 14. Final Recommendation

### ❌ **NOT READY FOR PRODUCTION**

**Why not “Approved with minor fixes”:** Distribution is wrong for customers (GitHub/Portal still on **3.0.4**), installed fleet path is **3.0.9**, packaged checksum is inconsistent, UI polish gates are explicitly unmet, Live shows Backup ERROR, and advertised snappy/offline patches are not proven on the installed customer binary. Those are release-channel and trust blockers, not polish nits.

**Minimum bar to re-open the gate:**
1. Ship matching Setup + GitHub latest + Portal download + checksums.  
2. Green pytest (0 fails) on the tagged commit.  
3. Clean-PC install + upgrade + first-sale + offline reconnect evidence.  
4. Honest UI score disclosure or actual ≥98% captures on that Setup.  
5. Backup ERROR cleared on Live.

---

*Report generated by autonomous acceptance gate 2026-07-24. No PASS claimed without evidence. Items not exercised are marked NOT VERIFIED.*
