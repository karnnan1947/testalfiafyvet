# Alfiafy Retail Pharmacy Counter Operations (`alfiafy_pos`, DES00135)

POS counter controls for the Alfiafyvet branches (Odoo 20). Depends on
`point_of_sale`, `pos_hr`, `pos_stock`, `alfiafy_product_base` and
`pos_multi_uom_price`.

| Control | How it works |
|---|---|
| Customer phone (BRD 1.1 #1) | Validating a payment without a customer asks to select one; a customer without a phone number gets a popup to type it (saved on the customer). Without it the order is not validated. |
| No negative stock (#2) | Adding a storable product, or raising its quantity, is refused beyond the free quantity of the register's stock location (Operation Type of the register). The order is checked again against the server at payment. |
| Discount limit (#3) | Line discounts are typed in a popup. Up to the cashier limit (5 % by default) they apply at once; above it a manager PIN is required (employees with manager access on the register). A wrong PIN refuses the discount. The approving manager is stored on the order line (`discount_approved_by_id`). The keypad Price key is reserved to managers so no fixed-amount discount can be given. |
| Wholesale cap (#4) | `Max POS Quantity per Order` on the product (Point of Sale tab). The total quantity of the product in one order (all lines, in the product's unit) cannot exceed it. |
| Multi-UoM prices (#5) | `pos_multi_uom_price`: UoM button on the order line. Each unit has its own price (Point of Sale tab > UOM Price); only priced units can be chosen. Single pieces of a pack can be returned (Orders screen, "Return Units") at the price paid per piece, unless the register setting "Block Fractional Returns" is on. |
| Credit hold (1.2 #4) | Customer Account payments are refused for customers with overdue invoices (unless "Block on Overdue Invoices" is unticked, with `alfiafy_sale`) or above their credit limit (Accounting setting "Customer Credit Limit"). Checked live on the server when the method is selected and at validation. |

Settings: Point of Sale > Configuration > Settings > Pharmacy Counter Controls
(per register): Discount Approval + cashier limit, Customer Phone Required,
Block Out-of-Stock Sales.

Tests: `--test-tags /alfiafy_pos` (server side). The cashier screens were
checked with the POS UI on the test database.
