# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _create_session_account_move(self, orders):
        """Session closing entry (Odoo 20 replacement of _create_account_move):
        tag its sales revenue lines with the branch analytic account of the
        register. The lines are built by pos.order._prepare_account_move_line_data."""
        analytic_account = self.config_id.analytic_account_id
        if analytic_account and orders:
            distribution = {str(analytic_account.id): 100.0}
            self = self.with_context(alfiafy_branch_analytic_distribution=distribution)
            orders = orders.with_context(alfiafy_branch_analytic_distribution=distribution)
        return super()._create_session_account_move(orders)
