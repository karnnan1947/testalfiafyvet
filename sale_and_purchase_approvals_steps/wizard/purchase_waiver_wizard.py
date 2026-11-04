# -*- coding: utf-8 -*-

from markupsafe import Markup

from odoo import fields, models, _
from odoo.exceptions import UserError

# Shared selection list, reused on the wizard and on the Purchase Order
# (see models/purchase.py) so both fields always stay in sync.
WAIVER_CATEGORY_SELECTION = [
    ('sole_supplier', 'Sole Supplier'),
    ('market_limitation', 'Market Limitation'),
    ('proprietary_oem', 'Proprietary / OEM'),
    ('strategic_vendor', 'Strategic Vendor'),
    ('emergency_purchase', 'Emergency Purchase'),
]


class PurchaseWaiverWizard(models.TransientModel):
    _name = 'purchase.waiver.wizard'
    _description = "Purchase Approval Waiver Form"

    purchase_order_id = fields.Many2one(
        'purchase.order', string="Purchase Order",
        required=True, readonly=True)
    alternative_po_count = fields.Integer(
        string="Alternative POs Linked",
        related='purchase_order_id.alternative_po_count',
        readonly=True)

    # NOTE: intentionally NOT required=True here; both fields are made
    # mandatory only at the view level (required="1" in the XML form),
    # and re-checked defensively in action_submit below.
    waiver_category = fields.Selection(
        selection=WAIVER_CATEGORY_SELECTION,
        string="Waiver Category")
    justification = fields.Html(string="Justification")

    def action_submit(self):
        """Record the waiver on the request and route it to the approver.

        The waiver is captured from the Procurement User at submission time,
        not from the approver, so the Director receives the request with the
        category and justification already attached.
        """
        self.ensure_one()
        if not self.waiver_category or not self.justification:
            raise UserError(_(
                "Please select a Waiver Category and provide a "
                "Justification before submitting."))

        order = self.purchase_order_id
        order.write({
            'waiver_applied': True,
            'waiver_category': self.waiver_category,
            'waiver_justification': self.justification,
        })
        order.message_post(body=Markup(_(
            "<b>Waiver applied</b> by %(user)s: fewer than 3 alternative "
            "supplier quotations were obtained.<br/>Category: "
            "<b>%(category)s</b><br/>Justification: %(justification)s"
        )) % {
            'user': self.env.user.display_name,
            'category': dict(WAIVER_CATEGORY_SELECTION).get(
                self.waiver_category, self.waiver_category),
            # Already-sanitised HTML from an Html field.
            'justification': Markup(self.justification or ''),
        })
        order.with_context(skip_waiver_check=True).action_send_for_approval()
        return {'type': 'ir.actions.act_window_close'}

    def action_cancel(self):
        """Simply close the wizard. No waiver is recorded and the request is
        left in its current stage (i.e. NOT sent for approval)."""
        return {'type': 'ir.actions.act_window_close'}