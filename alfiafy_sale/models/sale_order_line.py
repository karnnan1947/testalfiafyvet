# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import formatLang


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    alfiafy_is_storable = fields.Boolean(related='product_id.is_storable', string="Is Storable")
    warehouse_free_qty = fields.Float(
        string="Free Qty", digits='Product Unit', compute='_compute_warehouse_free_qty',
        help="Free quantity (on hand - reserved) of the product in the warehouse of "
             "the order, in the unit of the line.")
    is_out_of_stock = fields.Boolean(
        string="Out of Stock", compute='_compute_warehouse_free_qty')
    last_customer_price = fields.Float(
        string="Last Price", digits='Product Price', compute='_compute_last_customer_price',
        help="Net unit price (after discount) of the last confirmed sale of this product "
             "to this customer, in the unit and currency of this line.")
    last_customer_price_str = fields.Char(
        string="Last Customer Price", compute='_compute_last_customer_price')

    @api.depends('product_id', 'product_uom_id', 'order_id.warehouse_id', 'display_type')
    def _compute_warehouse_free_qty(self):
        for line in self:
            product = line.product_id
            warehouse = line.order_id.warehouse_id
            if line.display_type or not product.is_storable or not warehouse:
                line.warehouse_free_qty = 0.0
                line.is_out_of_stock = False
                continue
            free = product.sudo().with_context(warehouse_id=warehouse.id).free_qty
            uom = line.product_uom_id or product.uom_id
            line.warehouse_free_qty = product.uom_id._compute_quantity(free, uom, round=False)
            line.is_out_of_stock = free <= 0

    # ------------------------------------------------------------------
    # Customer price history
    # ------------------------------------------------------------------
    def _alfiafy_previous_sales(self, limit=5):
        """Lines of the last confirmed sales of this product to this customer
        (any contact of the same company), most recent first. Read as superuser:
        the history is shown whoever the salesperson of the old orders was."""
        self.ensure_one()
        partner = self.order_id.partner_id.commercial_partner_id
        if not self.product_id or not partner:
            return self.browse()
        domain = [
            ('product_id', '=', self.product_id.id),
            ('order_partner_id', 'child_of', partner.id),
            ('state', '=', 'sale'),
            ('display_type', '=', False),
            ('company_id', '=', self.order_id.company_id.id),
        ]
        current = self.order_id._origin.id
        if current:
            domain.append(('order_id', '!=', current))
        Line = self.sudo()
        orders = self.env['sale.order'].sudo().search(
            [('order_line', 'any', domain)], order='date_order desc, id desc', limit=limit)
        lines = Line.search(domain + [('order_id', 'in', orders.ids)])
        return lines.sorted(lambda l: (l.order_id.date_order, l.id), reverse=True)[:limit]

    def _alfiafy_net_price_for_line(self, past_line):
        """Net unit price of ``past_line`` in the unit and currency of self."""
        self.ensure_one()
        net = past_line.price_unit * (1.0 - (past_line.discount or 0.0) / 100.0)
        uom = self.product_uom_id or self.product_id.uom_id
        if past_line.product_uom_id and uom and past_line.product_uom_id != uom:
            net = past_line.product_uom_id._compute_price(net, uom)
        if past_line.currency_id and self.currency_id and past_line.currency_id != self.currency_id:
            net = past_line.currency_id._convert(
                net, self.currency_id, self.order_id.company_id,
                self.order_id.date_order or fields.Date.context_today(self))
        return net

    @api.depends('product_id', 'product_uom_id', 'order_id.partner_id', 'order_id.currency_id')
    def _compute_last_customer_price(self):
        for line in self:
            if line.display_type or not line.product_id or not line.order_id.partner_id:
                line.last_customer_price = 0.0
                line.last_customer_price_str = False
                continue
            previous = line._alfiafy_previous_sales(limit=1)
            if not previous:
                line.last_customer_price = 0.0
                line.last_customer_price_str = self.env._("First Time Sale")
                continue
            price = line._alfiafy_net_price_for_line(previous)
            line.last_customer_price = price
            line.last_customer_price_str = formatLang(
                self.env, price, currency_obj=line.currency_id or line.order_id.currency_id)

    def action_view_price_history(self):
        self.ensure_one()
        wizard = self.env['sale.order.line.price.history'].create({'order_line_id': self.id})
        wizard._populate_history()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Price History - %s", self.product_id.display_name),
            'res_model': 'sale.order.line.price.history',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
