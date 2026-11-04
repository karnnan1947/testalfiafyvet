# -*- coding: utf-8 -*-
{
    'name': "Hide Cost",
    'version': '20.0.1.0.0',
    'category': 'Tools',
    'summary': "Restrict visibility of cost and margin-related data across Sales, Inventory, POS, and Products.",
    'description': """
        This module hides cost and margin information (like standard price, margin, margin %, total cost, etc.)
        from unauthorized users in Product, Sale Order, POS, Inventory, and related views.

        Access to cost-related fields is restricted using a custom user group.
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'product',
        'stock',
        'stock_account',
        'stock_landed_costs',
        'sale',
        'sale_margin',
        'product_margin',
        'point_of_sale',
    ],
    'data': [
        'security/security.xml',
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/stock_views.xml',
        'views/pos_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
