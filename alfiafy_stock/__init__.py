# -*- coding: utf-8 -*-
from . import models


def _post_init_hook(env):
    """Internal transfers done before the install are Received."""
    env['stock.picking'].search([
        ('picking_type_code', '=', 'internal'), ('state', '=', 'done'),
    ]).write({'transfer_status': 'done'})
