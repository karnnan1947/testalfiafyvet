# -*- coding: utf-8 -*-
from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_domain_locations(self):
        """Scope On Hand / Reporting -> Stock totals to the warehouses the user
        is allowed to see (Default Warehouse + Additional Visible Warehouses),
        unless the user has 'View All Branches Stock' (or Inventory Manager), or
        internal code explicitly passes a warehouse/location in context."""
        if (
            not self.env.su
            and not self.env.context.get('location')
            and not self.env.context.get('search_location')
            and not self.env.context.get('warehouse_id')
            and not self.env.context.get('search_warehouse')
        ):
            allowed_wh_ids = self.env.user._get_visible_stock_warehouse_ids()
            if allowed_wh_ids is not None:
                if not allowed_wh_ids:
                    return self._get_domain_locations_new([])
                return super(
                    ProductProduct, self.with_context(warehouse_id=allowed_wh_ids)
                )._get_domain_locations()
        return super()._get_domain_locations()
