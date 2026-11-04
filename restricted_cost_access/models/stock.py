# -*- coding: utf-8 -*-
from odoo import models


class StockLot(models.Model):
    _name = "stock.lot"
    _inherit = ["stock.lot", "restricted.cost.mixin"]

    _restricted_cost_fields = ("standard_price", "avg_cost", "total_value")


class StockMove(models.Model):
    _name = "stock.move"
    _inherit = ["stock.move", "restricted.cost.mixin"]

    _restricted_cost_fields = ("value", "remaining_value", "standard_price", "price_unit")


class StockQuant(models.Model):
    _name = "stock.quant"
    _inherit = ["stock.quant", "restricted.cost.mixin"]

    _restricted_cost_fields = ("value",)
