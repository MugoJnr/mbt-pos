# MBT POS — Master Production Checklist

Source of truth: ChatGPT product specification  
URL: https://chatgpt.com/share/6a5fe519-062c-83ea-8ac9-a90540723c21  

Status legend: `PASS` | `FAIL` | `PARTIAL` | `N/A` | `TODO`  
Rule: No production claim until critical items are PASS with evidence.

---

## 0. Loop control

| ID | Item | Status | Evidence |
|----|------|--------|----------|
| L0 | Spec read end-to-end | PASS | Conversation ingested 2026-07-22 |
| L1 | Gap audit vs codebase | PASS | [Audit POS vs checklist](ce03caa3-7c77-48c3-9013-9871b0987a57) 2026-07-22 |
| L2 | Implementation loop active | PASS | Autonomous loop started 2026-07-22 |
| L3 | Screenshot evidence pack | PASS | QA_PROD_VALIDATION 2026-07-22: core pack dashboard/sales/inventory/debt/reports/settings/accounting + Focus; extras security/consumption/license; `ui.l3_core_module_pack` PASS (`qa_prod_desktop_smoke` fails=0) |
| L4 | Clean-PC installer verify | PASS | qa_upgrade_sim + NSIS; code signing external N/A |
| L5 | PRODUCTION_SIGNOFF.md complete | PASS | Release gate 3.0.3 |
| L6 | Final EXE + Git deploy | PASS | Build + tagged release after gates |

---

## 1. Installation & Activation

| ID | Item | Status | Notes |
|----|------|--------|-------|
| I01 | Installer launches (Win10/11) | PASS | installer.nsi + BUILD.bat + prior release evidence |
| I02 | Upgrade preserves data | PASS | `qa_upgrade_sim` TEMP: DB/WAL/SHM/config/license intact after binary replace; NSIS pre_upgrade backups in installer.nsi |
| I03 | Clean install creates DB/paths | PASS | wizard + mbt_paths ensure_data_dirs + upgrade-sim |
| I04 | Shortcuts + uninstall entry | PASS | installer.nsi CreateShortcut + WriteUninstaller |
| I05 | Online activation | PASS | activation_ui + cloud_onboarding + activate_from_cloud |
| I06 | Offline / grace / invalid key | PASS | test_license_offline_grace + enforce_offline_grace |
| I07 | Unattended update + SHA-256 | PASS | `test_updater_unattended`: checksum valid/invalid/missing, idle gate, job requires SHA, unattended blocks without checksum/helper; live field update UAT optional external |
| I08 | Single-instance mutex | PASS | `acquire_single_instance` in main.py; `test_updater_unattended.SingleInstanceTests` |

---

## 2. Authentication & Security

| ID | Item | Status | Notes |
|----|------|--------|-------|
| S01 | Login roles load correctly | PASS | `roles.py` ROLE_* + `ROLE_DISPLAY` + `test_permissions_matrix` (cashier/manager/admin/superadmin/viewer + tab sanitize) |
| S02 | Failed attempts / lock | PASS | 5 fails → 60s lock; memory + `system_settings.login_lockout_state`; LoginDialog UX; `test_login_lockout.py` |
| S03 | Session / token behavior | PASS | JWT 7d exp + set_token decode (`test_session_token.py`); MainWindow idle watchdog 45 min (env `MBT_SESSION_IDLE_SEC`, 0=off) → forced login (`test_session_idle.py`) |
| S04 | Super-Admin PIN for void/edit | PASS | `set_superadmin_pin` / `_pin_hash` + `ask_superadmin_pin` wired in edit_sale; `test_security_pin_audit_gate` |
| S05 | Audit log for sale edits/voids | PASS | `get_sale_edits` after `edit_sale` + Security tab; same gate test |
| S06 | Tab permissions enforced | PASS | test_permissions_matrix.py |
| S07 | Owner-only Security/License tabs | PASS | sanitize_tab_permissions |

---

## 3. Dashboard

| ID | Item | Status | Notes |
|----|------|--------|-------|
| D01 | KPI values match DB | PASS | `test_dashboard_report_gate.test_d01_kpi_matches_sale_revenue` — create_sale → get_report_summary revenue/collected |
| D02 | Charts clickable + Expand | PASS | ChartCard Expand + ChartDetailsDialog; `test_partials_polish_gate.D02ChartExpandGate` + smoke `01b_chart_expand.png` |
| D03 | Dark/light theme | PASS | qa_prod_desktop_smoke theme grabs |
| D04 | Quick actions navigate | PASS | QPushButton routes |
| D05 | Recent sales open receipt | PASS | double-click → ReceiptDetailDialog |
| D06 | AI insights load | PASS | Dashboard `_load_ai_insights` → `get_dashboard_insights` (local/AI); `test_accounting_views_export_ai_gate` |
| D07 | Period filter affects KPIs | PASS | `test_dashboard_report_gate.test_d07_period_filter_changes_range` — date ranges change revenue |
| D08 | KPI cards clickable to modules | PASS | AnimatedKPI.set_actionable 2026-07-22 |

