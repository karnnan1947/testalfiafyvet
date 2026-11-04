# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .selections import SOURCING_TYPES


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # Copied from the purchase order the receipt was generated from.
    sourcing_type = fields.Selection(
        SOURCING_TYPES, string="Sourcing", compute='_compute_sourcing_type',
        store=True, index=True)
    # Import shipment information, read from the purchase order.
    purchase_type = fields.Selection(related='purchase_id.purchase_type', string="Purchase Type")
    po_container_no = fields.Char(related='purchase_id.container_no', string="Container No.")
    po_bl_awb_no = fields.Char(related='purchase_id.bl_awb_no', string="B/L / AWB No.")
    po_etd = fields.Date(related='purchase_id.etd', string="ETD")
    po_eta = fields.Date(related='purchase_id.eta', string="ETA")
    po_shipment_status = fields.Selection(related='purchase_id.shipment_status', string="Shipment Status")

    @api.depends('move_ids.purchase_line_id.order_id.sourcing_type')
    def _compute_sourcing_type(self):
        for picking in self:
            orders = picking.move_ids.purchase_line_id.order_id
            picking.sourcing_type = orders[:1].sourcing_type


class StockLot(models.Model):
    _inherit = 'stock.lot'

    sourcing_type = fields.Selection(
        SOURCING_TYPES, string="Sourcing", readonly=True, copy=False, index=True,
        tracking=True,
        help="Stamped when the lot is received from a purchase order: Official "
             "Partner or Outside Supplier.")


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        moves._stamp_lot_sourcing_type()
        return moves

    def _stamp_lot_sourcing_type(self):
        """When a vendor receipt is validated, stamp the purchase order's
        sourcing on the lots that were received. A lot that already carries a
        sourcing keeps it (returns and later receipts do not overwrite it)."""
        for move in self:
            if move.state != 'done' or not move.purchase_line_id or move.location_id.usage != 'supplier':
                continue
            sourcing = move.purchase_line_id.order_id.sourcing_type
            if not sourcing:
                continue
            lots = move.move_line_ids.lot_id.filtered(lambda lot: not lot.sourcing_type)
            if lots:
                lots.sudo().write({'sourcing_type': sourcing})
