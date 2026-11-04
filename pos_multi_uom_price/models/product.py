# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    multi_uom_price_ids = fields.One2many('product.multi.uom.price', 'product_id', string='UOM Prices')