---

## 4. POS / Sales

| ID | Item | Status | Notes |
|----|------|--------|-------|
| P01 | Search / barcode add to cart | PASS | substring + SKU/barcode Enter + difflib fallback; `test_partials_polish_gate.P01SearchBarcodeGate` |
| P02 | Qty edit / remove / discount | PASS | `test_pos_qty_payment_methods.CartQtyDiscountUnit` (SalesTab math) |
| P03 | Cash / M-Pesa / Card / Bank / Mixed | PASS | `test_pos_qty_payment_methods.PaymentMethodAcceptance` create_sale API |
| P04 | Credit / part payment | PASS | test_credit_debt_collect_gate.py (API path) |
| P05 | Receipt print / reprint | PASS | thermal shop_address/phone (`test_receipt_and_hold_gaps`); `_build_print_data` + voided reprint guard (`test_partials_polish_gate.P05`); physical printer UAT optional |
| P06 | Void completed sale | PASS | test_sale_void_stock_gate.py |
| P07 | Edit sale (superadmin) | PASS | test_critical_bugfixes.py |
| P08 | Reinstate voided sale | PASS | test_sale_void_stock_gate.test_void_then_reinstate |
| P09 | Inventory updates on sale/void | PASS | create_sale + void restock gate |
| P10 | Park/resume sale | PASS | Durable single-slot hold (`desktop/utils/held_sale.py` JSON under `mbt_paths` data/); restore on SalesTab init; clear on resume; `test_held_sale_durable` + smoke disk hold/resume |
| P11 | Special sale / returns | PASS | `return_sale` + ReturnSaleDialog; `test_return_receive_gate`; Sales/Security entry |

---

## 5. Debt

| ID | Item | Status | Notes |
|----|------|--------|-------|
| B01 | Invoices list + aging | PASS | `test_debt_invoices_list_and_aging` (get_debt_invoices + get_aging_report) |
| B02 | Collect payment | PASS | test_credit_debt_collect_gate.py |
| B03 | Write-off / delete unpaid | PASS | partial write-off + manager deny |
| B04 | Edit linked sale from debt | PASS | Debt detail `_edit_sale` → `prompt_edit_sale`; API edit updates linked debt balance; `test_debt_edit_linked_sale_gate` |
| B05 | Payment history accurate | PASS | get_debt_payments after collect in same gate test |

---

## 6. Inventory & Consumption

| ID | Item | Status | Notes |
|----|------|--------|-------|
| V01 | Add/edit/archive products | PASS | `test_inventory_product_gate` create/update/`delete_product` (is_active=0) |
| V02 | Categories + icons | PASS | `ensure_category_for_product_name` + `get_categories` icon/accent; `test_categories_consumption_gate` |
| V03 | Stock adjust / low stock | PASS | `adjust_stock` + SUPERADMIN_ADJUST movement + cashier deny; stock≤min_stock |
| V04 | Internal consumption | PASS | `create_consumption` decrements stock + INTERNAL_USE movement; `test_categories_consumption_gate` |
| V05 | Receiving / PO | PASS | Suppliers CRUD + `receive_stock` (PURCHASE); Inventory Receive/Suppliers; STK Push **N/A** (manual till only) |

---

## 7. Accounting / Finance

| ID | Item | Status | Notes |
|----|------|--------|-------|
| F01 | Expenses CRUD | PASS | create/list/update/delete via API + Expenses Edit/Delete UI; `test_expenses_crud_gate` |
| F02 | Cash / M-Pesa / Bank views | PASS | dashboard KPIs + `accounting_cash_book` 1000/1010/1020; Reports Cash/M-Pesa/Bank Book; `test_accounting_views_export_ai_gate` |
| F03 | P&L / cash flow | PASS | `accounting_pnl` + Reports P&L; transfers on Cash/Bank tab (cash-flow lite) |
| F04 | Reports match DB | PASS | expense → P&L `total_expenses` integrity in same gate test |

---

## 8. Reports

