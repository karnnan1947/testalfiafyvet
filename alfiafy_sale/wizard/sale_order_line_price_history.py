# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import float_compare

COMPARISONS = [
    ('higher', 'Current is Higher'),
    ('lower', 'Current is Lower'),
    ('same', 'Same Price'),
]


class SaleOrderLinePriceHistory(models.TransientModel):
    _name = 'sale.order.line.price.history'
    _description = "Customer Price History"

    order_line_id = fields.Many2one('sale.order.line', string="Quotation Line", required=True, ondelete='cascade')
    order_id = fields.Many2one(related='order_line_id.order_id', string="Quotation")
    partner_id = fields.Many2one(related='order_line_id.order_id.partner_id', string="Customer")
    product_id = fields.Many2one(related='order_line_id.product_id', string="Product")
    uom_id = fields.Many2one(related='order_line_id.product_uom_id', string="Unit")
    currency_id = fields.Many2one(related='order_line_id.currency_id', string="Currency")
    current_price_unit = fields.Float(related='order_line_id.price_unit', string="Current Unit Price")
    current_discount = fields.Float(related='order_line_id.discount', string="Current Discount (%)")
    current_net_price = fields.Monetary(
        string="Current Net Price", compute='_compute_current_net_price', currency_field='currency_id')
    line_ids = fields.One2many('sale.order.line.price.history.line', 'wizard_id', string="Last Sales")

    @api.depends('current_price_unit', 'current_discount')
    def _compute_current_net_price(self):
        for wizard in self:
            wizard.current_net_price = wizard.current_price_unit * (1.0 - (wizard.current_discount or 0.0) / 100.0)

    def _populate_history(self):
        """Last 5 confirmed sales of the product to the customer, each tagged
        against the current net price (both in the unit/currency of the line)."""
        for wizard in self:
            line = wizard.order_line_id
            currency = line.currency_id
            current = wizard.current_net_price
            vals_list = []
            for past in line._alfiafy_previous_sales(limit=5):
                net = past.price_unit * (1.0 - (past.discount or 0.0) / 100.0)
                comparable = line._alfiafy_net_price_for_line(past)
                cmp = float_compare(current, comparable, precision_rounding=currency.rounding or 0.01)
                vals_list.append({
                    'wizard_id': wizard.id,
                    'sale_line_id': past.id,
                    'order_ref': past.order_id.name,
                    'order_date': past.order_id.date_order,
                    'salesperson_id': past.order_id.user_id.id,
                    'product_uom_qty': past.product_uom_qty,
                    'uom_id': past.product_uom_id.id,
                    'currency_id': past.currency_id.id,
                    'price_unit': past.price_unit,
                    'discount': past.discount,
                    'net_price': net,
                    'comparison': 'higher' if cmp > 0 else 'lower' if cmp < 0 else 'same',
                })
            self.env['sale.order.line.price.history.line'].create(vals_list)


class SaleOrderLinePriceHistoryLine(models.TransientModel):
    _name = 'sale.order.line.price.history.line'
    _description = "Customer Price History Line"
    _order = 'order_date desc, id desc'

    wizard_id = fields.Many2one('sale.order.line.price.history', required=True, ondelete='cascade')
    sale_line_id = fields.Many2one('sale.order.line', string="Sale Line")
    # Char, not a Many2one: a salesperson may not have access to the orders of
    # colleagues, which would break the popup.
    order_ref = fields.Char(string="Order Ref")
    order_date = fields.Datetime(string="Order Date")
    salesperson_id = fields.Many2one('res.users', string="Salesperson")
    product_uom_qty = fields.Float(string="Qty Sold", digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string="Unit")
    currency_id = fields.Many2one('res.currency', string="Currency")
    price_unit = fields.Monetary(string="Unit Price", currency_field='currency_id')
    discount = fields.Float(string="Discount (%)", digits='Discount')
    net_price = fields.Monetary(string="Net Price", currency_field='currency_id')
    comparison = fields.Selection(COMPARISONS, string="Current vs This Sale")
