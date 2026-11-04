/* global Sha1 */
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { parseFloat } from "@web/views/fields/parsers";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import {
    isStockControlled,
    productQtyInOrder,
    quantityError,
    stockCache,
} from "@alfiafy_pos/app/utils/counter_checks";

function parseDiscount(val) {
    const value = typeof val === "number" ? val : parseFloat(String(val ?? 0));
    return Math.min(Math.max(isNaN(value) ? 0 : value, 0), 100);
}

patch(PosStore.prototype, {
    async afterProcessServerData() {
        const result = await super.afterProcessServerData(...arguments);
        // Warm the branch stock cache (kept for offline use); not awaited.
        this.alfiafyRefreshStock(this.models["product.product"].getAll());
        return result;
    },

    // ------------------------------------------------------------------
    // Branch stock and wholesale cap
    // ------------------------------------------------------------------
    async alfiafyRefreshStock(products) {
        if (!this.config.block_out_of_stock_pos) {
            return true;
        }
        const ids = [
            ...new Set(
                products
                    .filter((p) => p?.product_tmpl_id?.is_storable && typeof p.id === "number")
                    .map((p) => p.id)
            ),
        ];
        if (!ids.length) {
            return true;
        }
        try {
            const result = await this.data.call("pos.config", "alfiafy_get_free_qty", [
                [this.config.id],
                ids,
            ]);
            for (const [id, qty] of Object.entries(result || {})) {
                stockCache.set(Number(id), qty);
            }
            return true;
        } catch {
            // Offline: keep the last known quantities.
            return false;
        }
    },

    alfiafySkipQuantityCheck(vals, order, opts) {
        return Boolean(
            opts.force ||
                vals.refunded_orderline_id ||
                order.isRefund ||
                order.preset_id?.is_return ||
                (vals.qty !== undefined && vals.qty <= 0)
        );
    },

    async addLineToOrder(vals, order, opts = {}, configure = true) {
        const template =
            typeof vals.product_tmpl_id === "number"
                ? this.models["product.template"].get(vals.product_tmpl_id)
                : vals.product_tmpl_id;
        const product =
            vals.product_id ||
            (template?.product_variant_ids?.length === 1 ? template.product_variant_ids[0] : null);
        if (product && order && !this.alfiafySkipQuantityCheck(vals, order, opts)) {
            if (isStockControlled(this.config, product)) {
                await this.alfiafyRefreshStock([product]);
            }
            const total = productQtyInOrder(order, product) + (vals.qty ?? 1);
            const error = quantityError(this.config, product, total);
            if (error) {
                this.dialog.add(AlertDialog, error);
                return;
            }
        }
        return await super.addLineToOrder(...arguments);
    },

    // ------------------------------------------------------------------
    // Discount approval
    // ------------------------------------------------------------------
    get alfiafyDiscountControl() {
        return Boolean(this.config.require_manager_discount_pin);
    },

    restrictLineDiscountChange() {
        // The discount is typed in a popup (whole value at once) so that the
        // approval is asked once for the final percentage, not per keystroke.
        return this.alfiafyDiscountControl || super.restrictLineDiscountChange(...arguments);
    },

    async setDiscountFromUI(line, val) {
        if (!this.alfiafyDiscountControl || !line) {
            return await super.setDiscountFromUI(...arguments);
        }
        const discount = parseDiscount(val);
        const limit = this.config.max_cashier_discount || 0;
        let approver = null;
        if (discount > limit + 1e-9) {
            approver = await this.alfiafyAskDiscountApproval(discount, limit);
            if (!approver) {
                return; // the line keeps its previous discount
            }
        }
        await super.setDiscountFromUI(line, discount);
        if (this.config.module_pos_hr) {
            for (const l of [line, ...(line.combo_line_ids || [])]) {
                if (approver || l.discount_approved_by_id) {
                    l.discount_approved_by_id = approver || false;
                }
            }
        }
    },

    /** Ask the PIN of an employee with manager access on this register.
     * Returns the employee, or null when cancelled / refused. */
    async alfiafyAskDiscountApproval(discount, limit) {
        if (!this.config.module_pos_hr) {
            this.dialog.add(AlertDialog, {
                title: _t("Discount above the limit"),
                body: _t(
                    "Discounts above %s need a manager PIN. Enable 'Log in with Employees' on this register to approve them.",
                    `${limit}%`
                ),
            });
            return null;
        }
        const pin = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Manager approval required"),
            subtitle: _t(
                "A %s discount is above the %s cashier limit. A manager must enter their PIN.",
                `${discount}%`,
                `${limit}%`
            ),
            formatDisplayedValue: (x) => x.replace(/./g, "•"),
            confirmButtonLabel: _t("Approve"),
        });
        if (!pin) {
            return null;
        }
        const hash = Sha1.hash(String(pin));
        const manager = this.models["hr.employee"].find(
            (employee) => employee._role === "manager" && employee._pin && employee._pin === hash
        );
        if (!manager) {
            this.dialog.add(AlertDialog, {
                title: _t("Access denied"),
                body: _t(
                    "This PIN does not belong to a manager of this register. The discount was not applied."
                ),
            });
            return null;
        }
        this.notification.add(_t("%s discount approved by %s", `${discount}%`, manager.name), {
            type: "success",
        });
        return manager;
    },

    // ------------------------------------------------------------------
    // Credit hold (Customer Account payments)
    // ------------------------------------------------------------------
    async alfiafyCreditAllowed(partner, amount) {
        let result;
        try {
            result = await this.data.call("res.partner", "alfiafy_pos_credit_check", [
                partner.id,
                amount,
                this.config.id,
            ]);
        } catch {
            this.dialog.add(AlertDialog, {
                title: _t("Credit check not possible"),
                body: _t(
                    "The customer's credit could not be checked with the server. Customer Account payments need a connection: use another payment method."
                ),
            });
            return false;
        }
        if (result?.blocked) {
            this.dialog.add(AlertDialog, {
                title: _t("Credit sale blocked"),
                body: result.message,
            });
            return false;
        }
        return true;
    },
});
