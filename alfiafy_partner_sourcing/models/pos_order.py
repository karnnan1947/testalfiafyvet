# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .selections import LINE_SOURCING_TYPES, sourcing_of


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # Taken from the lot(s) of the line when the order is saved (before the
    # invoice and the delivery are made), so the invoice can carry it.
    sourcing_type = fields.Selection(
        LINE_SOURCING_TYPES, string="Sourcing", compute='_compute_sourcing_type',
        store=True, index=True,
        help="Official Partner / Outside Supplier of the lot sold.")
    sourcing_unit_cost = fields.Float(
        string="Sourcing Unit Cost", digits='Product Price',
        compute='_compute_sourcing_type', store=True,
        help="Purchase cost of one product unit of the lot(s) sold (company currency).")

    @api.depends('pack_lot_ids.lot_name', 'product_id')
    def _compute_sourcing_type(self):
        for line in self:
            lots = line._alf_lots()
            line.sourcing_type = sourcing_of(lots.mapped('sourcing_type'))
            costs = [lot._alf_unit_cost() for lot in lots]
            line.sourcing_unit_cost = sum(costs) / len(costs) if costs else 0.0

    def _alf_lots(self):
        self.ensure_one()
        names = [name for name in self.pack_lot_ids.mapped('lot_name') if name]
        if not names or not self.product_id:
            return self.env['stock.lot']
        company = self.order_id.company_id or self.env.company
        return self.env['stock.lot'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('name', 'in', names),
            ('company_id', 'in', [False, company.id]),
        ])

    def _alf_set_sourcing(self):
        """Recompute (e.g. for lines saved before the module was installed)."""
        self._compute_sourcing_type()

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['sourcing_type']


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _prepare_account_move_line_data_from_base_line(self, base_lines):
        """POS invoice: each invoice line gets the sourcing of its POS line."""
        entries = super()._prepare_account_move_line_data_from_base_line(base_lines)
        for entry in entries:
            line = entry.get('metadata', {}).get('line')
            vals = entry.get('account.move.line', {})
            if (line and line._name == 'pos.order.line' and vals.get('display_type') == 'product'
                    and line.sourcing_type in ('partner', 'outside')):
                vals['sourcing_type'] = line.sourcing_type
                vals['sourcing_unit_cost'] = line.sourcing_unit_cost
        return entries
