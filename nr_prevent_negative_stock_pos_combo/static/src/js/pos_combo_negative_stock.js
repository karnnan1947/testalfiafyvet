/** @odoo-module **/

import {AlertDialog} from "@web/core/confirmation_dialog/confirmation_dialog";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";

const PosStore = odoo.loader.modules.get('@point_of_sale/app/store/pos_store')
    ? odoo.loader.modules.get('@point_of_sale/app/store/pos_store').PosStore
    : odoo.loader.modules.get('@point_of_sale/app/services/pos_store').PosStore;
const OrderSummary = odoo.loader.modules.get("@point_of_sale/app/screens/product_screen/order_summary/order_summary")?.OrderSummary
    || odoo.loader.modules.get("@point_of_sale/app/screens/product_screen/order_summary/order_summary/order_summary")?.OrderSummary;

function getCurrentOrder(pos) {
    return pos.getOrder ? pos.getOrder() : pos.get_order();
}

function getOrderlines(order) {
    return order.getOrderlines ? order.getOrderlines() : order.get_orderlines();
}

function getLineQuantity(line) {
    return line.getQuantity ? line.getQuantity() : line.get_quantity();
}

function getSelectedOrderline(order) {
    return order.getSelectedOrderline
        ? order.getSelectedOrderline()
        : order.get_selected_orderline();
}

/**
 * The component lines actually chosen inside a configured combo. `parentLine`
 * is the combo root; its `getAllLinesInCombo()` returns the whole tree, so the
 * real components are every node except the root itself.
 */
function getSelectedComboChildLines(parentLine) {
    return parentLine
        .getAllLinesInCombo()
        .filter((line) => line.combo_parent_id && line.product_id);
}

/**
 * Units of `productId` already committed to the current order, whether sold on
 * their own or as part of another combo. Lines in `ignoredLines` are skipped so
 * a combo being added or re-configured does not compete with itself.
 */
function quantityInCart(order, productId, ignoredLines = []) {
    const ignoredUuids = new Set(ignoredLines.map((line) => line.uuid));
    return getOrderlines(order)
        .filter((line) => line.product_id?.id === productId && !ignoredUuids.has(line.uuid))
        .reduce((sum, line) => sum + getLineQuantity(line), 0);
}

/**
 * How many units of each *selected* component a combo needs to reach
 * `targetComboQty` combos. Component quantities scale with the parent combo
 * quantity (see `pos.order.line.setQuantity`), so we derive the per-combo ratio
 * from the current line and project it onto the target quantity. Products that
 * appear in more than one choice are summed.
 *
 * @returns {Map<number, {product, required: number}>} keyed by product id
 */
function getRequiredComponentQtys(childLines, currentComboQty, targetComboQty) {
    const perCombo = currentComboQty || 1;
    const required = new Map();
    for (const line of childLines) {
        const product = line.product_id;
        const perUnit = getLineQuantity(line) / perCombo;
        const need = perUnit * targetComboQty;
        const entry = required.get(product.id);
        if (entry) {
            entry.required += need;
        } else {
            required.set(product.id, {product, required: need});
        }
    }
    return required;
}

/**
 * Fetch the live stock of the given selected components and return the ones
 * that cannot cover their required quantity, accounting for units already in
 * the cart (excluding `ignoredLines`, i.e. this combo's own lines).
 */
async function getOutOfStockComponents(pos, requiredByProduct, ignoredLines = []) {
    const productIds = [...requiredByProduct.keys()];
    if (!productIds.length) {
        return [];
    }

    let stockByProductId = {};
    try {
        stockByProductId = await pos.data.call(
            "product.product",
            "get_pos_combo_component_stock",
            [productIds, pos.config.id]
        );
    } catch (error) {
        // Without a trustworthy answer from the server we cannot assert the
        // combo is sellable, so let the sale go through rather than blocking
        // the cashier on a transient network failure.
        console.warn("Error fetching combo component stock info:", error);
        return [];
    }

    const order = getCurrentOrder(pos);
    const blocked = [];
    for (const [productId, {product, required}] of requiredByProduct) {
        const info = stockByProductId[productId];
        if (!info || !info.is_storable) {
            continue;
        }
        const available = info.available_quantity || 0;
        const inCart = order ? quantityInCart(order, productId, ignoredLines) : 0;
        if (available - inCart < required) {
            blocked.push({
                name: info.display_name || product.display_name,
                available: available,
                inCart: inCart,
                required: required,
            });
        }
    }
    return blocked;
}

