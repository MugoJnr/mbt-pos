# MBT POS — decisions taken from the shared conversation

Source read: https://chatgpt.com/share/6b012e46-c43c-83ea-b5e6-ff795d21d7b6
Title: Test MBT POS Everything (6)
Read in full on 21 Nov 2026 from the share’s data, not from the short page that first appeared. That page only showed the last few messages, about 90,000 characters. The share itself has 54 messages.

## What that conversation actually contains

It starts with the FIFO costing prompt, then your follow-ups. It does not go back to the first day of the MBT POS project. Licensing, backup, photos, and categories appear only inside the generated prompts at the end, not as their own discussion.

In order, you decided:

1. Product history must show every delivery batch, including batches bought on different days at different buying prices.
2. The product’s normal selling price stays the default. A batch may have its own selling price. A button under history manages that.
3. FIFO stays the normal way a sale takes stock. An authorised person may sell a chosen batch first.
4. On the cart and the receipt, the same product appears as separate lines when the batches have different selling prices, labelled with the batch, such as B002 and B003. If those prices are the same, the customer sees one line. The separate batch costs stay recorded either way.
5. Inventory has a Batches place: a searchable list, and opening a product shows the batch details and the same editing as history.
6. A return starts from the original receipt. The customer can return one line, or a quantity, not the whole receipt. A cashier sends it to the Request Centre. An admin can process it immediately. The original receipt is not rewritten.
7. Wherever a cashier already has to send a request, they can instead have a Super Admin enter a PIN and the action runs at once. Admin dashboards show a clickable banner while requests are waiting.

You then asked for one prompt covering that whole chat, and corrected the first draft because it only covered the PIN.

## What MBT POS is for

A shop should be able to sell, receive stock, track what each delivery cost, take returns, keep debts and expenses, and let the owner see the same truth on the till, the shop web dashboard, and the cloud portal. The till and the web dashboard work on the shop’s own database. The portal receives a copy. It does not share the live shop database. A second computer is another device and needs its own licence seat.

## Decision agreed in the shared chat: batch selling prices

- History lists every batch, including finished ones, with the date, buying price, what is left, and whether the selling price is the normal product price or a custom one.
- Receiving stock still records that delivery’s buying price. The batch selling price is optional. Leaving it empty means the product’s normal price.
- A custom price belongs to that batch only. Changing the product’s normal price moves every batch that is still on the normal price. It does not move a custom batch.
- Changing a batch price later does not change receipts already issued.
- A price below the landed cost warns. A price above the normal product price asks for confirmation.
- A finished batch can still be inspected. It cannot be given a new selling price for stock that is gone.
- Only an authorised person sets batch prices. A cashier does not get that automatically.
- A discount that is already allowed still works.

## Decision agreed in the shared chat: how a sale uses batches

- The till chooses the oldest stock first.
- An authorised person can pick another batch first, for example stock that is near expiry. That needs its own permission. The screen shows what FIFO would have done, what was actually chosen, the quantities, and a reason. The person and the time are stored.
- They cannot sell more than that batch has, change its buying price, or use the same units twice.
- If the quantity needs more than one batch, each batch keeps its own selling price and its own cost.
- The cashier sees that breakdown before payment. The customer is not charged a price they were not shown.
- Example that was agreed: 20 left at a selling price of KSh 70 and 50 left at KSh 65. A sale of 35 takes 20 at KSh 70 and 15 at KSh 65. Revenue is KSh 2,375. Cost uses each batch’s own landed cost.
- The cart and the receipt show those as two lines with the same product name and the batch reference. If both batches sell at the same price, the customer sees one line, and the two batch costs remain stored underneath.
- The till and the web dashboard follow the same rules. The portal stores the actual prices and the actual batch costs, and does not assume FIFO afterwards.

## Decision agreed in the shared chat: returns

- The reliable start is the original receipt, found from the Receipts tab. Point of Sale can also open a return, including when the product is now out of stock.
- The cashier enters the customer and the reason. The request waits in the Request Centre. An admin, or someone higher, can complete it immediately under the same checks.
- The customer can return one product, two products, or part of a quantity. Example agreed: 3 cooking oil, 2 sugar, 5 rice. Returning 1 oil and 2 rice refunds KSh 250 + KSh 320 = KSh 570. Sugar is untouched.
- The refund uses the price that was charged on that receipt, not today’s price.
- The most that can come back is what was sold minus what was already returned. An admin cannot pass that limit.
- Goods that can be sold again go back to the batch they came from, not onto the newest batch. Damaged goods are recorded and do not go back on the shelf.
- The original receipt stays as it was. The return is a separate note linked to it. One receipt can have several partial returns.
- A refund is not the same thing as putting the goods back. It is not marked paid until it is actually paid. An M-Pesa reversal is not claimed unless it happened.

## Decision agreed in the shared chat: three ways an action can proceed

This is the decision you wrote, and you described it as the behaviour to build.

1. The person already has permission. The action runs. No extra prompt.
2. The person does not have permission, but the action is allowed to be authorised. They get two choices:
   - Send Request. The exact proposed change is saved. Nothing in stock, money, or sales changes yet. An authorised reviewer approves or rejects it later.
   - Super Admin authorisation. A Super Admin types their own PIN and the exact action runs immediately.
