# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    # Field from alfiafy_purchase, made required: lots received from a
    # purchase order are stamped with its sourcing; lots created another way
    # (opening stock, inventory adjustment) are Outside unless set by hand.
    sourcing_type = fields.Selection(required=True, default='outside', readonly=False)
    origin_po_id = fields.Many2one(
        'purchase.order', string="Origin Purchase Order", readonly=True, copy=False,
        index='btree_not_null',
        help="Purchase order the lot was first received from.")
    origin_vendor_id = fields.Many2one(
        'res.partner', string="Origin Vendor", readonly=True, copy=False,
        index='btree_not_null')
    origin_currency_id = fields.Many2one(
        'res.currency', string="Cost Currency", compute='_compute_origin_currency_id')
    origin_unit_cost = fields.Monetary(
        string="Origin Unit Cost", currency_field='origin_currency_id', readonly=True,
        copy=False,
        help="Purchase price of one unit of the product (in its own unit of "
             "measure and the company currency, without taxes) on the purchase "
             "order the lot was received from.")

    @api.depends('company_id')
    def _compute_origin_currency_id(self):
        for lot in self:
            lot.origin_currency_id = (lot.company_id or self.env.company).currency_id

    def _alf_unit_cost(self):
        """Cost of one product unit of the lot (company currency): its purchase
        cost, or the product cost when the lot did not come from a purchase."""
        self.ensure_one()
        if self.origin_unit_cost:
            return self.origin_unit_cost
        company = self.company_id or self.env.company
        return self.product_id.with_company(company).sudo().standard_price

    def _alf_backfill_origin(self):
        """Origin of lots received before this module was installed."""
        MoveLine = self.env['stock.move.line'].sudo()
        for lot in self.filtered(lambda lot: not lot.origin_po_id):
            first = MoveLine.search([
                ('lot_id', '=', lot.id),
                ('state', '=', 'done'),
                ('move_id.purchase_line_id', '!=', False),
                ('location_id.usage', '=', 'supplier'),
            ], order='date, id', limit=1)
            if first:
                first.move_id._alf_stamp_lots(lot, keep_sourcing=True)

    @api.model
    def alf_pos_lot_sourcing(self, product_id, lot_names):
        """POS: sourcing of the lots chosen for a product, {lot name: sourcing}."""
        lots = self.sudo().search([
            ('product_id', '=', product_id),
            ('name', 'in', list(lot_names or [])),
            ('company_id', 'in', [False, self.env.company.id]),
        ])
        return {lot.name: lot.sourcing_type for lot in lots}
