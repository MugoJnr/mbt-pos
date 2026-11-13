# MBT POS exhaustive shop acceptance

Run `MBTQA-20261027-001` on 2026-10-27. Isolated database `C:\MBT_Build\qa-exhaustive-20261027\shop\data\mbt_pos.db`. The live shop database was not opened.

Branch `port/v3.1.66-audit`, committed HEAD `f1df495`, with uncommitted 3.1.73 work plus the FIFO receipt and dashboard-sale fixes from this run.

## Counts

| Status | Count |
|---|---:|
| PASS | 49 |
| FAIL | 0 |
| BLOCKED | 0 |
| NOT TESTED | 0 |

## Failures

- None

## Defects

- None opened by this run beyond the scenario results.

## FIFO

The layered product was received as 10 at 100 and 10 at 140, then 12 were sold at 200. Expected COGS is 1,280 and expected gross profit on that receipt is 1,120. Period profit after the run: COGS 2119.25, costed revenue 3219.8, profit 1100.55, uncosted revenue 0.0, uncosted lines 0.

Changing the product's current cost after the sale did not change the consumed layer cost.

## Dashboard UI on the isolated shop

Signed in on `http://127.0.0.1:5099` after the API run. Screenshots are in `qa-results\MBTQA-20261027-001\screenshots`.

- Cashier dashboard shows sales of KES 3,144.8 and does not show an inventory-value card.
- Cashier inventory has no Remove button. A direct delete returned 403: only an administrator can remove a product.
- Admin inventory shows KES 1,878.25 stock value and a Remove button on each product row. The table is wide, so the button sits to the right of Price and Cost.

## Not claimed

- The Windows till window was not clicked. The till sale path was the same `create_sale` function the till calls, on this isolated database.
- The installed Program Files till was left running and was not used for these sales.
- Edmus activation and two live command checks were not run.
- No real M-Pesa payment was sent. The split payment is a recorded tender, not a gateway charge.
- Cloud backup was not called. A SQLite snapshot of this disposable shop was reopened.
- The network was not disconnected.
- The PC was not restarted.
- This is not a shop certification.
