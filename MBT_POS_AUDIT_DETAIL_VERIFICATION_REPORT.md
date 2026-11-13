# Audit detail verification

Branch `port/v3.1.66-audit`, commit `3007035ab38f04536127500e500ce66fa9911820`.
Version files still say **3.1.70**. This work is uncommitted. No new installer was built. The packaged till was not launched.

## What was already there

The shop audit store is the `audit_log` table: event id, user id, username, action, module, details text, request address, and one recorded time. There is no separate role, source, correlation id, or before/after columns.

The dashboard Security page listed the newest rows. A row could not be opened. The till Security tab and the Users & Access footer showed the same columns. Double-click did nothing.

`GET /api/audit` requires `audit.view`. That permission is Admin and Super Admin only. There is no edit or delete route. The `audit.clear` permission exists and is unused.

Product updates already write changes into the details text, for example `price 120.0->125`.

## What was added

- `GET /api/audit/<id>` returns the stored event. It does not create historical values from the current database.
- Before and after are parsed only from `field before->after` text already stored on the event.
- A product id (`pid=`) or receipt number (`RCP-…`) in that text can show the record as it is now, with a note that this is not the historical snapshot. If the record is gone, the event says so.
- Other events that contain the same product id or receipt number are listed as related. Similar times or amounts are not treated as a link.
- Password, token, and secret values written as `name=value` are replaced with `[masked]`.
- The dashboard row opens the detail. Closing it leaves the search and page. `#audit-<id>` reopens the same event after a refresh.
- The till audit tables open the same stored detail on a double-click.
- `PUT` and `DELETE` on an event return 405.

## What is not recorded

Role at the time, till versus dashboard, a separate “when it happened” time, and a sync time are not in the table. The detail says **Not recorded** rather than guessing. Sale line items are not copied onto the audit row. They appear only when a receipt number was stored and the current receipt still exists.

## Tests

`python -m unittest tests.test_audit_detail -v`

3 tests, OK, 1.536s:

- Before/after is taken from the stored text.
- A secret in the text is masked.
- Cashier `GET /api/audit/1` is 403. Super Admin receives the event, the price change, the current product, and the related event. A missing id is 404. `PUT` is 405.

## Running dashboard

Isolated shop `C:\MBT_Build\qa-master-loop-20261024\shop` on `http://127.0.0.1:5108`. Not the live shop database.

Super Admin opened event 45, `UPDATE_PRODUCT` for UI Rice 1kg:

- Price before 120.0, after 125.
- Cost before 90.0, after 90.
- The current product is labelled as current, price 125, stock 6, active.
- No other event shares `pid=6`.

A cashier who opened `#audit-45` saw **Forbidden**. The audit rows were not shown.

Screenshots:

- `artifacts/audit-detail-20261027/07-audit-detail.png`
- `artifacts/audit-detail-20261027/08-audit-before-after.png`
- `artifacts/audit-detail-20261027/09-audit-price-change.png`
- `artifacts/audit-detail-20261027/10-cashier-audit-denied.png`

The till window was not opened, so the double-click dialog was not photographed. A direct URL to Security still loads the page shell for a cashier. The log and the event stay forbidden.
