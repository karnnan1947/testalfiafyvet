# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_max_cashier_discount = fields.Float(
        related='pos_config_id.max_cashier_discount', readonly=False)
    pos_require_manager_discount_pin = fields.Boolean(
        related='pos_config_id.require_manager_discount_pin', readonly=False)
    pos_enforce_pos_phone = fields.Boolean(
        related='pos_config_id.enforce_pos_phone', readonly=False)
    pos_block_out_of_stock_pos = fields.Boolean(
        related='pos_config_id.block_out_of_stock_pos', readonly=False)
