import { PosAccessRightPlugin } from "@point_of_sale/app/plugins/access_right_plugin";
import { patch } from "@web/core/utils/patch";

patch(PosAccessRightPlugin.prototype, {
    /**
     * Discounts are percentage only (BRD 1.1 #3): typing a lower price with the
     * keypad Price key would be a fixed-amount discount that bypasses the
     * cashier limit. While the discount approval is on, the Price key is
     * reserved to employees with manager access.
     *
     * (Core naming: a truthy value means the Price key is ENABLED.)
     */
    get disablePriceButton() {
        const enabled = super.disablePriceButton;
        if (
            enabled &&
            this.config.require_manager_discount_pin &&
            this.config.module_pos_hr &&
            this.loggedCashier?._role !== "manager"
        ) {
            return false;
        }
        return enabled;
    },
});
