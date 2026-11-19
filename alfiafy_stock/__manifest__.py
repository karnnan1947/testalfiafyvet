# -*- coding: utf-8 -*-
{
    'name': "Alfiafy Stock - Branch Transfers, Expiry Alerts & Stock Controls",
    'version': '20.0.1.2.0',
    'category': 'Inventory/Inventory',
    'summary': "DES00138 - Branch transfer limit and status tracking, delayed transit "
               "alerts, stock-take variance approval, branch near-expiry alerts, "
               "scrap restricted to the Stock Manager",
    'description': """
Alfiafy Stock (DES00138)
========================
BRD 1.5 points #14, #15, #16, #18, #19, #20 and #28:

* Branch-to-branch transfer limit per product (Max Transfer Qty).
* Internal transfer status: Draft, To Approve, Approved, In Transit, Received,
  with Dispatch Goods / Confirm Receipt buttons and a delayed flag (> 48 h in
  transit). When Internal Transfer approval steps are configured
  (sale_and_purchase_approvals_steps), the transfer is submitted for approval
  and goes through the approvers by sequence before it can be dispatched.
* Daily alert for transfers in transit for more than 48 hours.
* Stock-take variance approval: a count difference above 500 (configurable)
  applied by a non-manager waits for the Stock Manager.
* Daily near-expiry / expired digest per branch, sent only to the users of
  that branch and to management.
* Scrap restricted to the Stock Manager.
* Branch users can see on-hand stock of all branches; valuation stays with
  managers.
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'stock',
        'alfiafy_product_base',
        'purchase',
        'product_expiry',
        'sale_stock',
        'sale_and_purchase_approvals_steps',
    ],
    'data': [
        'security/stock_security.xml',
        'security/ir.access.csv',
        'data/cron_data.xml',
        'views/product_template_views.xml',
        'views/res_users_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_quant_views.xml',
        'views/stock_scrap_views.xml',
    ],
    'post_init_hook': '_post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
