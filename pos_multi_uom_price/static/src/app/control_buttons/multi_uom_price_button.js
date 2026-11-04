/** © 2025 ehuerta _at_ ixer.mx
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 */

import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { getProductUomPrice, getSellableUoms } from "@pos_multi_uom_price/utils/uom_price";

export async function selectOrderlineUOM(pos) {
    const order = pos.getOrder();
    const line = order?.getSelectedOrderline();
    if (!line) {
        pos.dialog.add(AlertDialog, {
            title: _t("No product"),
            body: _t("Select a product line first."),
        });
        return;
    }
    if (line.isPartOfCombo()) {
        pos.dialog.add(AlertDialog, {
            title: _t("Unit cannot be changed"),
            body: _t("The unit of a combo line cannot be changed."),
        });
        return;
    }
    if (line.refunded_orderline_id) {
        pos.dialog.add(AlertDialog, {
            title: _t("Unit cannot be changed"),
            body: _t(
                "A refund line keeps its unit. To return single pieces of a pack, open the order in the Orders screen, select the line and press \"Return %s\" before pressing Refund.",
                line.product_id.uom_id.name
            ),
        });
        return;
    }
    const product = line.product_id;
    const uoms = getSellableUoms(pos.models, product);
    if (uoms.length < 2) {
        pos.dialog.add(AlertDialog, {
            title: _t("Only one unit"),
            body: _t(
                "%s is only sold per %s. Enter a price for another unit on the product (Point of Sale tab, UOM Price) to sell it in that unit.",
                product.display_name,
                product.uom_id?.name || ""
            ),
        });
        return;
    }
    const current = line.getUnit();
    const list = uoms.map((uom) => {
        const price = getProductUomPrice(
            pos.models,
            product,
            uom,
            order.pricelist_id,
            1,
            line.getPriceExtra()
        );
        const description =
            uom.id === product.uom_id.id
                ? _t("Sales price")
                : _t("Own price for 1 %s", uom.name);
        return {
            id: uom.id,
            label: `${uom.name} - ${pos.formatCurrency(price)}`,
            description,
            item: uom,
            isSelected: uom.id === current?.id,
        };
    });
    const uom = await makeAwaitable(pos.dialog, SelectionPopup, {
        title: _t("Unit of Measure"),
        list,
    });
    if (uom && uom.id !== current?.id) {
        line.setUom(uom);
    }
}

patch(ControlButtons.prototype, {
    async onClickUOMSelector() {
        await selectOrderlineUOM(this.pos);
    },
});

patch(ActionpadWidget.prototype, {
    async onClickUOMSelector() {
        await selectOrderlineUOM(this.pos);
    },
});
