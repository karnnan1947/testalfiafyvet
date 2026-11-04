# -*- coding: utf-8 -*-
from odoo import fields, models

VET_ITEM_TYPES = [
    ('medicine', 'Medicine'),
    ('vaccine', 'Vaccine / Biological'),
    ('supplement', 'Feed Supplement'),
    ('equipment', 'Equipment'),
    ('instrument', 'Instrument'),
    ('other', 'Other'),
]

DOSAGE_FORMS = [
    ('injection', 'Injection'),
    ('tablet', 'Tablet / Bolus'),
    ('oral_liquid', 'Oral Liquid / Suspension'),
    ('powder', 'Powder / Granules'),
    ('paste', 'Oral Paste / Gel'),
    ('topical', 'Topical (Spray / Cream / Pour-on)'),
    ('drops', 'Eye / Ear Drops'),
    ('other', 'Other'),
]

STORAGE_CONDITIONS = [
    ('room', 'Room Temperature (below 25°C)'),
    ('cool_dry', 'Cool and Dry Place'),
    ('fridge', 'Refrigerated (2-8°C)'),
    ('frozen', 'Frozen'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # --- Bilingual master data (BRD 1.5 #8) ---------------------------
    name_ar = fields.Char(
        string="Arabic Name", index='trigram',
        help="Product name in Arabic, printed on Arabic documents and searchable.")
    description_ar = fields.Text(string="Arabic Description")

    # --- Veterinary classification ------------------------------------
    active_ingredient = fields.Char(
        string="Active Ingredient / Molecule", index='trigram',
        help="Generic chemical compound name (searchable), e.g. Ivermectin.")
    target_species_ids = fields.Many2many(
        'alfiafy.target.species', 'alfiafy_product_target_species_rel',
        'product_tmpl_id', 'species_id', string="Target Species")
    vet_item_type = fields.Selection(VET_ITEM_TYPES, string="Item Type")
    dosage_form = fields.Selection(DOSAGE_FORMS, string="Dosage Form")
    strength = fields.Char(string="Strength / Concentration", help="e.g. 1% w/v, 200 mg/ml")
    storage_condition = fields.Selection(STORAGE_CONDITIONS, string="Storage Condition")
    prescription_required = fields.Boolean(
        string="Prescription Required",
        help="Veterinary prescription needed before this item can be dispensed.")

    # --- Manufacturer and Supplier as separate fields (BRD 1.5 #8) ------
    manufacturer_id = fields.Many2one(
        'res.partner', string="Manufacturer", index='btree_not_null',
        help="Company that manufactures the product.")
    supplier_id = fields.Many2one(
        'res.partner', string="Supplier", index='btree_not_null',
        help="Company the product is bought from. May be the same as, or "
             "different from, the manufacturer.")
