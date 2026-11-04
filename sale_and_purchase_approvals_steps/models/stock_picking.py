from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError

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


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    state = fields.Selection(selection_add=[
        ('to_approve', 'To Approve'),
        ('assigned',),
    ], ondelete={'to_approve': 'cascade'})

    show_approve_button = fields.Boolean(
        compute='_compute_show_approve_button',
        search='_search_show_approve_button')

    # Records the approval outcome. Needed as its own field because the
    # picking's own state cannot carry it: a validated transfer is 'done' and
    # a cancelled one goes back to 'assigned' first, so without this the
    # outcome would leave no visible trace on the record.
    approval_status = fields.Selection([
        ('to_approve', 'Waiting for Approval'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Approval Status', copy=False, readonly=True, tracking=True)
    approval_step_sequence = fields.Integer(string='Approval Step Sequence', default=0, copy=False)

    @api.depends('approval_status')
    def _compute_state(self):
        """Keep a transfer in 'to_approve' for as long as its approval runs.

        Unlike sale.order.state and purchase.order.state, which are plain
        stored Selections, stock.picking.state is *computed* and stored
        (@api.depends('move_type', 'move_ids.state', 'move_ids.picking_id')).
        Writing 'to_approve' into it therefore only holds until the next
        recompute -- a reservation, an unreserve, the scheduler, an upstream
        MO or PO completing -- at which point core silently rewrites the state
        and the transfer drops out of its chain: it reads 'Ready' while its
        approval status still says it is waiting, the Approve button
        disappears (it is gated on state == 'to_approve'), and the approver is
        left holding an activity for a transfer nobody can approve.

        Core computes normally; 'to_approve' is then reapplied for transfers
        whose approval is still in flight. 'done' and 'cancel' are never
        overridden, so a transfer that really did finish or get cancelled is
        not resurrected into the chain.

        Declaring @api.depends here *adds* to core's dependencies rather than
        replacing them -- get_depends() unions the depends of every
        implementation in the MRO -- so the normal recomputation still works.
        """
        super()._compute_state()
        for picking in self:
            if picking.approval_status == 'to_approve' and picking.state not in ('done', 'cancel'):
                picking.state = 'to_approve'

    def _compute_validate_button_style(self):
        """Odoo 20 drives both Validate buttons from one computed style.
        A transfer waiting for approval must not offer Validate at all."""
        super()._compute_validate_button_style()
        for picking in self:
            if picking.state == 'to_approve':
                picking.validate_button_style = 'invisible'

    def _get_matching_delivery_steps(self):
        """Return, in sequence order, the configured 'delivery' approval
        steps whose Amount condition matches the amount_total of this
        picking's connected Sale Order."""
        self.ensure_one()
        all_steps = self.env['approval.steps'].search([
            ('company_id', '=', self.company_id.id),
            ('type', '=', 'delivery'),
        ], order='sequence asc')
        return all_steps.filtered(lambda step: step._matches_delivery_order(self))

    @api.depends('state', 'approval_step_sequence')
    def _compute_show_approve_button(self):
        for picking in self:
            steps = picking._get_matching_delivery_steps().filtered(
                lambda step: step.sequence == picking.approval_step_sequence
            )
            user_ids = steps.mapped('user_id').ids
            is_admin = self.env.user.has_group(APPROVAL_GROUP_XMLID)
            picking.show_approve_button = picking.state == 'to_approve' and (self.env.uid in user_ids or is_admin)

    def _search_show_approve_button(self, operator, value):
        return search_show_approve_button(self, operator, value)

    def _needs_delivery_approval(self):
        """Whether pressing Validate on this transfer should open an approval
        chain instead of validating it.

        A transfer that has already cleared its chain must not be re-tested
        against the steps: the steps match on the Sale Order's amount, which
        does not change when the delivery is approved, so they still match
        afterwards. Without this an approved delivery is sent back for
        approval on every Validate and can never reach 'done'.

        'cancelled' is deliberately not excluded here: validating a rejected
        transfer again is a fresh request and does restart the chain.
        """
        self.ensure_one()
        if self.approval_status == 'approved':
            return False
        return bool(self._get_matching_delivery_steps())

    def button_validate(self):
        # Reachable over RPC, and until the view fix also from a leaked
        # Validate button. Restarting the chain here would reset
        # approval_step_sequence and re-notify the first approver, silently
        # discarding the approvals already given on a multi-step chain.
        awaiting = self.filtered(lambda p: p.state == 'to_approve')
        if awaiting:
            raise UserError(_(
                "The following transfer(s) are waiting for approval and "
                "cannot be validated yet:\n\n%s"
            ) % '\n'.join('- %s' % rec.display_name for rec in awaiting))

        to_approve = self.filtered(lambda p: p._needs_delivery_approval())

        for picking in to_approve:
            steps = picking._get_matching_delivery_steps()
            first_sequence = min(steps.mapped('sequence'))
            picking.write({
                'state': 'to_approve',
                'approval_status': 'to_approve',
                'approval_step_sequence': first_sequence,
            })
            first_steps = steps.filtered(lambda s: s.sequence == first_sequence)
            notify_approvers(picking, first_steps.mapped('user_id'))
            notify_requester(picking, Markup(_(
                "Sent for approval to <b>%(approvers)s</b> before it can "
                "be validated."
            )) % {'approvers': approver_names(first_steps)})

        to_validate = self - to_approve
        if to_validate:
            return self._delivery_super_validate(to_validate)
        return True

    def _delivery_super_validate(self, pickings):
        """Hand `pickings` to core validation and pass its answer back to the
        caller untouched.

        Core returns an action rather than True whenever it needs the user to
        answer something -- the backorder confirmation on a partial transfer
        being the common one -- and performs no transfer until that action is
        answered. Dropping the action leaves the click doing nothing at all:
        no validation, no backorder prompt, just an unresponsive button.
        """
        return super(StockPicking, pickings).button_validate()

    def _finish_delivery_approval(self, picking):
        """Record the approval and hand the transfer back to whoever raised it.

        Approval deliberately does NOT validate. Whether to keep a backorder
        for the undelivered balance is a warehouse decision, and core asks it
        with a dialog at validation time -- so validating here put that
        question to the approver, who is not the person shipping the goods and
        may not even hold stock rights.

        This is what the module already does for the other two document types:
        final approval on a sale order leaves it a Quotation (see sale.py) and
        on a purchase order leaves it an RFQ (see purchase.py), each handing
        back an Activity for the requester to act on. Delivery was the odd one
        out.
        """
        picking.write({'state': 'assigned', 'approval_status': 'approved'})
        close_approval_activities(picking)
        picking.message_post(body=_(
            "Delivery approved by %s. It stays in Ready; validating it, and "
            "deciding on a backorder for any undelivered balance, is left to "
            "the warehouse."
        ) % self.env.user.display_name)
        # The ball is back with the requester, so this is an Activity rather
        # than a notification: they have something to do.
        schedule_requester_activity(
            picking,
            summary=_("Approved - Validate the Delivery"),
            note=Markup(_(
                "%(record)s is fully approved (final approval by "
                "%(approver)s).<br/>Click Validate to complete the transfer."
            )) % {
                'record': picking.display_name,
                'approver': self.env.user.display_name,
            },
        )

    def button_approve_delivery(self):
        for picking in self:
            steps = picking._get_matching_delivery_steps()
            # Authorisation is enforced here, not only by hiding the button.
            is_admin = check_approver_allowed(picking, steps)

            # Close out the current approver's activity, whether they approved
            # normally or an admin is bypassing the chain on their behalf.
            close_approval_activities(picking, user=self.env.user)

            if is_admin:
                self._finish_delivery_approval(picking)
                continue

            # Advance to the next matching step by ascending sequence, not by a
            # hard-coded +1, so steps numbered with gaps don't skip approvers.
            remaining = steps.filtered(
                lambda step: step.sequence > picking.approval_step_sequence
            )

            if remaining:
                next_sequence = min(remaining.mapped('sequence'))
                next_steps = remaining.filtered(
                    lambda step: step.sequence == next_sequence
                )
                picking.write({
                    'state': 'to_approve',
                    'approval_step_sequence': next_sequence,
                })
                notify_approvers(picking, next_steps.mapped('user_id'))
                notify_requester(picking, Markup(_(
                    "Approved by <b>%(approver)s</b>. Now awaiting approval "
                    "from <b>%(next_approvers)s</b>."
                )) % {
                    'approver': self.env.user.display_name,
                    'next_approvers': approver_names(next_steps),
                })
            else:
                self._finish_delivery_approval(picking)

        return True

    def _approval_requester(self):
        """Who raised this transfer, and therefore who gets told what happens
        to it. Falls back to the creator when no responsible user is set."""
        self.ensure_one()
        return self.user_id or self.create_uid

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
        return self._get_matching_delivery_steps()

    def _approval_cancel(self, reason):
        """Entry point used by the wizard once a reason has been given."""
        self.ensure_one()
        return self.with_context(approval_cancel_reason=reason).action_cancel()

    def action_cancel(self):
        """Cancelling a transfer that is out for approval is either a
        rejection (by an approver) or a withdrawal (by whoever raised it).
        Both need a reason; they are recorded differently. Cancelling anything
        else behaves exactly as before, with no prompt."""
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

        if pending:
            close_approval_activities(pending)
            # Core refuses to act on the 'to_approve' state this module adds,
            # so put the transfer back to Ready before handing over.
            pending.write({
                'state': 'assigned',
                'approval_status': 'cancelled',
                'approval_step_sequence': 0,
            })

        res = super().action_cancel()

        if reason:
            for rec, role, approvers in plan:
                post_approval_cancellation(rec, role, approvers, reason)
        return res
