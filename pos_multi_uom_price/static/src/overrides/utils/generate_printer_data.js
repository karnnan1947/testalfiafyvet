/** © 2025 ehuerta _at_ ixer.mx
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 */

import { GeneratePrinterData } from "@point_of_sale/app/utils/printer/generate_printer_data";
import { patch } from "@web/core/utils/patch";

patch(GeneratePrinterData.prototype, {
    generateLineData() {
        const data = super.generateLineData(...arguments);
        this.order.lines.forEach((line, index) => {
            if (data[index] && line.getUnit) {
                data[index].product_uom_name = line.getUnit()?.name || data[index].product_uom_name;
            }
        });
        return data;
    },
});
