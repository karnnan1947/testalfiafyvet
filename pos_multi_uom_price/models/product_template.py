# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    multi_uom_price_ids = fields.One2many('product.tmpl.multi.uom.price', 'product_tmpl_id', string='UOM Prices')
