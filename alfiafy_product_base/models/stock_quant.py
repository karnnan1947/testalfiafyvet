# -*- coding: utf-8 -*-
from odoo import fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    # Stored so that on-hand stock can be grouped / filtered by them
    # (BRD 1.5 #8: "filter and group available quantities by manufacturer
    # and by supplier").
    product_manufacturer_id = fields.Many2one(
        related='product_id.product_tmpl_id.manufacturer_id',
        string="Manufacturer", store=True, index='btree_not_null')
    product_supplier_id = fields.Many2one(
        related='product_id.product_tmpl_id.supplier_id',
        string="Supplier", store=True, index='btree_not_null')
