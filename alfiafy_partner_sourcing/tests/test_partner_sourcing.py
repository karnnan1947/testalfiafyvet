# -*- coding: utf-8 -*-
"""DES00139 - Partner vs Outside sourcing: purchase -> lot -> sale / POS ->
invoice -> sourcing margin report (implementation plan, phase 8)."""
from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon

REPORT = 'alfiafy.sourcing.margin.report'
MEASURES = ['qty_invoiced:sum', 'price_subtotal:sum', 'cogs_amount:sum',
            'gross_profit:sum', 'margin_percent:avg']


@tagged('post_install', '-at_install', 'alfiafy')
class TestPartnerSourcing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')  # approver of the purchase step
        Partner = cls.env['res.partner']
        cls.partner_vendor = Partner.create({
            'name': 'Agency Pharma (test)', 'is_company': True, 'vendor_sourcing_type': 'partner'})
        cls.outside_vendor = Partner.create({'name': 'Local Supplies (test)', 'is_company': True})
        cls.customer = Partner.create({'name': 'Wakra Farm (test)', 'phone': '+974 5000 0000'})
        cls.product = cls.env['product.product'].create({
            'name': 'Oxytetracycline LA (sourcing test)',
            'type': 'consu', 'is_storable': True, 'tracking': 'lot',
            'purchase_ok': True, 'sale_ok': True,
            'list_price': 100.0, 'standard_price': 30.0,
            'invoice_policy': 'delivery',
            'taxes_id': [Command.clear()], 'supplier_taxes_id': [Command.clear()],
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _receive(self, vendor, qty, price, lot_name, line_sourcing=None):
        po = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'picking_type_id': self.warehouse.in_type_id.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_qty': qty, 'price_unit': price,
            })],
        })
        if line_sourcing:
            po.order_line.sourcing_type = line_sourcing
        po.action_send_for_approval()
        po.with_user(self.admin).button_approve_po()
        po.button_confirm()
        receipt = po.picking_ids
        receipt.move_ids.move_line_ids.write({'lot_name': lot_name, 'quantity': qty})
        receipt.move_ids.picked = True
        receipt.button_validate()
        self.assertEqual(receipt.state, 'done')
        lot = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', self.product.id)])
        return po, receipt, lot

    def _deliver(self, sale, lots_qty):
        picking = sale.picking_ids
        self.assertEqual(len(picking), 1)
        move = picking.move_ids
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create([{
            'move_id': move.id, 'picking_id': picking.id, 'product_id': self.product.id,
            'lot_id': lot.id, 'quantity': qty, 'uom_id': self.product.uom_id.id,
            'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id,
        } for lot, qty in lots_qty])
        move.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        return picking

    def _sell_15(self):
        """10 units delivered from the partner lot, 5 from the outside lot."""
        _po1, _r1, partner_lot = self._receive(self.partner_vendor, 10, 40.0, 'SRC-PARTNER-01')
        _po2, _r2, outside_lot = self._receive(self.outside_vendor, 20, 25.0, 'SRC-OUTSIDE-01')
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': 15, 'price_unit': 100.0,
                'tax_ids': [Command.clear()],
            })],
        })
        sale.action_confirm()
        self.assertEqual(sale.state, 'sale')
        delivery = self._deliver(sale, [(partner_lot, 10), (outside_lot, 5)])
        return sale, delivery, partner_lot, outside_lot

    # ------------------------------------------------------------------
    # 8.1 / 8.2 inbound
    # ------------------------------------------------------------------
    def test_01_inbound_partner_sourcing(self):
        po, receipt, lot = self._receive(self.partner_vendor, 10, 40.0, 'SRC-PARTNER-A')
        self.assertEqual(po.sourcing_type, 'partner')
        self.assertEqual(po.order_line.sourcing_type, 'partner')
        self.assertEqual(receipt.move_ids.sourcing_type, 'partner')
        self.assertEqual(lot.sourcing_type, 'partner')
        self.assertEqual(lot.origin_po_id, po)
        self.assertEqual(lot.origin_vendor_id, self.partner_vendor)
        self.assertAlmostEqual(lot.origin_unit_cost, 40.0)

    def test_02_inbound_outside_sourcing(self):
        self.assertEqual(self.outside_vendor.vendor_sourcing_type, 'outside', "new vendors default to Outside")
        po, receipt, lot = self._receive(self.outside_vendor, 5, 25.0, 'SRC-OUTSIDE-A')
        self.assertEqual(po.sourcing_type, 'outside')
        self.assertEqual(receipt.sourcing_type, 'outside')
        self.assertEqual(lot.sourcing_type, 'outside')
        self.assertEqual(lot.origin_po_id, po)
        self.assertEqual(lot.origin_vendor_id, self.outside_vendor)
        self.assertAlmostEqual(lot.origin_unit_cost, 25.0)
        # a buyer can mark a line of an official partner's order as outside goods
        po2, _receipt2, lot2 = self._receive(self.partner_vendor, 3, 30.0, 'SRC-NON-AGENCY', line_sourcing='outside')
        self.assertEqual(po2.sourcing_type, 'partner')
        self.assertEqual(lot2.sourcing_type, 'outside')

    # ------------------------------------------------------------------
    # 8.3 sales delivery and invoice
    # ------------------------------------------------------------------
    def test_03_sale_delivery_and_invoice_split(self):
        sale, delivery, partner_lot, outside_lot = self._sell_15()
        self.assertEqual(sorted((ml.lot_id.name, ml.sourcing_type, ml.quantity) for ml in delivery.move_line_ids),
                         [('SRC-OUTSIDE-01', 'outside', 5.0), ('SRC-PARTNER-01', 'partner', 10.0)])
        self.assertEqual(sale.order_line.sourcing_type, 'mixed')
        invoice = sale._create_invoices()
        lines = invoice.invoice_line_ids.filtered(lambda line: line.display_type == 'product')
        self.assertEqual(sorted((line.sourcing_type, line.quantity, line.sourcing_unit_cost) for line in lines),
                         [('outside', 5.0, 25.0), ('partner', 10.0, 40.0)])
        self.assertEqual(lines.sale_line_ids, sale.order_line)
        self.assertAlmostEqual(invoice.amount_untaxed, 1500.0)
        self.assertEqual(sale.order_line.qty_invoiced, 15.0)
        self.assertEqual(sale.order_line.qty_to_invoice, 0.0)

    def test_04_partial_invoices_follow_deliveries(self):
        _po1, _r1, partner_lot = self._receive(self.partner_vendor, 10, 40.0, 'SRC-PARTNER-02')
        _po2, _r2, outside_lot = self._receive(self.outside_vendor, 10, 25.0, 'SRC-OUTSIDE-02')
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id, 'warehouse_id': self.warehouse.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 12,
                                           'price_unit': 100.0, 'tax_ids': [Command.clear()]})],
        })
        sale.action_confirm()
        # first delivery: 8 partner units, invoiced; backorder: 4 outside units
        picking = sale.picking_ids
        move = picking.move_ids
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id, 'picking_id': picking.id, 'product_id': self.product.id,
            'lot_id': partner_lot.id, 'quantity': 8, 'uom_id': self.product.uom_id.id,
            'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id,
        })
        move.picked = True
        picking.with_context(cancel_backorder=False)._action_done()
        first = sale._create_invoices()
        self.assertEqual([(line.sourcing_type, line.quantity) for line in first.invoice_line_ids],
                         [('partner', 8.0)])
        backorder = sale.picking_ids - picking
        self.assertEqual(len(backorder), 1)
        bo_move = backorder.move_ids
        bo_move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': bo_move.id, 'picking_id': backorder.id, 'product_id': self.product.id,
            'lot_id': outside_lot.id, 'quantity': 4, 'uom_id': self.product.uom_id.id,
            'location_id': bo_move.location_id.id, 'location_dest_id': bo_move.location_dest_id.id,
        })
        bo_move.picked = True
        backorder.button_validate()
        second = sale._create_invoices()
        self.assertEqual([(line.sourcing_type, line.quantity) for line in second.invoice_line_ids],
                         [('outside', 4.0)])

    # ------------------------------------------------------------------
    # 8.4 sourcing margin report
    # ------------------------------------------------------------------
    def test_05_sourcing_margin_report(self):
        sale, _delivery, _partner_lot, _outside_lot = self._sell_15()
        invoice = sale._create_invoices()
        invoice.action_post()
        self.env.flush_all()
        Report = self.env[REPORT]
        domain = [('move_id', '=', invoice.id)]
        groups = Report.formatted_read_group(domain, ['sourcing_type'], MEASURES)
        by_sourcing = {group['sourcing_type']: group for group in groups}
        partner, outside = by_sourcing['partner'], by_sourcing['outside']
        self.assertAlmostEqual(partner['qty_invoiced:sum'], 10.0)
        self.assertAlmostEqual(partner['price_subtotal:sum'], 1000.0)
        self.assertAlmostEqual(partner['cogs_amount:sum'], 400.0)
        self.assertAlmostEqual(partner['gross_profit:sum'], 600.0)
        self.assertAlmostEqual(partner['margin_percent:avg'], 60.0)
        self.assertAlmostEqual(outside['qty_invoiced:sum'], 5.0)
        self.assertAlmostEqual(outside['price_subtotal:sum'], 500.0)
        self.assertAlmostEqual(outside['cogs_amount:sum'], 125.0)
        self.assertAlmostEqual(outside['gross_profit:sum'], 375.0)
        self.assertAlmostEqual(outside['margin_percent:avg'], 75.0)
        total = Report.formatted_read_group(domain, [], ['margin_percent:avg'])[0]
        self.assertAlmostEqual(total['margin_percent:avg'], 65.0, msg="975 profit / 1500 revenue")

        # credit note of the partner units: revenue and cost come back out
        refund = invoice._reverse_moves([{'invoice_date': fields.Date.today()}])
        refund.invoice_line_ids.filtered(lambda line: line.sourcing_type == 'outside').unlink()
        refund.action_post()
        self.env.flush_all()
        groups = Report.formatted_read_group(
            [('move_id', 'in', (invoice | refund).ids)], ['sourcing_type'], MEASURES)
        partner = {group['sourcing_type']: group for group in groups}['partner']
        self.assertAlmostEqual(partner['qty_invoiced:sum'], 0.0)
        self.assertAlmostEqual(partner['price_subtotal:sum'], 0.0)
        self.assertAlmostEqual(partner['cogs_amount:sum'], 0.0)

    def test_06_manual_invoice_line_sourcing(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.customer.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id, 'quantity': 2, 'price_unit': 100.0,
                'tax_ids': [Command.clear()], 'sourcing_type': 'partner',
            })],
        })
        invoice.action_post()
        self.env.flush_all()
        row = self.env[REPORT].search([('move_id', '=', invoice.id)])
        self.assertEqual(row.sourcing_type, 'partner')
        self.assertAlmostEqual(row.cogs_amount, 60.0, msg="no lot cost: the product cost (30.00) is used")
        self.assertAlmostEqual(row.margin_percent, 70.0)


