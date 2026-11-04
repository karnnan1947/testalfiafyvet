# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

REQUISITION_STATES = [
    ('draft', 'Draft'),
    ('to_approve', 'Waiting Approval'),
    ('approved', 'Approved'),
    ('done', 'Done'),
    ('cancel', 'Cancelled'),
]

APPROVER_GROUP = 'purchase.group_purchase_manager'


class MaterialPurchaseRequisition(models.Model):
    """Internal material requisition raised by a branch / department before
    an RFQ (BRD 1.4 #4, customization #13)."""
    _name = 'material.purchase.requisition'
    _description = 'Material Purchase Requisition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string="Reference", required=True, readonly=True, copy=False, default='/', index='trigram')
    state = fields.Selection(
        REQUISITION_STATES, string="Status", default='draft', required=True,
        readonly=True, copy=False, tracking=True, index=True)
    requested_by_id = fields.Many2one(
        'res.users', string="Requested By", required=True, tracking=True,
        default=lambda self: self.env.user, domain=[('share', '=', False)])
    request_date = fields.Date(
        string="Request Date", required=True, default=fields.Date.context_today)
    required_date = fields.Date(string="Required By", tracking=True)
    company_id = fields.Many2one(
        'res.company', string="Company", required=True, default=lambda self: self.env.company)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string="Branch / Warehouse", required=True,
        default=lambda self: self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1),
        domain="[('company_id', '=', company_id)]",
        help="Branch or warehouse the goods are requested for; the generated "
             "RFQs receive into this warehouse.")
    vendor_id = fields.Many2one(
        'res.partner', string="Preferred Vendor",
        help="Used for lines without their own vendor. Otherwise the product's "
             "Supplier, then its first vendor pricelist entry, is used.")
    purpose = fields.Text(string="Purpose / Notes")
    line_ids = fields.One2many(
        'material.purchase.requisition.line', 'requisition_id', string="Products", copy=True)
    approved_by_id = fields.Many2one('res.users', string="Approved By", readonly=True, copy=False)
    approved_date = fields.Datetime(string="Approved On", readonly=True, copy=False)
    purchase_ids = fields.One2many('purchase.order', 'material_requisition_id', string="Purchase Orders")
    purchase_count = fields.Integer(compute='_compute_purchase_count', string="RFQ Count")

    @api.depends('purchase_ids')
    def _compute_purchase_count(self):
        for req in self:
            req.purchase_count = len(req.purchase_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'material.purchase.requisition') or '/'
        return super().create(vals_list)

    def unlink(self):
        if self.filtered(lambda req: req.state not in ('draft', 'cancel')):
            raise UserError(_("Only draft or cancelled requisitions can be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow: Draft > Waiting Approval > Approved > Done
    # ------------------------------------------------------------------
    def _check_approver(self):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise UserError(_("Only a Purchase Administrator can approve or reject material requisitions."))

    def action_submit(self):
        for req in self:
            if req.state != 'draft':
                raise UserError(_("%s is not in Draft.", req.name))
            if not req.line_ids:
                raise UserError(_("Add at least one product to %s before submitting it.", req.name))
        self.write({'state': 'to_approve'})
        approvers = self.env.ref(APPROVER_GROUP).all_user_ids.filtered(lambda u: not u.share)
        for req in self:
            req.message_post(body=_("Submitted for approval by %s.", self.env.user.display_name))
            for user in approvers[:5]:
                req.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_("Approve material requisition"),
                    note=_("%(req)s raised by %(user)s is waiting for your approval.",
                           req=req.name, user=req.requested_by_id.display_name))
        return True

    def action_approve(self):
        self._check_approver()
        for req in self:
            if req.state != 'to_approve':
                raise UserError(_("%s is not waiting for approval.", req.name))
        self.write({
            'state': 'approved',
            'approved_by_id': self.env.uid,
            'approved_date': fields.Datetime.now(),
        })
        self.activity_feedback(['mail.mail_activity_data_todo'])
        return True

    def action_reject(self):
        self._check_approver()
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self.write({'state': 'cancel'})
        return True

    def action_cancel(self):
        if self.filtered(lambda req: req.state == 'done'):
            raise UserError(_("A requisition that already generated purchase orders cannot be cancelled."))
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self.write({'state': 'cancel'})
        return True

    def action_reset_draft(self):
        self.write({'state': 'draft', 'approved_by_id': False, 'approved_date': False})
        return True

    # ------------------------------------------------------------------
    # RFQ generation
    # ------------------------------------------------------------------
    def _prepare_purchase_order_vals(self, vendor, lines):
        self.ensure_one()
        vals = {
            'partner_id': vendor.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'material_requisition_id': self.id,
            # Requisitions are always branch / department local purchases.
            'purchase_type': 'local',
            'order_line': [
                fields.Command.create(line._prepare_purchase_order_line_vals())
                for line in lines
            ],
        }
        if self.warehouse_id.in_type_id:
            vals['picking_type_id'] = self.warehouse_id.in_type_id.id
        if self.required_date:
            vals['date_planned'] = fields.Datetime.to_datetime(self.required_date)
        return vals

    def action_create_purchase_order(self):
        """Generate one draft Local Purchase RFQ per vendor and close the
        requisition."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Only an approved requisition can generate purchase orders."))
        by_vendor = defaultdict(lambda: self.env['material.purchase.requisition.line'])
        missing = []
        for line in self.line_ids:
            vendor = line._get_vendor()
            if not vendor:
                missing.append(line.product_id.display_name)
                continue
            by_vendor[vendor] |= line
        if missing:
            raise UserError(_(
                "No vendor found for:\n%s\n\nSet a Preferred Vendor on the "
                "requisition or on the line, or a Supplier on the product.",
                "\n".join("- %s" % name for name in missing)))
        orders = self.env['purchase.order']
        for vendor, lines in by_vendor.items():
            orders |= self.env['purchase.order'].create(self._prepare_purchase_order_vals(vendor, lines))
        self.write({'state': 'done'})
        self.message_post(body=_("Generated: %s", ", ".join(orders.mapped('name'))))
        return self.action_view_purchase_orders()

    def action_view_purchase_orders(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _("Purchase Orders"),
            'res_model': 'purchase.order',
            'domain': [('material_requisition_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'create': False},
        }
        if len(self.purchase_ids) == 1:
            action.update(view_mode='form', res_id=self.purchase_ids.id)
        return action


class MaterialPurchaseRequisitionLine(models.Model):
    _name = 'material.purchase.requisition.line'
    _description = 'Material Purchase Requisition Line'
    _order = 'requisition_id, sequence, id'

    requisition_id = fields.Many2one(
        'material.purchase.requisition', string="Requisition", required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='requisition_id.company_id', store=True)
    state = fields.Selection(related='requisition_id.state')
    product_id = fields.Many2one(
        'product.product', string="Product", required=True,
        domain=[('purchase_ok', '=', True)])
    description = fields.Char(string="Description")
    product_qty = fields.Float(string="Quantity", required=True, default=1.0, digits='Product Unit')
    uom_id = fields.Many2one(
        'uom.uom', string="Unit", compute='_compute_uom_id', store=True, readonly=False)
    vendor_id = fields.Many2one('res.partner', string="Vendor")
    qty_available = fields.Float(
        string="On Hand", related='product_id.qty_available', digits='Product Unit')

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    def _get_vendor(self):
        """Line vendor > requisition preferred vendor > product Supplier
        (alfiafy_product_base) > first vendor pricelist entry."""
        self.ensure_one()
        return (
            self.vendor_id
            or self.requisition_id.vendor_id
            or self.product_id.supplier_id
            or self.product_id.seller_ids[:1].partner_id
        )

    def _prepare_purchase_order_line_vals(self):
        self.ensure_one()
        vals = {
            'product_id': self.product_id.id,
            'product_qty': self.product_qty,
            'uom_id': (self.uom_id or self.product_id.uom_id).id,
        }
        if self.description:
            vals['name'] = self.description
        return vals
