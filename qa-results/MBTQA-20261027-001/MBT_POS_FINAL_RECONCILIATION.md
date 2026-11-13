# Final reconciliation — MBTQA-20261027-001

Independent figures for QA-Layered-Product before the void:

- Receipts: 10 x 100 + 10 x 140 = 2,400
- Sale of 12 at 200 = 2,400 revenue
- FIFO cost: 10 x 100 + 2 x 140 = 1,280
- Gross profit on that sale: 1,120

The Super Admin void restored that sale's layers. Later period totals include the other test sales and are in `snapshot.json`.

Debt series expected after a 1,000 credit sale: 700, 500, then 0.

Report summary from the application: `{"avg_transaction": 357.7555555555556, "cogs": 2119.25, "profit": 1100.55, "total_discounts": 10.0, "total_revenue": 3219.8, "total_tax": 0.0, "total_transactions": 9, "uncosted_lines": 0, "uncosted_revenue": 0.0}`

Period function: `{"profit": 1100.55, "revenue_costed": 3219.8, "cogs": 2119.25, "uncosted_revenue": 0.0, "uncosted_lines": 0, "costed_lines": 11}`
