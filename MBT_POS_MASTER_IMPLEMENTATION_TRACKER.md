# MBT POS master implementation tracker

Acceptance marksheet, 21 Nov 2026. A requirement is VERIFIED — PASS only after both screens and the applicable checks pass. Passed: 1. Incomplete: 24. Failed: 0. Blocked: 0. Requirement 1 is VERIFIED — PASS. The Edmus portal was deployed and operated on 21 Nov 2026; that does not add another pass. Cashier denial and Admin self-elevation were operated on the till and the web, and the API rejected the same attempts. Evidence: `qa_evidence/completion-20261121/REQ-01`, plus the earlier create/edit/disable records in `qa_evidence/acceptance-20261121/REQ-01`. Next: Requirement 2.

| Requirement | Main Till | Web Dashboard | Cross-interface | Portal | Evidence | Final |
| --- | --- | --- | --- | --- | --- | --- |
| 1 User accounts | 3 | 3 | 3 | N/A | qa_evidence/completion-20261121/REQ-01 | 3 |
| 2 Permissions and navigation | 2 | 2 | 0 | N/A | none | 1 |
| 3 Super Admin PIN | 2 | 2 | 0 | N/A | automated test only | 1 |
| 4 Send Request or PIN | 1 | 1 | 0 | N/A | none | 1 |
| 5 Request Centre | 2 | 2 | 0 | N/A | none | 1 |
| 6 Pending-request banner | 2 | 2 | 0 | N/A | none | 1 |
| 7 Products | 2 | 2 | 0 | N/A | none | 1 |
| 8 Product photos | 2 | 2 | 0 | N/A | none | 1 |
| 9 Categories | 2 | 2 | 0 | N/A | none | 1 |
| 10 Receiving and suppliers | 2 | 2 | 0 | N/A | none | 1 |
| 11 Batches and FIFO | 2 | 2 | 0 | 1 card price removed; Edmus lines have no batch cost | qa_evidence/completion-20261121/PORTAL | 1 |
| 12 Batch prices and manual selection | 2 | 2 | 0 | 1 | qa_evidence/completion-20261121/PORTAL | 1 |
| 13 Stock adjustments and stocktakes | 2 | 2 | 0 | N/A | none | 1 |
| 14 Sales | 2 | 2 | 0 | N/A | none | 1 |
| 15 Payments | 2 | 2 | 0 | N/A | none | 1 |
| 16 Receipts | 2 | 2 | 0 | N/A | none | 1 |
| 17 Voids and backdating | 2 | 2 | 0 | N/A | none | 1 |
| 18 Receipt-first returns | 2 | 2 | 0 | N/A | qa_evidence/completion-20261121/REQ-18 | 1 |
| 19 Customers and credit | 2 | 2 | 0 | N/A | none | 1 |
| 20 Debts | 2 | 2 | 0 | N/A | none | 1 |
| 21 Expenses and supplier finance | 2 | 2 | 0 | N/A | none | 1 |
| 22 Reports and exports | 2 | 2 | 0 | 1 finance categories operated on Edmus | qa_evidence/completion-20261121/PORTAL | 1 |
| 23 Audit | 2 | 2 | 0 | N/A | none | 1 |
| 24 Settings, backup, restore | 2 | 2 | 0 | N/A | none | 1 |
| 25 Offline, licence, sync, Portal | 1 | 1 | 0 | 1 Edmus portal operated; payments not uploaded | qa_evidence/completion-20261121/PORTAL | 1 |

Statuses: 0 not implemented, 1 partial, 2 code present and not operated, 3 verified pass, 4 failed, 5 blocked. Rows 2–25 were not operated in this session. A 2 is not a pass.

Feature notes from earlier code work follow. They are not acceptance results.

Updated 21 Nov 2026. Branch `port/v3.1.66-audit`, commit `8624c7b`, plus uncommitted work.
The share has 54 messages. The first read of the page missed the earlier ones. Batch selling prices, cart lines, choosing a batch, and partial returns were decided in that chat, not only inside the final prompt.
A requirement is VERIFIED only when the same workflow has been used on the Main Till and on the Web Dashboard against a disposable shop. A passing test is not verification. The live Edmus database was not used.

