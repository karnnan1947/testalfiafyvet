{
    "name": "Sale and Purchase Approvals",
    "version": "20.0.1.0.0",
    "author": "AGM Global Services",
    "license": "LGPL-3",
    # Odoo 20: the Alternatives tab (alternative_po_ids) moved from
    # purchase_requisition to purchase_alternative. sale_expense was not used.
    "depends": ["base", "sale_management", "sale", "purchase", "purchase_alternative", "stock", "sale_margin"],
    "data": [
        "security/groups.xml",
        "security/ir.access.csv",
        "data/mail_activity_type_data.xml",
        "views/approvals.xml",
        "views/sale_order.xml",
        "views/purchase_order.xml",
        "wizard/purchase_waiver_wizard_views.xml",
        "wizard/approval_cancel_wizard_views.xml",
        "views/stock_picking_view.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
