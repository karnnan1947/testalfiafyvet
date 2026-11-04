# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Field from alfiafy_purchase (Sales & Purchase tab of the vendor).
    # New vendors are Outside suppliers unless set to Official Partner.
    vendor_sourcing_type = fields.Selection(default='outside')
