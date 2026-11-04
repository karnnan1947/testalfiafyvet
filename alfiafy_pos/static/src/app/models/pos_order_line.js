import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";
import { parseFloat } from "@web/views/fields/parsers";
import {
    lineBaseQty,
    productQtyInOrder,
    quantityError,
} from "@alfiafy_pos/app/utils/counter_checks";

patch(PosOrderline.prototype, {
    setQuantity(quantity, keep_price) {
        const error = this.alfiafyQuantityError(quantity);
        if (error) {
            // Shown by the numpad (OrderSummary._setValue); the quantity is kept.
            return error;
        }
        return super.setQuantity(...arguments);
    },

    merge(orderline) {
        // Already checked before the line was added (PosStore.addLineToOrder).
        this.uiState.alfiafySkipQtyCheck = true;
        try {
            return super.merge(...arguments);
        } finally {
            this.uiState.alfiafySkipQtyCheck = false;
        }
    },

    alfiafyQuantityError(quantity) {
        const order = this.order_id;
        const product = this.product_id;
        if (
            !order ||
            !product ||
            this.uiState?.alfiafySkipQtyCheck ||
            this.refunded_orderline_id ||
            this.combo_parent_id ||
            order.isRefund ||
            order.preset_id?.is_return
        ) {
            return null;
        }
        const qty = typeof quantity === "number" ? quantity : parseFloat(String(quantity || 0));
        if (isNaN(qty) || qty <= this.qty) {
            return null; // decreasing a quantity is always allowed
        }
        const total = productQtyInOrder(order, product, this) + lineBaseQty(this, qty);
        return quantityError(this.config, product, total);
    },
});
