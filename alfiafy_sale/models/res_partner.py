# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    block_on_overdue = fields.Boolean(
        string="Block on Overdue Invoices", default=True,
        help="Sales orders of this customer cannot be confirmed (and Customer "
             "Account payments are refused in the POS) while they have an unpaid "
             "invoice past its due date.")

    def _commercial_fields(self):
        return super()._commercial_fields() + ['block_on_overdue']

    def _alfiafy_overdue_invoices(self, company):
        """Posted customer invoices of the commercial partner, unpaid and past
        their due date, in ``company``."""
        self.ensure_one()
        return self.env['account.move'].sudo().search([
            ('commercial_partner_id', '=', self.commercial_partner_id.id),
            ('company_id', '=', company.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_date_due', '<', fields.Date.context_today(self)),
        ], order='invoice_date_due')
