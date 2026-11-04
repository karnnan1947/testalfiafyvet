# Alfiafyvet - Purchase (`alfiafy_purchase`, DES00137)

Phase 2 (inbound supply chain) of the Alfiafyvet Odoo 20 implementation.
Depends on `alfiafy_product_base` and `sale_and_purchase_approvals_steps`.

| Area | What it does |
|---|---|
| Vendor (`res.partner`) | `vendor_sourcing_type` (Official Partner / Outside Supplier) and `default_purchase_type` (Local Purchase / Import Shipment) on the Purchase section of the Sales & Purchase tab; contacts follow their company. |
| Purchase order | `purchase_type` and `sourcing_type` pulled from the vendor (editable), badges in the RFQ / PO lists, filters and group-by. Sourcing is required before "To Approve" / Confirm. |
| Import tracking | Tab shown only for Import Shipment: shipment status, shipping line / forwarder, container no., B/L / AWB no., tracking no., port of entry, ETD, ETA (ETA >= ETD). Repeated read-only on the receipt. |
| PO line | `last_purchase_price` (latest confirmed price from this vendor, converted to the line's UoM and currency) and `price_trend` (▲ Increased / ▼ Decreased / ─ Same). |
| Price history | History button on each line opens `purchase.price.history.wizard`: last 10 confirmed purchases of the product across all vendors (date, PO, vendor, qty, unit price, sourcing). |
| Receipt / lot | `stock.picking.sourcing_type` follows the PO; when a vendor receipt is validated the lots received are stamped with the sourcing (`stock.lot.sourcing_type`). |
| Material requisition | `material.purchase.requisition` (MPR/YYYY/NNNNN): Draft > Waiting Approval > Approved > Done. Approval by Purchase Administrators. "Create Local RFQ" generates one draft Local Purchase RFQ per vendor (line vendor > preferred vendor > product Supplier > first vendor pricelist). Menu: Purchase > Requisitions > Material Requisitions. |
| PO approval | Installs an approval step "Purchase, Amount >= 0" for the administrator, so every PO goes through Waiting Approval. Add the accountant at the same sequence 10 (Settings > Technical > Approval Steps) so either can approve. |

The purchase order field linking to the requisition is `material_requisition_id`
(not `requisition_id`, which `purchase_requisition` already uses).

Tests: `--test-tags /alfiafy_purchase`
