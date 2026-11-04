# -*- coding: utf-8 -*-
from . import models
from . import report


def _post_init_backfill(env):
    """Existing data: give the lots already received from a purchase order
    their origin (PO, vendor, unit cost) and the POS order lines their sourcing."""
    lots = env['stock.lot'].search([('origin_po_id', '=', False)])
    lots._alf_backfill_origin()
    pos_lines = env['pos.order.line'].search([('pack_lot_ids', '!=', False)])
    pos_lines._alf_set_sourcing()
