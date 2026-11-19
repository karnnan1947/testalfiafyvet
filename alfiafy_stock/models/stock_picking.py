# -*- coding: utf-8 -*-
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

TRANSIT_DELAY_HOURS = 48
DELAY_ACTIVITY_SUMMARY = "Transfer in transit for more than 48 hours"


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    transfer_status = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('transit', 'In Transit'),
        ('done', 'Received'),
    ], string="Transfer Status", default='draft', copy=False, tracking=True, index=True,
        help="Internal transfer progress: Draft (requested), To Approve (waiting for the "
             "Internal Transfer approval steps), Approved, In Transit (dispatched), "
             "Received (confirmed by the branch).")
    dispatch_date = fields.Datetime(string="Dispatch Date", copy=False, readonly=True, tracking=True)
    is_delayed = fields.Boolean(
        string="Delayed", compute='_compute_is_delayed',
        help="In transit for more than 48 hours.")
    can_dispatch_transfer = fields.Boolean(
        string="Can Approve / Dispatch Transfer",
        compute='_compute_can_dispatch_transfer',
        help="True if the current user is a Stock Manager, belongs to the dispatching "
             "warehouse or is an approver of the transfer's Internal Transfer approval steps.")
    internal_approval_required = fields.Boolean(
        string="Approval Steps Apply",
        compute='_compute_internal_approval_required',
        help="An Internal Transfer approval step applies to this transfer: it goes "
             "through Submit for Approval instead of the direct Approve button.")

    @api.depends('picking_type_code', 'location_id')
    @api.depends_context('uid')
    def _compute_can_dispatch_transfer(self):
        for picking in self:
            picking.can_dispatch_transfer = (
                picking.picking_type_code == 'internal' and picking._is_transfer_dispatcher())

    @api.depends('picking_type_code', 'location_id')
    def _compute_internal_approval_required(self):
        for picking in self:
            picking.internal_approval_required = bool(picking._get_matching_internal_transfer_steps())

    def _is_transfer_dispatcher(self):
        """The current user may approve (direct flow) or dispatch this transfer:
        a Stock Manager, the storekeeper of the dispatching warehouse, or an
        approver of its Internal Transfer approval steps."""
        self.ensure_one()
        user = self.env.user
        if user.has_group('stock.group_stock_manager'):
            return True
        src_wh = self.location_id.warehouse_id
        if src_wh and user.property_warehouse_id == src_wh:
            return True
        return user in self._get_matching_internal_transfer_steps().user_id

    def _check_can_dispatch_transfer(self):
        for picking in self:
            if not picking._is_transfer_dispatcher():
                src_wh = picking.location_id.warehouse_id
                raise AccessError(self.env._(
                    "Only the storekeeper of %(wh)s, an approver of the transfer or a Stock "
                    "Manager can approve or dispatch %(name)s.",
                    wh=src_wh.name if src_wh else self.env._("the dispatching warehouse"),
                    name=picking.name,
                ))

    @api.depends('transfer_status', 'dispatch_date')
    def _compute_is_delayed(self):
        limit = fields.Datetime.now() - timedelta(hours=TRANSIT_DELAY_HOURS)
        for picking in self:
            picking.is_delayed = bool(
                picking.transfer_status == 'transit' and picking.dispatch_date and picking.dispatch_date < limit)

    def _check_internal_open(self):
        for picking in self:
            if picking.picking_type_code != 'internal':
                raise UserError(self.env._("%s is not an internal transfer.", picking.name))
            if picking.state in ('done', 'cancel'):
                raise UserError(self.env._("%s is already done or cancelled.", picking.name))

    def action_approve_transfer(self):
        """Storekeeper review: Draft -> Approved.

        Only used while no Internal Transfer approval step applies to the
        transfer. Once one does, the transfer goes through its approval chain
        (sale_and_purchase_approvals_steps): this entry point then submits it
        for approval instead of approving it."""
        self._check_internal_open()
        with_steps = self.filtered(lambda p: p._get_matching_internal_transfer_steps())
        if with_steps:
            with_steps.action_submit_internal_transfer_approval()
        direct = self - with_steps
        if not direct:
            return True
        direct._check_can_dispatch_transfer()
        for picking in direct:
            if picking.transfer_status != 'draft':
                raise UserError(self.env._("Only a draft transfer can be approved (%s).", picking.name))
        drafts = direct.filtered(lambda p: p.state == 'draft')
        if drafts:
            drafts.action_confirm()
        direct.write({'transfer_status': 'approved'})
        return True

    def action_dispatch_goods(self):
        """Approved -> In Transit; records the dispatch date."""
        self._check_internal_open()
        self._check_can_dispatch_transfer()
        for picking in self:
            if picking.transfer_status != 'approved':
                raise UserError(self.env._("Approve %s before dispatching it.", picking.name))
            if picking.approval_status != 'approved' and picking._get_matching_internal_transfer_steps():
                raise UserError(self.env._(
                    "%s must be approved through its approval steps before it can be "
                    "dispatched: click Submit for Approval.", picking.name))
            if picking.state != 'assigned':
                picking.sudo().action_assign()
            if picking.state != 'assigned':
                raise UserError(self.env._(
                    "%s cannot be dispatched: the goods are not available in %s.",
                    picking.name, picking.location_id.display_name))
        self.write({'transfer_status': 'transit', 'dispatch_date': fields.Datetime.now()})
        return True

    # ------------------------------------------------------------------
    # Approval steps (sale_and_purchase_approvals_steps) integration
    # ------------------------------------------------------------------
    @api.depends('transfer_status')
    def _compute_can_submit_internal_approval(self):
        super()._compute_can_submit_internal_approval()
        for picking in self:
            if picking.transfer_status not in ('draft', 'approved'):
                picking.can_submit_internal_approval = False

    def action_submit_internal_transfer_approval(self):
        """Draft -> To Approve."""
        for picking in self:
            if picking.picking_type_code == 'internal' and picking.transfer_status not in ('draft', 'approved'):
                raise UserError(self.env._(
                    "%s is already submitted, dispatched or received.", picking.name))
        res = super().action_submit_internal_transfer_approval()
        self.filtered(
            lambda p: p.picking_type_code == 'internal' and p.approval_status == 'to_approve'
        ).write({'transfer_status': 'to_approve'})
        return res

    def _finish_internal_transfer_approval(self, picking):
        """Final approval: To Approve -> Approved, ready for Dispatch Goods."""
        picking.transfer_status = 'approved'
        return super()._finish_internal_transfer_approval(picking)

    def _internal_transfer_approved_activity(self):
        """Once approved, the next step is Dispatch Goods: the follow-up goes to
        the final approver, who may dispatch it."""
        self.ensure_one()
        return (
            self.env._("Approved - Dispatch Goods"),
            Markup(self.env._(
                "%(record)s is fully approved.<br/>Click Dispatch Goods when the goods "
                "leave %(src)s (Print > Delivery Slip for the driver)."
            )) % {'record': self.display_name, 'src': self.location_id.display_name},
            self.env.user,
        )

    def _needs_internal_transfer_approval(self):
        """Dispatch Goods already requires the approval, so a transfer in
        transit (or received) is never sent back to it, including one that was
        dispatched before the approval steps were configured."""
        if self.transfer_status in ('transit', 'done'):
            return False
        return super()._needs_internal_transfer_approval()

    def action_cancel(self):
        """A transfer rejected or withdrawn during approval is cancelled: it is
        no longer waiting for approval."""
        pending = self.filtered(
            lambda p: p.picking_type_code == 'internal' and p.transfer_status == 'to_approve')
        res = super().action_cancel()
        pending.filtered(lambda p: p.state == 'cancel').write({'transfer_status': 'draft'})
        return res

    def button_validate(self):
        """Block direct validation of internal transfers before dispatch."""
        not_dispatched = self.filtered(
            lambda p: p.picking_type_code == 'internal' and p.transfer_status != 'transit'
        )
        if not_dispatched:
            raise UserError(self.env._(
                "Internal transfer %s cannot be validated directly. "
                "It must be approved and dispatched first, then confirmed via Confirm Receipt.",
                ", ".join(not_dispatched.mapped('name')),
            ))
        return super().button_validate()

    def action_confirm_receipt(self):
        """In Transit -> Received: validates the transfer, moving the stock into
        the destination branch."""
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(self.env._("Only Inventory users can confirm receipt of an internal transfer."))
        self._check_internal_open()
        for picking in self:
            if picking.transfer_status != 'transit':
                raise UserError(self.env._("%s has not been dispatched yet.", picking.name))
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                if move.uom_id.is_zero(move.quantity):
                    move.quantity = move.product_uom_qty
                move.picked = True
        # Validate with sudo() so branch users restricted to their own warehouse's
        # quants can still receive stock dispatched from the main warehouse.
        return self.sudo().button_validate()

    def _action_done(self):
        res = super()._action_done()
        self.filtered(lambda p: p.picking_type_code == 'internal' and p.state == 'done').write(
            {'transfer_status': 'done'})
        return res

    @api.model
    def _cron_check_delayed_transfers(self):
        """Daily: an urgent activity for the dispatching warehouse and the
        receiving branch on transfers in transit for more than 48 hours."""
        limit = fields.Datetime.now() - timedelta(hours=TRANSIT_DELAY_HOURS)
        pickings = self.search([
            ('picking_type_code', '=', 'internal'),
            ('transfer_status', '=', 'transit'),
            ('state', 'not in', ('done', 'cancel')),
            ('dispatch_date', '<', limit),
        ])
        todo = self.env.ref('mail.mail_activity_data_todo')
        managers = self.env.ref('stock.group_stock_manager').all_user_ids.filtered(
            lambda u: u.active and not u.share and u.id != self.env.ref('base.user_root').id)
        Users = self.env['res.users']
        for picking in pickings:
            users = Users
            for warehouse in (picking.location_id.warehouse_id, picking.location_dest_id.warehouse_id):
                if warehouse:
                    users |= Users.with_company(warehouse.company_id).search([
                        ('property_warehouse_id', '=', warehouse.id), ('share', '=', False)])
            if not users:
                users = managers
            open_users = picking.activity_ids.filtered(
                lambda a: a.activity_type_id == todo and a.summary == DELAY_ACTIVITY_SUMMARY).user_id
            hours = int((fields.Datetime.now() - picking.dispatch_date).total_seconds() // 3600)
            for user in users - open_users:
                picking.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=DELAY_ACTIVITY_SUMMARY,
                    note=self.env._(
                        "%(name)s (%(src)s to %(dst)s) was dispatched on %(date)s, %(hours)s hours ago, "
                        "and is not confirmed as received yet. Please follow up.",
                        name=picking.name, src=picking.location_id.display_name,
                        dst=picking.location_dest_id.display_name,
                        date=fields.Datetime.to_string(picking.dispatch_date), hours=hours),
                    user_id=user.id,
                )
        return pickings
