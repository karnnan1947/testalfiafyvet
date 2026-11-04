# -*- coding: utf-8 -*-
from odoo import api, fields, models

HISTORY_LIMIT = 10


class PurchasePriceHistoryWizard(models.TransientModel):
    """Popup listing the last confirmed purchases of a product across ALL
    vendors (BRD 1.4 #2: vendor, date, unit price)."""
    _name = 'purchase.price.history.wizard'
    _description = 'Purchase Price History'

    product_id = fields.Many2one('product.product', string="Product", required=True, readonly=True)
    order_line_id = fields.Many2one('purchase.order.line', string="Order Line", readonly=True)
    currency_id = fields.Many2one(related='order_line_id.currency_id')
    current_price = fields.Float(related='order_line_id.price_unit', string="Current Unit Price")
    last_purchase_price = fields.Monetary(
        related='order_line_id.last_purchase_price', string="Last Price (this vendor)",
        currency_field='currency_id')
    price_trend = fields.Selection(related='order_line_id.price_trend')
    history_line_ids = fields.Many2many(
        'purchase.order.line', string="Last Purchases", compute='_compute_history_line_ids')

    @api.depends('product_id')
    def _compute_history_line_ids(self):
        PurchaseLine = self.env['purchase.order.line']
        for wizard in self:
            if not wizard.product_id:
                wizard.history_line_ids = PurchaseLine
                continue
            wizard.history_line_ids = PurchaseLine._latest_purchase_lines([
                ('product_id', '=', wizard.product_id.id),
                ('state', '=', 'purchase'),
                ('display_type', '=', False),
            ], limit=HISTORY_LIMIT)