@tagged('post_install', '-at_install', 'alfiafy')
class TestPartnerSourcingPos(TestPoSCommon):
    """Phase 4: lot sold in the POS -> POS line -> POS invoice -> report."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        categ = cls.env['product.category'].create({'name': 'Vet (sourcing test)'})
        cls.product = cls.create_product('Ivermectin lot (sourcing test)', categ, 45.0, standard_price=20.0)
        cls.product.tracking = 'lot'
        cls.partner_lot = cls.env['stock.lot'].create({
            'name': 'POS-PARTNER-01', 'product_id': cls.product.id, 'sourcing_type': 'partner'})
        cls.partner_lot.sudo().write({'origin_unit_cost': 27.5})
        location = cls.basic_config.picking_type_id.default_location_src_id
        cls.env['stock.quant']._update_available_quantity(cls.product, location, 50, lot_id=cls.partner_lot)
        cls.customer = cls.env['res.partner'].create({'name': 'Khor Stables (test)', 'phone': '+974 5000 0001'})

    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def _sell(self, qty, invoiced):
        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data([
            {'product': self.product, 'quantity': qty,
             'pack_lot_ids': [(0, 0, {'lot_name': 'POS-PARTNER-01'})]},
        ], customer=self.customer, is_invoiced=invoiced)])
        return self.env['pos.order'].browse(result['pos.order'][0]['id'])

    def test_01_pos_line_and_invoice_sourcing(self):
        self.assertEqual(
            self.env['stock.lot'].alf_pos_lot_sourcing(self.product.id, ['POS-PARTNER-01']),
            {'POS-PARTNER-01': 'partner'})
        self.assertIn('sourcing_type', self.env['pos.order.line']._load_pos_data_fields(self.config))
        self.open_new_session()
        order = self._sell(2, invoiced=True)
        self.assertEqual(order.lines.sourcing_type, 'partner')
        self.assertAlmostEqual(order.lines.sourcing_unit_cost, 27.5)
        invoice_line = order.account_move.invoice_line_ids.filtered(lambda line: line.display_type == 'product')
        self.assertEqual((invoice_line.sourcing_type, invoice_line.sourcing_unit_cost), ('partner', 27.5))
        self.assertEqual(order.picking_ids.move_line_ids.sourcing_type, 'partner')

    def test_02_report_includes_pos_orders_not_invoiced(self):
        self.open_new_session()
        order = self._sell(3, invoiced=False)
        self.assertFalse(order.account_move)
        self.env.flush_all()
        row = self.env[REPORT].search([('pos_order_id', '=', order.id)])
        self.assertEqual((row.origin, row.sourcing_type), ('pos', 'partner'))
        self.assertAlmostEqual(row.qty_invoiced, 3.0)
        self.assertAlmostEqual(row.price_subtotal, 135.0)
        self.assertAlmostEqual(row.cogs_amount, 82.5)
        self.assertAlmostEqual(row.gross_profit, 52.5)

    def test_03_report_pos_refund_is_negative(self):
        """POS line amounts are positive in Odoo 20: a refund must reduce revenue and cost."""
        self.open_new_session()
        order = self._sell(3, invoiced=False)
        result = self.env['pos.order'].sync_from_ui([self.create_ui_order_data([
            {'product': self.product, 'quantity': -1,
             'refunded_orderline_id': order.lines.id,
             'pack_lot_ids': [(0, 0, {'lot_name': 'POS-PARTNER-01'})]},
        ], {'is_refund': True}, customer=self.customer)])
        # the result also returns the refunded order
        refund = self.env['pos.order'].browse([vals['id'] for vals in result['pos.order']]).filtered('is_refund')
        self.assertEqual(len(refund), 1)
        self.assertEqual(refund.lines.sourcing_type, 'partner')
        self.env.flush_all()
        row = self.env[REPORT].search([('pos_order_id', '=', refund.id)])
        self.assertAlmostEqual(row.qty_invoiced, -1.0)
        self.assertAlmostEqual(row.price_subtotal, -45.0)
        self.assertAlmostEqual(row.cogs_amount, -27.5)
        self.assertAlmostEqual(row.gross_profit, -17.5)
        rows = self.env[REPORT].search([('pos_order_id', 'in', (order | refund).ids)])
        self.assertAlmostEqual(sum(rows.mapped('price_subtotal')), 90.0)
        self.assertAlmostEqual(sum(rows.mapped('cogs_amount')), 55.0)