| Requirement | Backend | Main Till | Web Dashboard | Portal where applicable | Verified |
| --- | --- | --- | --- | --- | --- |
| Three paths: allowed, request-or-PIN, or blocked | Stock reduction, delivery correction, approval execution, and debt write-off now check the named Super Admin's own PIN. The shop-wide hash is not accepted there. Emergency password reset still uses the shop hash. The two-choice screen is not on every action | Till dialog asks for the Super Admin username, then their PIN | Stock adjustment asks for the username and PIN | Not the live till | NO |
| Each Super Admin has their own hashed PIN | A per-account salted hash, lockout after five failures, and an authorise check that does not run the action. The older shared shop PIN still gates existing approvals | Not operated | Set and authorise endpoints exist. Not operated | Not applicable | NO |
| Request does not change stock or money until execution | Existing request flows | Existing screens | Existing screens | Finished rows upload later | NO |
| Approval is not the same as execution | Status fields exist on some workflows | Same records | Same records | Not applicable | NO |
| Request Centre is the one review place | Shared request records | Screen exists | Screen exists | Not applicable | NO |
| Dashboard banner with a live pending count | Count comes from Request Centre for manager, admin, and super admin | Dashboard banner opens Request Centre and hides at zero | Web banner links to Request Centre and hides at zero | Not applicable | NO |
| No double submit and no double approval | Some client tokens exist | Same | Same | Upload keys exist | NO |
| Cashier sees only their own requests | Not rechecked | Not rechecked | Not rechecked | Not applicable | NO |
| Portal is a copy, not the live shop database | Shop uploads selected rows | Local database | Local database | Reads the copy | NO |
| FIFO batches keep their own buying price | Cost layers and sale-line snapshots | History shows the batches | History uses the same API | Stored line cost only after a shop build syncs it | NO |
| 100 at 40, 100 at 55, sell 120 at 70 = cost 5,100, profit 3,300 | Disposable test passed | Not operated | Not operated | Edmus has no uploaded batch cost, so this example is not on the live portal | NO |
| Unknown cost stays unknown | Card price is not used as a cost | Same rule | Same rule | Operated on Edmus: 744 lines, profit Unknown | NO |
| Product history lists every batch | Same history API, with batch references B001, B002 | Batches tab and an Inventory Batches list | Purchase batches panel and an Inventory Batches list | Not applicable | NO |
| Buying price empty, negative, or zero is rejected | Enforced on receive | Receive dialog | Receive form | Not applicable | NO |
| Optional selling price on a batch | Stored, audited, permission `inventory.batch_price` | Set batch selling price on history; optional on receive | Set price on history; optional on receive | Not synced | NO |
| A sale charges different batch prices as separate lines | Quote is ready before payment. Same price stays one line. Test: 20 at 70 and 15 at 65 = 2,375, labelled B001 and B002 | Cart asks for the quote when the product is added or the quantity changes | Cart asks for the quote when the product is added or the quantity changes | Posted lines sync later. Live portal unchanged | NO |
| Custom batch price survives a product price change | Disposable test passed | Same record | Same record | Not applicable | NO |
| Reset batch price back to the product price | Blank price clears it | Leave the price blank | Leave the price blank | Not applicable | NO |
| Warn when the custom price is below landed cost | Warning returned | Dialog after save | Toast after save | Not applicable | NO |
| Price above the normal product price needs confirmation | Saved after the screen confirms | Confirmation dialog | Confirmation dialog | Not applicable | NO |
| Exhausted batch cannot be repriced | Rejected | Message, button does not save | Button hidden | Not applicable | NO |
| Manual batch pick with a reason | Permission `inventory.sales.override_fifo` on admin and super admin. Named batch is consumed. Reason is required and audited. Cashier is rejected | Right-click a cart line, Sell a chosen batch. FIFO comparison is shown before payment | Choose batch on the cart line. Same preview | The sale line syncs later. The override reason is local audit | NO |
| Returns from the original receipt, partial, original price | Existing return flows | Existing screens | Existing screens | Uploads the result | NO |
| Cashier cannot set a batch selling price | Permission denied | Button hidden | Button hidden | Not applicable | NO |
| Build and publish | Not in this pass | 3.1.90 remains the published installer | Not rebuilt | Portal deployed and operated on Edmus. Shop installer unchanged | NO |

## Done in this pass

- Batch selling price can be set from product history on the till and on the web dashboard. Cashiers do not have `inventory.batch_price`. The change is audited.
- Receiving can store an optional batch selling price on both screens.
- A sale that ignores a custom batch price is not posted. Both carts split into the FIFO lines, including the worked example of 20 at 70 and 15 at 65. Payment is taken again.
- None of this is marked VERIFIED. The till window and the web dashboard have not been operated yet.

## Not done

The published installer is still 3.1.90. The live Edmus portal no longer prices profit from the product card. Every sale line in 1–21 Nov 2026 has no batch cost, so profit is Unknown. Supplier payments, phone, email, address, and contact were not in the uploaded copy.
