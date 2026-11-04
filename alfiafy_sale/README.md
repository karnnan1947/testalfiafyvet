# Alfiafy Wholesale Sales & Commercial Controls (`alfiafy_sale`, DES00136)

Sales controls for Alfiafyvet (Odoo 20). Depends on `sale`, `sale_stock`,
`alfiafy_product_base` and `sale_and_purchase_approvals_steps`.

| Control | How it works |
|---|---|
| Discount approval (BRD 1.2 #1) | New Sale approval criterion **Any Discount** (Settings > Technical > Approval Steps). A step "Sale / Any Discount / administrator" is created on install. A quotation with a discount on any line shows "Send for Approval" instead of Confirm, and Confirm called from anywhere else also sends it for approval. |
| Customer price history (#2) | "Last Price" column on quotation lines (last confirmed net price for this customer, or "First Time Sale") and a history button opening the last 5 confirmed sales (date, qty, unit price, discount, net price, Current is Higher / Lower / Same Price). |
| Out-of-stock (#3) | "Free Qty" column (free quantity of the order's warehouse, in the line's unit; red when none, orange when not enough). Quotations can be saved; Confirm is refused with the available quantity when the ordered quantity (all lines of a product together) is not free. |
| Credit hold (#4) | Red banner on the quotation and Confirm refused when the customer is over the credit limit (receivable + confirmed orders not invoiced + this order, Accounting setting "Customer Credit Limit") or has unpaid invoices past their due date. "Block on Overdue Invoices" on the customer (Invoicing tab, on by default) switches the overdue hold off for one customer. |

Order of the checks on Confirm: stock, credit limit / overdue invoices, then
the discount approval.

Tests: `--test-tags /alfiafy_sale`.
