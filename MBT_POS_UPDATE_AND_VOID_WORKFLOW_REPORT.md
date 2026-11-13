# Update notice and void workflow

Branch `port/v3.1.66-audit`, commit `3007035ab38f04536127500e500ce66fa9911820`.
Version files still say **3.1.70**. This work is uncommitted. No installer was built. The packaged till was not launched.

## What was already there

The till already checks GitHub releases, then the portal update list. The dashboard only showed the installed version in the footer. It did not say when a newer release existed.

Voiding from the dashboard always created an approval request, including for Super Admin. Approving that request is what voided the receipt. The request list lived inside Approvals and a row could not be opened, corrected, or returned.

`sales.void` is on Manager, Admin, and Super Admin, and it means they can approve a void. Direct void without a request is Super Admin only.

## What changed

- The dashboard reads the installed version from `version.json` and compares it numerically with the release feed. A controlled test feed can be supplied with `MBT_UPDATE_FEED_JSON`. The page does not download or install anything, and it does not change the licence.
- Super Admin can void a completed receipt from the receipt with a reason. The server checks the signed-in role. Admin, Cashier, and Viewer receive 403. A second void returns 409 and does not restore stock again.
- An open void request for that receipt is cancelled so it cannot void the receipt a second time.
- Void Requests is its own page. A row opens the receipt, the original reason, the current reason, the reviewer comment, and the history. A reviewer can return it for correction. The requester can correct the reason and send it back. The original reason stays.
- On the till, a signed-in Super Admin voids directly. Other roles still send a request. That till window was not opened.

## Tests

`python -m unittest tests.test_update_and_direct_void -v`

2 tests, OK, 1.759s.

- `3.1.71` is newer than `3.1.70`. `3.1.9` is not. An unreachable feed, a missing installed version, a bad published version, and an incompatible release are separate states. The incompatible release has no install link.
- Cashier and Admin cannot call the direct void. Super Admin voids once. The audit row contains the reason. The earlier request is cancelled. A viewer cannot list void requests. A returned request keeps the original reason and accepts a corrected one. The receipt stays completed until it is actually voided.

## Running dashboard

Isolated shop `C:\MBT_Build\qa-master-loop-20261024\shop` on `http://127.0.0.1:5108`. Not the live shop database.

The notice was driven by a controlled feed, version 3.1.71, because the published GitHub release is not newer than the installed 3.1.70. The notice says the shop is still on 3.1.70 and that the dashboard does not install the update.

Super Admin opened `RCP-20261027-0001` (QA Audit Candle, KES 42), confirmed the reason “Wrong item rung on the test till”, and the receipt became voided. Stock for that candle went from 9 to 7 after two test sales, then back to 8 after the one void. A second void returned 409. A cashier direct void returned 403, and that denial is audit event `VOID_SALE_DENIED`. A viewer list request returned 403.

Request 6 for `RCP-20261027-0002` was returned with the comment “Name the product the customer returned”. The receipt is still completed. The original reason is still “Customer changed their mind”.

Audit event 54 records the void and links the earlier `CREATE_SALE` for the same receipt. It does not invent a before-and-after table, because the void text does not store one.

## Screenshots

`artifacts/update-void-20261027/`

- `01-update-available.png`
- `02-void-receipt-button.png`
- `03-void-confirm.png`
- `04-voided-receipt.png`
- `05-void-requests.png`
- `06-void-request-detail.png`
- `07-request-returned.png`
- `08-void-audit.png`

## Limits

The available-update screenshot is a controlled feed, not a published installer. GitHub’s current public release is older than 3.1.70, so a live check reports the shop as up to date. The till void dialog was not photographed. No new installer was produced.
