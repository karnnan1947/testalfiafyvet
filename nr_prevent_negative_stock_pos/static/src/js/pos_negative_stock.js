/** @odoo-module **/

import {AlertDialog} from "@web/core/confirmation_dialog/confirmation_dialog";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";
import {rpc} from "@web/core/network/rpc";
const PosStore = odoo.loader.modules.get('@point_of_sale/app/store/pos_store') ? odoo.loader.modules.get('@point_of_sale/app/store/pos_store').PosStore : odoo.loader.modules.get('@point_of_sale/app/services/pos_store').PosStore;
const ProductConfiguratorPopup = odoo.loader.modules.get("@point_of_sale/app/store/product_configurator_popup/product_configurator_popup") ? odoo.loader.modules.get("@point_of_sale/app/store/product_configurator_popup/product_configurator_popup").ProductConfiguratorPopup : odoo.loader.modules.get("@point_of_sale/app/components/popups/product_configurator_popup/product_configurator_popup").ProductConfiguratorPopup;
const OrderSummary = odoo.loader.modules.get("@point_of_sale/app/screens/product_screen/order_summary/order_summary")?.OrderSummary || odoo.loader.modules.get("@point_of_sale/app/screens/product_screen/order_summary/order_summary/order_summary")?.OrderSummary;
const is_pos_sale = Boolean(PosStore?.prototype?.onClickSaleOrder)

