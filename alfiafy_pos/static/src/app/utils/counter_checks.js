/**
 * Alfiafy POS counter checks shared by the store, the order lines and the
 * payment validation: wholesale cap, branch stock and customer phone.
 */
import { _t } from "@web/core/l10n/translation";
import { formatFloat } from "@web/core/utils/numbers";

/** Free quantity of the branch location per product id, in the product's
 * unit. Filled from the server (pos.config.alfiafy_get_free_qty) when a
 * product is added and before payment; kept when offline. */
export const stockCache = new Map();

export function fmtQty(qty) {
    return formatFloat(qty, { digits: [69, 3], trailingZeros: false });
}

/** Quantity of a line in the product's own unit (a line can be sold in another
 * unit with pos_multi_uom_price). */
export function lineBaseQty(line, qty = line.qty) {
    return line.getQuantityInProductUom ? line.getQuantityInProductUom(qty) : qty;
}

export function productQtyInOrder(order, product, excludeLine = null) {
    let total = 0;
    for (const line of order?.lines || []) {
        if (line !== excludeLine && line.product_id?.id === product.id) {
            total += lineBaseQty(line);
        }
    }
    return total;
}

export function isStockControlled(config, product) {
    return Boolean(config?.block_out_of_stock_pos && product?.product_tmpl_id?.is_storable);
}

/** Error ({title, body}) when `totalQty` of `product` (in the product unit)
 * cannot be in one POS order, or null. */
export function quantityError(config, product, totalQty) {
    const template = product.product_tmpl_id;
    const unit = product.uom_id?.name || "";
    const maxQty = template?.max_pos_qty || 0;
    if (maxQty > 0 && totalQty > maxQty + 1e-6) {
        return {
            title: _t("Wholesale quantity"),
            body: _t(
                "The retail limit for %(product)s is %(max)s %(unit)s per POS order (requested: %(qty)s %(unit)s).\n\nLarger quantities are wholesale: please refer the customer to the Sales team (Sales module quotation).",
                {
                    product: product.display_name,
                    max: fmtQty(maxQty),
                    qty: fmtQty(totalQty),
                    unit,
                }
            ),
        };
    }
    if (isStockControlled(config, product) && stockCache.has(product.id)) {
        const available = stockCache.get(product.id);
        if (totalQty > available + 1e-6) {
            if (available > 0) {
                return {
                    title: _t("Out of stock"),
                    body: _t(
                        "Only %(available)s %(unit)s of %(product)s are available in this branch's stock (requested: %(qty)s %(unit)s).",
                        {
                            product: product.display_name,
                            available: fmtQty(available),
                            qty: fmtQty(totalQty),
                            unit,
                        }
                    ),
                };
            }
            return {
                title: _t("Out of stock"),
                body: _t(
                    "%(product)s is not available in this branch's stock. Branch purchases must be received in the system before the item can be sold.",
                    { product: product.display_name }
                ),
            };
        }
    }
    return null;
}

/** A phone number with at least 7 digits and only phone characters. */
export function isValidPhone(value) {
    const text = (value || "").trim();
    if (!text || !/^[+\d\s\-()./]+$/.test(text)) {
        return false;
    }
    return text.replace(/\D/g, "").length >= 7;
}

export function partnerHasPhone(partner) {
    return isValidPhone(partner?.phone) || isValidPhone(partner?.mobile);
}