3. The action is blocked by licensing, the device, or financial integrity. Neither a request nor a PIN can bypass it.

The PIN authorises that one action. It does not turn the cashier into a Super Admin.

## Decision agreed in the shared chat: the PIN

- Each Super Admin has their own PIN, tied to that account.
- There is no PIN shared by the whole shop, and none baked into the program.
- It is checked on the server, stored hashed, and never written into logs.
- Wrong attempts are limited and then locked for a while.
- The Super Admin should type it themselves. The cashier should not be given the PIN.
- The screen must show the exact action first, for example the receipt and the refund amount, not a bare “Confirm”.
- A PIN cannot bypass an expired licence, the wrong device, or a change that would break the books.

## Decision agreed in the shared chat: Request Centre and the dashboard

- One Request Centre for the shop, on the till and the web dashboard, using the same records.
- A request stores the reference, who asked, their role, the exact before-and-after values, the reason, the reviewer, and the result.
- Statuses are Pending, Approved, Rejected, Executed, Cancelled, and Failed.
- Approved is not the same as done. The books change only after the action commits.
- Clicking twice must not create two requests or run the action twice.
- Two administrators must not both execute the same request.
- If the proposed numbers change after submission, that is a new or revised request. The reviewer must not approve one set of numbers while another set is applied.
- Admin and Super Admin dashboards show a banner only while they have requests they are allowed to review. It shows the count, can show the types, opens the Request Centre, and disappears when nothing is waiting.
- Reviewers are notified when a request arrives. The person who asked is notified of the outcome. A cashier can see their own requests.
- An action done immediately with a PIN is audited. It is not also stored as a fake pending request.
- The portal receives the finished transactions through the existing upload. It is not a second live till.

## Requested by the master prompt, original thread not in the link

These are in the prompt you asked to be followed. They are requirements of this task. They are not quotes from an earlier design discussion inside the shared link.

- Deliveries keep their own buying price. A later delivery does not rewrite older stock. The product-card buying price is not the cost of a past sale. If no batch cost exists, the cost stays unknown.
- The worked example is 100 at KSh 40, then 100 at KSh 55, then sell 120 at KSh 70. Cost is KSh 5,100. Profit is KSh 3,300. The second batch still has 80.
- Product history on the till and the web dashboard shows each batch.
- Empty and negative buying prices are rejected. Zero needs an explicit free-stock confirmation. A buying price above the selling price needs a warning and a confirmation, and is not silently blocked.
- A batch may have its own selling price. Blank means use the product’s normal price. Changing the product price does not change a custom batch price. Resetting the batch returns it to the normal price. A custom price below landed cost warns. Exhausted batches stay in history and cannot be sold.
- Normal sales use FIFO. Choosing a different batch needs a separate permission, a reason, and an audit record. Cashiers do not get that by default.
- If one sale takes batches with different selling prices, the customer sees each price before payment. A return uses the price that was charged, not today’s price.
- Returns start from the original receipt, can be partial, cannot exceed what is still returnable, restore resalable goods to the original batch, and do not put damaged goods back on the shelf. The original receipt is not rewritten.
- Split payment may use more than two methods, including cash, M-Pesa, card, and credit, as long as they add up.
- Cancelling a debt is not the same as reversing the sale or refunding cash.
- Cashiers see their own selling work. They do not automatically see profit, buying prices, or stock value. The server enforces that, not only the screen.
- Categories are created by the shop. There is no fixed global category list.
- Product photos can be added, replaced, and removed, and must not block selling.
- Backup, encrypted cloud copy, and restore are different from “the portal can see the sale”. Restore is tested on a disposable database and does not merge into the live shop.
- Licensing stays enforced offline. Recovery codes come from the MugoByte portal, are bound to the shop device, last about 30 minutes, are checked offline with a public key, and do not create a permanent developer login.
- The till must not say success before the database commit. Slow screens are to be measured and fixed at the cause.
- A release is real only after a separate install shows the new version. Pushing Git is not that.

## Already settled in this Cursor project, not in the shared chat

These come from the current source and from the work already done in this session. They match the prompt. They were not debated inside the shared link.

- The shop database already stores each delivery as a batch and consumes the oldest batch first.
- The till and the web product history already list those batches.
- A sale is no longer given the product-card buying price when it has no batch. That cost stays unknown.
- The portal profit code now ignores the card price and uses only a cost stored on the sale line.
- That portal change is not deployed. The installer that would stamp costs on the shop till has not been built. Older portal sales stay unknown.

## Unresolved

- The shared link does not include the earlier chats, so any refinement that lived only in those chats is not visible here. The master prompt is the latest written list.
- Per-person Super Admin PINs are the agreed design. The program today stores one shop PIN hash. Replacing that has not been designed in detail beyond the rules above.
- Whether every existing approval screen should be moved onto the new framework, or only the ones that are safe to authorise with a PIN, still has to be decided per action. Licensing and device checks stay blocked.
- Batch selling prices are requested and are not in the batch records yet. Sale pricing still uses the price sent by the till.
- Production deploy and a shop installer were explicitly not to be published until the chain is verified. That limit still stands.
