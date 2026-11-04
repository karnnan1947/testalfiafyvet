# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    zkteco_default_policy_id = fields.Many2one(
        related='company_id.zkteco_default_policy_id', readonly=False,
        string="Default Attendance Policy")
    zkteco_device_offline_minutes = fields.Integer(
        related='company_id.zkteco_device_offline_minutes', readonly=False,
        string="Device Offline After (min)")
