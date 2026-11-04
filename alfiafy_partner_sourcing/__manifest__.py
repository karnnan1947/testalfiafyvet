# -*- coding: utf-8 -*-
{
    'name': "Alfiafy Partner vs. Outside Sourcing Traceability",
    'version': '20.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': "DES00139 - Official Partner / Outside sourcing from purchase to "
               "lot, sales delivery, POS, invoices and a sourcing margin report",
    'description': """
Alfiafy Partner vs. Outside Sourcing Traceability (DES00139)
============================================================
BRD 1.4 #6 / customization #30: products bought from Official Partners and
from Outside local suppliers are identified at purchase; the source is carried
to the receipt and the lot and shows on POS, sales order lines and invoices,
so management can compare margin by Partner vs Outside, even for the same
product.

* Vendor -> purchase order (and line) -> receipt moves -> lot: the lot keeps
  its sourcing, the purchase order, the vendor and the unit purchase cost.
* Sales: delivery move lines carry the sourcing of the lot delivered; the
  sales order line shows it; invoice lines are split by sourcing (e.g. 10
  units from a partner lot and 5 from an outside lot give two lines).
* POS: the sourcing of the lot sold is shown on the order line and stored on
  the POS order line; POS invoices carry it.
* Invoicing > Reporting > Sourcing Margin Analysis: revenue, cost of goods
  sold (purchase cost of the lots sold), gross profit and margin % by
  sourcing (pivot and graph).

The vendor / purchase order / receipt / lot sourcing itself was delivered with
alfiafy_purchase (DES00137); this module completes the traceability.
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'purchase',
        'stock',
        'sale',
        'point_of_sale',
        'account',
        'alfiafy_product_base',
        # technically required in Odoo 20
        'alfiafy_purchase',    # vendor / PO / receipt / lot sourcing (DES00137)
        'purchase_stock',      # receipts generated from purchase orders
        'sale_stock',          # delivery moves of sales order lines
        'pos_stock',           # lots sold in the POS
    ],
    'data': [
        'security/ir.access.csv',
        'views/purchase_order_views.xml',
        'views/stock_lot_views.xml',
        'views/stock_move_line_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'views/pos_order_views.xml',
        'report/sourcing_margin_report_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'alfiafy_partner_sourcing/static/src/**/*',
        ],
    },
    'post_init_hook': '_post_init_backfill',
    'installable': True,
    'application': False,
    'auto_install': False,
}
