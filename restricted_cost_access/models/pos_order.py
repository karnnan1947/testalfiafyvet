# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosOrder(models.Model):
    _name = "pos.order"
    _inherit = ["pos.order", "restricted.cost.mixin"]

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


class PosOrderLine(models.Model):
    _name = "pos.order.line"
    _inherit = ["pos.order.line", "restricted.cost.mixin"]

    _restricted_cost_fields = ("margin", "margin_percent", "total_cost")


class PosOrderReport(models.Model):
    _name = "report.pos.order"
    _inherit = ["report.pos.order", "restricted.cost.mixin"]

    _restricted_cost_fields = ("margin",)
