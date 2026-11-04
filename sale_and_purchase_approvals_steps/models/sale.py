from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from .approvals import (
    APPROVAL_GROUP_XMLID,
    approver_names,
    check_approval_cancel_allowed,
    check_approver_allowed,
    close_approval_activities,
    current_approvers,
    notify_approvers,
    notify_requester,
    post_approval_cancellation,
    schedule_requester_activity,
    search_show_approve_button,
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    state = fields.Selection(selection_add=
                             [('to_approve', 'To Approve'),
                              ('sent',)], ondelete={'to_approve': 'cascade'}, copy=False)
    show_approve_button = fields.Boolean(
        compute='_compute_show_approve_button',
        search='_search_show_approve_button')
    # copy=False: without it, duplicating an approved order carries its step
    # number into the new quotation, and every approval step at or below that
    # number is skipped on the copy.
    approval_step_sequence = fields.Integer(
        string='Approval Step Sequence', default=0, copy=False)
    # Tracks which approval type triggered to_approve: 'sale' or 'expense'
    approval_type = fields.Selection(
        [('sale', 'Sale')],
        string='Approval Type', copy=False,
    )

    # ------------------------------------------------------------------
    # Approval outcome
    # ------------------------------------------------------------------
    # Approving no longer confirms the order. The outcome is recorded here
    # and the record is handed back to the salesperson as a Quotation, who
    # sends it to the customer and confirms it manually when the customer
    # accepts.
    approval_status = fields.Selection([
        ('to_approve', 'Waiting for Approval'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Approval Status', copy=False, readonly=True, tracking=True)
    # State to restore once the chain completes (Quotation vs Quotation Sent).
    approval_prev_state = fields.Char(copy=False, readonly=True)
    # Total the approval was granted on. Because the record stays editable in
    # the Quotation stage after approval, an order approved at QAR 1,000 could
    # otherwise be edited to QAR 1,000,000 and confirmed on that approval.
    approval_amount_total = fields.Monetary(
        string='Approved Amount', copy=False, readonly=True)

    approval_required = fields.Boolean(compute='_compute_approval_state')
    approval_blocked = fields.Boolean(compute='_compute_approval_state')
    show_send_for_approval = fields.Boolean(compute='_compute_approval_state')

    def _get_approval_type(self):
        self.ensure_one()
        return 'sale'

    def _approval_requester(self):
        """Who raised this record, and therefore who gets told what happens
        to it. Falls back to the creator when no salesperson is set."""
        self.ensure_one()
        return self.user_id or self.create_uid

    @api.depends('state', 'approval_status', 'approval_amount_total',
                 'amount_total', 'margin_percent', 'company_id')
    def _compute_approval_state(self):
        for order in self:
            required = bool(order._get_matching_sale_steps())
            approved = order._approval_is_valid()
            # Only ever gate the pre-confirmation stages: an order that is
            # already a Sales Order must keep its normal buttons even if it
            # would match an approval step today.
            pending = order.state in ('draft', 'sent', 'to_approve')
            order.approval_required = required
            order.approval_blocked = required and not approved and pending
            order.show_send_for_approval = (
                required and not approved and order.state in ('draft', 'sent')
            )

    def _approval_is_valid(self):
        """True when this order carries an approval that still applies to its
        current total."""
        self.ensure_one()
        if self.approval_status != 'approved':
            return False
        rounding = self.currency_id.rounding or 0.01
        return float_compare(
            self.amount_total, self.approval_amount_total,
            precision_rounding=rounding) == 0

    @api.depends('state', 'approval_step_sequence', 'approval_type')
    def _compute_show_approve_button(self):
        for order in self:
            if order.state != 'to_approve':
                order.show_approve_button = False
                continue
            steps = order._get_matching_sale_steps().filtered(
                lambda step: step.sequence == order.approval_step_sequence
            )
            user_ids = steps.mapped('user_id').ids
            is_admin = self.env.user.has_group(APPROVAL_GROUP_XMLID)
            order.show_approve_button = (self.env.uid in user_ids or is_admin)

    def _search_show_approve_button(self, operator, value):
        return search_show_approve_button(self, operator, value)

    def _get_matching_sale_steps(self):
        """Return, in sequence order, the configured 'sale' approval steps whose
        dynamic condition (amount/margin/both, with its operators and AND/OR
        logic) actually matches this order. An empty result means the order
        does not require approval at all."""
        self.ensure_one()
        all_steps = self.env['approval.steps'].search([
            ('company_id', '=', self.company_id.id),
            ('type', '=', 'sale'),
        ], order='sequence asc')
        return all_steps.filtered(lambda step: step._matches_sale_order(self))

    def _sale_needs_approval(self):
        self.ensure_one()
        return bool(self._get_matching_sale_steps())

    def action_send_for_approval(self):
        """Enter the approval chain.

        Submitting for approval is now an explicit action, separate from
        Confirm. Confirm converts the quotation into a Sales Order and does
        nothing else.
        """
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError(_(
                    "Only a quotation can be sent for approval. %s is no "
                    "longer in the Quotation stage."
                ) % order.display_name)

            steps = order._get_matching_sale_steps()
            if not steps:
                raise UserError(_(
                    "%s does not require approval and can be confirmed directly."
                ) % order.display_name)

            # Always restart from the lowest matching sequence rather than from
            # whatever step the record happens to be carrying.
            first_sequence = min(steps.mapped('sequence'))
            order.write({
                'approval_prev_state': order.state,
                'state': 'to_approve',
                'approval_status': 'to_approve',
                'approval_step_sequence': first_sequence,
                'approval_type': order._get_approval_type(),
                'approval_amount_total': 0.0,
            })
            first_steps = steps.filtered(lambda s: s.sequence == first_sequence)
            notify_approvers(order, first_steps.mapped('user_id'))
            notify_requester(order, Markup(_(
                "Sent for approval to <b>%(approvers)s</b>. You will be "
                "notified as it moves through the approval chain."
            )) % {'approvers': approver_names(first_steps)})
        return True

    def action_confirm(self):
        """Confirm is a manual, deliberate conversion to a Sales Order.

        It never happens as a side effect of an approval, and it is refused
        while an approval is outstanding.
        """
        blocked = self.filtered(lambda order: order.approval_blocked)
        if blocked:
            raise UserError(_(
                "The following quotation(s) must be approved before they can "
                "be confirmed:\n\n%s\n\n"
                "Use 'Send for Approval' to start the approval workflow."
            ) % '\n'.join('- %s' % order.display_name for order in blocked))
        res = super().action_confirm()
        # The "Approved - Send to Customer" activity has been acted on.
        close_approval_activities(self)
        return res

    def button_approve(self):
        for order in self:
            steps = order._get_matching_sale_steps()
            # Authorisation is enforced here, not only by hiding the button.
            is_admin = check_approver_allowed(order, steps)

            # Close out the current approver's activity, whether they approved
            # normally or an admin is bypassing the chain on their behalf.
            close_approval_activities(order, user=self.env.user)

            # Advance to the next matching step by ascending sequence, not by a
            # hard-coded +1: matching steps re-evaluated now (the order may have
            # changed since it entered the chain) can sit at any higher sequence.
            # An Approval-group member closes the whole chain in one click.
            if is_admin:
                remaining = self.env['approval.steps']
            else:
                remaining = steps.filtered(
                    lambda step: step.sequence > order.approval_step_sequence
                )

            if remaining:
                next_sequence = min(remaining.mapped('sequence'))
                next_steps = remaining.filtered(
                    lambda step: step.sequence == next_sequence
                )
                order.write({
                    'state': 'to_approve',
                    'approval_step_sequence': next_sequence
                })
                notify_approvers(order, next_steps.mapped('user_id'))
                notify_requester(order, Markup(_(
                    "Approved by <b>%(approver)s</b>. Now awaiting approval "
                    "from <b>%(next_approvers)s</b>."
                )) % {
                    'approver': self.env.user.display_name,
                    'next_approvers': approver_names(next_steps),
                })
                continue

            # Final approval. The order goes back to being a Quotation: it is
            # NOT converted into a Sales Order here. The salesperson can now
            # send it to the customer and confirm it when the customer accepts.
            close_approval_activities(order)
            order.write({
                'state': order.approval_prev_state or 'draft',
                'approval_status': 'approved',
                'approval_amount_total': order.amount_total,
                'approval_prev_state': False,
                'approval_type': False,
            })
            order.message_post(body=_(
                "Approved by %s. The quotation stays in the Quotation stage "
                "and can now be sent to the customer; it becomes a Sales "
                "Order only when Confirm is clicked."
            ) % self.env.user.display_name)
            # The ball is back with the salesperson, so this one is an
            # Activity rather than a notification: they have something to do.
            schedule_requester_activity(
                order,
                summary=_("Approved - Send to Customer"),
                note=Markup(_(
                    "%(record)s is fully approved (final approval by "
                    "%(approver)s).<br/>You can now send it to the customer, "
                    "and confirm it once they accept."
                )) % {
                    'record': order.display_name,
                    'approver': self.env.user.display_name,
                },
            )
        return True

    # ------------------------------------------------------------------
    # Cancellation (which, for a record out for approval, is the rejection)
    # ------------------------------------------------------------------
    def _open_approval_cancel_wizard(self, role):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Request") if role == 'approver' else _("Withdraw Request"),
            'res_model': 'approval.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'default_record_name': self.display_name,
                'default_is_approver': role == 'approver',
            },
        }

    def _approval_matching_steps(self):
        """Uniform accessor so the shared approval helpers can find this
        model's steps without knowing which document type it is."""
        return self._get_matching_sale_steps()

    def _approval_cancel(self, reason):
        """Entry point used by the wizard once a reason has been given."""
        self.ensure_one()
        return self.with_context(approval_cancel_reason=reason).action_cancel()

    def action_cancel(self):
        """Cancelling a quotation that is out for approval is either a
        rejection (by an approver) or a withdrawal (by the salesperson who
        raised it). Both need a reason; they are recorded differently.
        Cancelling anything else behaves exactly as before, with no prompt."""
        reason = self.env.context.get('approval_cancel_reason')
        pending = self.filtered(lambda rec: rec.state == 'to_approve')

        if pending and not reason:
            if len(self) == 1:
                role = check_approval_cancel_allowed(self)
                return self._open_approval_cancel_wizard(role)
            raise UserError(_(
                "The following record(s) are waiting for approval and must be "
                "cancelled one at a time, so a reason can be recorded:\n\n%s"
            ) % '\n'.join('- %s' % rec.display_name for rec in pending))

        # Resolve the role and capture who was waiting BEFORE anything is
        # reset, otherwise the approver list is gone by the time we notify.
        plan = []
        for rec in pending:
            plan.append((rec, check_approval_cancel_allowed(rec), current_approvers(rec)))

        close_approval_activities(self)
        # Clear the approval bookkeeping only. 'state' is deliberately NOT
        # written here: cancelling a sale order is not a state flip. Core
        # cancels the order's draft invoices (sale/models/sale_order.py,
        # _action_cancel) and its outstanding deliveries (sale_stock overrides
        # the same method), and refuses to cancel a locked order. Writing
        # 'cancel' directly skipped all of it, leaving deliveries live and
        # validatable against a cancelled order.
        self.write({
            'approval_type': False,
            # Distinguishes a cancel made during approval from an ordinary
            # cancel, which leaves the approval status empty.
            'approval_status': 'cancelled' if pending else False,
            'approval_prev_state': False,
            'approval_amount_total': 0.0,
            'approval_step_sequence': 0,
        })

        res = super().action_cancel()

        if reason:
            for rec, role, approvers in plan:
                post_approval_cancellation(rec, role, approvers, reason)
        return res

    def write(self, vals):
        """Freeze the contents of an order that is out for approval.

        Both the Approve button's visibility and the routing to the next step
        are derived from the order's current amount and margin. Editing it
        mid-approval can therefore change which steps match, leaving nobody
        able to approve it and the record stuck in 'To Approve' with Cancel as
        the only way out. Approvers must also be sure they are approving what
        they were sent.
        """
        if 'order_line' in vals:
            frozen = self.filtered(lambda order: order.state == 'to_approve')
            if frozen:
                raise UserError(_(
                    "The following order(s) are out for approval and cannot be "
                    "modified:\n\n%s\n\n"
                    "Cancel the approval first if the order has to change."
                ) % '\n'.join('- %s' % order.display_name for order in frozen))
        return super().write(vals)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _check_order_not_under_approval(self):
        frozen = self.filtered(lambda line: line.order_id.state == 'to_approve')
        if frozen:
            raise UserError(_(
                "The following order(s) are out for approval and their lines "
                "cannot be changed:\n\n%s\n\n"
                "Cancel the approval first if the order has to change."
            ) % '\n'.join(
                '- %s' % name for name in sorted(set(frozen.mapped('order_id.display_name')))
            ))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_order_not_under_approval()
        return lines

    def write(self, vals):
        self._check_order_not_under_approval()
        return super().write(vals)

    def unlink(self):
        self._check_order_not_under_approval()
        return super().unlink()
