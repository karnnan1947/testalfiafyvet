# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import float_compare

from .selections import PRICE_TRENDS


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    last_purchase_price = fields.Monetary(
        string="Last Price", compute='_compute_last_purchase', currency_field='currency_id',
        help="Unit price of the most recent confirmed purchase of this product "
             "from this vendor, converted to this order's currency and unit.")
    last_purchase_date = fields.Datetime(
        string="Last Purchase Date", compute='_compute_last_purchase')
    price_trend = fields.Selection(
        PRICE_TRENDS, string="Trend", compute='_compute_price_trend',
        help="Current unit price compared with the last purchase price from this vendor.")
    # Shown in the price history popup.
    order_sourcing_type = fields.Selection(related='order_id.sourcing_type', string="Sourcing")
    order_purchase_type = fields.Selection(related='order_id.purchase_type', string="Purchase Type")

    def _get_last_purchase_line(self):
        """Most recent confirmed purchase line for the same product and vendor
        (commercial entity), excluding this order."""
        self.ensure_one()
        vendor = self.order_id.partner_id.commercial_partner_id
        if not self.product_id or not vendor:
            return self.browse()
        domain = [
            ('product_id', '=', self.product_id.id),
            ('partner_id', 'child_of', vendor.id),
            ('state', '=', 'purchase'),
            ('display_type', '=', False),
        ]
        if self.order_id._origin:
            domain.append(('order_id', '!=', self.order_id._origin.id))
        return self._latest_purchase_lines(domain, limit=1)

    @api.model
    def _latest_purchase_lines(self, domain, limit):
        """Purchase lines matching ``domain``, most recently confirmed first.
        The ORM cannot order lines by their order's confirmation date, so the
        latest orders are fetched first and their lines sorted afterwards."""
        orders = self.env['purchase.order'].search(
            [('order_line', 'any', domain)], order='date_approve desc, id desc', limit=limit)
        lines = self.search(domain + [('order_id', 'in', orders.ids)])
        return lines.sorted(
            lambda l: (l.order_id.date_approve or l.order_id.date_order, l.id), reverse=True)[:limit]

    @api.depends('product_id', 'uom_id', 'order_id.partner_id', 'order_id.currency_id')
    def _compute_last_purchase(self):
        for line in self:
            previous = line._get_last_purchase_line() if not line.display_type else line.browse()
            if not previous:
                line.last_purchase_price = 0.0
                line.last_purchase_date = False
                continue
            price = previous.price_unit
            # same unit of measure as the current line
            if previous.uom_id and line.uom_id and previous.uom_id != line.uom_id:
                price = previous.uom_id._compute_price(price, line.uom_id)
            # same currency as the current order
            to_currency = line.order_id.currency_id
            from_currency = previous.order_id.currency_id
            if from_currency and to_currency and from_currency != to_currency:
                price = from_currency._convert(
                    price, to_currency, line.order_id.company_id or line.env.company,
                    line.order_id.date_order or fields.Date.context_today(line))
            line.last_purchase_price = price
            line.last_purchase_date = previous.order_id.date_approve

    @api.depends('price_unit', 'last_purchase_price', 'last_purchase_date')
    def _compute_price_trend(self):
        for line in self:
            if line.display_type or not line.last_purchase_date:
                line.price_trend = False
                continue
            rounding = line.currency_id.rounding or 0.01
            cmp = float_compare(line.price_unit, line.last_purchase_price, precision_rounding=rounding)
            line.price_trend = 'up' if cmp > 0 else 'down' if cmp < 0 else 'same'

    def action_open_price_history(self):
        """[History] button on the order line: last 10 purchases of the
        product across all vendors, without leaving the order."""
        self.ensure_one()
        wizard = self.env['purchase.price.history.wizard'].create({
            'product_id': self.product_id.id,
            'order_line_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _("Purchase Price History - %s", self.product_id.display_name),
            'res_model': 'purchase.price.history.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
