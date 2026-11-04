# -*- coding: utf-8 -*-
from odoo import fields, models

from .selections import LOT_SOURCING_TYPES


class StockMove(models.Model):
    _inherit = 'stock.move'

    # Receipt moves: from the purchase order line (see purchase_order.py).
    sourcing_type = fields.Selection(
        LOT_SOURCING_TYPES, string="Sourcing", index=True,
        help="Official Partner / Outside Supplier of the purchase order line "
             "this receipt move comes from.")

    def _stamp_lot_sourcing_type(self):
        """Replaces the alfiafy_purchase rule: when a vendor receipt is
        validated, the lots received keep their sourcing, purchase order,
        vendor and unit purchase cost. A lot already received from another
        purchase order keeps its first origin."""
        for move in self:
            if move.state != 'done' or not move.purchase_line_id or move.location_id.usage != 'supplier':
                continue
            lots = move.move_line_ids.lot_id.filtered(lambda lot: not lot.origin_po_id)
            if lots:
                move._alf_stamp_lots(lots)

    def _alf_stamp_lots(self, lots, keep_sourcing=False):
        self.ensure_one()
        po_line = self.purchase_line_id
        order = po_line.order_id
        vals = {
            'origin_po_id': order.id,
            'origin_vendor_id': order.partner_id.commercial_partner_id.id,
            'origin_unit_cost': po_line._get_stock_move_price_unit(at_date=self.date),
        }
        sourcing = self.sourcing_type or po_line.sourcing_type or order.sourcing_type
        if sourcing and not keep_sourcing:
            vals['sourcing_type'] = sourcing
        lots.sudo().write(vals)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # Deliveries (sales and POS): the sourcing of the lot reserved / delivered.
    sourcing_type = fields.Selection(
        related='lot_id.sourcing_type', string="Lot Sourcing", store=True, index=True)
