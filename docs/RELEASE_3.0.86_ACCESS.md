# MBT POS 3.0.86 — production access + honest UI

## Shipped in this version
- Cashier: Add Product, edit info, Receive Stock; Inventory tab on upgrade
- Cost/margin hidden without inventory.view_cost
- Category Visuals / Export / Adjust Stock: locked buttons with reasons when denied
- Product delete split to inventory.delete (manager+)
- Manager Settings: view-only banner + Save disabled without settings.edit
- Denial messages explain role / PIN / policy
- Users & Access: tab vs vault copy
- Backdate + debt write-off remain Super-Admin PIN + role gated

## Verify
- pytest permissions/inventory/receive/version: pass
- Install 3.0.86, cashier Add+Receive, locked Adjust/Export/Categories
- Manager settings Save disabled; Super Admin write-off still PIN
