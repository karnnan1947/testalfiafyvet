# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models

VARIANCE_PARAM = 'alfiafy_stock.variance_approval_threshold'
DEFAULT_VARIANCE_THRESHOLD = 500.0
APPROVAL_ACTIVITY_SUMMARY = "Inventory variance approval"


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    variance_value = fields.Float(
        string="Variance Value", compute='_compute_variance_value', digits='Product Price',
        groups='restricted_cost_access.group_manager_cost',
        help="(Counted quantity - On hand quantity) x product cost, in company currency.")
    variance_exceeded = fields.Boolean(
        string="Variance Above Limit", compute='_compute_variance_exceeded',
        help="The value of the count difference is above the approval limit "
             "(system parameter alfiafy_stock.variance_approval_threshold, default 500).")
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'Waiting Approval'),
        ('approved', 'Approved'),
    ], string="Variance Approval", default='draft', copy=False, index=True)

    @api.model
    def _get_variance_threshold(self):
        return self.env['ir.config_parameter'].sudo().get_float(VARIANCE_PARAM, DEFAULT_VARIANCE_THRESHOLD)

    def _get_variance_value(self):
        """(inventory_quantity - quantity) * product cost, read with sudo so the
        check also works for users who cannot see costs."""
        self.ensure_one()
        quant = self.sudo()
        if not quant.inventory_quantity_set:
            return 0.0
        cost = quant.product_id.with_company(quant.company_id).standard_price
        return (quant.inventory_quantity - quant.quantity) * cost

    @api.depends('inventory_quantity', 'quantity', 'inventory_quantity_set', 'product_id')
    def _compute_variance_value(self):
        for quant in self:
            quant.variance_value = quant._get_variance_value()

    @api.depends('inventory_quantity', 'quantity', 'inventory_quantity_set', 'product_id')
    def _compute_variance_exceeded(self):
        threshold = self._get_variance_threshold()
        for quant in self:
            quant.variance_exceeded = abs(quant._get_variance_value()) > threshold

    def action_apply_inventory(self, date=None):
        """A count difference above the limit applied by a non-manager waits
        for the Stock Manager (activity); the other lines are applied."""
        if self.env.user.has_group('stock.group_stock_manager'):
            waiting = self.filtered(lambda q: q.approval_state == 'to_approve')
            res = super().action_apply_inventory(date=date)
            waiting.filtered(lambda q: not q.inventory_quantity_set).sudo().write({'approval_state': 'approved'})
            return res
        threshold = self._get_variance_threshold()
        to_approve = self.filtered(lambda q: abs(q._get_variance_value()) > threshold)
        allowed = self - to_approve
        res = None
        if allowed:
            res = super(StockQuant, allowed).action_apply_inventory(date=date)
        if to_approve:
            to_approve._request_variance_approval()
            if not res:
                res = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': self.env._("Approval required"),
                        'message': self.env._(
                            "%(count)s count difference(s) above %(limit)s were sent to the Stock Manager "
                            "for approval and not applied.", count=len(to_approve), limit=threshold),
                        'type': 'warning',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    },
                }
        return res

    def _request_variance_approval(self):
        """Mark the quants as waiting approval and schedule an activity for the
        Stock Managers on the product (quants have no chatter)."""
        self.sudo().write({'approval_state': 'to_approve'})
        managers = self.env.ref('stock.group_stock_manager').sudo().all_user_ids.filtered(
            lambda u: u.active and not u.share and u.id != self.env.ref('base.user_root').id)
        for quant in self.sudo():
            note = Markup("%s<br/>%s") % (
                self.env._("%(location)s, %(product)s%(lot)s: on hand %(qty)s, counted %(counted)s by %(user)s.",
                           location=quant.location_id.display_name, product=quant.product_id.display_name,
                           lot=(" / " + quant.lot_id.name) if quant.lot_id else "",
                           qty=quant.quantity, counted=quant.inventory_quantity, user=self.env.user.name),
                self.env._("Variance value %(value).2f is above the approval limit. Review it in "
                           "Inventory > Physical Inventory > Pending Variance Approvals.",
                           value=quant._get_variance_value()))
            for user in managers:
                quant.product_id.product_tmpl_id.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=APPROVAL_ACTIVITY_SUMMARY,
                    note=note,
                    user_id=user.id,
                )
