# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # storage of the compliance alert recipients set in Documents settings
    compliance_manager_ids = fields.Many2many(
        'res.users', 'alfiafy_company_compliance_manager_rel', 'company_id', 'user_id',
        string="Compliance Alert Recipients",
        domain=[('share', '=', False)])
