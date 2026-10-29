# Shop roles

The till and the dashboard use the same `users` table. The signed-in role is read from that row on every request. A role sent in the request body is not treated as the caller's role.

| Action | Cashier | Viewer | Manager | Admin | Super Admin |
|---|---|---|---|---|---|
| Sell and take payment | Yes | No | Yes | Yes | Yes |
| Request a void | Yes | No | Yes | Yes | Yes |
| Void a sale | No | No | PIN | PIN | Signed-in session |
| Restore a voided sale or consumption | No | No | No | No | Yes, once |
| Add or edit a product, including price | Yes | Yes | Yes | Yes | Yes |
| Remove a product | No | No | No | Yes | Yes |
| Deactivate another staff account | No | No | No | Yes, not Super Admin or yourself | Yes, not yourself |
| Receive a supplier delivery | Yes | No | Yes | Yes | Yes |
| Change stock quantity directly | No | No | No | No | Yes |
| Approve a stock request | No | No | No | No | Yes |
| Create a user | No | No | No | Yes, not Super Admin | Yes |
| Change a Super Admin account | No | No | No | No | Yes |
| Change the Super Admin PIN or its hash | No | No | No | No | Yes |
| Edit shop settings | No | No | No | Yes | Yes |

A login password and the Super Admin PIN are different secrets. The PIN hash and messaging tokens are not included in settings or profile responses.

A viewer cannot take a payment. Product cost is limited to a manager, an admin, and the Super Admin. A cashier records only their own expenses and their own debts, and does not see shop profit, live monitoring, notifications, backup, or system health. A manager can open Settings and cannot save them.

A cashier cannot type a past business date on the sales screen. The cashier prepares a backdating request instead. A manager, admin, or Super Admin reviews it. Approval posts the sales, stock, and any debt once. A cashier sees only their own requests, sales, and notes. A viewer can read notes but cannot write them. The audit log is limited to Admin and Super Admin. Marking the sync queue as sent is limited to Admin and Super Admin. The shop must keep one active Super Admin. An unknown role is denied.
