# Defect register — mixed tender

## Fixed in this working tree

- DEF-TENDER-1: The dashboard sale rejected a split that did not cover the total, so cash + M-Pesa + customer credit could not be one sale. `allocate_sale` now accepts that allocation, ignores unconfirmed electronic lines, and creates one debt for the credit remainder.

## Still open

- The installed 3.1.73 executable does not include this fix.
- Splitting one open cart into several bills is not a single action.
- Edmus activation and live command checks were not run.