if(is_pos_sale) {
    patch(PosStore.prototype, {
        async downPaymentSO(sale_order, isPercentage) {
            var is_negative = false;
            var negative_product = false;
            var negative_avail_qty = 0;
            var negative_req_qty = 0;
            for (const line of sale_order.order_line) {
                if (line.display_type || line.is_downpayment) continue;

                const product =
                    typeof line.product_id === "number"
                        ? this.data.models["product.product"].get(line.product_id)
                        : line.product_id;

                if (product?.type === "consu" || product?.type === "product") {
                    let availableQty = 0;
                    let productInfo = false;

                    try {
                        // Handle SaaS vs non-SaaS
                        const is_saas = Boolean(this.getOrder);
                        if (is_saas) {
                            productInfo = await this.getProductInfo(
                                product.product_tmpl_id,
                                1,
                                0,
                                product
                            );
                            availableQty =
                                productInfo?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                        } else {
                            productInfo = await this.getProductInfo(product, 1);
                            availableQty =
                                productInfo?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                        }
                    } catch (error) {
                        console.warn("Error fetching product stock info:", error);
                    }

                    const requestedQty = line.product_uom_qty || 0;
                    if (availableQty < requestedQty || requestedQty == 0 && availableQty == 0) {
                        is_negative = true;
                        negative_product = product;
                        negative_avail_qty = availableQty;
                        negative_req_qty = requestedQty==0?1:requestedQty;
                    }
                }
            }
            if(is_negative) {
                this.dialog.add(AlertDialog, {
                    title: _t("No Stock Available"),
                    body: _t(
                        `Product "${negative_product.display_name}" has insufficient stock.\n` +
                            `Available: ${negative_avail_qty}, Requested: ${negative_req_qty}`
                    ),
                });

                return;
            }
            return await super.downPaymentSO(sale_order, isPercentage);
        },
        async settleSO(sale_order, orderFiscalPos) {
            var is_negative = false;
            var negative_product = false;
            var negative_avail_qty = 0;
            var negative_req_qty = 0;
            for (const line of sale_order.order_line) {
                if (line.display_type || line.is_downpayment) continue;

                const product =
                    typeof line.product_id === "number"
                        ? this.data.models["product.product"].get(line.product_id)
                        : line.product_id;

                if (product?.type === "consu" || product?.type === "product") {
                    let availableQty = 0;
                    let productInfo = false;

                    try {
                        // Handle SaaS vs non-SaaS
                        const is_saas = Boolean(this.getOrder);
                        if (is_saas) {
                            productInfo = await this.getProductInfo(
                                product.product_tmpl_id,
                                1,
                                0,
                                product
                            );
                            availableQty =
                                productInfo?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                        } else {
                            productInfo = await this.getProductInfo(product, 1);
                            availableQty =
                                productInfo?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                        }
                    } catch (error) {
                        console.warn("Error fetching product stock info:", error);
                    }

                    const requestedQty = line.product_uom_qty || 0;
                    if (availableQty < requestedQty || requestedQty == 0 && availableQty == 0) {
                        is_negative = true;
                        negative_product = product;
                        negative_avail_qty = availableQty;
                        negative_req_qty = requestedQty==0?1:requestedQty;
                    }
                }
            }
            if(is_negative) {
                this.dialog.add(AlertDialog, {
                    title: _t("No Stock Available"),
                    body: _t(
                        `Product "${negative_product.display_name}" has insufficient stock.\n` +
                            `Available: ${negative_avail_qty}, Requested: ${negative_req_qty}`
                    ),
                });

                return;
            }
            return await super.settleSO(sale_order, orderFiscalPos);
        },
        async addLineToOrder(vals, order, opts = {}, configure = true) {
            let product = null;

            // Handle product retrieval for both SaaS and non-SaaS versions
            if (vals.product_id) {
                product = typeof vals.product_id === "number"
                    ? this.data.models["product.product"].get(vals.product_id)
                    : vals.product_id;
            } else if (vals.product_tmpl_id) {
                // SaaS version handling for product template
                product = typeof vals.product_tmpl_id === "number"
                    ? this.data.models["product.template"].get(vals.product_tmpl_id).product_variant_ids?.[0]
                    : vals.product_tmpl_id.product_variant_ids?.[0];
            }

            // Product check for consu type and stock
            if (product?.type === "consu" && !(product.isConfigurable() && configure)) {
                const is_saas = this.getOrder ? true : false;

                // Fetch available quantity using version-safe `getProductInfo`
                let result = false;
                let available = 0;

                if (is_saas) {
                    result = await this.getProductInfo(product.product_tmpl_id, 1, 0, product);
                    available = result?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                } else {
                    result = await this.getProductInfo(product, 1);
                    available = result?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                }
                const requestedQty = vals.qty || 1;

                // Get current order using appropriate method based on version
                const currentOrder = this.getOrder ? this.getOrder() : this.get_order();

                // Get orderlines using appropriate method based on version
                const orderlines = currentOrder.getOrderlines
                    ? currentOrder.getOrderlines()
                    : currentOrder.get_orderlines();

                // Calculate existing quantity using appropriate method
                const existingQty = orderlines
                    .filter((line) => line.product_id?.id === product.id)
                    .reduce((sum, line) => {
                        // Use appropriate quantity method based on version
                        const qty = line.getQuantity ? line.getQuantity() : line.get_quantity();
                        return sum + qty;
                    }, 0);

                const totalQty = existingQty + requestedQty;
                if (available < totalQty) {
                    this.dialog.add(AlertDialog, {
                        title: _t("No Stock Available"),
                        body: _t(
                            `Product "${product.display_name}" has insufficient stock.\n` +
                                `Available: ${available}, In Cart: ${existingQty}, Attempted to Add: ${requestedQty}`
                        ),
                    });

                    return;
                }
            }

            return await super.addLineToOrder(vals, order, opts, configure);
        },
    });
} else {
    patch(PosStore.prototype, {
        async addLineToOrder(vals, order, opts = {}, configure = true) {
            let product = null;

            // Handle product retrieval for both SaaS and non-SaaS versions
            if (vals.product_id) {
                product = typeof vals.product_id === "number"
                    ? this.data.models["product.product"].get(vals.product_id)
                    : vals.product_id;
            } else if (vals.product_tmpl_id) {
                // SaaS version handling for product template
                product = typeof vals.product_tmpl_id === "number"
                    ? this.data.models["product.template"].get(vals.product_tmpl_id).product_variant_ids?.[0]
                    : vals.product_tmpl_id.product_variant_ids?.[0];
            }

            // Product check for consu type and stock
            if (product?.type === "consu" && !(product.isConfigurable() && configure)) {
                const is_saas = this.getOrder ? true : false;

                // Fetch available quantity using version-safe `getProductInfo`
                let result = false;
                let available = 0;

                if (is_saas) {
                    result = await this.getProductInfo(product.product_tmpl_id, 1, 0, product);
                    available = result?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                } else {
                    result = await this.getProductInfo(product, 1);
                    available = result?.productInfo?.warehouses?.[0]?.available_quantity || 0;
                }
                const requestedQty = vals.qty || 1;

                // Get current order using appropriate method based on version
                const currentOrder = this.getOrder ? this.getOrder() : this.get_order();

                // Get orderlines using appropriate method based on version
                const orderlines = currentOrder.getOrderlines
                    ? currentOrder.getOrderlines()
                    : currentOrder.get_orderlines();

                // Calculate existing quantity using appropriate method
                const existingQty = orderlines
                    .filter((line) => line.product_id?.id === product.id)
                    .reduce((sum, line) => {
                        // Use appropriate quantity method based on version
                        const qty = line.getQuantity ? line.getQuantity() : line.get_quantity();
                        return sum + qty;
                    }, 0);

                const totalQty = existingQty + requestedQty;
                if (available < totalQty) {
                    this.dialog.add(AlertDialog, {
                        title: _t("No Stock Available"),
                        body: _t(
                            `Product "${product.display_name}" has insufficient stock.\n` +
                                `Available: ${available}, In Cart: ${existingQty}, Attempted to Add: ${requestedQty}`
                        ),
                    });

                    return;
                }
            }

            return await super.addLineToOrder(vals, order, opts, configure);
        },
    });
}

