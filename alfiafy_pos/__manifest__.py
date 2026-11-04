# -*- coding: utf-8 -*-
{
    'name': "Alfiafy Retail Pharmacy Counter Operations",
    'version': '20.0.1.0.0',
    'category': 'Point of Sale',
    'summary': "DES00135 - POS counter controls: mandatory customer phone, no "
               "out-of-stock sales, manager PIN for discounts above the cashier "
               "limit, wholesale quantity cap, multi-UoM prices, credit hold",
    'description': """
Alfiafy Retail Pharmacy Counter Operations (DES00135)
=====================================================
BRD 1.1 POS customizations #1-#5 and the POS side of 1.2 customization #4:

* Mandatory customer phone: an order cannot be validated without a customer
  that has a phone number; the cashier can add the number on the spot.
* No negative stock: a storable product cannot be added / increased beyond the
  free quantity of the branch stock location, and the order is re-checked
  against the server at payment.
* Discounts: percentage only (the keypad Price key is reserved to managers);
  up to the cashier limit (5 % by default) without approval, above it a
  manager PIN is required and the manager is recorded on the order line.
* Wholesale cap: "Max POS Quantity per Order" on the product.
* Multi-UoM with a separate price per unit (pos_multi_uom_price).
* Customer Account (credit) payments are refused for customers with overdue
  invoices or over their credit limit.
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'point_of_sale',
        'pos_hr',
        'pos_stock',
        'stock',
        'account',
        'alfiafy_product_base',
        'pos_multi_uom_price',
    ],
    'data': [
        'views/product_template_views.xml',
        'views/res_config_settings_views.xml',
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'alfiafy_pos/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
