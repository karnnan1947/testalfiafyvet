# -*- coding: utf-8 -*-
from odoo import fields, models

from .selections import LOT_SOURCING_TYPES


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Set from the lots delivered (sales) or sold (POS); an accountant can
    # choose it on a manual customer invoice line.
    sourcing_type = fields.Selection(
        LOT_SOURCING_TYPES, string="Sourcing", index=True, copy=True,
        help="Official Partner / Outside Supplier of the goods invoiced on "
             "this line. Used by the Sourcing Margin Analysis.")
    sourcing_unit_cost = fields.Float(
        string="Sourcing Unit Cost", digits='Product Price', copy=True, readonly=True,
        help="Purchase cost of one product unit of the lots invoiced on this "
             "line (company currency). Empty on manual lines: the product cost "
             "is used instead.")
