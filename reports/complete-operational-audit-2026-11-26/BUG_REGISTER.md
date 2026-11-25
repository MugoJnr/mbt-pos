# BUG REGISTER — MBT POS v3.1.93, repair status

Source audit: 26 Nov 2026, tag `v3.1.93` (`b3da4aa`) on `port/v3.1.66-audit`.
Repair branch: `cursor/audit-defect-repairs-cec0`.
Version was not bumped. Production Supabase was not touched. The till is still not approved for Eugene's portal org, so the 403 "device not approved" outbox errors stay until he approves that device on purpose.

## Test results

| Suite | Before (audit, 26 Nov) | After this repair |
|---|---|---|
| pytest | 961 passed, 73 failed, 3 errors, 6 skipped | **1020 passed, 23 failed, 3 errors, 6 skipped** (`TZ=Africa/Nairobi`) |
| Web unit tests (`node --test src/lib`) | 5 passed | 5 passed |
| `tsc --noEmit` | 97 errors | 92 errors |
| `vite build` | built | built |

The remaining pytest failures are stale permission expectations (a cashier or the same user is asserted to do something the current rules refuse), sale-line checks that reject a zero price, emergency-recovery cases that already failed in isolation, branding/update/Windows widget checks, and three order-dependent checkout-layout errors. They were not deleted and the rules were not loosened to turn them green.

`tsc` still fails on the unused shadcn `src/components/ui/*` files, which import Radix packages that are not dashboard dependencies, plus strictness errors in routes that are not the runtime crashes below. The Vite build succeeds.

## Open questions (current behaviour kept)

- Cashiers stay unable to record expenses and the supplier-receive API still refuses a cashier, even though `accounting.create_expenses` and `supplier.pay` appear on the cashier permission list. Eugene has not decided whether cashiers may record expenses or pay suppliers.
- Managers still have `settings.view` and `users.view`, so they still see Settings and the user list.
- Cashiers can still open the web M-Pesa page, because that route is guarded by the sales tab (B-022).

## Fix status

