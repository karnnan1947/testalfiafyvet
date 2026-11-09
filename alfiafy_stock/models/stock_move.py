# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.exceptions import AccessError, UserError


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _is_branch_to_branch(self):
        """Internal transfer from one branch to another branch.

        A branch is a warehouse other than the main warehouse of the company
        (the first warehouse, by sequence).
        """
        self.ensure_one()
        picking_type = self.picking_type_id or self.picking_id.picking_type_id
        if picking_type.code != 'internal':
            return False
        source_wh = self.location_id.warehouse_id
        dest_wh = self.location_dest_id.warehouse_id
        if not source_wh or not dest_wh or source_wh == dest_wh:
            return False
        main_wh = self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', source_wh.company_id.id)], limit=1)
        return main_wh not in (source_wh, dest_wh)

    def _check_branch_transfer_limit(self):
        """Block a branch-to-branch transfer above the product's Max Branch
        Transfer Qty, unless the user is a Stock Manager (management)."""
        if self.env.user.has_group('stock.group_stock_manager'):
            return
        for move in self:
            product = move.product_id
            limit = product.max_transfer_qty
            if not limit or move.is_scrap or move.state == 'cancel' or not move._is_branch_to_branch():
                continue
            qty = max(move.product_uom_qty, move.quantity)
            if move.uom_id and move.uom_id != product.uom_id:
                qty = move.uom_id._compute_quantity(qty, product.uom_id)
            if product.uom_id.compare(qty, limit) > 0:
                raise UserError(self.env._(
                    "Branch-to-branch transfer limit exceeded for %(product)s: %(qty)s %(uom)s requested, "
                    "maximum %(limit)s %(uom)s per transfer (%(src)s to %(dst)s). "
                    "Only a Stock Manager can authorise a larger transfer.",
                    product=product.display_name, qty=qty, limit=limit, uom=product.uom_id.name,
                    src=move.location_id.warehouse_id.name, dst=move.location_dest_id.warehouse_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        moves._check_branch_transfer_limit()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if {'product_uom_qty', 'quantity', 'location_id', 'location_dest_id', 'product_id'} & set(vals):
            self._check_branch_transfer_limit()
        return res

    def _action_done(self, cancel_backorder=False):
        self._check_branch_transfer_limit()
        return super()._action_done(cancel_backorder=cancel_backorder)

    def action_scrap(self):
        """Stock disposal: only the Stock Manager can validate a scrap."""
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(self.env._("Only a Stock Manager can scrap (write off) stock."))
        return super().action_scrap()
