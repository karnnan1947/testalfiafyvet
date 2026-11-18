# Alfiafy Stock - Branch Transfers, Expiry Alerts & Stock Controls (`alfiafy_stock`, DES00138)

BRD 1.5 points #14, #15/#16, #18, #19, #20 and #28 (Odoo 20).

Depends on `stock`, `alfiafy_product_base`, `purchase` (as in the plan), plus
`product_expiry` (lot expiration dates), `sale_stock` (the user's Default
Warehouse, used as "the user's branch") and `sale_and_purchase_approvals_steps`
(Internal Transfer approval steps).

| Area | What it does |
|---|---|
| Branch transfer limit (#28) | Product > Inventory > Branch Stock Controls > **Max Branch Transfer Qty** (0 = unlimited). An internal move between two branches (warehouses other than the main, first warehouse of the company) above the limit is refused when it is created, changed or validated. Stock Managers can authorise larger transfers; resupply from the main warehouse is not limited. |
| Transfer status (#15/#16) | Internal transfers get **Transfer Status** Draft > (To Approve >) Approved > In Transit > Received, **Dispatch Date** and **Delayed** (> 48 h in transit). Buttons **Approve**, **Dispatch Goods** (reserves the goods, records the dispatch date) and **Confirm Receipt** (validates the transfer into the branch). Status bar on the form, red banner when delayed, colour badges in the Internal Transfers list. |
| Transfer approval steps (#2) | Settings > Technical > Approval Management > **Approval Steps**, Type **Internal Transfer**: **Sequence**, **User** and an optional **Source Warehouse** (blank = every internal transfer; no amount condition). When a step applies, the requester clicks **Submit for Approval** (status **To Approve**) instead of the direct Approve. Approvers on the same sequence are alternatives (either one approves); higher sequences follow in order. Pending transfers are under Inventory > Operations > **My Approvals**. **Cancel** while To Approve is a rejection/withdrawal with a mandatory reason. After the last step the transfer is **Approved** and the final approver gets a "Approved - Dispatch Goods" activity. **Dispatch Goods**: Stock Manager, a user of the dispatching warehouse or an approver of the transfer. Validate stays hidden and blocked on internal transfers. Without such a step the direct storekeeper **Approve** is used as before. |
| Delayed transit alert | Daily scheduled action "Stock: Delayed In-Transit Transfers": a To-Do "Transfer in transit for more than 48 hours" for the users of the dispatching warehouse and of the receiving branch (Stock Managers if none), not repeated while open. |
| Variance approval (#19) | Physical Inventory: **Variance Value** = (counted - on hand) x cost (cost-access users only), red rows above the threshold, **Variance Approval** badge (Draft / Waiting Approval / Approved). A non-manager applying a count above the threshold gets "Approval required": the line is not applied, it waits for approval and every Stock Manager gets an activity on the product. Smaller differences are applied as usual. The Stock Manager applies the line (filter **Pending Variance Approvals**) and it becomes Approved. Threshold: system parameter `alfiafy_stock.variance_approval_threshold` (default 500). |
| Near-expiry alerts (#14) | Product > **Expiry Alert Window (days)** (default 180). Daily scheduled action "Stock: Branch Near-Expiry Alerts": one e-mail per warehouse listing its expired (red) and near-expiry (orange) lots on hand, sent only to the users whose Default Warehouse is that warehouse and to the Stock Managers. |
| Scrap (#20) | Scrap menu, Scrap action and the Scrap actions on transfers and lots are for Stock Managers only; the scrap Confirm buttons and the server-side `action_scrap` too. |
| Stock visibility (#18) | Branch (Inventory) users read on-hand stock of all branches; valuation (`product.value`) and cost fields stay with managers. |

Users: set each branch user's **Default Warehouse** (user form, Preferences)
to their branch; it decides who gets the delayed-transfer and expiry alerts.

Tests: `--test-tags /alfiafy_stock` (13 tests).
