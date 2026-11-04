# -*- coding: utf-8 -*-
"""Server side of the Alfiafy POS counter controls and of the multi-UoM
pricing (the cashier screens themselves are checked with the POS UI)."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install', 'alfiafy')
class TestAlfiafyPos(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('restricted_cost_access.group_manager_cost')
        cls.unit = cls.env.ref('uom.product_uom_unit')
        cls.box10 = cls.env['uom.uom'].create({
            'name': 'Box of 10 (test)', 'relative_factor': 10, 'relative_uom_id': cls.unit.id})
        cls.litre = cls.env.ref('uom.product_uom_litre')
        categ = cls.env['product.category'].create({'name': 'Vet medicines'})
        cls.ivermectin = cls.create_product('Ivermectin 1% (test)', categ, 45.0, standard_price=30.0)
        cls.ivermectin.max_pos_qty = 5
        cls.oxy = cls.create_product('Oxytetracycline LA (test)', categ, 55.0, standard_price=35.0)
        cls.service = cls.env['product.product'].create({
            'name': 'Consultation (test)', 'type': 'service', 'available_in_pos': True})
        cls.stock_location = cls.basic_config.picking_type_id.default_location_src_id
        cls.env['stock.quant']._update_available_quantity(cls.ivermectin, cls.stock_location, 100)
        cls.env['stock.quant']._update_available_quantity(cls.oxy, cls.stock_location, 40)
        cls.customer = cls.env['res.partner'].create({'name': 'Al Khor Stables', 'phone': '+974 5555 0001'})
        cls.manager = cls.env['hr.employee'].sudo().create({'name': 'Dr. Branch Manager', 'pin': '9999'})

    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    # ------------------------------------------------------------------
    # Data sent to the POS
    # ------------------------------------------------------------------
    def test_01_pos_loaded_fields_and_defaults(self):
        self.assertIn('max_pos_qty', self.env['product.template']._load_pos_data_fields(self.config))
        self.assertIn('product_uom_id', self.env['pos.order.line']._load_pos_data_fields(self.config))
        self.config.module_pos_hr = True
        self.assertIn('discount_approved_by_id', self.env['pos.order.line']._load_pos_data_fields(self.config))
        # the POS only sends plain fields back when it syncs an order
        relations = self.env['pos.order.line']._load_data_relations(['product_uom_id', 'discount_approved_by_id'])
        for field_name in ('product_uom_id', 'discount_approved_by_id'):
            self.assertFalse(relations[field_name]['compute'] or relations[field_name]['related'], field_name)
        self.assertEqual(self.config.max_cashier_discount, 5.0)
        self.assertTrue(self.config.require_manager_discount_pin)
        self.assertTrue(self.config.enforce_pos_phone)
        self.assertTrue(self.config.block_out_of_stock_pos)
        models = self.env['pos.session']._load_pos_data_models(self.config)
        self.assertIn('product.multi.uom.price', models)
        self.assertIn('product.tmpl.multi.uom.price', models)

    # ------------------------------------------------------------------
    # 6.2 Branch stock
    # ------------------------------------------------------------------
    def test_02_branch_free_qty(self):
        free = self.config.alfiafy_get_free_qty([self.ivermectin.id, self.oxy.id, self.service.id])
        self.assertEqual(free, {self.ivermectin.id: 100.0, self.oxy.id: 40.0},
                         "storable products only, quantity of the branch location")
        # stock of another warehouse does not count
        other_wh = self.env['stock.warehouse'].create({'name': 'Branch 2 (test)', 'code': 'TB2'})
        self.env['stock.quant']._update_available_quantity(self.oxy, other_wh.lot_stock_id, 500)
        self.assertEqual(self.config.alfiafy_get_free_qty([self.oxy.id])[self.oxy.id], 40.0)

    def test_03_free_qty_counts_sales_not_yet_delivered(self):
        self.env.company.point_of_sale_update_stock_quantities = 'closing'
        self.open_new_session()
        self.env['pos.order'].sync_from_ui([self.create_ui_order_data(
            [{'product': self.oxy, 'quantity': 1, 'product_uom_id': self.box10.id}], customer=self.customer)])
        self.assertFalse(self.pos_session.order_ids.picking_ids, "stock is moved at closing")
        self.assertEqual(self.config.alfiafy_get_free_qty([self.oxy.id])[self.oxy.id], 30.0,
                         "40 - 1 Box of 10 sold in the open session")

    # ------------------------------------------------------------------
    # 6.4 Discount approval is recorded on the line
    # ------------------------------------------------------------------
    def test_04_discount_approver_saved(self):
        self.open_new_session()
        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data([
            {'product': self.ivermectin, 'quantity': 2, 'discount': 10.0,
             'discount_approved_by_id': self.manager.id},
            {'product': self.oxy, 'quantity': 1, 'discount': 3.0},
        ], customer=self.customer)])
        order = self.env['pos.order'].browse(result['pos.order'][0]['id'])
        approved, small = order.lines.sorted('discount', reverse=True)
        self.assertEqual(approved.discount_approved_by_id, self.manager)
        self.assertFalse(small.discount_approved_by_id)

    # ------------------------------------------------------------------
    # 6.5 Credit hold for Customer Account payments
    # ------------------------------------------------------------------
    def test_05_credit_hold(self):
        Partner = self.env['res.partner']
        check = lambda partner, amount: Partner.alfiafy_pos_credit_check(partner.id, amount, self.config.id)
        self.assertFalse(check(self.customer, 1000)['blocked'])

        invoice = self.init_invoice(
            'out_invoice', partner=self.customer, amounts=[500.0], post=True,
            invoice_date=fields.Date.today() - timedelta(days=40))
        self.assertLess(invoice.invoice_date_due, fields.Date.today())
        result = check(self.customer, 100)
        self.assertTrue(result['blocked'])
        self.assertIn('overdue invoice', result['message'])
        if 'block_on_overdue' in Partner._fields:  # alfiafy_sale installed
            self.customer.block_on_overdue = False
            self.assertFalse(check(self.customer, 100)['blocked'])
            self.customer.block_on_overdue = True

        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertFalse(check(self.customer, 100)['blocked'], "paid in full: hold lifted")

        self.env.company.account_use_credit_limit = True
        self.customer.credit_limit = 300.0
        self.assertFalse(check(self.customer, 250)['blocked'])
        result = check(self.customer, 350)
        self.assertTrue(result['blocked'])
        self.assertIn('Credit limit', result['message'])

    # ------------------------------------------------------------------
    # Multi-UoM (pos_multi_uom_price)
    # ------------------------------------------------------------------
    def test_06_uom_price_rows(self):
        template = self.oxy.product_tmpl_id
        row = self.env['product.tmpl.multi.uom.price'].create({
            'product_tmpl_id': template.id, 'uom_id': self.box10.id, 'price': 500.0})
        variant_row = self.oxy.multi_uom_price_ids
        self.assertEqual((variant_row.uom_id, variant_row.price), (self.box10, 500.0))
        row.price = 480.0
        self.assertEqual(variant_row.price, 480.0)
        with self.assertRaises(ValidationError):  # the product's own unit
            self.env['product.tmpl.multi.uom.price'].create({
                'product_tmpl_id': template.id, 'uom_id': self.unit.id, 'price': 50.0})
        with self.assertRaises(ValidationError):  # not convertible to Units
            self.env['product.tmpl.multi.uom.price'].create({
                'product_tmpl_id': template.id, 'uom_id': self.litre.id, 'price': 50.0})
        row.unlink()
        self.assertFalse(self.oxy.multi_uom_price_ids)

    def test_07_order_in_box_moves_stock(self):
        self.open_new_session()
        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data([
            {'product': self.oxy, 'quantity': 2, 'product_uom_id': self.box10.id},
            {'product': self.oxy, 'quantity': 3},
        ], customer=self.customer)])
        order = self.env['pos.order'].browse(result['pos.order'][0]['id'])
        box_line = order.lines.filtered(lambda l: l.product_uom_id == self.box10)
        self.assertEqual(box_line.qty, 2)
        self.assertEqual(order.picking_ids.state, 'done')
        moves = order.picking_ids.move_ids
        self.assertEqual([(m.uom_id, m.quantity) for m in moves], [(self.unit, 23.0)],
                         "2 Boxes of 10 + 3 Units move 23 Units")
        self.assertEqual(self.oxy.with_context(location=self.stock_location.id).qty_available, 40 - 23)
        # cost of the box line is for 20 units (35.00 each)
        self.assertAlmostEqual(box_line.total_cost, 2 * 10 * 35.0)
        self.assertAlmostEqual(box_line.unit_cost, 350.0)

    def test_08_lot_tracked_product_sold_in_box(self):
        product = self.create_product('Ivermectin lot-tracked (test)', self.ivermectin.categ_id, 45.0, standard_price=30.0)
        product.tracking = 'lot'
        lot = self.env['stock.lot'].create({'name': 'IVM-TEST-01', 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(product, self.stock_location, 50, lot_id=lot)
        self.open_new_session()
        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data([
            {'product': product, 'quantity': 1, 'product_uom_id': self.box10.id,
             'pack_lot_ids': [(0, 0, {'lot_name': 'IVM-TEST-01'})]},
        ], customer=self.customer)])
        order = self.env['pos.order'].browse(result['pos.order'][0]['id'])
        picking = order.picking_ids
        self.assertEqual(picking.state, 'done')
        self.assertFalse(picking.backorder_ids, "the whole box is delivered")
        self.assertEqual([(ml.lot_id, ml.quantity, ml.uom_id) for ml in picking.move_line_ids],
                         [(lot, 10.0, self.unit)])
        self.assertEqual(self.env['stock.quant']._get_available_quantity(
            product, self.stock_location, lot_id=lot, strict=True), 40.0)

    def test_09_refund_single_pieces_of_a_pack(self):
        """Pack of 6 sold at 300.00: 1 piece is returned at the price paid per
        piece (50.00); the back-office refund of the rest is per piece too."""
        self.assertFalse(self.config.block_fractional_return, "fractional returns allowed by default")
        pack6 = self.env['uom.uom'].create({
            'name': 'Pack of 6 (test)', 'relative_factor': 6, 'relative_uom_id': self.unit.id})
        self.open_new_session()

        def line(qty, uom, price, **extra):
            return {'product': self.oxy, 'quantity': qty, 'product_uom_id': uom.id, 'price_unit': price,
                    'price_subtotal': abs(qty * price), 'price_subtotal_incl': abs(qty * price), **extra}

        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data(
            [line(1, pack6, 300.0)], customer=self.customer)])
        sale = self.env['pos.order'].browse(result['pos.order'][0]['id'])
        sold_line = sale.lines
        self.assertEqual(self.oxy.with_context(location=self.stock_location.id).qty_available, 40 - 6)

        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data(
            [line(-1, self.unit, 50.0, refunded_orderline_id=sold_line.id)],
            pos_order_ui_args={'is_refund': True}, customer=self.customer)])
        refund = self.env['pos.order'].browse([o['id'] for o in result['pos.order']]) - sale
        self.assertAlmostEqual(refund.amount_total, -50.0)
        self.assertEqual(refund.lines.product_uom_id, self.unit)
        self.assertAlmostEqual(sold_line.refunded_qty, 1 / 6, places=4, msg="1 piece = 1/6 of the pack")
        self.assertTrue(sale.has_refundable_lines)
        self.assertEqual(self.oxy.with_context(location=self.stock_location.id).qty_available, 40 - 6 + 1,
                         "the returned piece is back in stock")

        rest = sale._refund()
        rest_line = rest.lines
        self.assertEqual(rest_line.product_uom_id, self.unit)
        self.assertAlmostEqual(rest_line.qty, -5.0)
        self.assertAlmostEqual(rest_line.price_unit, 50.0)
