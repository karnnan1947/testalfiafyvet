# Alfiafy Partner vs. Outside Sourcing Traceability (`alfiafy_partner_sourcing`, DES00139)

BRD 1.4 #6 / customization #30 (Odoo 20). Goods bought from Official Partners
and from Outside local suppliers are identified at purchase, and the source
follows the goods to the lot, the sale (delivery, POS) and the invoice, so the
margin can be compared by source, even for the same product.

Depends on `alfiafy_purchase` (vendor / purchase order / receipt / lot
sourcing, DES00137), `purchase_stock`, `sale_stock`, `pos_stock`, `account`.

| Step | What is recorded |
|---|---|
| Vendor | Vendor Sourcing (Sales & Purchase tab), **Outside** by default for new vendors. |
| Purchase order | Sourcing from the vendor (badge in the header), editable; each line has its own sourcing, editable while the RFQ is draft. |
| Receipt | Each receipt move takes the sourcing of its purchase line. |
| Lot | Lot form > *Sourcing & Procurement Traceability*: sourcing (required, Outside for lots not received from a purchase order), origin purchase order, vendor and unit purchase cost (company currency, product unit), set when the lot is first received. |
| Delivery | Each move line keeps the sourcing of its lot ("Lot Sourcing" column in the move details, detailed operations and moves history). |
| Sales order line | *Sourcing* column: Official Partner / Outside Supplier / Mixed, from the lots reserved or delivered. |
| Customer invoice | *Sourcing* column on the lines. A sales line delivered from lots of both sources is invoiced as one line per source (e.g. 10 partner + 5 outside). Delivered quantities are invoiced first, then reserved ones; manual lines can be set by hand. |
| POS | The order line shows the sourcing next to the lot (e.g. "Lot OXY-2605-A · Official Partner"); the POS order line keeps it and the POS invoice carries it. |
| Report | Invoicing > Reporting > *Sourcing Margin Analysis*: quantity, revenue, cost of goods sold, gross profit, margin % by product and sourcing (pivot), gross profit by sourcing (graph). Customer invoices / credit notes plus POS orders not invoiced. |

Cost of goods sold = quantity sold (product unit) x purchase cost of the lots
sold (stored on the invoice / POS line when its sourcing is set); lines without
it use the product cost. Margin % of a group = gross profit / revenue. Credit
notes and POS refunds count as negative (Odoo 20 stores POS line amounts as
positive values; the sign comes from the quantity).

Tests: `--test-tags /alfiafy_partner_sourcing`.
