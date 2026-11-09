# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    max_transfer_qty = fields.Float(
        string="Max Branch Transfer Qty", default=0.0, digits='Product Unit',
        help="Maximum quantity of this product per branch-to-branch transfer "
             "(product unit). 0 = unlimited. Stock Managers can exceed it.")
    expiry_alert_days = fields.Integer(
        string="Expiry Alert Window (days)", default=180,
        help="Lots expiring within this many days are included in the daily "
             "near-expiry alert of their branch.")
