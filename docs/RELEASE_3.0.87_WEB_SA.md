# MBT POS 3.0.87 — web Super Admin role coverage

## Shipped in this version
- Web Super Admin can perform elevated actions cashiers cannot (Adjust, debt write-off with PIN, Users & Access)
- Cashier inventory export / cost / inventory_value nav hardened (POS inventory tab no longer grants valuation/export)
- Web APIs: POST adjust (SA), receive, debt write-off; GET products redacts cost without inventory.view_cost
- SPA: Adjust / Receive on Inventory; Collect + Write-off on Debt; Add/Edit users for admin/SA
- Legacy dashboard.html fallback aligned for cost gate + Receive/write-off honesty

## Verify
- pytest: tests/test_access_audit_web_gates.py + tests/test_permissions_matrix.py (+ export-related)
- Install 3.0.87; license remains Active; LocalAppData identity preserved
- Cashier: no cost, no inventory export, Adjust denied; SA: Adjust/write-off/Users on web
