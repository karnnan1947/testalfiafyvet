import operator

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, ValidationError, UserError

APPROVAL_GROUP_XMLID = 'sale_and_purchase_approvals_steps.group_approval'

OPERATOR_FUNCS = {
    '<': operator.lt,
    '<=': operator.le,
    '>': operator.gt,
    '>=': operator.ge,
}


class ApprovalSteps(models.Model):
    _name = 'approval.steps'
    _description = 'Approval Steps'
    # Group the matrix by type, then walk each chain in approval order, so the
    # list reads the way the approvals actually run.
    _order = 'type, sequence, id'

    type = fields.Selection([('sale', 'Sale'),('purchase', 'Purchase'),('delivery', 'Delivery'),], string='Type', required=True)
    # Must be 1 or more. 0 is reserved: it is the value an order carries when
    # it is not in an approval chain at all, so a step numbered 0 could never
    # be told apart from "no approval in progress".
    # Default 10, and steps are meant to be numbered 10/20/30 so a new level
    # can be inserted later without renumbering the whole matrix.
    sequence = fields.Integer(string='Sequence', required=True, default=10)
    user_id = fields.Many2one('res.users', string='User', required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one('res.currency', string='Currency', compute='_compute_currency', store=True, readonly=True)

    # --- Dynamic Condition Builder ---
    # amount_operator / amount_value are shared by both Sale and Purchase steps.
    # sale_criteria_type / logic_operator / margin_* only apply to Sale steps
    # (Purchase steps only ever use the amount condition).
    # Default is 'amount', NOT 'both'. With 'both' the step also has to satisfy
    # the margin condition, whose own defaults are "< 0%" combined with AND --
    # a condition that is almost never true. A step configured as "Amount >
    # 50000" with Criteria left untouched would then silently never fire, and
    # the order would confirm with no approval at all.
    sale_criteria_type = fields.Selection([
        ('amount', 'Amount Only'),
        ('margin', 'Margin Only'),
        ('both', 'Amount and Margin'),
    ], string='Criteria', default='amount')

    amount_operator = fields.Selection([
        ('<', '<'),
        ('<=', '≤'),
        ('>', '>'),
        ('>=', '≥'),
    ], string='Amount Operator', default='>')
    amount_value = fields.Float(string='Amount Value')
    # Which total the Amount condition is measured against. Defaults to the
    # tax-inclusive total, which is what this module has always compared, so
    # existing steps keep behaving exactly as before.
    amount_base = fields.Selection([
        ('total', 'Total (tax included)'),
        ('untaxed', 'Untaxed Total (tax excluded)'),
    ], string='Amount Based On', default='total', required=True,
        help="Whether the Amount condition is measured on the tax-inclusive "
             "total or on the untaxed total. A 'greater than 5,000' rule on "
             "the tax-inclusive total is reached at 4,762 net when 5% VAT "
             "applies.")

    logic_operator = fields.Selection([
        ('and', 'AND'),
        ('or', 'OR'),
    ], string='Logic', default='and')

    margin_operator = fields.Selection([
        ('<', '<'),
        ('<=', '≤'),
        ('>', '>'),
        ('>=', '≥'),
    ], string='Margin Operator', default='<')
    margin_value = fields.Integer(string='Margin Value (%)')

    # --- Waiver Mechanism (Purchase steps only) ---
    # When enabled on a matching purchase step, confirming a Purchase Order
    # that needs approval but has fewer than 3 linked Alternative POs will
    # pop up the Waiver Form instead of entering the approval chain directly.
    # See models/purchase.py (_requires_purchase_waiver) and
    # wizard/purchase_waiver_wizard.py.
    waiver_mechanism = fields.Boolean(
        string='Waiver Mechanism', default=False,
        help="Only applicable to Purchase approval steps. When enabled, a "
             "matching Purchase Order with fewer than 3 Alternative POs "
             "will require a Waiver Form to be submitted before it can "
             "proceed to approval.")

    @api.onchange('type')
    def _onchange_type_reset_waiver(self):
        for rec in self:
            if rec.type != 'purchase':
                rec.waiver_mechanism = False

    @api.depends('company_id.currency_id')
    def _compute_currency(self):
        # The step's own company, not the company the user happens to be
        # browsing in: otherwise a step belonging to company B displays (and
        # is read as) company A's currency.
        for record in self:
            record.currency_id = record.company_id.currency_id or record.env.company.currency_id

    # ------------------------------------------------------------------
    # Amount resolution
    # ------------------------------------------------------------------
    def _order_amount(self, record, currency=None, date=None):
        """Return the amount to test against `amount_value`, expressed in the
        step's own currency.

        Two things happen here:
        * 'Amount Based On' decides between the tax-inclusive and untaxed total;
        * the amount is converted into the step's currency, so a 10,000 USD
          order is no longer compared against a 10,000 QAR threshold as if the
          two numbers were interchangeable.
        """
        self.ensure_one()
        amount = record.amount_untaxed if self.amount_base == 'untaxed' else record.amount_total

        from_currency = currency if currency is not None else record.currency_id
        to_currency = self.currency_id or self.company_id.currency_id
        if not from_currency or not to_currency or from_currency == to_currency:
            return amount
        return from_currency._convert(
            amount, to_currency,
            self.company_id or record.company_id,
            date or fields.Date.context_today(self),
        )

    @api.constrains('sequence')
    def _check_sequence_positive(self):
        for rec in self:
            if rec.sequence < 1:
                raise ValidationError(_(
                    "Approval step sequence must be 1 or greater (0 is "
                    "reserved for 'no approval in progress').\n\n"
                    "Number your steps 10, 20, 30... so you can insert a new "
                    "approval level later without renumbering the others."
                ))

    @api.constrains('type', 'sale_criteria_type', 'amount_operator', 'amount_value',
                     'margin_operator', 'margin_value', 'logic_operator')
    def _check_sale_criteria_required(self):
        for rec in self:
            if rec.type in ('purchase', 'delivery'):
                if not rec.amount_operator:
                    raise ValidationError(_("Please select an Amount operator."))
                continue

            if rec.type != 'sale':
                continue

            if not rec.sale_criteria_type:
                raise ValidationError(_(
                    "Please select whether this Sale approval step is based on Amount, "
                    "Margin, or both."
                ))
            if rec.sale_criteria_type in ('amount', 'both') and not rec.amount_operator:
                raise ValidationError(_("Please select an Amount operator."))
            if rec.sale_criteria_type in ('margin', 'both') and not rec.margin_operator:
                raise ValidationError(_("Please select a Margin operator."))
            if rec.sale_criteria_type == 'both' and not rec.logic_operator:
                raise ValidationError(_(
                    "Please select AND/OR to combine the Amount and Margin conditions."
                ))

    def _matches_sale_order(self, order):
        # Return True if this step's condition applies to the given sale.order.
        self.ensure_one()
        amount_ok = None
        margin_ok = None

        if self.sale_criteria_type in ('amount', 'both'):
            # A blank operator can only come from imported or legacy data (the
            # constraint below covers anything edited through the UI). Treat it
            # as "does not match" rather than raising KeyError mid-confirm,
            # which is what the purchase and delivery matchers already do.
            if not self.amount_operator:
                return False
            amount = self._order_amount(order, date=order.date_order)
            amount_ok = OPERATOR_FUNCS[self.amount_operator](amount, self.amount_value)

        if self.sale_criteria_type in ('margin', 'both'):
            if not self.margin_operator:
                return False
            margin_percent = (order.margin_percent or 0) * 100
            margin_ok = OPERATOR_FUNCS[self.margin_operator](margin_percent, self.margin_value)

        if self.sale_criteria_type == 'both':
            if self.logic_operator == 'and':
                return bool(amount_ok and margin_ok)
            return bool(amount_ok or margin_ok)
        elif self.sale_criteria_type == 'amount':
            return bool(amount_ok)
        else:
            return bool(margin_ok)

    def _matches_purchase_order(self, order):
        """Return True if this step's Amount condition applies to the given
        purchase.order (Purchase steps only ever use the amount condition)."""
        self.ensure_one()
        if not self.amount_operator:
            return False
        amount = self._order_amount(order, date=order.date_order)
        return OPERATOR_FUNCS[self.amount_operator](amount, self.amount_value)

    def _matches_delivery_order(self, picking):
        # Return True if this step's Amount condition applies to the given stock.picking.
        self.ensure_one()
        if not self.amount_operator:
            return False
        sale_order = picking.sale_id
        if not sale_order:
            return False
        amount = self._order_amount(sale_order, date=sale_order.date_order)
        return OPERATOR_FUNCS[self.amount_operator](amount, self.amount_value)

    # ------------------------------------------------------------------
    # Human readable condition
    # ------------------------------------------------------------------
    condition_display = fields.Char(
        string='Condition', compute='_compute_condition_display',
        help="Exactly what this step evaluates. Read it as a sentence: the "
             "order's own figure is always on the left of the operator.")

    @api.depends('type', 'sale_criteria_type', 'amount_operator', 'amount_value',
                 'amount_base', 'logic_operator', 'margin_operator',
                 'margin_value', 'currency_id')
    def _compute_condition_display(self):
        for step in self:
            step.condition_display = step._condition_display()

    def _condition_display(self):
        """Human readable summary of the configured condition.

        Surfaced in the list view so a step that can never match (the classic
        one being "Amount > 50000 AND Margin < 0%") is visible at a glance
        instead of silently doing nothing.
        """
        self.ensure_one()
        currency = self.currency_id.name or ''
        base = _("untaxed") if self.amount_base == 'untaxed' else _("incl. tax")

        def amount_part():
            return _("Amount %(op)s %(value)s %(currency)s (%(base)s)") % {
                'op': self.amount_operator or '?',
                'value': self.amount_value,
                'currency': currency,
                'base': base,
            }

        def margin_part():
            return _("Margin %(op)s %(value)s%%") % {
                'op': self.margin_operator or '?',
                'value': self.margin_value,
            }

        if self.type != 'sale':
            return amount_part()

        parts = []
        if self.sale_criteria_type in ('amount', 'both'):
            parts.append(amount_part())
        if self.sale_criteria_type == 'both':
            parts.append((self.logic_operator or 'and').upper())
        if self.sale_criteria_type in ('margin', 'both'):
            parts.append(margin_part())
        return ' '.join(str(p) for p in parts)


#                       Approval notification helpers

APPROVAL_ACTIVITY_XMLID = 'sale_and_purchase_approvals_steps.mail_activity_data_approval'


def notify_approvers(record, users, extra_note=None):
    """Schedule an Approval activity and notify each user in `users` that
    `record` (a sale.order or purchase.order now in 'to_approve') is
    waiting on them.

    `extra_note` is appended to the activity body; the purchase flow uses it
    to carry the Waiver Category and Justification to the approver, so the
    Director sees why the 3-quotation rule was not met without having to open
    the Waiver tab.
    """
    # Markup, not a plain str: message_post() and Html fields escape str
    # bodies, which would show the tags to the user instead of rendering them.
    # Values substituted through Markup % {...} are escaped automatically, so
    # a document name or a user-typed reason cannot inject markup.
    note = Markup("%s") % (record.env._("%s is waiting for your approval.") % record.display_name)
    if extra_note:
        note = Markup("%s<br/><br/>%s") % (note, extra_note)
    for user in users:
        if not user:
            continue
        record.activity_schedule(
            APPROVAL_ACTIVITY_XMLID,
            user_id=user.id,
            summary=record.env._("Approval Required"),
            note=note,
        )


def notify_requester(record, body):
    """Tell the person who raised the record what just happened.

    Progress through the chain is information, not a task, so the requester
    gets a notification addressed to them rather than an Activity: an Activity
    would sit in their to-do list with nothing for them to actually do.
    Reserved for the stages where they cannot act -- see
    schedule_requester_activity() for the ones where they can.
    """
    user = record._approval_requester()
    if not user or not user.partner_id:
        return
    record.message_post(
        body=body,
        partner_ids=[user.partner_id.id],
        subtype_xmlid='mail.mt_note',
    )


def schedule_requester_activity(record, summary, note):
    """Give the requester an Activity, for the points where the ball is back
    in their court: the record is fully approved, or it was cancelled during approval."""
    user = record._approval_requester()
    if not user:
        return
    record.activity_schedule(
        APPROVAL_ACTIVITY_XMLID,
        user_id=user.id,
        summary=summary,
        note=note,
    )


def approver_names(steps):
    """Readable list of the approvers on `steps`, for notification bodies."""
    names = [name for name in steps.mapped('user_id.name') if name]
    return ', '.join(names) or steps.env._("an approver")


def current_approvers(record):
    """The users whose approval the record is currently waiting on."""
    steps = record._approval_matching_steps().filtered(
        lambda step: step.sequence == record.approval_step_sequence
    )
    return steps.mapped('user_id')


def approval_cancel_role(record):
    """Work out, from who is calling, what kind of cancellation this is.

    An approver refusing a request and a requester pulling their own request
    back are different business events and must not read the same in the
    audit trail.

    Returns 'approver', 'requester', or None when the caller is entitled to
    do neither.
    """
    record.ensure_one()
    if record.env.user.has_group(APPROVAL_GROUP_XMLID):
        return 'approver'
    if record.env.uid in current_approvers(record).ids:
        return 'approver'
    requester = record._approval_requester()
    if requester and record.env.uid == requester.id:
        return 'requester'
    return None


def check_approval_cancel_allowed(record):
    """Same role check, but raising for anyone who has no business here.

    Without this, any internal user with write access could pull a record out
    of an approval chain -- including over RPC, where hiding the button
    achieves nothing.
    """
    role = approval_cancel_role(record)
    if not role:
        raise AccessError(record.env._(
            "You cannot cancel %(record)s while it is waiting for approval.\n\n"
            "Only %(approvers)s (as approver) or %(requester)s (as the person "
            "who raised it) may do that."
        ) % {
            'record': record.display_name,
            'approvers': ', '.join(current_approvers(record).mapped('name')) or record.env._("the configured approver"),
            'requester': record._approval_requester().display_name or record.env._("the requester"),
        })
    return role


def format_cancellation(user, reason):
    return Markup(user.env._(
        "<b>Rejected during approval</b> by %(user)s.<br/>Reason: %(reason)s"
    )) % {'user': user.display_name, 'reason': reason}


def format_withdrawal(user, reason):
    return Markup(user.env._(
        "<b>Withdrawn</b> by %(user)s before the approval completed."
        "<br/>Reason: %(reason)s"
    )) % {'user': user.display_name, 'reason': reason}


def post_approval_cancellation(record, role, approvers, reason):
    """Record the cancellation and tell whoever was left waiting.

    An approver's refusal goes to the requester as an Activity; a requester's
    withdrawal goes to the approvers who no longer need to act, so nobody is
    left expecting a document that has been pulled.
    """
    user = record.env.user
    if role == 'approver':
        body = format_cancellation(user, reason)
        record.message_post(body=body)
        schedule_requester_activity(
            record, summary=record.env._("Approval Rejected"),
            note=Markup(record.env._("%(record)s was rejected during approval.<br/>%(body)s")) % {
                'record': record.display_name, 'body': body,
            },
        )
        return

    body = format_withdrawal(user, reason)
    record.message_post(body=body)
    partner_ids = [u.partner_id.id for u in approvers if u.partner_id]
    if partner_ids:
        record.message_post(
            body=Markup(record.env._("%(record)s was withdrawn, so it no longer needs "
                          "your approval.<br/>%(body)s")) % {
                'record': record.display_name, 'body': body,
            },
            partner_ids=partner_ids,
            subtype_xmlid='mail.mt_note',
        )


def search_show_approve_button(model, operator, value):
    """`search` implementation for the `show_approve_button` field.

    Makes "waiting on me" expressible as a domain, so the My Approvals menus
    can list the records a user actually has to approve. They used to filter
    on user_id, which is the Salesperson / Buyer -- not the approver -- so an
    approver opening that menu saw an empty list.

    The candidate set is only the records currently in 'to_approve', which is
    small, so evaluating the compute over it is cheap.
    """
    if operator not in ('=', '!='):
        raise UserError(model.env._("Unsupported operator %s for 'show_approve_button'.") % operator)
    candidates = model.search([('state', '=', 'to_approve')])
    matching = candidates.filtered(lambda rec: rec.show_approve_button)
    positive = (operator == '=') == bool(value)
    return [('id', 'in' if positive else 'not in', matching.ids)]


def check_approver_allowed(record, steps):
    """Server-side authorisation for an Approve click.

    The Approve buttons are only hidden through `show_approve_button`, which
    is a UI modifier: any internal user could otherwise call button_approve()
    over RPC and approve their own order. Every approve entry point must run
    this first.

    Returns True when the caller is approving as a member of the Approval
    group (which bypasses the remaining steps), False for a normal approver.
    """
    record.ensure_one()
    if record.state != 'to_approve':
        raise UserError(record.env._(
            "%s is not waiting for approval."
        ) % record.display_name)
    if record.env.user.has_group(APPROVAL_GROUP_XMLID):
        return True
    current_steps = steps.filtered(
        lambda step: step.sequence == record.approval_step_sequence
    )
    if record.env.uid not in current_steps.mapped('user_id').ids:
        raise AccessError(record.env._(
            "You are not an approver for the current step of %(record)s.\n\n"
            "Approval step %(sequence)s must be approved by: %(approvers)s."
        ) % {
            'record': record.display_name,
            'sequence': record.approval_step_sequence,
            'approvers': ', '.join(
                current_steps.mapped('user_id.name')) or record.env._("nobody (no approval step is configured for this step number)"),
        })
    return False


def close_approval_activities(record, user=None):
    """Mark `user`'s pending Approval activity on `record` as done. If no
    user is given, remove any remaining Approval activities on the record
    (used once the approval chain is finished/bypassed/cancelled)."""
    if user:
        record.activity_feedback([APPROVAL_ACTIVITY_XMLID], user_id=user.id)
    else:
        record.activity_unlink([APPROVAL_ACTIVITY_XMLID])