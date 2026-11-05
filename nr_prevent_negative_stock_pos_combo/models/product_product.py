from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def get_pos_combo_component_stock(self, product_ids, config_id=False):
        """Return the real-time stock of the combo component products.

        The quantity is read in the warehouse of the POS configuration so it
        matches the ``available_quantity`` the POS shows through
        ``get_product_info_pos``.

        :param list product_ids: ids of the ``product.product`` components.
        :param int config_id: id of the ``pos.config`` the session runs on.
        :return: {product_id: {"available_quantity", "is_storable", "display_name"}}
        """
        products = self.browse(product_ids).exists()
        if not products:
            return {}

        config = self.env["pos.config"].browse(config_id).exists() if config_id else False
        warehouse = config.picking_type_id.warehouse_id if config else False
        if warehouse:
            products = products.with_context(warehouse_id=warehouse.id)

        return {
            product.id: {
                "available_quantity": product.qty_available,
                # Services and non-storable goods carry no inventory, so they
                # must never block a combo.
                "is_storable": product.type == "consu" and product.is_storable,
                "display_name": product.display_name,
            }
            for product in products
        }
