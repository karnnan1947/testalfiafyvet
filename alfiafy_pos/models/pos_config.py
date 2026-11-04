# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    max_cashier_discount = fields.Float(
        string="Cashier Discount Limit (%)", default=5.0, digits=(16, 2),
        help="Highest line discount (%) a cashier may give without approval.")
    require_manager_discount_pin = fields.Boolean(
        string="Manager PIN Above Limit", default=True,
        help="A discount above the cashier limit needs the PIN of an employee with "
             "manager access on this register (Employees with manager level access). "
             "The keypad Price key is then also reserved to managers, so discounts "
             "can only be given as a percentage.")
    enforce_pos_phone = fields.Boolean(
        string="Customer Phone Required", default=True,
        help="An order can only be validated for a customer with a phone number.")
    block_out_of_stock_pos = fields.Boolean(
        string="Block Out-of-Stock Sales", default=True,
        help="A storable product cannot be sold beyond the free quantity of the "
             "branch stock location (no negative stock).")

    _max_cashier_discount_range = models.Constraint(
        'CHECK(max_cashier_discount >= 0 AND max_cashier_discount <= 100)',
        "The cashier discount limit must be between 0 and 100%.",
    )

    # ------------------------------------------------------------------
    # Branch stock
    # ------------------------------------------------------------------
    def _alfiafy_stock_location(self):
        self.ensure_one()
        return self.picking_type_id.default_location_src_id

    def _alfiafy_pending_pos_qty(self, products, locations):
        """Quantities already sold by paid POS orders of these locations whose
        delivery has not been created yet (stock updated at session closing).
        Expressed in the product's unit."""
        pending = defaultdict(float)
        if not products:
            return pending
        lines = self.env['pos.order.line'].sudo().search([
            ('product_id', 'in', products.ids),
            ('order_id.state', 'in', ('paid', 'done')),
            ('order_id.picking_ids', '=', False),
            ('order_id.session_id.state', '!=', 'closed'),
            ('order_id.config_id.picking_type_id.default_location_src_id', 'in', locations.ids),
        ])
        for line in lines:
            uom = line.product_uom_id or line.product_id.uom_id
            pending[line.product_id.id] += uom._compute_quantity(
                line.qty, line.product_id.uom_id, round=False)
        return pending

    def alfiafy_get_free_qty(self, product_ids):
        """Free quantity (on hand - reserved - sold and not yet delivered) of
        each storable product in the branch stock location of this register,
        in the product's unit. Called by the POS when a product is added and
        before payment. Non-storable products are not returned."""
        self.ensure_one()
        location = self._alfiafy_stock_location()
        if not location:
            return {}
        products = self.env['product.product'].sudo().browse(product_ids).exists().filtered('is_storable')
        if not products:
            return {}
        locations = self.env['stock.location'].sudo().search([('id', 'child_of', location.id)])
        pending = self._alfiafy_pending_pos_qty(products, locations)
        products = products.with_context(location=location.id)
        return {
            product.id: product.free_qty - pending.get(product.id, 0.0)
            for product in products
        }
