# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

TRANSIT_DELAY_HOURS = 48
DELAY_ACTIVITY_SUMMARY = "Transfer in transit for more than 48 hours"


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    transfer_status = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('transit', 'In Transit'),
        ('done', 'Received'),
    ], string="Transfer Status", default='draft', copy=False, tracking=True, index=True,
        help="Internal transfer progress: Draft (requested), Approved (reviewed by the "
             "storekeeper), In Transit (dispatched), Received (confirmed by the branch).")
    dispatch_date = fields.Datetime(string="Dispatch Date", copy=False, readonly=True, tracking=True)
    is_delayed = fields.Boolean(
        string="Delayed", compute='_compute_is_delayed',
        help="In transit for more than 48 hours.")

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
        """Storekeeper review: Draft -> Approved."""
        self._check_internal_open()
        for picking in self:
            if picking.transfer_status != 'draft':
                raise UserError(self.env._("Only a draft transfer can be approved (%s).", picking.name))
        drafts = self.filtered(lambda p: p.state == 'draft')
        if drafts:
            drafts.action_confirm()
        self.write({'transfer_status': 'approved'})
        return True

    def action_dispatch_goods(self):
        """Approved -> In Transit; records the dispatch date."""
        self._check_internal_open()
        for picking in self:
            if picking.transfer_status != 'approved':
                raise UserError(self.env._("Approve %s before dispatching it.", picking.name))
            if picking.state != 'assigned':
                picking.action_assign()
            if picking.state != 'assigned':
                raise UserError(self.env._(
                    "%s cannot be dispatched: the goods are not available in %s.",
                    picking.name, picking.location_id.display_name))
        self.write({'transfer_status': 'transit', 'dispatch_date': fields.Datetime.now()})
        return True

    def action_confirm_receipt(self):
        """In Transit -> Received: validates the transfer, moving the stock into
        the destination branch."""
        self._check_internal_open()
        for picking in self:
            if picking.transfer_status != 'transit':
                raise UserError(self.env._("%s has not been dispatched yet.", picking.name))
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                if move.uom_id.is_zero(move.quantity):
                    move.quantity = move.product_uom_qty
                move.picked = True
        return self.button_validate()

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
