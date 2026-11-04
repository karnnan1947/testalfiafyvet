# Alfiafy Financial Intelligence & Branch KPI Dashboards (`alfiafy_account_reports`, DES00140)

BRD 1.6 customization #1 (branch-wise profit tracking) and 1.7 #1 / #3 (Odoo 20).

Depends on `account`, `point_of_sale`, `analytic`, `alfiafy_product_base`.

| Area | What it does |
|---|---|
| Branch analytic accounts | Analytic plan **Branches** with: Branch 1 - Al Rayyan, Branch 2 - Al Wakra, Branch 3 - Al Khor, Branch 4 - Al Shahaniya, Branch 5 - Umm Salal, Branch 6 - Doha Central, Main Warehouse (Wholesale), Oman Branch Operations (shared by all companies, not updated on module upgrade). |
| POS register | Point of Sale > Configuration > Settings > Accounting > *Branch Analytic Account* (field `analytic_account_id` on `pos.config`). |
| Session closing | When a session is closed, the sales revenue lines (product lines) of the closing entry get the analytic distribution `{branch account: 100 %}`; refunds too. Invoiced POS orders are posted by their own invoice and are not tagged. |
| Branch P&L | Standard Accounting > Reporting > Profit and Loss: *Analytic* filter (one branch) or analytic columns (one column per branch). Requires Accounting > Settings > *Analytic Accounting*. |
| Sales targets | Point of Sale > Reporting > **Branch Performance Dashboard** (`pos.branch.target`): register, period, target. Live KPIs from the register's paid / posted POS orders in the period: achieved sales (sum of order totals, refunds deducted), achievement %, orders, unique customers, average ticket, MoM growth. Kanban dashboard, list (achievement green >= 90 %, orange 70-89 %, red < 70 %) and form. |
| Fast / slow movers | Point of Sale > Reporting > Orders > Favorites: **Fast-Moving Items** / **Slow-Moving Items** (product quantity by product, graph sorted descending / ascending). |

MoM growth = average daily sales of the target period (days elapsed so far
while the period is running) compared with the average daily sales of the
previous calendar month; 0 when the previous month has no sales.

## Procedure for branch managers: fast and slow-moving items

1. Point of Sale > Reporting > Orders.
2. Favorites > *Fast-Moving Items* (best sellers first) or *Slow-Moving Items*
   (lowest quantities first).
3. Filter the period (Date filter) and the branch (search *Point of Sale*,
   e.g. "Branch 2 - Al Wakra").
4. Switch to the pivot view for the figures; click the *Product Quantity*
   header to sort it.

Access: POS managers and accounting managers create / edit targets; POS users
read them.

Tests: `--test-tags /alfiafy_account_reports`.
