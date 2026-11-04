import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import {
    lotSourcing,
    lotSourcingKey,
    sourcingLabel,
} from "@alfiafy_partner_sourcing/lot_sourcing";

patch(Orderline.prototype, {
    /** "Lot OXY-2605-A · Official Partner" */
    get lineScreenValues() {
        const values = super.lineScreenValues;
        const lots = this.line.pack_lot_ids || [];
        if (!values.lotLines?.length || values.lotLines.length !== lots.length) {
            return values;
        }
        values.lotLines = values.lotLines.map((text, index) => {
            const key = lotSourcingKey(this.line.product_id.id, lots[index].lot_name);
            const sourcing =
                lotSourcing.get(key) ||
                (["partner", "outside"].includes(this.line.sourcing_type) && this.line.sourcing_type);
            return sourcing ? `${text} · ${sourcingLabel(sourcing)}` : text;
        });
        return values;
    },
});
