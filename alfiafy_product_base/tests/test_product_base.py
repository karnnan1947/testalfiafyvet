# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'alfiafy')
class TestAlfiafyProductBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.manufacturer = Partner.create({'name': 'Test Vet Manufacturing', 'is_company': True})
        cls.supplier = Partner.create({'name': 'Test Vet Distribution', 'is_company': True})
        cls.camel = cls.env.ref('alfiafy_product_base.species_camel')
        cls.horse = cls.env.ref('alfiafy_product_base.species_horse')
        cls.product = cls.env['product.product'].create({
            'name': 'Ivermectin 1% Injection 50ml (test)',
            'name_ar': 'ايفرمكتين ١٪ حقن ٥٠ مل',
            'active_ingredient': 'Ivermectin',
            'target_species_ids': [Command.set([cls.camel.id, cls.horse.id])],
            'vet_item_type': 'medicine',
            'dosage_form': 'injection',
            'strength': '1% w/v',
            'storage_condition': 'room',
            'prescription_required': True,
            'manufacturer_id': cls.manufacturer.id,
            'supplier_id': cls.supplier.id,
            'type': 'consu',
            'is_storable': True,
            'standard_price': 40.0,
            'list_price': 65.0,
        })
        cls.stock_location = cls.env.ref('stock.warehouse0').lot_stock_id
        cls.cost_user = new_test_user(
            cls.env, login='alf_cost_user', name='Cost Manager',
            groups='base.group_user,stock.group_stock_user,restricted_cost_access.group_manager_cost')
        cls.branch_user = new_test_user(
            cls.env, login='alf_branch_user', name='Branch Pharmacist',
            groups='base.group_user,stock.group_stock_user')

    # ------------------------------------------------------------------
    # master data fields
    # ------------------------------------------------------------------
    def test_01_vet_fields_stored_on_template(self):
        tmpl = self.product.product_tmpl_id
        self.assertEqual(tmpl.active_ingredient, 'Ivermectin')
        self.assertEqual(tmpl.target_species_ids, self.camel | self.horse)
        self.assertEqual(tmpl.manufacturer_id, self.manufacturer)
        self.assertEqual(tmpl.supplier_id, self.supplier)
        self.assertNotEqual(tmpl.manufacturer_id, tmpl.supplier_id,
                            "Manufacturer and supplier are separate fields")

    def test_02_search_by_molecule_arabic_name_and_species(self):
        Template = self.env['product.template']
        tmpl = self.product.product_tmpl_id
        self.assertIn(tmpl, Template.search([('active_ingredient', 'ilike', 'iverm')]))
        self.assertIn(tmpl, Template.search([('name_ar', 'ilike', 'ايفرمكتين')]))
        self.assertIn(tmpl, Template.search([('target_species_ids', 'in', self.camel.ids)]))
        # variants can be searched on the same fields (delegation)
        self.assertIn(self.product, self.env['product.product'].search([('active_ingredient', 'ilike', 'iverm')]))

    def test_03_stock_grouped_by_manufacturer_and_supplier(self):
        self.env['stock.quant']._update_available_quantity(self.product, self.stock_location, 25)
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', self.stock_location.id)])
        self.assertEqual(quant.product_manufacturer_id, self.manufacturer)
        self.assertEqual(quant.product_supplier_id, self.supplier)
        groups = self.env['stock.quant'].formatted_read_group(
            [('product_manufacturer_id', '=', self.manufacturer.id)],
            ['product_manufacturer_id'], ['quantity:sum'])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['quantity:sum'], 25)

    # ------------------------------------------------------------------
    # cost security (restricted_cost_access)
    # ------------------------------------------------------------------
    def test_04_cost_hidden_from_branch_user(self):
        as_branch = self.product.with_user(self.branch_user)
        self.assertEqual(as_branch.read(['standard_price'])[0]['standard_price'], 0.0)
        self.assertEqual(
            as_branch.product_tmpl_id.read(['standard_price', 'list_price'])[0],
            {'id': self.product.product_tmpl_id.id, 'standard_price': 0.0, 'list_price': 65.0},
            "Sales price stays visible, cost is redacted")
        desc = as_branch.fields_get(['standard_price'])['standard_price']
        self.assertFalse(desc['exportable'], "Cost must not be offered in Export")
        self.assertNotIn('aggregator', desc)

    def test_05_cost_visible_to_cost_manager(self):
        as_manager = self.product.with_user(self.cost_user)
        self.assertEqual(as_manager.read(['standard_price'])[0]['standard_price'], 40.0)
        self.assertTrue(as_manager.fields_get(['standard_price'])['standard_price'].get('exportable', True))

    def test_06_product_form_loads_for_both_users(self):
        for user, sees_cost in ((self.branch_user, False), (self.cost_user, True)):
            views = self.env['product.template'].with_user(user).get_views([(False, 'form')])
            arch = views['views']['form']['arch']
            self.assertIn('name="active_ingredient"', arch)
            self.assertIn('name="manufacturer_id"', arch)
            self.assertEqual('name="standard_price"' in arch, sees_cost)
