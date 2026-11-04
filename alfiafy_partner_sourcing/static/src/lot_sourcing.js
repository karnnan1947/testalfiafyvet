/** Sourcing (Official Partner / Outside Supplier) of the lots chosen in the
 * POS, read from the server when a lot is chosen: "<product id>|<lot name>". */
import { _t } from "@web/core/l10n/translation";

export const lotSourcing = new Map();

export function lotSourcingKey(productId, lotName) {
    return `${productId}|${lotName}`;
}

export function sourcingLabel(sourcing) {
    return {
        partner: _t("Official Partner"),
        outside: _t("Outside Supplier"),
        mixed: _t("Mixed"),
    }[sourcing];
}
