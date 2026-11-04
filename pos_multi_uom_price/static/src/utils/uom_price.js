/** © 2025 ehuerta _at_ ixer.mx
 * License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 *
 * Price of a product in a given unit of measure.
 *
 * - The product's own unit uses the normal sales price / pricelist.
 * - Every other unit has its own price in the "UOM Price" table (variant row
 *   first, then template row), e.g. Unit = 100.00, Box of 5 = 300.00,
 *   Box of 10 = 500.00. Prices are never derived from the unit price: a unit
 *   without a row cannot be chosen in the POS.
 */

/** Number of product units in one `uom` (used for quantities only). */
export function uomRatio(product, uom) {
    const base = product.uom_id;
    if (!uom || !base || uom.id === base.id || !base.factor) {
        return 1;
    }
    return uom.factor / base.factor;
}

export function getExplicitUomPrice(models, product, uom) {
    if (!uom || uom.id === product.uom_id?.id) {
        return null;
    }
    const variantRow = models["product.multi.uom.price"].find(
        (row) => row.product_id?.id === product.id && row.uom_id?.id === uom.id
    );
    if (variantRow) {
        return variantRow.price;
    }
    const templateRow = models["product.tmpl.multi.uom.price"].find(
        (row) => row.product_tmpl_id?.id === product.product_tmpl_id?.id && row.uom_id?.id === uom.id
    );
    return templateRow ? templateRow.price : null;
}

/** Price of one `uom` of the product, or null for another unit that has no
 * price in the UOM Price table. */
export function getProductUomPrice(models, product, uom, pricelist, qty = 1, priceExtra = 0) {
    if (!uom || uom.id === product.uom_id?.id) {
        return product.product_tmpl_id.getPrice(pricelist, qty, priceExtra, false, product);
    }
    return getExplicitUomPrice(models, product, uom);
}

/** True when `qty` is a whole number (1, 2, 3 packs...). */
export function isWholeQty(qty) {
    return Math.abs(qty - Math.round(qty)) < 1e-6;
}

/** Price the customer paid for one `uom` of the product on `soldLine`
 * (e.g. Pack of 6 sold at 300.00 -> 50.00 per Unit). Used for returns only. */
export function paidPricePerUom(soldLine, uom) {
    const product = soldLine.product_id;
    const soldRatio = uomRatio(product, soldLine.getUnit());
    return (soldLine.price_unit / soldRatio) * uomRatio(product, uom);
}

/** Units the product can be sold in: its own unit and the units that have a
 * price row. */
export function getSellableUoms(models, product) {
    const result = [];
    const seen = new Set();
    const add = (uom) => {
        if (uom && !seen.has(uom.id)) {
            seen.add(uom.id);
            result.push(uom);
        }
    };
    add(product.uom_id);
    for (const row of models["product.multi.uom.price"].filter(
        (row) => row.product_id?.id === product.id
    )) {
        add(row.uom_id);
    }
    for (const row of models["product.tmpl.multi.uom.price"].filter(
        (row) => row.product_tmpl_id?.id === product.product_tmpl_id?.id
    )) {
        add(row.uom_id);
    }
    return result;
}
