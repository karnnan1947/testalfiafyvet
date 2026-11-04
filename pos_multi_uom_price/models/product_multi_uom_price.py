# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class UomPriceMixin(models.AbstractModel):
    """Shared rules of a "price per unit of measure" row.

    A row gives the price of ONE unit of ``uom_id`` (e.g. one "Box of 10").
    The product's own unit keeps its normal sales price / pricelist, so a row
    on it is refused, and the unit must convert to the product's unit
    (same reference unit), otherwise stock could not be moved in it.
    """
    _name = 'pos.uom.price.mixin'
    _description = 'POS price per unit of measure (mixin)'

    uom_id = fields.Many2one('uom.uom', string="Unit of Measure", required=True)
    price = fields.Float('Price', required=True, digits='Product Price')

    def _get_product_uom(self):
        raise NotImplementedError

    @api.constrains('uom_id', 'price')
    def _check_uom_price(self):
        for rec in self:
            product_uom = rec._get_product_uom()
            if not product_uom:
                continue
            if rec.uom_id == product_uom:
                raise ValidationError(self.env._(
                    "%(uom)s is the product's own unit: its price is the sales price "
                    "of the product. Only add other units (packs, boxes...) here.",
                    uom=rec.uom_id.name))
            if not rec.uom_id._has_common_reference(product_uom):
                raise ValidationError(self.env._(
                    "%(uom)s cannot be converted to %(product_uom)s, the unit of the product.",
                    uom=rec.uom_id.name, product_uom=product_uom.name))
            if rec.price < 0:
                raise ValidationError(self.env._("A unit price cannot be negative."))


class prod_tmpl_multi_uom(models.Model):
    _name = 'product.tmpl.multi.uom.price'
    _inherit = ['pos.uom.price.mixin', 'pos.load.mixin']
    _description = 'Product template multiple uom price'

    product_tmpl_id = fields.Many2one(
        'product.template',
        'Product Template',
        required=True,
        ondelete="cascade",
        index=True,
    )

    _product_tmpl_uom_uniq = models.Constraint(
        'UNIQUE(product_tmpl_id, uom_id)',
        'Each Unit of Measure must be unique per product template.',
    )

    def _get_product_uom(self):
        return self.product_tmpl_id.uom_id

    # ------------------------------------------------------------------
    # Variant rows are kept in sync, so a variant can still override the
    # price on its own form.
    # ------------------------------------------------------------------
    def _sync_price_to_variants(self):
        ProductMultiUom = self.env['product.multi.uom.price']
        variants = self.product_tmpl_id.product_variant_ids
        existing = {
            (row.product_id.id, row.uom_id.id): row
            for row in ProductMultiUom.search([
                ('product_id', 'in', variants.ids),
                ('uom_id', 'in', self.uom_id.ids),
            ])
        }
        to_create = []
        for rec in self:
            for variant in rec.product_tmpl_id.product_variant_ids:
                row = existing.get((variant.id, rec.uom_id.id))
                if row:
                    if row.price != rec.price:
                        row.price = rec.price
                else:
                    to_create.append({
                        'product_id': variant.id,
                        'uom_id': rec.uom_id.id,
                        'price': rec.price,
                    })
        if to_create:
            ProductMultiUom.create(to_create)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_price_to_variants()
        return records

    def write(self, vals):
        if 'uom_id' in vals:
            self._variant_rows().unlink()
        res = super().write(vals)
        self._sync_price_to_variants()
        return res

    def unlink(self):
        self._variant_rows().unlink()
        return super().unlink()

    def _variant_rows(self):
        keys = {(rec.product_tmpl_id.id, rec.uom_id.id) for rec in self}
        rows = self.env['product.multi.uom.price'].search([
            ('product_id', 'in', self.product_tmpl_id.product_variant_ids.ids),
            ('uom_id', 'in', self.uom_id.ids),
        ])
        return rows.filtered(lambda row: (row.product_id.product_tmpl_id.id, row.uom_id.id) in keys)

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'product_tmpl_id', 'uom_id', 'price']


class prod_multi_uom(models.Model):
    _name = 'product.multi.uom.price'
    _inherit = ['pos.uom.price.mixin', 'pos.load.mixin']
    _description = 'Product variant multiple uom price'

    product_id = fields.Many2one(
        'product.product',
        'Product variant',
        required=True,
        ondelete="cascade",
        index=True,
    )

    _product_variant_uom_uniq = models.Constraint(
        'UNIQUE(product_id, uom_id)',
        'Each Unit of Measure must be unique per product variant.',
    )

    def _get_product_uom(self):
        return self.product_id.uom_id

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'product_id', 'uom_id', 'price']
