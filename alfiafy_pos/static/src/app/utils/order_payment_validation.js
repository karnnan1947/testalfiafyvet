import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ask, makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import {
    fmtQty,
    isValidPhone,
    lineBaseQty,
    partnerHasPhone,
    stockCache,
} from "@alfiafy_pos/app/utils/counter_checks";

patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        if (!this.order.isRefund) {
            if (!(await this.alfiafyCheckCustomerPhone())) {
                return false;
            }
            if (!(await this.alfiafyCheckStock())) {
                return false;
            }
            if (!(await this.alfiafyCheckCredit())) {
                return false;
            }
        }
        return await super.isOrderValid(...arguments);
    },

    /** Every sale is linked to a customer with a phone number (BRD 1.1 #1). */
    async alfiafyCheckCustomerPhone() {
        const pos = this.pos;
        if (!pos.config.enforce_pos_phone) {
            return true;
        }
        let partner = this.order.getPartner();
        if (!partner) {
            const confirmed = await ask(pos.dialog, {
                title: _t("Customer required"),
                body: _t(
                    "Every sale must be linked to a customer with a phone number. Select or create the customer, then validate again."
                ),
                confirmLabel: _t("Select Customer"),
            });
            if (confirmed) {
                await pos.selectPartner(this.order);
            }
            partner = this.order.getPartner();
            if (!partner) {
                return false;
            }
        }
        if (partnerHasPhone(partner)) {
            return true;
        }
        const phone = await makeAwaitable(pos.dialog, TextInputPopup, {
            title: _t("Phone number of %s", partner.name),
            placeholder: _t("Customer phone number (required)"),
        });
        if (!phone) {
            return false;
        }
        if (!isValidPhone(phone)) {
            pos.dialog.add(AlertDialog, {
                title: _t("Invalid phone number"),
                body: _t("'%s' is not a valid phone number.", phone),
            });
            return false;
        }
        pos.data.write("res.partner", [partner.id], { phone: phone.trim() });
        return true;
    },

    /** Final check of the order against the branch stock (BRD 1.1 #2). */
    async alfiafyCheckStock() {
        const pos = this.pos;
        if (!pos.config.block_out_of_stock_pos) {
            return true;
        }
        const totals = new Map();
        for (const line of this.order.getOrderlines()) {
            const product = line.product_id;
            if (product?.product_tmpl_id?.is_storable) {
                totals.set(product, (totals.get(product) || 0) + lineBaseQty(line));
            }
        }
        if (!totals.size) {
            return true;
        }
        await pos.alfiafyRefreshStock([...totals.keys()]);
        const problems = [];
        for (const [product, qty] of totals) {
            if (qty <= 0 || !stockCache.has(product.id)) {
                continue;
            }
            const available = stockCache.get(product.id);
            if (qty > available + 1e-6) {
                problems.push(
                    _t("%(product)s: %(qty)s %(unit)s in the order, %(available)s available", {
                        product: product.display_name,
                        qty: fmtQty(qty),
                        available: fmtQty(Math.max(available, 0)),
                        unit: product.uom_id?.name || "",
                    })
                );
            }
        }
        if (problems.length) {
            pos.dialog.add(AlertDialog, {
                title: _t("Not enough stock in this branch"),
                body: _t(
                    "The order cannot be completed:\n%s\n\nBranch purchases must be received in the system before the items can be sold.",
                    problems.join("\n")
                ),
            });
            return false;
        }
        return true;
    },

    /** Customer Account payments: overdue / credit limit hold (BRD 1.2 #4). */
    async alfiafyCheckCredit() {
        const creditPayments = this.order.payment_ids.filter(
            (payment) => payment.payment_method_id?.type === "pay_later" && payment.amount > 0
        );
        const partner = this.order.getPartner();
        if (!creditPayments.length || !partner) {
            return true;
        }
        const amount = creditPayments.reduce((sum, payment) => sum + payment.amount, 0);
        return await this.pos.alfiafyCreditAllowed(partner, amount);
    },
});
