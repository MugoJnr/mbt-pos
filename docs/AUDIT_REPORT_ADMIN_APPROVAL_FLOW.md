# Approval-flow audit — independent verification

Date: 2026-10-23
Repository: `C:\MBT_Build\mbt-pos-port`
Branch: `port/controlled-master`
Starting commit: `0ad7b6db8b0232175f561a3d60d3e9b9c2205a0c`
Candidate version: 3.1.64
Published tag left untouched: `v3.1.63` (GitHub release, target branch `port/controlled-master`)

The file named in the assignment was not present in the tree at the start of this verification. The claims below are the ones stated in that assignment. Each one was checked against the current source and the isolated test run. Line numbers in any earlier note were not treated as evidence.

## What was inspected

- `desktop/utils/api_client.py`: `request_sale_void`, `request_stock_adjustment`, `execute_approval`, `_approval_pin_error`, `_approval_is_expired`, `_finish_approval`, `_apply_stock_adjustment`, `void_sale`, `_restock_sale_items`
- `desktop/utils/security.py`: `ask_superadmin_pin`, `_pin_hash`
- `web/web_routes.py`: `POST/GET /api/approvals` and approve, reject, escalate
- `backend/app.py`: bearer auth, login rate limit, Origin check, CORS, security headers
- `web/dashboard-ui/src/routes/approvals.tsx`
- `tests/test_executable_approvals.py`, `tests/test_approvals_status_only_gate.py`

Isolated environment for every pytest command:

- `MBT_DATA_ROOT=C:\MBT_Build\qa-isolated-20261023`
- `PROGRAMDATA=C:\MBT_Build\qa-isolated-20261023\programdata`
- `QT_QPA_PLATFORM=offscreen`
- Python: `C:\MBT_Build\_python311\python.exe`

The live shop database and the machine licence database were not opened.

## Original claims

| Claim | Result | Evidence |
|---|---|---|
| A report file `docs/AUDIT_REPORT_ADMIN_APPROVAL_FLOW.md` already existed | FAILED | The path was absent. This file is the verification record. |
| 549 tests passed, including 17 approval tests | UNVERIFIED as that exact run | No command, commit, or log in the tree reproduced 549. Before this fix the approval modules contained 11 tests (6 executable + 5 source/UI gates). |
| Cashier void request does not void the sale | VERIFIED | `request_sale_void` inserts `cc_approvals` only. `test_repeat_void_request_does_not_duplicate_or_void` keeps the sale `completed` and stock unchanged. |
| Repeated void requests are safe | VERIFIED after fix | A second request for the same open sale returns the existing row with `duplicate=True`. |
| Stock request does not change stock until approval | VERIFIED | `request_stock_adjustment` writes `stock_adjustment_requests` with status `pending`. `review_stock_adjustment` is a separate super-admin path. Executable `stock_adjust` approvals go through `adjust_stock`. |
| Approval applies a void or stock change once | VERIFIED | `test_void_approval_restores_stock_once`, `test_stock_approval_applies_once_and_wrong_pin_does_not`, `test_concurrent_stock_approval_applies_once`. |
| Pending → executing → approved is atomic | FAILED as a single transaction, then limited | The business call cannot stay inside the claim transaction, because `void_sale` and `adjust_stock` open their own write transactions. The claim is conditional. A live `executing` row cannot be taken for 45 seconds. A stale claim can be recovered. Stock retries use reference `APPROVAL:{id}`. |
| A zero-row status update was reported as success | FAILED in the previous code, fixed | `_finish_approval` now returns status 409 unless the row is already `approved`. Covered by `test_failed_status_write_is_not_reported_as_success`. |
| Expired requests do not execute | VERIFIED | `test_expired_request_does_not_void`. Expiry uses `expires_at`, or `created_at` plus 24 hours. New void requests store both in local time. |
| Server checks the Super-Admin PIN | VERIFIED | `_approval_pin_error` and `_apply_stock_adjustment` call `_pin_hash` (PBKDF2-SHA256, salt `MBT_POS_SUPERADMIN_SALT_2024`). Wrong, empty, and missing hashes return 403 and do not echo the PIN. |
| Web approve sent the PIN | FAILED in the previous UI, fixed | `approvals.tsx` posted `{}`. It now sends the password field for void and stock, and it shows the server error instead of refreshing as if the action succeeded. |
| Refund and other non-executable types can be decided | FAILED in the previous service, fixed | Those types were sent through the executor, failed, and returned to `pending`. They are now marked `approved` with `executed=False` and no stock change. |
| Generic web create could mint a void or stock approval with no target | FAILED in the previous route, fixed | `POST /api/approvals` rejects `void` and `stock_adjust`. Those requests are created from the receipt or inventory flow. |
| CSRF tokens are required | UNVERIFIED as a defect | Dashboard and till API auth is a bearer token in `Authorization`, not a cookie session. `supports_credentials` is false. Unsafe methods that send an `Origin` outside the allowlist, and not equal to the request host, receive 403. A CSRF token was not added. |
| Approval endpoints had no rate limit | VERIFIED, then limited per account | Login already had a process-local limiter. Approval PIN failures and stock-reduction PIN failures now stop after 8 failures in 10 minutes for that user id. Another user's PIN is not cleared or blocked by those failures. This limiter is in process memory. A multi-worker deployment would not share it. The desktop till runs one web process. |
| Security headers and CORS | VERIFIED present | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CSP, and `Cache-Control: no-store` on `/api/`. HSTS is set only when the request is HTTPS or `X-Forwarded-Proto` is `https`. CORS origins come from `MBT_CORS_ORIGINS`, defaulting to `https://portal.mugobyte.com`, `http://127.0.0.1:5173`, and `http://127.0.0.1:5174`. |

