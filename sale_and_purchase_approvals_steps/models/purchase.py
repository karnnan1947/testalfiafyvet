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
from ..wizard.purchase_waiver_wizard import WAIVER_CATEGORY_SELECTION


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Labelled "Waiting Approval", not "To Approve": core purchase already
    # ships a state keyed 'to approve' (with a space) for Odoo's own PO
    # double-validation feature, and two entries both reading "To Approve" in
    # the status bar is indistinguishable to the user.
    state = fields.Selection(selection_add=
                             [('to_approve', 'Waiting Approval'),
                              ('sent',)], ondelete={'to_approve': 'cascade'})
    show_approve_button = fields.Boolean(
        compute='_compute_show_approve_button',
        search='_search_show_approve_button')
    # copy=False: without it, duplicating an approved order carries its step
    # number into the new RFQ, and every approval step at or below that number
    # is skipped on the copy.
    approval_step_sequence = fields.Integer(
        string='Approval Step Sequence', default=0, copy=False)

    # ------------------------------------------------------------------
    # Approval outcome
    # ------------------------------------------------------------------
    # Approving records the outcome here and leaves the record in the RFQ /
    # RFQ Sent stage. It does not create the Purchase Order and it does not
    # create a Goods Receipt; the buyer does that with Confirm Order once the
    # approval is in place.
    approval_status = fields.Selection([
        ('to_approve', 'Waiting for Approval'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Approval Status', copy=False, readonly=True, tracking=True)
    # Stage to restore once the chain completes (RFQ vs RFQ Sent).
    approval_prev_state = fields.Char(copy=False, readonly=True)
    # Total the approval was granted on; the RFQ stays editable afterwards, so
    # changing the total invalidates the approval and re-triggers the workflow.
    approval_amount_total = fields.Monetary(
        string='Approved Amount', copy=False, readonly=True)

    approval_required = fields.Boolean(compute='_compute_approval_state')
    approval_blocked = fields.Boolean(compute='_compute_approval_state')
    show_send_for_approval = fields.Boolean(compute='_compute_approval_state')

    # ------------------------------------------------------------------
    # Waiver (Procurement Approval exception)
    # ------------------------------------------------------------------
    waiver_applied = fields.Boolean(
        string="Waiver Applied", copy=False, readonly=True, tracking=True,
        help="Set automatically when this request was sent for approval "
             "through the Waiver Form instead of meeting the 3 Alternative "
             "POs requirement.")
    waiver_category = fields.Selection(
        selection=WAIVER_CATEGORY_SELECTION,
        string="Waiver Category", copy=False, readonly=True, tracking=True)
    waiver_justification = fields.Html(
        string="Waiver Justification", copy=False, readonly=True)

    # Alternatives tab comes from the "Purchase Agreements"
    # (purchase_requisition) addon: alternative_po_ids.
    alternative_po_count = fields.Integer(
        string="Alternative PO Count", compute='_compute_alternative_po_count')

    def _approval_requester(self):
        """Who raised this request, and therefore who gets told what happens
        to it. Falls back to the creator when no buyer is set."""
        self.ensure_one()
        return self.user_id or self.create_uid

    @api.depends('alternative_po_ids')
    def _compute_alternative_po_count(self):
        for order in self:
            order.alternative_po_count = len(order.alternative_po_ids)

    @api.depends('state', 'approval_status', 'approval_amount_total',
                 'amount_total', 'company_id')
    def _compute_approval_state(self):
        for order in self:
            required = bool(order._get_matching_purchase_steps())
            approved = order._approval_is_valid()
            # Only gate the pre-confirmation stages, so an existing Purchase
            # Order keeps its normal buttons.
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

    def _requires_purchase_waiver(self):
        """Return True if sending this request for approval must first be
        routed through the Waiver Form: at least one matching purchase
        approval step has the Waiver Mechanism enabled, and the request
        doesn't (yet) have 3 linked Alternative POs."""
        self.ensure_one()
        if self.waiver_applied:
            # Already waived previously, don't ask again.
            return False
        steps = self._get_matching_purchase_steps()
        if not steps.filtered('waiver_mechanism'):
            return False
        return self.alternative_po_count < 3

    def action_open_purchase_waiver_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Waiver Form"),
            'res_model': 'purchase.waiver.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_purchase_order_id': self.id},
        }

    def _get_matching_purchase_steps(self):
        """Return, in sequence order, the configured 'purchase' approval steps
        whose Amount condition (operator + value) matches this order."""
        self.ensure_one()
        all_steps = self.env['approval.steps'].search([
            ('company_id', '=', self.company_id.id),
            ('type', '=', 'purchase'),
        ], order='sequence asc')
        return all_steps.filtered(lambda step: step._matches_purchase_order(self))

    @api.depends('state', 'user_id', 'approval_step_sequence')
    def _compute_show_approve_button(self):
        for order in self:
            steps = order._get_matching_purchase_steps().filtered(
                lambda step: step.sequence == order.approval_step_sequence
            )
            user_ids = steps.mapped('user_id').ids
            is_admin = self.env.user.has_group(APPROVAL_GROUP_XMLID)
            order.show_approve_button = order.state == 'to_approve' and (self.env.uid in user_ids or is_admin)

    def _search_show_approve_button(self, operator, value):
        return search_show_approve_button(self, operator, value)

    def _check_approval_step_sequence(self):
        """Kept as an extension point; no longer bans repeated sequences.

        Purchase steps used to be rejected outright if any two shared a
        sequence number, which was wrong on two counts. It blocked a perfectly
        valid setup -- several approvers at the same approval level, any one of
        whom may sign -- which Sale and Delivery steps have always allowed. And
        it searched every purchase step regardless of company, so company B
        could not reuse a sequence number already used by company A even though
        their approval chains are unrelated.

        Routing has always coped with repeats: every step at the winning
        sequence is notified, and the first of them to approve moves the record
        on to the next level.
        """
        return True

    def action_send_for_approval(self):
        """Enter the approval chain ("To Approve").

        This is where the Waiver Mechanism is checked: the Procurement User
        who submits the request is the one who has to justify why fewer than
        3 supplier quotations were obtained, and the waiver travels with the
        request to the Director. The approver is never asked for it.
        """
        self._check_approval_step_sequence()

        # Route through the Waiver Form before anything is written, so the
        # request only moves once the justification is on record. Cancelling
        # the wizard leaves the RFQ exactly where it was.
        if len(self) == 1 and not self.env.context.get('skip_waiver_check') \
                and self.state in ('draft', 'sent') and self._requires_purchase_waiver():
            return self.action_open_purchase_waiver_wizard()

        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError(_(
                    "Only an RFQ can be sent for approval. %s is no longer in "
                    "the RFQ stage."
                ) % order.display_name)

            steps = order._get_matching_purchase_steps()
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
                'approval_amount_total': 0.0,
            })
            first_steps = steps.filtered(lambda s: s.sequence == first_sequence)
            notify_approvers(order, first_steps.mapped('user_id'),
                             extra_note=order._waiver_activity_note())
            notify_requester(order, Markup(_(
                "Sent for approval to <b>%(approvers)s</b>. You will be "
                "notified as it moves through the approval chain."
            )) % {'approvers': approver_names(first_steps)})
        return True

    def _waiver_activity_note(self):
        """Waiver details to carry into the approver's activity, so the
        Director sees the category and justification up front."""
        self.ensure_one()
        if not self.waiver_applied:
            return None
        category = dict(WAIVER_CATEGORY_SELECTION).get(
            self.waiver_category, self.waiver_category)
        return Markup(_(
            "<b>Waiver applied</b> (fewer than 3 alternative supplier "
            "quotations).<br/>Category: <b>%(category)s</b>"
            "<br/>Justification: %(justification)s"
        )) % {
            'category': category,
            # Already-sanitised HTML from an Html field: mark it safe so the
            # justification is not double-escaped into visible tags.
            'justification': Markup(self.waiver_justification or ''),
        }

    def button_confirm(self):
        """Confirm Order is a manual, deliberate conversion into a Purchase
        Order. It never happens as a side effect of an approval, and it is
        refused while an approval is outstanding."""
        blocked = self.filtered(lambda order: order.approval_blocked)
        if blocked:
            raise UserError(_(
                "The following request(s) must be approved before they can be "
                "confirmed:\n\n%s\n\n"
                "Use 'To Approve' to start the approval workflow."
            ) % '\n'.join('- %s' % order.display_name for order in blocked))
        res = super().button_confirm()
        # The "Approved - Confirm the Order" activity has been acted on.
        close_approval_activities(self)
        return res

    def button_approve(self, force=False):
        """Guard Odoo's built-in Approve.

        The stock Approve button is still reachable from the standard Purchase
        form, from XML-RPC, and from any inheriting module; without this guard
        it would confirm a request whose approval workflow has not been
        completed.
        """
        blocked = self.filtered(lambda order: order.approval_blocked)
        if blocked:
            raise UserError(_(
                "The following request(s) have not completed their approval "
                "workflow:\n\n%s"
            ) % '\n'.join('- %s' % order.display_name for order in blocked))
        return super().button_approve(force=force)

    def button_approve_po(self):
        for order in self:
            steps = order._get_matching_purchase_steps()
            # Authorisation is enforced here, not only by hiding the button.
            is_admin = check_approver_allowed(order, steps)

            # Close out the current approver's activity, whether they approved
            # normally or an admin is bypassing the chain on their behalf.
            close_approval_activities(order, user=self.env.user)

            # Advance to the next matching step by ascending sequence, not by a
            # hard-coded +1, so steps numbered with gaps don't skip approvers.
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
                notify_approvers(
                    order, next_steps.mapped('user_id'),
                    extra_note=order._waiver_activity_note(),
                )
                notify_requester(order, Markup(_(
                    "Approved by <b>%(approver)s</b>. Now awaiting approval "
                    "from <b>%(next_approvers)s</b>."
                )) % {
                    'approver': self.env.user.display_name,
                    'next_approvers': approver_names(next_steps),
                })
                continue

            # Final approval. The status becomes Approved and the record stays
            # in the RFQ / RFQ Sent stage: no Purchase Order and no Goods
            # Receipt are created here.
            close_approval_activities(order)
            order.write({
                'state': order.approval_prev_state or 'draft',
                'approval_status': 'approved',
                'approval_amount_total': order.amount_total,
                'approval_prev_state': False,
            })
            order.message_post(body=_(
                "Approved by %s. The request stays in the RFQ stage; it "
                "becomes a Purchase Order, and generates its Goods Receipt, "
                "only when Confirm Order is clicked."
            ) % self.env.user.display_name)
            # The ball is back with the buyer, so this one is an Activity
            # rather than a notification: they have something to do.
            schedule_requester_activity(
                order,
                summary=_("Approved - Confirm the Order"),
                note=Markup(_(
                    "%(record)s is fully approved (final approval by "
                    "%(approver)s).<br/>Click Confirm Order to raise the "
                    "Purchase Order and its Goods Receipt."
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
        return self._get_matching_purchase_steps()

    def _approval_cancel(self, reason):
        """Entry point used by the wizard once a reason has been given."""
        self.ensure_one()
        return self.with_context(approval_cancel_reason=reason).button_cancel()

    def button_cancel(self):
        """Cancelling a request that is out for approval is either a rejection
        (by an approver) or a withdrawal (by the buyer who raised it). Both
        need a reason; they are recorded differently. Cancelling anything else
        behaves exactly as before, with no prompt."""
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
        # written here: cancelling a purchase order is not a state flip. Core
        # cancels the order's receipts and repairs the MTO chain
        # (purchase_stock overrides button_cancel), refuses to cancel a locked
        # order, and refuses to cancel one whose vendor bills are still
        # posted. Writing 'cancel' directly skipped all of it, leaving
        # receipts live and validatable against a cancelled order.
        self.write({
            # Distinguishes a cancel made during approval from an ordinary
            # cancel, which leaves the approval status empty.
            'approval_status': 'cancelled' if pending else False,
            'approval_prev_state': False,
            'approval_amount_total': 0.0,
            'approval_step_sequence': 0,
        })

        res = super().button_cancel()

        if reason:
            for rec, role, approvers in plan:
                post_approval_cancellation(rec, role, approvers, reason)
        return res

    def write(self, vals):
        """Freeze the contents of a request that is out for approval.

        Which steps match, and therefore who can approve, is derived from the
        request's current amount. Editing it mid-approval can leave nobody
        able to approve it, and the approver must be sure they are approving
        what they were sent.
        """
        if 'order_line' in vals:
            frozen = self.filtered(lambda order: order.state == 'to_approve')
            if frozen:
                raise UserError(_(
                    "The following request(s) are out for approval and cannot "
                    "be modified:\n\n%s\n\n"
                    "Cancel the approval first if the request has to change."
                ) % '\n'.join('- %s' % order.display_name for order in frozen))
        return super().write(vals)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _check_order_not_under_approval(self):
        frozen = self.filtered(lambda line: line.order_id.state == 'to_approve')
        if frozen:
            raise UserError(_(
                "The following request(s) are out for approval and their lines "
                "cannot be changed:\n\n%s\n\n"
                "Cancel the approval first if the request has to change."
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
