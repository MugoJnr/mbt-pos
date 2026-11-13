# MBT POS release certification — 27 October 2026

This is not a shop certification. Edmus activation and the two live command checks were not run. The installed Program Files copy was not rebuilt after the accounting fixes below.

## Identity

| Item | Value |
|---|---|
| Repository | `C:\MBT_Build\mbt-pos-port` |
| Branch | `port/v3.1.66-audit` |
| Last commit | `f1df495` — Fix the 3.1.71 startup crash by including the Users screen in the package |
| Working tree | Uncommitted. Includes the 3.1.73 inventory, removal, and profit work, plus the receipt and credit fixes from this run |
| Source version file | 3.1.73 |
| Installed executable | `C:\Program Files\MugoByte\MBT POS\MBT_POS.exe` |
| Installed file version | 3.1.73.0 |
| Installed size | 11,065,833 bytes |
| Installed written | 2026-10-27 18:31 |
| Installer checksum already stamped for that 3.1.73 file | `f42de4725ea385cc4e7038239d9c7dd560f984a113584c808bc4fa59c2bacb3c` |
| GitHub latest | Still 3.1.72. 3.1.73 was not published |

The installed 3.1.73 binary does not contain the supplier-receipt cost layer, credit-customer, or void-request body fixes made after it was built.

## What this run proved

Run `MBTQA-20261027-001` used only `C:\MBT_Build\qa-exhaustive-20261027\shop`. The live shop database was not opened.

49 API scenarios passed and 0 failed. Evidence is in `qa-results\MBTQA-20261027-001`.

The dashboard at `http://127.0.0.1:5099` was the same isolated shop. Screenshots:

- Cashier home has no inventory-value card.
- Cashier `DELETE /api/products/2` returned 403.
- Admin inventory shows stock value and a Remove button on each product row.

## Fixes made in source during this run

- A supplier receipt now writes a FIFO cost layer at the cost entered, and a repeated client token does not receive the stock twice.
- A dashboard sale consumes those layers the same way the till sale does. A zero quantity is rejected.
- A credit or part-payment sale without a customer is rejected. When a customer is present, the debt invoice is created for that cashier.
- A void request can be opened with the sale id.
- A new user response includes the new id.
- A return puts the consumed layers back for the returned quantity. A stock increase adds a layer and a stock decrease consumes one.
- Historical profit uses the remaining unreturned quantity. It does not switch to today's product cost.

No cost layers were invented for old Edmus sales.

## Not certified

- Edmus activation.
- Two live command polls.
- The physical Edmus computer and the flash drive.
- A real M-Pesa charge. The split tender was recorded only.
- Offline mode and a Windows restart.
- Clicking through the installed Windows till. The till function `create_sale` was executed on the isolated database. The installed till process was left on the normal shop and was not used for these sales.
- Publishing 3.1.73 or replacing the 3.1.72 installer.

Rollback for the installed test PC remains `C:\MBT_Build\release_3.1.70`.