## Tests

Focused command:

```text
python -m pytest tests/test_executable_approvals.py tests/test_approvals_status_only_gate.py tests/test_return_edit_idempotency.py tests/test_version_consistency.py -q --tb=short
```

Result: 22 passed, exit 0, 39.60s. This was before the 3.1.64 version bump. The version test was run again after the bump: 2 passed, exit 0.

Full suite, first run: 554 passed, 1 failed, 92 warnings, 5 subtests, exit 1, 129.99s.
Failure: `tests/test_security_pin_audit_gate.py::SuperadminPinAndSaleEditAuditGate::test_emergency_pin_cannot_reset_cashier` with `sqlite3.OperationalError: no such table: users`.
That file alone then passed 4 tests in 1.96s.

Full suite, second run: **555 passed, 92 warnings, 5 subtests, exit 0, 130.10s.**
The single failure did not reproduce. It is not closed as a product defect and it is not counted as a pass of the first run.

Ruff and mypy are not installed in `C:\MBT_Build\_python311`, and the repository has no `ruff.toml`, `mypy.ini`, or `pyproject.toml`. The historical "52 ruff / 272 mypy" figures were not reproduced. They were not treated as a release gate for this candidate.

## Fixes in this verification

1. Web approvals ask for the Super-Admin PIN and surface server errors, including a failed refresh.
2. A void or stock approval that is already `executing` and newer than 45 seconds is not run again. A stale `executing` row can be recovered. Stock movement reference `APPROVAL:{id}` makes that recovery apply once.
3. `_finish_approval` does not report success when the status update changes zero rows.
4. A second open void request for the same sale reuses the first row.
5. Status-only approval types are recorded as approved and do not call `void_sale` or `adjust_stock`.
6. `POST /api/approvals` rejects a void or stock request that did not come from the receipt or inventory flow.
7. Wrong PIN attempts are limited per user. The response does not include the PIN.

## Remaining approval limitations

- The 45-second claim lease and the PIN limiter are process-local.
- Refund, discount, expense, credit, and price-override approvals still do not perform those business actions. They only record the decision.
- `review_stock_adjustment` remains a separate super-admin stock path. It checks the role and the expected quantity. It does not ask for the PIN, because that path is not `adjust_stock`.
- A credit sale that already has debt payments still cannot be voided through an approval unless `void_sale` is called with `force_with_payments`. The approval path does not set that flag.
- Browser verification of the approvals screen was not run. The UI change is covered by the source gate and the service tests.

## Packaged candidate

- Command: `C:\MBT_Build\_python311\python.exe -m PyInstaller --noconfirm --clean mbt_pos.spec` then `makensis installer.nsi`
- PyInstaller exit 0. NSIS exit 0.
- `dist\MBT_POS\_internal\version.json` is 3.1.64 with an empty checksum.
- EXE file version and product version are 3.1.64.0.
- The packaged dashboard bundle contains the server-PIN approval copy.
- Installer: `C:\MBT_Build\release_3.1.64\MBT_POS_Setup.exe`
- Size: 59431891 bytes
- SHA-256: `168c0bc1bbde072ee6a1c3ee15ad75882fa21ef332e1852c3fb2a785df570114`
- The previous installer `C:\MBT_Build\release_3.1.63\MBT_POS_Setup.exe` was left in place (59420956 bytes, 2026-10-21).
- The installer was not run. `BUILD.bat` was not run, because it kills `MBT_POS.exe`. No second till was launched.

## Verdict

The approval flow's confirmed execution, PIN, duplicate-request, and false-success defects are fixed and covered by regression tests. That does not make the whole product production-ready. Packaging, install, and live-shop activation were not certified by this audit.
