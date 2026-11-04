# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "restricted.cost.mixin"]

    _restricted_cost_fields = ("margin", "margin_percent")

    cost_visible = fields.Boolean(
        "Cost Visible",
        compute="_compute_cost_visible",
    )

    @api.depends_context("uid")
    def _compute_cost_visible(self):
        visible = not self._is_cost_restricted()
        for rec in self:
            rec.cost_visible = visible


class SaleOrderLine(models.Model):
    _name = "sale.order.line"
    _inherit = ["sale.order.line", "restricted.cost.mixin"]

    _restricted_cost_fields = ("purchase_price", "margin", "margin_percent")


class SaleReport(models.Model):
    _name = "sale.report"
    _inherit = ["sale.report", "restricted.cost.mixin"]

    # Odoo 20 also exposes the expected cost in the "Projected Margins" report.
    _restricted_cost_fields = ("margin", "margin_percent", "purchase_price")
