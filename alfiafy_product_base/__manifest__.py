# -*- coding: utf-8 -*-
{
    'name': "Alfiafyvet - Product Base",
    'version': '20.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': "DES00134 - Veterinary product master fields and cost security (foundation module)",
    'description': """
Alfiafyvet Product Base (DES00134)
==================================
Foundation module of the Alfiafyvet implementation. Every other alfiafy_*
module depends on it.

* Veterinary product master fields: Arabic name / description, active
  ingredient (molecule), target species, dosage form, strength, storage
  condition, prescription flag, item type.
* Manufacturer and Supplier as separate fields on the product (BRD 1.5 #8).
* Stock on hand can be filtered and grouped by Manufacturer and Supplier.
* Product cost / margin visibility restriction, provided by the
  restricted_cost_access module (BRD 1.6 #2): only users in
  "Show Cost and Margin" see cost and margin figures.
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'product',
        'stock',
        'restricted_cost_access',
    ],
    'data': [
        'security/ir.access.csv',
        'data/target_species_data.xml',
        'views/target_species_views.xml',
        'views/product_template_views.xml',
        'views/stock_quant_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
