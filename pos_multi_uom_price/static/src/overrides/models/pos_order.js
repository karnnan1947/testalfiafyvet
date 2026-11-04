/** © 2025 ehuerta _at_ ixer.mx
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setLinePriceFromPriceList(line, pricelist) {
        if (line.isAlternativeUom) {
            // Each unit has its own fixed price, the same for every pricelist.
            const price = line.getUomPrice(line.getUnit(), pricelist);
            if (price !== null) {
                line.setUnitPrice(price);
            }
            return;
        }
        return super.setLinePriceFromPriceList(...arguments);
    },
});
