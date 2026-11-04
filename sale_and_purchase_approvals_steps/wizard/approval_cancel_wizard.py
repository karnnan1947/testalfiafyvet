# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class ApprovalCancelWizard(models.TransientModel):
    """Capture a mandatory reason when a record out for approval is cancelled.

    Cancelling a record that is waiting on an approver *is* the rejection, so
    the approver is asked why. The reason goes on the chatter and reaches the
    requester as an Activity; the cancellation itself then proceeds exactly as
    it always has.

    One wizard serves sale.order, purchase.order and stock.picking; each of
    those implements _approval_cancel().
    """
    _name = 'approval.cancel.wizard'
    _description = "Cancel Approval Request"

    res_model = fields.Char(string="Model", required=True, readonly=True)
    res_id = fields.Integer(string="Record ID", required=True, readonly=True)
    record_name = fields.Char(string="Document", readonly=True)
    reason = fields.Text(string="Reason", required=True)
    # True when an approver is refusing the request, False when the person who
    # raised it is pulling it back. Only changes the wording; the caller's role
    # is re-derived server-side before anything is written.
    is_approver = fields.Boolean(string="Cancelling as Approver", readonly=True)

    def action_confirm_cancel(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("Please give a reason before cancelling."))

        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_("The record being cancelled no longer exists."))

        record._approval_cancel(reason)
        return {'type': 'ir.actions.act_window_close'}
