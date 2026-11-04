/** © 2025 ehuerta _at_ ixer.mx
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";
import { getProductUomPrice, uomRatio } from "@pos_multi_uom_price/utils/uom_price";

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(vals);
        if (!this.product_id) {
            return;
        }
        if (!this.product_uom_id) {
            // A refund line is returned in the unit the product was sold in.
            this.product_uom_id =
                this.refunded_orderline_id?.product_uom_id || this.product_id.uom_id;
        }
    },
    getUnit() {
        return this.product_uom_id || this.product_id.uom_id;
    },
    /** True when the line is sold in another unit than the product's own. */
    get isAlternativeUom() {
        const uom = this.product_uom_id;
        const base = this.product_id?.uom_id;
        return Boolean(uom && base && uom.id !== base.id);
    },
    /** Quantity of the line expressed in the product's own unit. */
    getQuantityInProductUom(qty = this.qty) {
        return qty * uomRatio(this.product_id, this.getUnit());
    },
    getUomPrice(uom = this.getUnit(), pricelist = this.order_id.pricelist_id) {
        return getProductUomPrice(
            this.models,
            this.product_id,
            uom,
            pricelist,
            this.getQuantity() || 1,
            this.getPriceExtra()
        );
    },
    setUom(uom) {
        this.product_uom_id = uom;
        this.price_type = "original";
        this.recomputeUnitPrice();
    },
    recomputeUnitPrice() {
        if (this.isAlternativeUom) {
            // A unit without its own price (e.g. a refund of a unit whose
            // price row was removed) keeps the price already on the line.
            const price = this.getUomPrice();
            if (price !== null) {
                this.setUnitPrice(price);
            }
            return;
        }
        return super.recomputeUnitPrice(...arguments);
    },
    /** Refunded quantity in this line's unit: a line sold per Pack of 6 may be
     * refunded per piece (Orders screen, "Return Units"), 1 piece = 1/6 pack. */
    get refundedQty() {
        const product = this.product_id;
        const ratio = uomRatio(product, this.getUnit());
        return (
            this.refund_orderline_ids?.reduce((acc, line) => {
                if (line.order_id?.state === "cancel") {
                    return acc;
                }
                return acc - (line.qty * uomRatio(product, line.getUnit())) / ratio;
            }, 0) || 0
        );
    },
    canBeMergedWith(orderline) {
        if (this.getUnit()?.id !== orderline.getUnit()?.id) {
            return false;
        }
        return super.canBeMergedWith(...arguments);
    },
    isPosGroupable() {
        const unit = this.getUnit();
        return Boolean(unit?.is_pos_groupable) && !this.isPartOfCombo();
    },
    prepareBaseLineForTaxesComputationExtraValues(customValues = {}) {
        const values = super.prepareBaseLineForTaxesComputationExtraValues(...arguments);
        if (!("product_uom_id" in customValues) && this.product_uom_id) {
            values.product_uom_id = this.product_uom_id;
        }
        return values;
    },
});