patch(ProductConfiguratorPopup.prototype, {
    async confirm() {
        const is_saas = this.pos.getOrder ? true : false;
        var product = false;
        if (is_saas) {
            if (!this.product?.id) {
                const selectedAttributeValuesIds = this.selectedValues.map(({ id }) => id);
                let template =
                    this.pos.models?.["product.template"]?.get(this.props.productTemplate?.id) ||
                    this.pos.data?.models?.["product.template"]?.get(this.props.productTemplate?.id) ||
                    this.props.productTemplate;

                if (!template) {
                    console.warn("Product template not found:", this.props.productTemplate);
                } else {
                    // Try both direct and lazy variant lists
                    const variantList =
                        template.product_variant_ids ||
                        template.__lazy_product_variant_ids ||
                        [];

                    let get_product = Array.isArray(variantList)
                        ? variantList.find((product_product) => {
                              const variantValues = product_product.product_template_variant_value_ids || [];
                              return (
                                  variantValues.length > 0 &&
                                  variantValues.every(({ id }) => selectedAttributeValuesIds.includes(id))
                              );
                          })
                        : false;

                    // Fallback: if not found, pick first variant
                    if (!get_product && Array.isArray(variantList) && variantList.length) {
                        get_product = variantList[0];
                    }

                    // Ensure consistent format
                    product = Array.isArray(get_product) ? this.pos.models["product.product"].get(get_product[0]) : get_product;
                }
            } else {
                product = this.pos.data.models["product.product"].get(this.product.id);
            }
        } else {
            product = this.state.product;
        }
        if (product?.type === "consu") {
            var result = false;
            var available = 0;
            if (is_saas) {
                result = await this.pos.getProductInfo(product.product_tmpl_id, 1, 0, product);
                available = result?.productInfo?.warehouses[0]?.available_quantity || 0;
            } else {
                result = await this.pos.getProductInfo(product, 1);
                available = result?.productInfo?.warehouses[0]?.available_quantity || 0;
            }

            // Get current order using version-safe method
            const currentOrder = this.pos.getOrder ? this.pos.getOrder() : this.pos.get_order();

            // Get orderlines using version-safe method
            const orderlines = currentOrder.getOrderlines
                ? currentOrder.getOrderlines()
                : currentOrder.get_orderlines();

            // how many units are already in the cart
            const existingQty = orderlines
                .filter((line) => line.product_id.id === product.id)
                .reduce((sum, line) => sum + (line.getQuantity ? line.getQuantity() : line.get_quantity()), 0);

            // attempted to add → for configurator usually 1 unit
            const requestedQty = 1;

            if (available < existingQty + requestedQty) {
                this.pos.dialog.add(AlertDialog, {
                    title: _t("No Stock Available"),
                    body: _t(
                        `Product "${product.display_name}" has insufficient stock.\n` +
                        `Available: ${available}, In Cart: ${existingQty}, Attempted to Add: ${requestedQty}`
                    ),
                });
                return;
            }
        }
        return await super.confirm();
    },
});

patch(OrderSummary.prototype, {
    async _setValue(val) {
        const { numpadMode } = this.pos;
        let selectedLine = this.currentOrder.getSelectedOrderline ? this.currentOrder.getSelectedOrderline() : this.currentOrder.get_selected_orderline();
        if (!selectedLine) return;
        const product = this.pos.data.models["product.product"].get(selectedLine.product_id.id);
        if (numpadMode === "quantity" && product?.type === "consu") {
            // Get orderlines using version-safe method
            const orderlines =  this.currentOrder.getOrderlines
                ?  this.currentOrder.getOrderlines()
                :  this.currentOrder.get_orderlines();
            // Fetch available stock
            const is_saas = this.pos.getOrder ? true : false;
            var result = false;
            var available = 0;
            if (is_saas) {
                result = await this.pos.getProductInfo(product.product_tmpl_id, 1, 0, product);
                available = result?.productInfo?.warehouses[0]?.available_quantity || 0;
            } else {
                result = await this.pos.getProductInfo(product, 1);
                available = result?.productInfo?.warehouses[0]?.available_quantity || 0;
            }

            if (val > available) {
                this.dialog.add(AlertDialog, {
                    title: _t("No Stock Available"),
                    body: _t(
                        `Product "${product.display_name}" has insufficient stock.\n` +
                        `Available: ${available}, Attempted to Set: ${val}`
                    ),
                });
                this.numberBuffer.reset();
                return;
            }
        }

        // Call original _setValue
        return super._setValue(val);
    },
});