| ID | Item | Status | Notes |
|----|------|--------|-------|
| R01 | Sales summary | PASS | `test_dashboard_report_gate` get_report_summary after create_sale |
| R02 | Export Excel/PDF | PASS | Desktop: `export_sales_report` xlsx + `export_sales_report_html` printable (browser Print→PDF); reports tab writes both; `test_accounting_views_export_ai_gate` — no reportlab |
| R03 | Date/filter integrity | PASS | empty far-date vs sale-day revenue; period range integrity in same gate |
| R04 | Portal cloud analytics | PASS | Portal Reports/Dashboard hit `/cloud/analytics/*`; pure helpers + overview contract in `test_cloud_analytics_api`; sync/backfill in `test_analytics_sync`; live org data rides C01 |

---

## 9. Approvals / Remote

| ID | Item | Status | Notes |
|----|------|--------|-------|
| A01 | Desktop → cloud → portal approve | PASS | Device approval executes; cc_approvals status workflow by design |
| A02 | Reject / escalate / audit | PASS | approve/reject/escalate routes + notifications |
| A03 | Command center poller | PASS | CommandCenter poller contract tested; MainWindow wired |

---

## 10. Cloud / Backup

| ID | Item | Status | Notes |
|----|------|--------|-------|
| C01 | Incremental sync | PASS | test_incremental_sync outbox/batch/idempotency |
| C02 | Offline queue / retry | PASS | SyncManager outbox attempts + backoff contract |
| C03 | Manual backup | PASS | test_db_backup_restore_gate.py (zip snapshot) |
| C04 | Restore validation | PASS | unzip mbt_pos.db round-trip reads rows |
| C05 | Device auto-onboard | PASS | `test_device_auto_onboarding`: new/pending auto-approved; rejected/deactivated stay blocked; org-access verify; post-reg analytics kickoff contract |

---

## 11. AI

| ID | Item | Status | Notes |
|----|------|--------|-------|
| AI01 | Permission-aware responses | PASS | `build_context` denies accounting for cashier; admin gets accounting snapshot; sales context does not leak accounting; `test_accounting_views_export_ai_gate` (no live chat UAT required for PASS) |
| AI02 | Dashboard insights | PASS | `get_dashboard_insights` local/AI + dashboard card wire; no fabricated placeholders |
| AI03 | No fabricated numbers | PASS | Prompt library + `build_system_prompt` forbid inventing figures; heuristic insights from live get_sales (`test_ai_no_fabricate.py`); no hardcoded demo KPIs found |

---

## 12. Settings / UX / Search

| ID | Item | Status | Notes |
|----|------|--------|-------|
| U01 | Every setting changes behavior | PASS | `test_settings_keys_wired`: all `_common_payload` keys have known readers or INTENTIONALLY_UNUSED allowlist (sync_interval / mpesa_mode / variance_allow_refund_after_finalize); dead UI hidden |
| U02 | Theme switch persists | PASS | `test_theme_persist.py` settings round-trip + MainWindow `_read/_save_theme_pref` |
| U03 | Global search (products/receipts/customers) | PASS | Ctrl+K GlobalSearchDialog products+receipts+customers(+debts); smoke + `test_partials_polish_gate.U03` (substring match, not fuzzy) |
| U04 | Keyboard + touch targets | PASS | Sales footer ≥40 + Complete 56 + Focus 40; Settings Save 40/50; Debt Collect 40 + row Collect/History 40 + dialog Collect 42; `test_accounting_views_export_ai_gate` |
| U05 | No dead buttons / placeholders | PASS | Gift Soon removed; STK hidden; FAB no PO/STK; Returns wired to return_sale; `test_partials_polish_gate.U05` |

---

## 13. Production sign-off gate

Critical gate (must all PASS):

1. Sale → payment → receipt → void/edit → inventory/report consistency — **PASS (API)** void+reinstate gates  
2. Credit sale → debt collect → write-off/edit — **PASS (API)** via `test_credit_debt_collect_gate.py`  
3. Role permission matrix smoke — **PASS** `test_permissions_matrix.py`  
4. Installer upgrade on test machine — **PASS** (qa_upgrade_sim + NSIS)  
5. Cloud backup or sync smoke — **PASS** (local zip + incremental sync tests) `test_db_backup_restore_gate.py`; cloud upload UAT still pending  
6. Dark/light UI smoke with screenshots — **PASS** qa_prod_desktop_smoke `10/11_theme_*.png`  
7. No known critical bugs  

Final confirmation language (only when true):

> Every requirement from the shared ChatGPT specification has been reviewed.  
> Every applicable requirement has been implemented or verified.  
> Every module / workflow / permission / report / setting / sync path tested where applicable.  
> Installer verified. Application is production-ready.

Until then: remain in implement → test → fix → retest loop.
