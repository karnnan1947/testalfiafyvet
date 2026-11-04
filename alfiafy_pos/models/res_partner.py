# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import format_date, formatLang


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def alfiafy_pos_credit_check(self, partner_id, amount, config_id):
        """Hold on Customer Account (credit) payments in the POS.

        Refused when the customer has overdue unpaid invoices (unless the
        overdue hold is switched off on the customer, see alfiafy_sale) or when
        ``amount`` would take them over their credit limit. Always computed
        live: POS caches partner records, so loaded values would be stale.

        :param amount: amount charged to the customer account, POS currency
        :return: {'blocked': bool, 'message': str}
        """
        config = self.env['pos.config'].browse(config_id).exists()
        company = config.company_id or self.env.company
        partner = self.browse(partner_id).exists()
        if not partner:
            return {'blocked': False, 'message': ''}
        commercial = partner.commercial_partner_id.sudo().with_company(company)
        currency = company.currency_id
        today = fields.Date.context_today(self)
        reasons = []

        hold_on_overdue = commercial.block_on_overdue if 'block_on_overdue' in commercial._fields else True
        if hold_on_overdue:
            overdue = self.env['account.move'].sudo().search([
                ('commercial_partner_id', '=', commercial.id),
                ('company_id', '=', company.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('invoice_date_due', '<', today),
            ], order='invoice_date_due')
            if overdue:
                reasons.append(self.env._(
                    "%(partner)s has %(count)s overdue invoice(s) for %(amount)s "
                    "(oldest due on %(date)s). Credit sales are blocked until they are paid.",
                    partner=commercial.name, count=len(overdue),
                    amount=formatLang(self.env, sum(overdue.mapped('amount_residual_signed')), currency_obj=currency),
                    date=format_date(self.env, overdue[0].invoice_date_due),
                ))

        if company.account_use_credit_limit and commercial.credit_limit > 0:
            pos_currency = config.currency_id or currency
            amount_company = pos_currency._convert(amount or 0.0, currency, company, today)
            # Customer-account sales of open sessions are not in the
            # receivable balance until the session is posted.
            open_pos_credit = sum(self.env['pos.payment'].sudo().search([
                ('payment_method_id.type', '=', 'pay_later'),
                ('pos_order_id.partner_id', 'child_of', commercial.id),
                ('pos_order_id.state', 'in', ('paid', 'done')),
                ('pos_order_id.account_move', '=', False),
                ('pos_order_id.session_id.state', '!=', 'closed'),
                ('company_id', '=', company.id),
            ]).mapped('amount'))
            exposure = commercial.credit + commercial.credit_to_invoice + open_pos_credit
            if exposure + amount_company > commercial.credit_limit:
                reasons.append(self.env._(
                    "Credit limit of %(limit)s exceeded: balance %(balance)s + this sale "
                    "%(amount)s = %(total)s.",
                    limit=formatLang(self.env, commercial.credit_limit, currency_obj=currency),
                    balance=formatLang(self.env, exposure, currency_obj=currency),
                    amount=formatLang(self.env, amount_company, currency_obj=currency),
                    total=formatLang(self.env, exposure + amount_company, currency_obj=currency),
                ))
        return {'blocked': bool(reasons), 'message': '\n'.join(reasons)}
