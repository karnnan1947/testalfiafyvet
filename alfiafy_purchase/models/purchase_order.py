# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .selections import PURCHASE_TYPES, SHIPMENT_STATUSES, SOURCING_TYPES


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # ------------------------------------------------------------------
    # Classification (pulled from the vendor, editable on the order)
    # ------------------------------------------------------------------
    purchase_type = fields.Selection(
        PURCHASE_TYPES, string="Purchase Type",
        compute='_compute_purchase_type', store=True, readonly=False,
        precompute=True, tracking=True, index=True,
        help="Local Purchase (main warehouse or a branch buying locally) or "
             "Import Shipment. Defaults from the vendor.")
    sourcing_type = fields.Selection(
        SOURCING_TYPES, string="Sourcing",
        compute='_compute_sourcing_type', store=True, readonly=False,
        precompute=True, tracking=True, index=True,
        help="Official Partner or Outside Supplier. Carried to the receipt "
             "and stamped on the lots received.")

    # ------------------------------------------------------------------
    # Import shipment tracking (BRD 1.4 #3)
    # ------------------------------------------------------------------
    container_no = fields.Char(string="Container No.", tracking=True, copy=False)
    bl_awb_no = fields.Char(string="B/L / AWB No.", tracking=True, copy=False,
                            help="Bill of Lading or Air Waybill number")
    tracking_no = fields.Char(string="Tracking No.", copy=False)
    shipping_line = fields.Char(string="Shipping Line / Forwarder")
    port_of_entry = fields.Char(string="Port of Entry")
    etd = fields.Date(string="ETD", tracking=True, copy=False,
                      help="Estimated Time of Departure")
    eta = fields.Date(string="ETA", tracking=True, copy=False,
                      help="Estimated Time of Arrival")
    shipment_status = fields.Selection(
        SHIPMENT_STATUSES, string="Shipment Status", tracking=True, copy=False)

    # ------------------------------------------------------------------
    # Material requisition link
    # ------------------------------------------------------------------
    # Not 'requisition_id': purchase_requisition already uses that name
    # for Purchase Agreements.
    material_requisition_id = fields.Many2one(
        'material.purchase.requisition', string="Material Requisition",
        copy=False, readonly=True, index='btree_not_null')

    # Two separate computes on purpose: a value given explicitly at creation
    # (e.g. purchase_type='local' from a material requisition) must not stop
    # the other one from being pulled from the vendor.
    @api.depends('partner_id')
    def _compute_purchase_type(self):
        for order in self:
            vendor = order.partner_id.commercial_partner_id
            order.purchase_type = vendor.default_purchase_type or order.purchase_type or 'local'

    @api.depends('partner_id')
    def _compute_sourcing_type(self):
        for order in self:
            order.sourcing_type = order.partner_id.commercial_partner_id.vendor_sourcing_type or False

    @api.constrains('etd', 'eta')
    def _check_etd_before_eta(self):
        for order in self:
            if order.etd and order.eta and order.eta < order.etd:
                raise ValidationError(_("The ETA of %s cannot be before its ETD.", order.display_name))

    def _check_sourcing_type_set(self):
        missing = self.filtered(lambda order: not order.sourcing_type)
        if missing:
            raise UserError(_(
                "Set the Sourcing (Official Partner / Outside Supplier) on the "
                "following purchase order(s) first, so it can be carried to the "
                "receipt and the lots:\n\n%s",
                "\n".join("- %s" % order.display_name for order in missing),
            ))

    def action_send_for_approval(self):
        self._check_sourcing_type_set()
        return super().action_send_for_approval()

    def button_confirm(self):
        self._check_sourcing_type_set()
        return super().button_confirm()

    def action_view_requisition(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'material.purchase.requisition',
            'res_id': self.material_requisition_id.id,
            'view_mode': 'form',
        }
