/** License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
 *
 * Refund of a line sold per pack / box (Orders screen). Odoo does not allow
 * quantities to be changed on the refund order itself, so the quantity to
 * return is chosen here, before pressing Refund:
 * - the numpad sets a whole number of packs;
 * - "Return Units" sets a number of single pieces, refunded at the price the
 *   customer paid per piece (Pack of 6 at 300.00 -> 50.00 per Unit), unless
 *   the register has "Block Fractional Returns";
 * - when pieces of the pack were already returned, the rest is refunded per
 *   piece too.
 */

import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { isWholeQty, paidPricePerUom, uomRatio } from "@pos_multi_uom_price/utils/uom_price";

patch(TicketScreen.prototype, {
    _alfRound(qty) {
        const rounder = this.pos.models["decimal.precision"].find(
            (dp) => dp.name === "Product Unit"
        );
        return rounder.round(qty);
    },
    _alfSelectedLine() {
        const order = this.getSelectedOrder();
        const lineId = this.getSelectedOrderlineId();
        return order?.lines?.find((line) => line.id == lineId);
    },
    /** Pieces in one unit sold (6 for a Pack of 6). */
    _alfRatio(line) {
        return uomRatio(line.product_id, line.getUnit());
    },
    /** "Return Units" is offered for a line sold per pack / box. */
    alfCanReturnPieces(line = this._alfSelectedLine()) {
        return Boolean(
            line &&
                this.isOrderSynced &&
                line.isAlternativeUom &&
                !line.combo_parent_id &&
                !line.combo_line_ids?.length &&
                !line.refunded_orderline_id &&
                !this.pos.config.block_fractional_return &&
                line.qty - line.refundedQty > 1e-6
        );
    },
    alfReturnPiecesLabel(line = this._alfSelectedLine()) {
        return _t("Return %s", line?.product_id?.uom_id?.name || "");
    },
    /** Price paid for one piece of `line` (shown on the Orders screen). */
    alfPiecePrice(line) {
        return paidPricePerUom(line, line.product_id.uom_id);
    },
    /** Pieces already refunded on a pack line, when not whole packs. */
    alfRefundedPieces(line) {
        if (!line.isAlternativeUom || isWholeQty(line.refundedQty)) {
            return 0;
        }
        return this._alfRound(line.refundedQty * this._alfRatio(line));
    },
    async onClickReturnPieces() {
        const line = this._alfSelectedLine();
        if (!this.alfCanReturnPieces(line)) {
            return;
        }
        const detail = this.getToRefundDetail(line);
        if (detail.destination_order_uuid) {
            return;
        }
        const product = line.product_id;
        const unit = product.uom_id.name;
        const maxPieces = this._alfRound(detail.refundableQty * this._alfRatio(line));
        this.numberBuffer.capture();
        const value = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("%s to return", unit),
            subtitle: _t(
                "%s: sold per %s (%s %s). Refunded at %s per %s, up to %s %s.",
                product.display_name,
                line.getUnit().name,
                this._alfRatio(line),
                unit,
                this.pos.formatCurrency(this.alfPiecePrice(line)),
                unit,
                maxPieces,
                unit
            ),
            startingValue: detail.alfPieceQty || "",
        });
        if (value === undefined || value === null || value === "") {
            return;
        }
        const pieces = Math.abs(parseFloat(value));
        if (isNaN(pieces)) {
            return;
        }
        this.numberBuffer.reset();
        if (pieces > maxPieces + 1e-6) {
            this.dialog.add(AlertDialog, {
                title: _t("Maximum Exceeded"),
                body: _t("Only %s %s of this line can still be returned.", maxPieces, unit),
            });
            return;
        }
        if (this.pos.isProductQtyZero(pieces)) {
            detail.qty = 0;
            delete detail.alfPieceQty;
            return;
        }
        detail.qty = pieces / this._alfRatio(line);
        detail.alfPieceQty = this._alfRound(pieces);
    },

    _setToRefundDetail(toRefundDetail, buffer) {
        const line = toRefundDetail.line;
        if (line?.isAlternativeUom) {
            // A quantity typed on the numpad is a number of packs again.
            delete toRefundDetail.alfPieceQty;
            if (buffer != null && buffer !== "") {
                const quantity = Math.abs(parseFloat(buffer));
                const refundable = toRefundDetail.refundableQty;
                if (!isNaN(quantity) && quantity > 0) {
                    if (!isWholeQty(refundable) && quantity >= refundable - 1e-6) {
                        // Pieces of the pack were already returned: the rest.
                        toRefundDetail.qty = refundable;
                        toRefundDetail.alfPieceQty = this._alfRound(refundable * this._alfRatio(line));
                        return;
                    }
                    if (!isWholeQty(quantity)) {
                        this.numberBuffer.reset();
                        const unit = line.getUnit().name;
                        this.dialog.add(AlertDialog, {
                            title: _t("Whole %s only", unit),
                            body: this.pos.config.block_fractional_return
                                ? _t(
                                      "A line sold per %s can only be returned in whole %s on this register.",
                                      unit,
                                      unit
                                  )
                                : _t(
                                      "Type a whole number of %s. To return single pieces, press \"Return %s\".",
                                      unit,
                                      line.product_id.uom_id.name
                                  ),
                        });
                        return;
                    }
                }
            }
        }
        return super._setToRefundDetail(...arguments);
    },

    getRefundLinesDetails(refundDetail, destinationOrder) {
        const values = super.getRefundLinesDetails(...arguments);
        const line = refundDetail.line;
        if (!line.isAlternativeUom) {
            return values;
        }
        let pieces = refundDetail.alfPieceQty;
        if (!pieces && !isWholeQty(refundDetail.qty)) {
            pieces = this._alfRound(refundDetail.qty * this._alfRatio(line));
        }
        if (!pieces) {
            return values;
        }
        // Single pieces: the refund line is in the product's own unit, at the
        // price paid per piece (not rounded, 100.00 / 3 stays exact).
        const baseUom = line.product_id.uom_id;
        values.product_uom_id = baseUom;
        values.qty = -pieces;
        values.price_unit = paidPricePerUom(line, baseUom);
        if (line.pack_lot_ids?.length && !values.pack_lot_ids?.length) {
            // pos_stock keeps as many lots as whole packs refunded (none here)
            const returned = line.refund_orderline_ids
                .filter((item) => !["cancel", "draft"].includes(item.order_id.state))
                .flatMap((item) => item.pack_lot_ids)
                .map((lot) => lot.lot_name);
            const lots = line.pack_lot_ids.map((lot) => lot.lot_name);
            const free = lots.filter((name) => !returned.includes(name));
            values.pack_lot_ids = (free.length ? free : lots)
                .slice(0, 1)
                .map((lotName) => ["create", { lot_name: lotName }]);
        }
        return values;
    },
});