function showOutOfStockDialog(pos, comboName, blocked) {
    const details = blocked
        .map(
            (component) =>
                `• ${component.name} — Needed: ${component.required}, ` +
                `Available: ${component.available}, In Cart: ${component.inCart}`
        )
        .join("\n");

    pos.dialog.add(AlertDialog, {
        title: _t("No Stock Available"),
        body: _t(
            `Combo "${comboName}" cannot be sold because ` +
                `${blocked.length > 1 ? "these components are" : "this component is"} out of stock.\n\n${details}`
        ),
    });
}

function isComboTemplate(productTemplate) {
    return Boolean(productTemplate?.isCombo?.() || productTemplate?.type === "combo");
}

patch(PosStore.prototype, {
    async addLineToOrder(vals, order, opts = {}, configure = true) {
        // Let the base flow open the ComboConfiguratorPopup and build the line
        // first — only once the cashier has picked the components do we know
        // which products to check. The returned value is the (selected) combo
        // parent line, or undefined if the flow was cancelled.
        const line = await super.addLineToOrder(vals, order, opts, configure);

        // Only enforce on interactive cashier adds; a non-configuring call
        // (e.g. restoring an order) must never be blocked or torn down.
        if (!configure) {
            return line;
        }

        const parentLine = line || getSelectedOrderline(order);
        if (!parentLine || !parentLine.combo_line_ids?.length) {
            return line;
        }

        const productTemplate = parentLine.product_id?.product_tmpl_id;
        if (!isComboTemplate(productTemplate)) {
            return line;
        }

        const childLines = getSelectedComboChildLines(parentLine);
        const comboQty = getLineQuantity(parentLine);
        const requiredByProduct = getRequiredComponentQtys(childLines, comboQty, comboQty);
        // The combo's own lines are already in the cart at this point, so they
        // must not count against their own availability.
        const ignoredLines = parentLine.getAllLinesInCombo();
        const blocked = await getOutOfStockComponents(this, requiredByProduct, ignoredLines);
        if (blocked.length) {
            order.removeOrderline(parentLine);
            showOutOfStockDialog(this, productTemplate.display_name, blocked);
            return;
        }

        return line;
    },
});

patch(OrderSummary.prototype, {
    async _setValue(val) {
        const {numpadMode} = this.pos;
        const selectedLine = getSelectedOrderline(this.currentOrder);
        if (!selectedLine) {
            return super._setValue(val);
        }

        // In quantity mode the base `_setValue` applies the value to the combo
        // parent even when a component line is selected, so check that parent.
        const comboLine = selectedLine.combo_parent_id || selectedLine;
        const productTemplate = comboLine.product_id?.product_tmpl_id;
        const isComboParent = isComboTemplate(productTemplate) && comboLine.combo_line_ids?.length;
        // The numpad passes its buffer as a string (e.g. "3").
        const targetQty = val === "remove" ? NaN : parseFloat(val);

        if (numpadMode === "quantity" && isComboParent && targetQty > 0) {
            const childLines = getSelectedComboChildLines(comboLine);
            const currentComboQty = getLineQuantity(comboLine);
            // Scope the check to the components actually on this line, projected
            // onto the target quantity.
            const requiredByProduct = getRequiredComponentQtys(childLines, currentComboQty, targetQty);
            const ignoredLines = comboLine.getAllLinesInCombo();
            const blocked = await getOutOfStockComponents(this.pos, requiredByProduct, ignoredLines);
            if (blocked.length) {
                showOutOfStockDialog(this.pos, productTemplate.display_name, blocked);
                this.numberBuffer.reset();
                return;
            }
        }

        return super._setValue(val);
    },
});
