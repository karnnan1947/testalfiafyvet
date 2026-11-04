import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { lotSourcing, lotSourcingKey } from "@alfiafy_partner_sourcing/lot_sourcing";

patch(PosStore.prototype, {
    async editLots(product, packLotLinesToEdit) {
        const result = await super.editLots(...arguments);
        const names = [
            ...(result?.newPackLotLines || []).map((lot) => lot.lot_name),
            ...Object.values(result?.modifiedPackLotLines || {}),
        ].filter((name) => name && !lotSourcing.has(lotSourcingKey(product.id, name)));
        if (names.length) {
            try {
                const sourcing = await this.data.call("stock.lot", "alf_pos_lot_sourcing", [
                    product.id,
                    names,
                ]);
                for (const [name, value] of Object.entries(sourcing || {})) {
                    lotSourcing.set(lotSourcingKey(product.id, name), value);
                }
            } catch {
                // offline: the sourcing is still set on the server when the order is saved
            }
        }
        return result;
    },
});
