# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

{
    'name': "POS multi uom price",
    'summary': 'POS Price per unit of measure',
    'category': 'Point of Sale',
    'version': '20.0.1.0.0',
    'license': "AGPL-3",
    'description': """
        Sell a product in POS in several units of measure, each with its own price.

        * Each unit has its own price in the "UOM Price" table (e.g. one Unit
          = 100.00 sales price, Box of 5 = 300.00, Box of 10 = 500.00); prices
          are never derived from the unit price.
        * Only the product's own unit and the units with a price can be chosen.
        * Stock moves, invoices and costs use the unit the line was sold in.
        * Returns: a line sold per pack can be returned per piece (Orders
          screen, "Return Units"), at the price paid per piece (Pack of 6 sold
          at 300.00 -> 50.00 per piece), unless "Block Fractional Returns" is
          set on the register.
    """,

    'author': "ehuerta _at_ ixer.mx",
    'depends': ['point_of_sale', 'pos_stock'],
    'data': [
        'security/ir.access.csv',
        'views/product_view.xml',
        'views/pos_order_view.xml',
        'views/res_config_settings_views.xml',
    ],
    'images': [
        'static/description/POS_multi_uom_price.png',
    ],
    'installable': True,
    'auto_install': False,
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_multi_uom_price/static/src/**/*',
        ],
    },
}
