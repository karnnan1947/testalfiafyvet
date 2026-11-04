# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import api, fields, models
from odoo.tools import float_is_zero, float_round

from .stock_picking import PRODUCT_QTY_CONTEXT


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # Core makes this a plain related to the product's unit. Here it is the
    # unit the line was sold in, chosen in the POS (defaults to the product's).
    # It must stay a plain stored field: the POS does not send computed or
    # related fields when it syncs an order.
    product_uom_id = fields.Many2one('uom.uom', string='Product UoM', related=False)
    unit_cost = fields.Float(string='Unit cost', compute='_compute_unit_cost', digits='Product Price')

    @api.model_create_multi
    def create(self, vals_list):
        products = self.env['product.product'].browse(
            [vals['product_id'] for vals in vals_list if vals.get('product_id')])
        uom_by_product = {product.id: product.uom_id for product in products}
        for vals in vals_list:
            product_uom = uom_by_product.get(vals.get('product_id'))
            if not product_uom:
                continue
            uom = self.env['uom.uom'].browse(vals.get('product_uom_id'))
            if not uom or not uom._has_common_reference(product_uom):
                vals['product_uom_id'] = product_uom.id
        return super().create(vals_list)

    @api.model
    def _load_pos_data_fields(self, config):
        params = super()._load_pos_data_fields(config)
        params += ['product_uom_id']
        return params

    def _compute_total_cost(self, at_closing=False):
        """Express the line cost in the UoM the product was actually sold in.

        Core computes ``total_cost = qty * (cost per the product's unit)``, while
        ``qty`` is here in the *sold* unit (e.g. Box of 10). ``super()`` is called
        first so that core's FIFO/AVCO costing, currency conversion and refund
        handling still apply; the result is then rescaled into the sold unit.
        """
        lines_to_convert = self.filtered(lambda l: not l.is_total_cost_computed)
        super()._compute_total_cost(at_closing)
        for line in lines_to_convert:
            sale_uom = line.product_uom_id
            default_uom = line.product_id.uom_id
            if (line.qty and sale_uom and default_uom
                    and sale_uom != default_uom
                    and sale_uom._has_common_reference(default_uom)):
                cost_per_sale_uom = default_uom._compute_price(line.total_cost / line.qty, sale_uom)
                line.total_cost = line.qty * cost_per_sale_uom

    # ------------------------------------------------------------------
    # Refunds: a line sold per pack may be refunded per piece
    # ------------------------------------------------------------------
    def _line_uom(self):
        self.ensure_one()
        return self.product_uom_id or self.product_id.uom_id

    @api.depends('refund_orderline_ids', 'refund_orderline_ids.order_id.state',
                 'refund_orderline_ids.qty', 'refund_orderline_ids.product_uom_id')
    def _compute_refund_qty(self):
        """Refunded quantity in the unit of this line: 1 piece refunded on a
        line sold per Pack of 6 is 1/6 of a pack (not 1 pack)."""
        for line in self:
            uom = line._line_uom()
            refunded = 0.0
            for refund in line.refund_orderline_ids.filtered(lambda r: r.order_id.state != 'cancel'):
                refund_uom = refund._line_uom()
                qty = refund.qty
                if refund_uom != uom and refund_uom._has_common_reference(uom):
                    qty = refund_uom._compute_quantity(qty, uom, round=False)
                refunded -= qty
            line.refunded_qty = refunded

    def _prepare_refund_data(self, refund_order):
        """Back-office refund of what is left: when single pieces of a pack
        were already returned, the rest is refunded per piece too, at the price
        paid per piece."""
        data = super()._prepare_refund_data(refund_order)
        uom = self._line_uom()
        product_uom = self.product_id.uom_id
        remaining = self.qty - self.refunded_qty
        if uom != product_uom and not float_is_zero(remaining - round(remaining), precision_digits=4):
            precision = self.env['decimal.precision'].precision_get('Product Unit')
            data.update({
                'product_uom_id': product_uom.id,
                'qty': -float_round(uom._compute_quantity(remaining, product_uom, round=False),
                                    precision_digits=precision),
                'price_unit': uom._compute_price(self.price_unit, product_uom),
            })
        return data

    # ------------------------------------------------------------------
    # Stock: quantities in the product's unit (see stock_picking.py)
    # ------------------------------------------------------------------
    def _to_product_uom_qty(self, qty):
        self.ensure_one()
        uom = self.product_uom_id
        product_uom = self.product_id.uom_id
        if not uom or not product_uom or uom == product_uom:
            return qty
        return uom._compute_quantity(qty, product_uom, round=False)

    def _get_qty_to_move(self):
        qty = super()._get_qty_to_move()
        if self.env.context.get(PRODUCT_QTY_CONTEXT):
            return self._to_product_uom_qty(qty)
        return qty

    def _launch_stock_rule_from_pos_order_lines(self):
        # "Ship later" orders: the procurement is made in the product's unit.
        return super(PosOrderLine, self.with_context(**{PRODUCT_QTY_CONTEXT: True}))._launch_stock_rule_from_pos_order_lines()

    @api.depends('total_cost', 'qty')
    def _compute_unit_cost(self):
        for line in self:
            line.unit_cost = line.total_cost / line.qty if line.qty else line.total_cost
