# -*- coding: utf-8 -*-
from odoo import fields, models


class AlfiafyTargetSpecies(models.Model):
    _name = 'alfiafy.target.species'
    _description = 'Target Species'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(string="Color Index")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique (name)',
        "A target species with this name already exists.",
    )
