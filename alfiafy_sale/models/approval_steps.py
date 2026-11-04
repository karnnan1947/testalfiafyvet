# -*- coding: utf-8 -*-
from odoo import fields, models


class ApprovalSteps(models.Model):
    _inherit = 'approval.steps'

    # BRD 1.2 customization #1: "no discount shall be given without management
    # approval". A Sale step with this criterion matches every quotation that
    # has a discount on at least one line, whatever its amount or margin.
    sale_criteria_type = fields.Selection(
        selection_add=[('discount', 'Any Discount')],
        ondelete={'discount': 'set default'})

    def _matches_sale_order(self, order):
        self.ensure_one()
        if self.type == 'sale' and self.sale_criteria_type == 'discount':
            return order._alfiafy_has_discount()
        return super()._matches_sale_order(order)

    def _condition_display(self):
        self.ensure_one()
        if self.type == 'sale' and self.sale_criteria_type == 'discount':
            return self.env._("Any line discount > 0%")
        return super()._condition_display()
