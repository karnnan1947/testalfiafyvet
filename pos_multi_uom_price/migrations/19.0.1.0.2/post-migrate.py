# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0.html).
"""One-time recompute of historical POS order-line cost.

Before this version, ``pos.order.line.total_cost`` was stored as
``qty * (cost per the product's DEFAULT UoM)`` even when the line was sold in a
different UoM of the same reference tree (e.g. a "Box of 4" product sold as a
single "Pcs"). That left the stored cost / margin wrong on already-posted orders.

This script rescales the stored ``total_cost`` of those historical lines into the
sold UoM using Odoo's native ``uom._compute_price`` (same logic as the runtime
override in models/pos_order.py). It is version-keyed, so Odoo runs it exactly
once and never double-scales on a later re-upgrade. ``margin`` / ``unit_cost`` are
non-stored and recompute automatically from the corrected ``total_cost``.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Lines sold in a UoM different from the product's default UoM.
    cr.execute("""
        SELECT l.id
        FROM pos_order_line l
        JOIN product_product p ON p.id = l.product_id
        JOIN product_template t ON t.id = p.product_tmpl_id
        WHERE l.product_uom_id IS NOT NULL
          AND l.product_uom_id <> t.uom_id
          AND l.is_total_cost_computed = TRUE
    """)
    ids = [r[0] for r in cr.fetchall()]
    if not ids:
        _logger.info("pos_multi_uom_price migration: no mismatched-UoM lines to fix.")
        return

    fixed = 0
    for line in env['pos.order.line'].browse(ids):
        sale_uom = line.product_uom_id
        default_uom = line.product_id.uom_id
        if (line.qty and sale_uom and default_uom
                and sale_uom != default_uom
                and sale_uom._has_common_reference(default_uom)):
            new_total = line.qty * default_uom._compute_price(line.total_cost / line.qty, sale_uom)
            if abs(new_total - line.total_cost) > 1e-6:
                line.total_cost = new_total
                fixed += 1

    _logger.info(
        "pos_multi_uom_price migration: rescaled total_cost on %s of %s mismatched-UoM POS line(s).",
        fixed, len(ids),
    )
