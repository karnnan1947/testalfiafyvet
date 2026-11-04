# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # unit_cost comes from pos_multi_uom_price: hide it like the other cost
    # fields of the line (restricted_cost_access).
    _restricted_cost_fields = ("margin", "margin_percent", "total_cost", "unit_cost")

    discount_approved_by_id = fields.Many2one(
        'hr.employee', string="Discount Approved By", readonly=True,
        index='btree_not_null',
        help="Manager who entered their PIN in the POS to allow a discount above "
             "the cashier limit of the register.")

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        # hr.employee is only loaded in the POS when employee login is enabled.
        if config and config.module_pos_hr:
            fields_list.append('discount_approved_by_id')
        return fields_list
