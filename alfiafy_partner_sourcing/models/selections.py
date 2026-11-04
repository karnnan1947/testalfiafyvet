# -*- coding: utf-8 -*-
from odoo.addons.alfiafy_purchase.models.selections import SOURCING_TYPES

# Lots, purchase lines, receipts and invoice lines: one source.
LOT_SOURCING_TYPES = SOURCING_TYPES

# A sales order line or a POS line can take goods from lots of both sources
# (e.g. 10 units from a partner lot and 5 from an outside lot).
LINE_SOURCING_TYPES = SOURCING_TYPES + [('mixed', 'Mixed')]


def sourcing_of(values):
    """'partner' / 'outside' / 'mixed' / False for a set of sourcing values."""
    values = {value for value in values if value}
    if not values:
        return False
    if len(values) > 1:
        return 'mixed'
    return values.pop()
