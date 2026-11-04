# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .selections import PURCHASE_TYPES, SOURCING_TYPES


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_sourcing_type = fields.Selection(
        SOURCING_TYPES, string="Vendor Sourcing",
        help="Official Partner (inside supplier) or Outside local supplier. "
             "Copied to new purchase orders, their receipts and the lots "
             "received, so margins can be compared by source.")
    default_purchase_type = fields.Selection(
        PURCHASE_TYPES, string="Default Purchase Type",
        help="Purchase type proposed on new purchase orders for this vendor.")

    @api.model
    def _commercial_fields(self):
        # Contacts of a vendor company follow the company's classification.
        return super()._commercial_fields() + ['vendor_sourcing_type', 'default_purchase_type']
