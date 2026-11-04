# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .selections import LOT_SOURCING_TYPES


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    # Follows the order (itself pulled from the vendor); a buyer can change it
    # on a line when an official partner supplies non-agency items or the
    # other way round. The receipt moves and the lots take the line's value.
    sourcing_type = fields.Selection(
        LOT_SOURCING_TYPES, string="Line Sourcing",
        compute='_compute_sourcing_type', store=True, readonly=False,
        precompute=True, index=True)

    @api.depends('order_id.sourcing_type')
    def _compute_sourcing_type(self):
        for line in self:
            line.sourcing_type = line.order_id.sourcing_type

    def _prepare_stock_move_vals(self, picking, price_unit, product_uom_qty, product_uom):
        vals = super()._prepare_stock_move_vals(picking, price_unit, product_uom_qty, product_uom)
        vals['sourcing_type'] = self.sourcing_type or self.order_id.sourcing_type or False
        return vals
