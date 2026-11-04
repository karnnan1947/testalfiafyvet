# -*- coding: utf-8 -*-
from odoo import api, models

# Cost / margin values that are replaced by 0.0 for non-authorised users.
PRODUCT_COST_FIELDS = (
    "standard_price", "avg_cost", "total_value",
    # product_margin analysis
    "total_cost", "normal_cost", "expected_margin", "total_margin",
    "expected_margin_rate", "total_margin_rate", "purchase_avg_price",
    "purchase_gap",
)
# Additional product_margin figures only removed from export / filters / measures.
PRODUCT_SCHEMA_FIELDS = (
    "sales_gap", "turnover", "sale_expected", "sale_avg_price",
    "sale_num_invoiced", "purchase_num_invoiced",
)


class ProductTemplate(models.Model):
    _name = "product.template"
    _inherit = ["product.template", "restricted.cost.mixin"]

    _restricted_cost_fields = ("standard_price",)
    _restricted_cost_schema_fields = PRODUCT_COST_FIELDS + PRODUCT_SCHEMA_FIELDS


class ProductProduct(models.Model):
    _name = "product.product"
    _inherit = ["product.product", "restricted.cost.mixin"]

    _restricted_cost_fields = PRODUCT_COST_FIELDS
    _restricted_cost_schema_fields = PRODUCT_SCHEMA_FIELDS

    @api.model
    def _load_pos_data_read(self, records, config):
        """POS loads products through its own reader: make sure the cost that
        travels to the POS frontend is redacted as well."""
        read_records = super()._load_pos_data_read(records, config)
        if self._is_cost_restricted():
            for product in read_records:
                if "standard_price" in product:
                    product["standard_price"] = 0.0
        return read_records
