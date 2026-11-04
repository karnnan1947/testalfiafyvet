# -*- coding: utf-8 -*-
{
    'name': "Alfiafy Wholesale Sales & Commercial Controls",
    'version': '20.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': "DES00136 - discount approval, customer price history, no "
               "out-of-stock confirmation, credit limit and overdue invoice hold",
    'description': """
Alfiafy Wholesale Sales & Commercial Controls (DES00136)
========================================================
BRD 1.2 Sales customizations #1-#4:

* Discount approval: a quotation with a discount on any line is routed to
  "To Approve" (sale_and_purchase_approvals_steps) when it is confirmed. A
  new approval criterion "Any Discount" is added to the Sale approval steps
  and an "Any Discount" step for the administrator is created on install.
* Customer price history: last confirmed net price of the product for this
  customer on each quotation line, and a popup with the last 5 confirmed sales.
* Out-of-stock restriction: a quotation can contain products without stock,
  but it cannot be confirmed when the warehouse free quantity is not enough.
* Credit hold: confirmation is blocked when the customer is over the credit
  limit or has overdue unpaid invoices ("Block on Overdue Invoices" on the
  customer, on by default).
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'sale',
        'sale_stock',
        'stock',
        'account',
        'alfiafy_product_base',
        'sale_and_purchase_approvals_steps',
    ],
    'data': [
        'security/ir.access.csv',
        'data/approval_steps_data.xml',
        'wizard/sale_order_line_price_history_views.xml',
        'views/approval_steps_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
