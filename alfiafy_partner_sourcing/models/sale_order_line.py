# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import float_compare, float_is_zero

from .selections import LINE_SOURCING_TYPES, sourcing_of


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    sourcing_type = fields.Selection(
        LINE_SOURCING_TYPES, string="Sourcing", compute='_compute_sourcing_type',
        store=True, index=True,
        help="Official Partner / Outside Supplier of the lots reserved or "
             "delivered for this line (Mixed when both).")

    @api.depends('move_ids.state', 'move_ids.move_line_ids.quantity',
                 'move_ids.move_line_ids.lot_id.sourcing_type')
    def _compute_sourcing_type(self):
        for line in self:
            digits = line._alf_qty_digits()
            quantities = line._alf_delivered_by_sourcing(include_reserved=True)
            line.sourcing_type = sourcing_of(
                key for key, data in quantities.items()
                if float_compare(data['qty'], 0.0, precision_digits=digits) > 0
            )

    def _alf_qty_digits(self):
        return self.env['decimal.precision'].precision_get('Product Unit')

    def _alf_moved_by_sourcing(self, done=True):
        """Quantities of the line taken from lots of each sourcing, from the
        delivery move lines (done moves, or the moves still to deliver with
        their reserved lots), returns deducted:
        {sourcing or False: {'qty' (line unit), 'qty_product' (product unit),
        'cost' (company currency), 'date'}}."""
        self.ensure_one()
        result = {}
        if self.display_type or not self.product_id or not self.product_id.is_storable:
            return result
        product_uom = self.product_id.uom_id
        outgoing, incoming = self.sudo()._get_outgoing_incoming_moves()
        for moves, sign in ((outgoing, 1), (incoming, -1)):
            for move in moves:
                if (move.state == 'done') != done or move.state in ('draft', 'cancel'):
                    continue
                for move_line in move.move_line_ids:
                    if not move_line.quantity:
                        continue
                    lot = move_line.lot_id
                    qty_product = move_line.uom_id._compute_quantity(move_line.quantity, product_uom, round=False)
                    entry = result.setdefault(lot.sourcing_type or False, {
                        'qty': 0.0, 'qty_product': 0.0, 'cost': 0.0, 'date': move.date,
                    })
                    entry['qty'] += sign * move_line.uom_id._compute_quantity(
                        move_line.quantity, self.product_uom_id, round=False)
                    entry['qty_product'] += sign * qty_product
                    unit_cost = lot._alf_unit_cost() if lot else self.product_id.sudo().standard_price
                    entry['cost'] += sign * qty_product * (unit_cost or 0.0)
                    entry['date'] = min(entry['date'], move.date)
        return result

    def _alf_delivered_by_sourcing(self, include_reserved=False):
        """Done (and, when asked, reserved) quantities per sourcing."""
        result = self._alf_moved_by_sourcing(done=True)
        if include_reserved:
            for key, data in self._alf_moved_by_sourcing(done=False).items():
                entry = result.setdefault(key, dict(data, qty=0.0, qty_product=0.0, cost=0.0))
                for field in ('qty', 'qty_product', 'cost'):
                    entry[field] += data[field]
                entry['date'] = min(entry['date'], data['date'])
        return result

    def _alf_invoiced_by_sourcing(self):
        """Quantities already invoiced per sourcing (credit notes deducted)."""
        self.ensure_one()
        invoiced = {}
        for invoice_line in self.invoice_lines:
            if invoice_line.move_id.state == 'cancel' or invoice_line.display_type != 'product':
                continue
            qty = invoice_line.product_uom_id._compute_quantity(
                invoice_line.quantity, self.product_uom_id, round=False)
            if invoice_line.move_id.move_type == 'out_refund':
                qty = -qty
            key = invoice_line.sourcing_type or False
            invoiced[key] = invoiced.get(key, 0.0) + qty
        return invoiced

    def _alf_split_invoice_qty(self, quantity):
        """[(sourcing, quantity, unit cost per product unit)] for a quantity
        to invoice: taken first from the delivered quantities of each sourcing
        not invoiced yet (oldest delivery first), then from the lots reserved
        for what is still to deliver. A part that cannot be matched to a lot
        (no lot, invoiced before reservation) has no sourcing."""
        digits = self._alf_qty_digits()
        sign = 1 if quantity > 0 else -1
        done = self._alf_moved_by_sourcing(done=True)
        reserved = self._alf_moved_by_sourcing(done=False)
        invoiced = self._alf_invoiced_by_sourcing()
        both = self._alf_delivered_by_sourcing(include_reserved=True)
        buckets = []
        for key in {*done, *reserved} - {False}:
            done_left = done.get(key, {}).get('qty', 0.0) - invoiced.get(key, 0.0)
            reserved_left = reserved.get(key, {}).get('qty', 0.0)
            if sign > 0 and done_left < 0:
                # invoiced ahead of delivery from the reserved lots
                reserved_left += done_left
                done_left = 0.0
            data = both.get(key) or {}
            unit_cost = data['cost'] / data['qty_product'] if data.get('qty_product') else 0.0
            if key in done:
                buckets.append((0, done[key]['date'], key, done_left, unit_cost))
            if key in reserved:
                buckets.append((1, reserved[key]['date'], key, reserved_left, unit_cost))
        left = abs(quantity)
        parts = {}
        for _priority, _date, key, qty, unit_cost in sorted(buckets):
            available = qty * sign
            if float_compare(available, 0.0, precision_digits=digits) <= 0:
                continue
            take = min(available, left)
            parts.setdefault(key, [key, 0.0, unit_cost])[1] += sign * take
            left -= take
            if float_is_zero(left, precision_digits=digits):
                break
        result = [tuple(part) for part in parts.values()]
        if not float_is_zero(left, precision_digits=digits):
            result.append((False, sign * left, 0.0))
        return result

    def _prepare_invoice_lines_vals_list(self, **optional_values):
        vals_list = super()._prepare_invoice_lines_vals_list(**optional_values)
        if (len(vals_list) != 1 or self.display_type or not self.product_id
                or vals_list[0].get('display_type', 'product') != 'product'):
            return vals_list
        vals = vals_list[0]
        quantity = vals.get('quantity') or 0.0
        if float_is_zero(quantity, precision_digits=self._alf_qty_digits()):
            return vals_list
        parts = self._alf_split_invoice_qty(quantity)
        if not parts or (len(parts) == 1 and not parts[0][0]):
            return vals_list
        if len(parts) == 1:
            sourcing, _qty, unit_cost = parts[0]
            vals.update({'sourcing_type': sourcing, 'sourcing_unit_cost': unit_cost})
            return vals_list
        # e.g. 10 units from a partner lot + 5 from an outside lot: one invoice
        # line per sourcing, both linked to the sales order line.
        result = []
        for sourcing, qty, unit_cost in parts:
            part = dict(vals, quantity=qty, sourcing_type=sourcing or False,
                        sourcing_unit_cost=unit_cost if sourcing else False)
            part.pop('extra_tax_data', None)  # recomputed for each part
            result.append(part)
        return result
