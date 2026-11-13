# Mixed-tender acceptance MBTQA-20261027-002

Branch `port/v3.1.66-audit`, commit `f1df495`, plus uncommitted tender work.
Isolated database `C:\MBT_Build\qa-mixed-tender-20261027\shop\data\mbt_pos.db`. The live shop database was not opened.

| Status | Count |
|---|---:|
| PASS | 13 |
| FAIL | 0 |
| NOT SUPPORTED | 2 |

A KES 1,000 sale can now take cash, M-Pesa, card, bank transfer, and a customer-credit remainder in one receipt. A pending M-Pesa line is not collected. Repeating the same client token does not create a second sale. Repayments of 100, 150, and 250 take a 500 balance to 0 and do not add a sale.

Dedicated cart-splitting is not a separate action. Two checkouts sell the chosen quantities once each.
Real Safaricom charges were not made.

The installed Program Files till is still 3.1.73 and does not contain this tender change.

The dashboard UI was used for one live checkout on the disposable shop. Receipt RCP-20261027-0014 is KES 1,000, paid KES 500, notes show Credit 500, M-Pesa 300 and Cash 200, and the linked debt balance is KES 500. Stock moved from 382 to 372. Screenshot: `qa-results/MBTQA-20261027-002/MBT_POS_QA_SCREENSHOTS/st05-cash-mpesa-credit-receipt.png`.
