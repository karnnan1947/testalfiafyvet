# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import api, models

# While the delivery of POS lines is prepared, quantities are converted from
# the unit the line was sold in to the product's unit: the POS stock code
# (pos_stock) builds moves, move lines and lot assignments in the product's
# unit everywhere. 1 "Box of 10" sold therefore moves 10 Units.
PRODUCT_QTY_CONTEXT = 'pos_multi_uom_product_qty'


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _create_picking_from_pos_order_lines(self, location_dest_id, lines, picking_type, partner=False):
        lines = lines.with_context(**{PRODUCT_QTY_CONTEXT: True})
        return super(StockPicking, self.with_context(**{PRODUCT_QTY_CONTEXT: True}))._create_picking_from_pos_order_lines(
            location_dest_id, lines, picking_type, partner=partner)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_lot_line_qty(self, line, move, lines_data):
        qty = super()._get_lot_line_qty(line, move, lines_data)
        if line.product_id.tracking == 'serial':
            return qty
        return line._to_product_uom_qty(qty)
