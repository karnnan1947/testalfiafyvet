import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod, args = {}) {
        const order = this.currentOrder;
        const partner = order?.getPartner();
        if (paymentMethod.type === "pay_later" && partner && !order.isRefund) {
            // Refuse the Customer Account method right away for a customer on
            // credit hold; validation checks it again.
            const amount = Math.max(order.remainingDue || 0, 0);
            if (!(await this.pos.alfiafyCreditAllowed(partner, amount))) {
                return false;
            }
        }
        return await super.addNewPaymentLine(...arguments);
    },
});
