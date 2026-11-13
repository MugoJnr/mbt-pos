# MBT POS release check — 27 Oct 2026

This is not a shop certification. Edmus activation and the two live command checks were not run. The 3.1.73 installer finished with exit 0. Program Files is now 3.1.73.0. The installed till was started and stayed running. It was not signed in.

Published GitHub latest remains **3.1.72**. That installer does not contain the fixes below. It was not replaced. 3.1.73 was not published, because the installed shortcut has not been verified and the Edmus activation checks are still open.

## Source

- Repository: `C:\MBT_Build\mbt-pos-port`
- Branch: `port/v3.1.66-audit`
- Last commit: `f1df495` (the 3.1.72 startup fix)
- The 3.1.73 fixes are in the working tree and are not committed.

## Why this is 3.1.73

3.1.72 is already published. It still shows Archive product only after a product is chosen, and a cashier can still be sent inventory value. Replacing that installer would change a published file. The fixes are in 3.1.73.

## Artifacts

| File | Identity |
| --- | --- |
| Installer | `C:\MBT_Build\mbt-pos-port\dist\MBT_POS_Setup.exe` |
| Installer size | 59,585,928 |
| Installer SHA-256 | `f42de4725ea385cc4e7038239d9c7dd560f984a113584c808bc4fa59c2bacb3c` |
| Packaged till | `C:\MBT_Build\mbt-pos-port\dist-3173\MBT_POS\MBT_POS.exe` |
| Packaged file version | 3.1.73.0, size 11,065,833, written 2026-10-27 18:31 |
| Build tag | `RC-2026-10-27-v3.1.73` |
| Installed shortcut | `C:\Program Files\MugoByte\MBT POS\MBT_POS.exe`, file version **3.1.73.0**, size 11,065,833, written 2026-10-27 18:31 |
| Rollback installer | `C:\MBT_Build\release_3.1.70\MBT_POS_Setup.exe` (not overwritten) |

The packaged dashboard bundle is `index-CKq57uMs.js`. It contains the Remove product wording. The build warning list does not omit `desktop.tabs.admin_tab`.

## What was wrong in published 3.1.72

- A cashier with the Inventory tab was sent inventory value. The page also added stock value from the selling price when cost was hidden. A viewer could see the same figure.
- Product removal was labelled Delete in the new screens, but the server only archived. On 3.1.72 the control was Archive product and appeared only after Adjust product. The till hid it in the ⋮ menu.
- Dashboard profit used the product's current cost, not the FIFO layers the till consumed when the sale was saved.

## Fixes in 3.1.73

- Cashier and viewer are refused inventory value on the server, including the command-center figure, the AI lines, and the inventory export cost column. Product cost is removed from the product list and supplier-receipt payload for those roles. Manager, admin, and Super Admin still receive it.
- Remove product is on each inventory row and in the edit window, on the till and on the dashboard. If the product has stock, a receipt, or a stock movement, it is archived and old receipts keep it. If it has no history, it is deleted. The button says Remove. The server says which one happened.
- Profit for a day uses `cost_layer_uses` written by the till. A sale with no cost layer is counted as uncosted revenue and is not given today's product cost.

## Tests that passed

Disposable database. Not the Edmus shop database.

`python -m unittest tests.test_release_gaps tests.test_role_boundaries.CashierInventoryValueTests tests.test_inventory_product_gate.InventoryProductGate.test_v01_create_update_archive_product tests.test_version_consistency tests.test_role_boundaries.RoleBoundaryTests.test_shop_https_origin_is_allowed_and_another_site_is_not`

8 tests, OK.

- An unused product with no stock is deleted.
- A product created with stock is archived and stays in the database as inactive.
- A cashier remove is refused and the product stays.
- Two layers, cost 4 then 10. Selling 3 units consumes 2 at 4 and 1 at 10. Cost of goods is 18. Sale total 30. Profit is 12. A second sale with no layer adds 10 to uncosted revenue and does not change the 12.
- Cashier inventory value is false even with the Inventory tab. Viewer with Inventory and Reports is false. Admin and manager are true.
- The existing product-archive test still passes for a stocked product.
- Version files agree on 3.1.73.
- `https://edmus.mugobyte.com` is accepted by hostname. A different site is refused. This is the same rule for every shop address, not a hardcoded Edmus exception.

## Not verified

- The installed till started from Program Files and was still running after startup. No “Failed to execute script” dialog appeared. The window was not signed in, and the Users screen was not opened in that session.
- No screenshot was taken of the installed 3.1.73 window, a cashier screen, the till Remove button, or a shop-address login on the new package.
- Edmus activation, the first live command check, and the second live command check were not run. They need the Edmus computer. They are not passed.
- The Edmus flash is not connected. It was not rechecked.
- Edmus cloud sales, debts, and the 26 October backup were not changed.
- The installer copied the shop database to `backups\pre_upgrade\3.1.73\mbt_pos.db` (2,641,920 bytes, timestamp 2026-10-27 16:47:57). Starting the installed till opened that database. After startup the live file was 2,646,016 bytes, written 2026-10-27 18:56:55. Its contents were not queried.
- Dashboard profit was proved by the FIFO unit test above. It was not compared on the Edmus shop, and no historical cost layers were invented for old Edmus sales.
- GitHub and the portal update list still advertise 3.1.72. 3.1.73 was not added, and it is not marked mandatory.

## Rollback

Leave `C:\MBT_Build\release_3.1.70\MBT_POS_Setup.exe` in place. Do not install 3.1.71. Do not replace the published 3.1.72 GitHub file.
