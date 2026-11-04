# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    max_pos_qty = fields.Float(
        string="Max POS Quantity per Order", digits='Product Unit', default=0.0,
        help="Retail ceiling: the largest quantity of this product (in its own unit "
             "of measure) that one POS order may contain. Larger quantities are "
             "wholesale and must be sold through the Sales module. 0 = no limit.")

    _max_pos_qty_positive = models.Constraint(
        'CHECK(max_pos_qty >= 0)',
        "The maximum POS quantity cannot be negative.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['max_pos_qty']
