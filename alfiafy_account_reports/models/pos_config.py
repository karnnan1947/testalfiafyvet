# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    analytic_account_id = fields.Many2one(
        'account.analytic.account', string="Branch Analytic Account",
        check_company=True,
        help="The sales revenue lines of the session closing entry are tagged "
             "with this analytic account (branch P&L).")