| ID | Sev | Status | What changed |
|---|---|---|---|
| B-001 | Critical | **Fixed** | Security, Settings, and `change_superadmin_pin` write `users.pin_hash` / `pin_salt`, which is what verification reads. Until that person has a personal PIN, the old shop-wide hash still works, so existing shops and tests are not locked out. A personal PIN overrides the shop hash. |
| B-002 | High | **Fixed** | The wizard asks for 6 to 8 digits, stores that PIN on the Super Admin, and rejects a 4-digit PIN. The Security tab says "6 to 8 digits". |
| B-003 | High | **Fixed** | Manager and Admin voids and refunds require a Super Admin PIN. A signed-in Super Admin still skips the prompt and the skip is audited. The receipt Void action asks for confirmation before it runs. |
| B-004 | High | **Fixed** | A refund shares the order-level discount. The maize example (line net 140, sale 180 on line nets of 200) refunds 126. |
| B-005 | High | **Fixed** | Paid sales subtract refund rows. |
| B-006 | High | **Fixed** | Today's snapshot, command-centre sales, best sellers, and month revenue include return rows so the money is net. The sale count stays completed sales only. |
| B-007 | High | **Fixed** | Opening stock posts Dr 1200 Inventory, Cr 3200 Opening Balance Equity. A stocktake shortage posts Dr 6200, a stocktake gain credits 6200. |
| B-008 | High | **Fixed (clock, tables, status)** | Retry time is UTC, matching SQLite `CURRENT_TIMESTAMP`. Expenses map to `expense_entries`. Supplier payments get an outbox trigger. The dashboard "Sync clear" badge counts `sync_outbox`. The 403 itself is the unapproved QA device; it was not approved. |
| B-009 | Medium | **Partial** | New audit rows store shop local time (Africa/Nairobi). Older UTC rows are left as stored so they are not shifted a second time. |
| B-010 | High | **Fixed** | A single M-Pesa, card, or bank sale is stored as electronic money with `cash_paid` 0. The till payload does the same. |
| B-011 | Medium | **Fixed** | Payment bars use every displayed amount, including credit issued, so the percentages add to 100. |
| B-012 | Medium | **Fixed** | Reports cash uses the same financials as Finance: sales cash, later cash repayments, and cash refunds. |
| B-013 | Low | **Fixed** | Refund methods are stored in the same lowercase form as sales (`cash`, `m-pesa`). |
| B-014 | High | **Fixed** | Local and desktop cloud backups are written into `cc_backup_history`, and the Backup page also reads the last local and cloud markers. |
| B-015 | Medium | **Fixed** | Cloud history drops a second row with the same content hash, and zoned timestamps are shown in East Africa Time. |
| B-016 | High | **Fixed** | "Restore latest" picks the newest backup of at least 50 KB, so an empty newer file is still skipped and an older larger file is not preferred. |
| B-017 | High | **Fixed** | Diagnostics reads `sync_outbox` and does not call `.get` on `sqlite3.Row`. |
| B-018 | Medium | **Fixed** | The wizard summary says Activated when sign-in activation set `license_activated`, even with no typed key. |
| B-019 | Critical | **Fixed** | `GET /api/cloud/licenses` requires the licence-view check. A cashier token is no longer enough. |
| B-020 | Medium | **Fixed for cashiers** | Cashier and viewer settings are limited to checkout fields (currency, shop, tax, receipt text, public M-Pesa till/paybill, `pin_configured`). Managers still see the full public settings list. See the open question. |
| B-021 | Medium | **Fixed** | Till login failures and lockouts are written to the audit log. Lockout is 15 minutes after 5 failures, matching the PIN lock. |
| B-022 | Medium | **Not fixed** | Open question: cashiers may still open the web M-Pesa page. |
| B-023 | High | **Fixed (runtime) / typecheck partial** | Browser print is defined. Opening a recent supplier delivery no longer calls a missing `setPayAmount`. The edit-product panel is a real panel state. The M-Pesa default-profile comparison no longer compares a boolean with a string. `tsc` is 92 errors, down from 97; the rest are mostly missing Radix type packages. |
| B-024 | Low | **Fixed** | Text receipts no longer print the literal `[logo]`. |
| B-025 | Low | **Fixed** | The button label is `Save && Continue`, so Qt shows "Save & Continue". |
| B-026 | Low | **Fixed** | "Shop" and "Owner" are skipped, so "Shop Owner" is greeted as "there". |
| B-027 | Low | **Fixed** | The manual journal form starts with empty account codes. |
| B-028 | High | **Fixed** | Stock-adjustment write-downs: internal, staff, and samples → 6100; wastage and damage → 6200; expiry → **6300 Inventory Expiry** (that is the chart's expiry account; there is no separate wastage account); owner drawings → 3300. An unnamed write-down stays on 6200. |
| B-029 | Medium | **Not changed** | A positive stock adjustment still credits 3200 Opening Balance Equity. Eugene has not named a different gain account. Stocktake gains credit 6200 instead, because a count gain is not opening equity. |
| B-030 | Low | **Fixed** | The stocktake movement stores the user who applied it. |
| B-031 | Low | **Fixed** | `/api/version` uses `build_date`, or `released` from `version.json` (`2026-11-25`). The version number was not changed. |
| B-032 | Medium | **Partial** | The suite is 1020 passed / 23 failed / 3 errors. The sidebar probe implements the update-banner handlers it was missing. Remaining reds are listed above and were not deleted. |
| B-033 | Low | **Fixed** | Portal licence `activated_at`, `assigned_at`, `claimed_at`, `last_validated_at`, and `revoked_at` are stored as real UTC instants. |

## Shop-day run (added after the first repair)

These were seen on the installed v3.1.93 till (Wine on Linux) and fixed on the same branch.

| ID | Sev | Status | What changed |
|---|---|---|---|
| N-4 | High | **Fixed** | Voiding a goods receipt now reverses its journal (Dr 2000 / Cr 1200), so accounts payable and ledger inventory come back down with the stock. Recent deliveries show VOIDED and outstanding 0 when `status` is `reversed`, on the till and the web. The void asks for confirmation and a Super Admin PIN, including for a signed-in Super Admin. The reversal only reduces the cost layer whose source id is that receipt and product. A regression test keeps an opening layer of 10 and an older purchase layer of 5 while the voided receipt's own layer goes to 0. |
| N-split | High | **Fixed** | Part payment through the tender list adds the unpaid remainder as customer credit before the amounts are checked, so 3,000 cash on a 7,000 sale can complete as 4,000 credit. A mismatch stays on the payment panel instead of only a short toast. New "Add payment" rows grow the list instead of staying clipped in a 220px box. |
| N-round | Medium | **Fixed** | A credit sale does not apply cash rounding. 732.50 stays 732.50. Rounding still applies to cash tender. |
| N-6 | Medium | **Fixed** | The mouse wheel over a quantity or amount box, including its text field, does not change the value unless that box is focused. |
| N-5 | Medium | **Fixed** | The POS quantity box uses a dot as the decimal separator, and a whole-unit rejection no longer opens a dialog from inside the value-changed handler (that re-entry is a Wine page-fault). Typing 2.5 is kept. |
| N-minor | Low | **Fixed** | Security already says "6 to 8 digits" (B-002). The Users screen labels the receipts tab "Receipts" instead of `receipts`. New supplier from Receive stock has a phone field. The zero-cost badge reads "Zero buying price" and is wide enough not to end in "ne…". Starting a shift on the till asks for the opening float and stores it on the till session. Automated tests skip that prompt. |

## Screen observations

| ID | Status | Note |
|---|---|---|
| S-01 | Not fixed | Voided-receipt presentation was not reworked in this pass. |
| S-02, S-18 | Not fixed | Oversell is still blocked; the toast copy was not redesigned. |
| S-03 | Not fixed | New-customer form behaviour was left as it is. |
| S-04 | Not fixed | Debt invoice table layout was not changed. |
| S-05 | Not fixed | Health-score difference was not chased. |
| S-06 | Improved | The sync badge uses the outbox count (B-008). The pending records remain until the device is approved. |
| S-07 | Not fixed | Developer recovery on the login screen was left. Removing it is a product decision. |
| S-08 | Not fixed | Report notification timing was not changed. |
| S-09 | Not fixed | Receipt subtotal-before-line-discount layout was not changed. |
| S-10 | Not fixed | POS tile refresh after a refund was not changed. |
| S-11 | **Fixed** | Refund numbers are `RET-YYYYMMDD-####`. |
| S-12 | Not fixed | Supplier dropdown empty-state copy was not changed. |
| S-13 | Not fixed | Duplicate settings rows were not removed. |
| S-14 | Not fixed | Wizard layout overlap was not changed. |
| S-15 | Not fixed | Activation message timing and spelling were not changed. |
| S-16 | Not fixed | Portal page 404s and the "Add Save" label were not changed. |
| S-17 | Not fixed here | Zero-price lines stay rejected by the sale-line check. |
| S-19 | **Fixed** | Covered by B-002. |
| S-20 | Not fixed | System Status printer wording was not changed. |

## Regression tests

`tests/test_operational_audit_20261126.py` covers the PIN store, manager PIN on void and refund, order-discount refund, M-Pesa tender, split and part-pay, opening-stock journal, adjustment accounts, consumption cost, paid-sales net of refunds, backup selection, payment-bar totals, and the greeting. Existing tests were updated where they still granted a cashier an action the role cannot do, or where they voided as a manager without the PIN the till now requires.
