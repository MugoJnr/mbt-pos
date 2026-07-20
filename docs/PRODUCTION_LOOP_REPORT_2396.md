# MBT POS — Enterprise Autonomous Production Loop Report

**Date:** 2026-07-20  
**Tip version:** **2.3.96** (`6151569`)  
**Design authority:** Current implementation + approved screenshots (no Figma URL)

## Cycle summary

| Phase | Result |
|-------|--------|
| Audit (imports, tip, markers) | **PASS** — 8 critical modules import clean |
| Authz (cashier scope) | **PASS** — `own_sales` / `cashier_id` in web_routes |
| Sales (variance default + line discount UI) | **PASS** — Return Change default; Discount (KES) per cart line |
| AI seed | **PASS** — `configured=True` on test PC |
| Local backup | **PASS** — `create_local_backup` exercised |
| Web dashboard POS discount | **PASS** — source + npm build previously OK |
| Screenshots | **PASS** — `Desktop/QA_VISUAL_POS/discount_lines/` |
| Installer build | **PASS** — Setup on Desktop + GitHub |
| Cloud login E2E | **PARTIAL** — prior agents resource-exhausted; local backup OK |
| Figma pixel match | **N/A** — no Figma URL (by directive) |
| Printer / live M-Pesa | **BLOCKED** — hardware/live rails not exercised this cycle |

## Improvements this tip (2.3.96)

- Per-line **Discount (KES)** highlighted box on desktop cart rows
- Web POS matching discount field + “Save …” line
- Visible **Remove** label button (not tiny ✕ only)
- Taller cart rows / scroll area for touch

## Production readiness score

**78 / 100 — Conditional commercial ready** for shop install of desktop POS + Command Center on this tip, after installing Setup 2.3.96.

Not a full “enterprise Ready” gate until cloud login E2E, printer, and live M-Pesa are signed off.

## Remaining risks

1. Cloud login/upload not fully proven on this PC in the last E2E attempts  
2. No Figma SoT for pixel QA  
3. Printer / M-Pesa live paths not re-verified this cycle  
4. Multi-branch revenue still partial (prior gap doc)

## Recommendations

1. Install **MBT_POS_Setup_v2.3.96.exe** on shop PCs (close POS first)  
2. Complete Settings → MBT Cloud Backup Create Business / sign-in once per shop  
3. Paste Figma URL when available for screen-by-screen visual lock  
4. Run one live M-Pesa + one print receipt on a shop till before wide rollout  

## Deploy checklist

- [x] Code on `main` (2.3.96)  
- [x] Setup built & on Desktop  
- [x] GitHub release `v2.3.96` Latest  
- [x] Packaged `Discount (KES)` confirmed in `_internal`
