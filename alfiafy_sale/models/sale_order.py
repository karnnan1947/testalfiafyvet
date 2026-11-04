# -*- coding: utf-8 -*-
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, format_date, formatLang


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    alfiafy_company_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', string="Company Currency")
    has_overdue_invoices = fields.Boolean(
        string="Has Overdue Invoices", compute='_compute_credit_hold')
    overdue_invoice_count = fields.Integer(
        string="Overdue Invoices", compute='_compute_credit_hold')
    overdue_amount_total = fields.Monetary(
        string="Overdue Amount", compute='_compute_credit_hold',
        currency_field='alfiafy_company_currency_id')
    credit_warning_banner = fields.Html(
        string="Credit Warning", compute='_compute_credit_hold', sanitize=False)

    # ------------------------------------------------------------------
    # Credit limit / overdue invoices
    # ------------------------------------------------------------------
    def _alfiafy_credit_exposure(self):
        """(limit, balance, this order) in company currency, or None when no
        credit limit applies. The balance is the receivable plus confirmed
        orders not invoiced yet, as in Odoo's credit limit warning."""
        self.ensure_one()
        company = self.company_id
        partner = self.partner_id.commercial_partner_id.sudo().with_company(company)
        if not company.account_use_credit_limit or partner.credit_limit <= 0:
            return None
        balance = partner.credit + partner.credit_to_invoice
        amount = 0.0
        if self.state in ('draft', 'sent', 'to_approve'):
            amount = self.currency_id._convert(
                self.amount_total, company.currency_id, company,
                self.date_order or fields.Date.context_today(self))
        return partner.credit_limit, balance, amount

    def _alfiafy_credit_hold_messages(self):
        """Reasons why this quotation cannot be confirmed (credit limit
        exceeded, overdue invoices). Empty when it can be."""
        self.ensure_one()
        messages = []
        if not self.partner_id:
            return messages
        partner = self.partner_id.commercial_partner_id
        currency = self.company_id.currency_id
        exposure = self._alfiafy_credit_exposure()
        if exposure:
            limit, balance, amount = exposure
            if float_compare(balance + amount, limit, precision_rounding=currency.rounding) > 0:
                messages.append(self.env._(
                    "Credit limit exceeded: %(partner)s has a credit limit of %(limit)s; "
                    "balance %(balance)s + this order %(amount)s = %(total)s.",
                    partner=partner.name,
                    limit=formatLang(self.env, limit, currency_obj=currency),
                    balance=formatLang(self.env, balance, currency_obj=currency),
                    amount=formatLang(self.env, amount, currency_obj=currency),
                    total=formatLang(self.env, balance + amount, currency_obj=currency),
                ))
        if partner.block_on_overdue:
            overdue = partner._alfiafy_overdue_invoices(self.company_id)
            if overdue:
                messages.append(self.env._(
                    "Overdue invoices: %(partner)s has %(count)s unpaid invoice(s) past their "
                    "due date for %(amount)s (oldest due on %(date)s: %(invoice)s). "
                    "New orders are blocked until they are fully paid.",
                    partner=partner.name, count=len(overdue),
                    amount=formatLang(self.env, sum(overdue.mapped('amount_residual_signed')), currency_obj=currency),
                    date=format_date(self.env, overdue[0].invoice_date_due),
                    invoice=overdue[0].name,
                ))
        return messages

    @api.depends('partner_id', 'company_id', 'amount_total', 'currency_id', 'state')
    def _compute_credit_hold(self):
        for order in self:
            partner = order.partner_id.commercial_partner_id
            overdue = partner._alfiafy_overdue_invoices(order.company_id) if partner else self.env['account.move']
            order.has_overdue_invoices = bool(overdue)
            order.overdue_invoice_count = len(overdue)
            order.overdue_amount_total = sum(overdue.mapped('amount_residual_signed'))
            messages = []
            if order.state in ('draft', 'sent', 'to_approve'):
                messages = order._alfiafy_credit_hold_messages()
            order.credit_warning_banner = Markup('<br/>').join(
                Markup('<i class="fa fa-ban me-1"/>%s') % escape(message) for message in messages
            ) if messages else False

    def _alfiafy_check_credit_hold(self):
        for order in self:
            messages = order._alfiafy_credit_hold_messages()
            if messages:
                raise UserError(self.env._(
                    "%(order)s cannot be confirmed:\n\n%(reasons)s",
                    order=order.display_name, reasons='\n\n'.join(messages)))

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------
    def _alfiafy_stock_shortages(self):
        """[(product, ordered qty, free qty)] for storable products whose
        ordered quantity (all lines together, product unit) is not free in
        the order's warehouse."""
        self.ensure_one()
        needed = defaultdict(float)
        for line in self.order_line:
            if line.display_type or not line.product_id.is_storable or line.product_uom_qty <= 0:
                continue
            needed[line.product_id] += line.product_uom_id._compute_quantity(
                line.product_uom_qty, line.product_id.uom_id, round=False)
        digits = self.env['decimal.precision'].precision_get('Product Unit')
        shortages = []
        for product, qty in needed.items():
            free = product.sudo().with_context(warehouse_id=self.warehouse_id.id).free_qty
            if free <= 0 or float_compare(qty, free, precision_digits=digits) > 0:
                shortages.append((product, qty, free))
        return shortages

    def _alfiafy_check_stock(self):
        for order in self:
            shortages = order._alfiafy_stock_shortages()
            if shortages:
                details = '\n'.join(
                    self.env._("- %(product)s: ordered %(qty)s %(uom)s, available %(free)s %(uom)s",
                               product=product.display_name, qty=formatLang(self.env, qty),
                               free=formatLang(self.env, max(free, 0.0)), uom=product.uom_id.name)
                    for product, qty, free in shortages)
                raise UserError(self.env._(
                    "%(order)s cannot be confirmed: not enough stock in %(warehouse)s.\n\n%(details)s\n\n"
                    "Reduce the quantities or wait for the stock to be received.",
                    order=order.display_name, warehouse=order.warehouse_id.display_name,
                    details=details))

    # ------------------------------------------------------------------
    # Discount approval
    # ------------------------------------------------------------------
    def _alfiafy_has_discount(self):
        self.ensure_one()
        return any(line.discount > 0 for line in self.order_line if not line.display_type)

    @api.depends('order_line.discount')
    def _compute_approval_state(self):
        # Adds the line discounts to the dependencies of the approval state
        # (the "Any Discount" approval criterion).
        return super()._compute_approval_state()

    def action_confirm(self):
        """Hard stops first (stock, credit limit, overdue invoices), then a
        quotation with a discount that is not approved yet is sent for
        approval instead of being confirmed."""
        self._alfiafy_check_stock()
        self._alfiafy_check_credit_hold()
        to_approve = self.filtered(
            lambda order: order.state in ('draft', 'sent')
            and order.approval_blocked and order._alfiafy_has_discount())
        if to_approve:
            to_approve.action_send_for_approval()
        remaining = self - to_approve
        if not remaining:
            return True
        return super(SaleOrder, remaining).action_confirm()
