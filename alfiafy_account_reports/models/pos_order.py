# -*- coding: utf-8 -*-
from odoo import models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _prepare_account_move_line_data(self, aggregate=True):
        res = super()._prepare_account_move_line_data(aggregate=aggregate)
        # set by pos.session._create_session_account_move (session closing only)
        distribution = self.env.context.get('alfiafy_branch_analytic_distribution')
        if distribution:
            for line_data in res:
                vals = line_data['account.move.line']
                if vals.get('display_type') == 'product':  # sales revenue lines
                    vals['analytic_distribution'] = {
                        **(vals.get('analytic_distribution') or {}),
                        **distribution,
                    }
        return res
