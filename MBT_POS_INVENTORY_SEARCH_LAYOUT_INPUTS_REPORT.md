# Inventory search, layout, and numeric inputs

Source commit: `3007035ab38f04536127500e500ce66fa9911820` on `port/v3.1.66-audit`.
Version files still say **3.1.70**. This work is uncommitted and is **not** in the 3.1.70 installer.
No new installer was compiled. The frozen `MBT_POS.exe` was not launched.

## What “delete” means

A product is archived. `products.is_active` becomes `0`. The row stays, so old receipts still name the product. There is no hard delete.

- Till: an administrator already had Delete on the product menu. It asks for confirmation, then calls the same archive.
- Dashboard: Inventory now has **Archive product** for Admin and Super Admin. The button asks for the product name and says old receipts are kept. Cancel does nothing.
- Server: `inventory.delete` is required. Cashier, viewer, and manager receive 403. Hiding the button is not the only check.
- Covered by `tests.test_role_boundaries.RoleBoundaryTests.test_only_an_administrator_can_remove_a_product_or_other_staff` (pass). The Archive button itself was not clicked in the browser in this pass.

## Search

Inventory search on the till and the dashboard matches the product **name** only. `unga`, `UNGA`, and `cook` match names. SKU, barcode, category, cost, and stock do not.

The dashboard list is filtered before paging. An empty search restores the list. `zzzz-none` showed “No products match that name.”

POS product search is unchanged and still matches name, SKU, and barcode.

Finance expenses and the user list gained a name/number search with Clear. Receipts, debt, and notes already had search.

## Numeric inputs

Dashboard stock adjustment and supplier receiving used `step={0.001}`. They now use the shop setting, default **1**. A focused number wheel uses that step. An unfocused wheel scrolls the page.

POS quantity wheel and the plus/minus buttons default to **0.25**. Typing **1.37** is kept. On the isolated dashboard, Cooking Oil at KES 320 with quantity 1.37 showed **TOTAL KES 438.4**. The cart was then cleared. No sale was posted and stock was not changed.

Settings → **Numeric Input & Mouse-Wheel Behavior** stores:

| Setting | Default |
| --- | --- |
| POS sale quantity | 0.25 |
| Inventory quantity adjustment | 1 |
| Supplier receiving quantity | 1 |
| General dashboard quantity | 1 |

Zero and negative steps are rejected (`400`). An admin save of `0.5` was read back and then restored to `0.25` on the isolated shop. A manager still cannot save shop settings. The till reads `wheel_pos_qty` when the sales screen opens. A focused till spin box steps by its own increment. An unfocused wheel still scrolls.

## Layout

The dashboard sidebar collapses to icons and can be dragged between 180 and 420 pixels. The choice is stored in this browser as `mbt-sidebar`. Collapsing it widened the inventory page in the running dashboard.

The till already had an enlarged cart. The button is now labelled **View Cart** and stays visible. **Back to products** returns to the product list without clearing the sale. The dashboard POS has the same pair of labels and edits the same cart.

## Tests

`python -m unittest tests.test_inventory_name_search tests.test_role_boundaries tests.test_permissions_matrix`

**21 tests, OK**, 9.638s, isolated data root `C:\MBT_Build\qa-master-loop-20261024\role-gaps`.

Dashboard production build succeeded. Last bundle: `web/dashboard-ui/dist/assets/index-WHUgGwsd.js`.

## Evidence

Running isolated dashboard at `http://127.0.0.1:5108`, shop data `C:\MBT_Build\qa-master-loop-20261024\shop`. Not the live shop database.

- `artifacts/layout-20261027/01-inventory-sidebar-open.png`
- `artifacts/layout-20261027/03-search-cook.png` — `cook` shows Cooking Oil 1L only
- `artifacts/layout-20261027/04-sidebar-collapsed.png`
- `artifacts/layout-20261027/06-view-cart-137.png` — View Cart open
- Browser check after the last build: quantity `1.37` produced total `KES 438.4`, then the cart was cleared
- Settings page showed the four wheel fields at 0.25, 1, 1, and 1
- DOM check: adjustment and receiving inputs had `step="1"`

## Not done

- The Windows till window was not opened, so the till search box, View Cart button, and focused spin-box wheel were not photographed.
- Archive was not clicked in the browser. The API test already covers the permission and the soft archive.
- No sale was completed, so receipt printing was not exercised.
- No new installer. `C:\MBT_Build\release_3.1.70\MBT_POS_Setup.exe` does not contain this work. Program Files is still 3.1.68. GitHub latest is still v3.1.67.
- Edmus activation and the two live command-poll checks were not run.
