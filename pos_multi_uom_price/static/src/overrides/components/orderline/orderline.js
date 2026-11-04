/** © 2025 ehuerta _at_ ixer.mx
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 */

import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

patch(Orderline.prototype, {
    get lineScreenValues() {
        const vals = super.lineScreenValues;
        const line = this.line;
        if (!line?.order_id) {
            return vals;
        }
        // Always show "price / unit" for a line sold in another unit, and use
        // the unit of the line (not the product's) in the label.
        const uomName = line.getUnit()?.name || "";
        if (line.isAlternativeUom || vals.displayPriceUnit) {
            vals.displayPriceUnit = `${line.currencyDisplayPriceUnit} / ${uomName}`;
        }
        return vals;
    },
});
