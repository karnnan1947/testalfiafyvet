# -*- coding: utf-8 -*-
{
    'name': "Alfiafyvet - Purchase",
    'version': '20.0.1.0.0',
    'category': 'Supply Chain/Purchase',
    'summary': "DES00137 - PO approvals, local/import PO, price trend & history, "
               "sourcing hand-over to receipts and lots, material requisitions",
    'description': """
Alfiafyvet Purchase (DES00137)
==============================
Phase 2 - inbound supply chain. Covers BRD 1.4 customizations #10-13, #27 and
the purchase side of #30:

* Vendor defaults: sourcing (Official Partner / Outside Supplier) and default
  purchase type (Local Purchase / Import Shipment) on the vendor.
* Purchase order: purchase type + sourcing pulled from the vendor, list
  badges, "Import Tracking" tab (container, B/L / AWB, forwarder, port of
  entry, ETD / ETA, shipment status) shown only for imports.
* Purchase order line: last purchase price for the product from this vendor
  and a price trend indicator (increased / decreased / same).
* Price history popup: last 10 confirmed purchases of the product across all
  vendors.
* Sourcing hand-over: receipts carry the PO sourcing; validated lots are
  stamped Official Partner / Outside Supplier.
* Material Purchase Requisition (MPR/YYYY/NNNNN): Draft > Waiting Approval >
  Approved > Done, generating draft Local Purchase RFQs per vendor.
* Purchase order approval for ALL purchase orders through
  sale_and_purchase_approvals_steps (an "amount >= 0" purchase step is
  created on install).
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'purchase',
        'purchase_stock',
        'stock',
        'alfiafy_product_base',
        'sale_and_purchase_approvals_steps',
    ],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/approval_steps_data.xml',
        'wizard/purchase_price_history_views.xml',
        'views/res_partner_views.xml',
        'views/purchase_order_views.xml',
        'views/material_requisition_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
