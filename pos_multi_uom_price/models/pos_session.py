# -*- coding: utf-8 -*-
# © 2025 ehuerta _at_ ixer.mx
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).

from odoo import api, models


class PosSession(models.Model):
    _inherit = 'pos.session'

    @api.model
    def _load_pos_data_models(self, config):
        data = super()._load_pos_data_models(config)
        # All rows are loaded (no domain): products are loaded lazily and a
        # product fetched later must still find its unit prices.
        data += ['product.tmpl.multi.uom.price', 'product.multi.uom.price']
        return data
