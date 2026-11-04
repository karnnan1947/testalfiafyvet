# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    block_fractional_return = fields.Boolean(
        string='Block Fractional Returns',
        help="On: a line sold per pack / box can only be returned in whole packs. "
             "Off: on the Orders screen the cashier can press \"Return Units\" and "
             "return single pieces of a pack, refunded at the price paid per piece "
             "(Pack of 6 sold at 300.00 -> 50.00 per piece).")
