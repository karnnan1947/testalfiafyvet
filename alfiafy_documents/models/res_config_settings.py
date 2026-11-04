# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    compliance_manager_ids = fields.Many2many(
        related='company_id.compliance_manager_ids', readonly=False,
        string="Compliance Alert Recipients",
        help="Users who receive the license expiry activities and e-mails.")
