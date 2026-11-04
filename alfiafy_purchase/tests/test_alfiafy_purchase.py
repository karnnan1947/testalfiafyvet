# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'alfiafy')
class TestAlfiafyPurchase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')  # approver of the "all POs" step
        cls.buyer = new_test_user(
            cls.env, login='alf_buyer', name='Branch Buyer',
            groups='base.group_user,purchase.group_purchase_user,stock.group_stock_user')
        Partner = cls.env['res.partner']
        cls.partner_vendor = Partner.create({
            'name': 'Official Partner Pharma', 'is_company': True,
            'vendor_sourcing_type': 'partner', 'default_purchase_type': 'import',
        })
        cls.outside_vendor = Partner.create({
            'name': 'Doha Outside Supplies', 'is_company': True,
            'vendor_sourcing_type': 'outside', 'default_purchase_type': 'local',
        })
        # explicit: alfiafy_partner_sourcing defaults new vendors to Outside
        cls.unclassified_vendor = Partner.create({
            'name': 'Unclassified Vendor', 'is_company': True, 'vendor_sourcing_type': False})
        cls.product = cls.env['product.product'].create({
            'name': 'Oxytetracycline 20% LA 100ml (test)',
            'active_ingredient': 'Oxytetracycline',
            'type': 'consu', 'is_storable': True, 'tracking': 'lot',
            'purchase_ok': True, 'standard_price': 30.0,
            'supplier_id': cls.outside_vendor.id,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _create_po(self, vendor, price, qty=10.0, user=None):
        env = self.env(user=user) if user else self.env
        return env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_qty': qty, 'price_unit': price,
            })],
        })

    def _approve_and_confirm(self, po):
        po.action_send_for_approval()
        po.with_user(self.admin).button_approve_po()
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        return po

    # ------------------------------------------------------------------
    # 1. vendor auto-fill
    # ------------------------------------------------------------------
    def test_01_vendor_autofill(self):
        po_form = Form(self.env['purchase.order'])
        po_form.partner_id = self.partner_vendor
        self.assertEqual(po_form.purchase_type, 'import')
        self.assertEqual(po_form.sourcing_type, 'partner')
        po_form.partner_id = self.outside_vendor
        self.assertEqual(po_form.purchase_type, 'local')
        self.assertEqual(po_form.sourcing_type, 'outside')
        # a contact of the vendor company follows the company classification
        contact = self.env['res.partner'].create({'name': 'Sales Rep', 'parent_id': self.partner_vendor.id})
        self.assertEqual(contact.vendor_sourcing_type, 'partner')
        po = self.env['purchase.order'].create({'partner_id': contact.id})
        self.assertEqual((po.purchase_type, po.sourcing_type), ('import', 'partner'))

    # ------------------------------------------------------------------
    # 2. last price and trend
    # ------------------------------------------------------------------
    def test_02_last_price_and_trend(self):
        self._approve_and_confirm(self._create_po(self.partner_vendor, 100.0))
        po2 = self._create_po(self.partner_vendor, 120.0)
        line = po2.order_line
        self.assertEqual(line.last_purchase_price, 100.0)
        self.assertEqual(line.price_trend, 'up')
        line.price_unit = 80.0
        self.assertEqual(line.price_trend, 'down')
        line.price_unit = 100.0
        self.assertEqual(line.price_trend, 'same')
        # never bought from this vendor -> no previous price, no trend
        other = self._create_po(self.outside_vendor, 90.0).order_line
        self.assertFalse(other.last_purchase_date)
        self.assertFalse(other.price_trend)

    # ------------------------------------------------------------------
    # 3. price history popup: last 10, all vendors
    # ------------------------------------------------------------------
    def test_03_price_history_popup(self):
        for i in range(6):
            self._approve_and_confirm(self._create_po(self.partner_vendor, 100.0 + i))
            self._approve_and_confirm(self._create_po(self.outside_vendor, 90.0 + i))
        draft = self._create_po(self.partner_vendor, 110.0)
        action = draft.order_line.action_open_price_history()
        self.assertEqual(action['res_model'], 'purchase.price.history.wizard')
        self.assertEqual(action['target'], 'new')
        wizard = self.env['purchase.price.history.wizard'].browse(action['res_id'])
        history = wizard.history_line_ids
        self.assertEqual(len(history), 10, "Only the last 10 purchases are listed")
        self.assertEqual(set(history.partner_id.ids), {self.partner_vendor.id, self.outside_vendor.id},
                         "History covers all vendors")
        self.assertNotIn(draft.order_line, history, "Unconfirmed RFQs are not history")
        self.assertEqual(set(history.mapped('order_sourcing_type')), {'partner', 'outside'})
        self.assertEqual(wizard.current_price, 110.0)

    # ------------------------------------------------------------------
    # 4. import tab is only shown for imports
    # ------------------------------------------------------------------
    def test_04_import_tracking_tab(self):
        arch = self.env['purchase.order'].get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('name="alfiafy_import_tracking"', arch)
        self.assertIn("purchase_type != 'import'", arch)
        po = self._create_po(self.partner_vendor, 50.0)
        po.write({'container_no': 'MSCU1234567', 'etd': '2026-11-01', 'eta': '2026-11-20',
                  'shipment_status': 'in_transit'})
        with self.assertRaises(Exception):
            po.write({'eta': '2026-10-01'})  # ETA before ETD

    # ------------------------------------------------------------------
    # 5. sourcing hand-over: PO -> receipt -> lot
    # ------------------------------------------------------------------
    def test_05_sourcing_handover_to_receipt_and_lot(self):
        po = self._approve_and_confirm(self._create_po(self.partner_vendor, 100.0, qty=5))
        receipt = po.picking_ids
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt.sourcing_type, 'partner')
        self.assertEqual(receipt.purchase_type, 'import')
        receipt.move_ids.move_line_ids.write({'lot_name': 'OXY-PARTNER-001', 'quantity': 5})
        receipt.move_ids.picked = True
        receipt.button_validate()
        self.assertEqual(receipt.state, 'done')
        lot = self.env['stock.lot'].search([('name', '=', 'OXY-PARTNER-001'), ('product_id', '=', self.product.id)])
        self.assertEqual(lot.sourcing_type, 'partner')

        # same product, outside supplier -> a separate lot tagged "outside"
        po2 = self._approve_and_confirm(self._create_po(self.outside_vendor, 80.0, qty=3))
        receipt2 = po2.picking_ids
        self.assertEqual(receipt2.sourcing_type, 'outside')
        receipt2.move_ids.move_line_ids.write({'lot_name': 'OXY-OUTSIDE-001', 'quantity': 3})
        receipt2.move_ids.picked = True
        receipt2.button_validate()
        lot2 = self.env['stock.lot'].search([('name', '=', 'OXY-OUTSIDE-001')])
        self.assertEqual(lot2.sourcing_type, 'outside')

    # ------------------------------------------------------------------
    # 6. material requisition -> draft local RFQ
    # ------------------------------------------------------------------
    def test_06_material_requisition_flow(self):
        Req = self.env['material.purchase.requisition'].with_user(self.buyer)
        req = Req.create({
            'purpose': 'Branch 3 replenishment',
            'line_ids': [Command.create({'product_id': self.product.id, 'product_qty': 24})],
        })
        self.assertRegex(req.name, r'^MPR/\d{4}/\d{5}$')
        self.assertEqual(req.state, 'draft')
        req.action_submit()
        self.assertEqual(req.state, 'to_approve')
        with self.assertRaises(UserError):
            req.action_approve()  # a plain purchase user cannot approve
        req.with_user(self.admin).action_approve()
        self.assertEqual(req.state, 'approved')
        self.assertEqual(req.approved_by_id, self.admin)
        req.action_create_purchase_order()
        self.assertEqual(req.state, 'done')
        po = req.purchase_ids
        self.assertEqual(len(po), 1)
        self.assertEqual(po.state, 'draft')
        self.assertEqual(po.purchase_type, 'local', "Requisition RFQs are pre-tagged Local Purchase")
        self.assertEqual(po.partner_id, self.outside_vendor, "Vendor taken from the product Supplier")
        self.assertEqual(po.sourcing_type, 'outside')
        self.assertEqual(po.origin, req.name)
        self.assertEqual(po.order_line.product_qty, 24)
        self.assertTrue(po.approval_blocked, "The generated RFQ still needs PO approval")

    # ------------------------------------------------------------------
    # 7. approval lock
    # ------------------------------------------------------------------
    def test_07_approval_lock(self):
        po = self._create_po(self.outside_vendor, 75.0, user=self.buyer)
        self.assertTrue(po.approval_required, "Every purchase order requires approval")
        with self.assertRaises(UserError):
            po.button_confirm()
        po.action_send_for_approval()
        self.assertEqual(po.state, 'to_approve')
        with self.assertRaises(AccessError):
            po.button_approve_po()  # the buyer is not an approver
        po.with_user(self.admin).button_approve_po()
        self.assertEqual(po.approval_status, 'approved')
        self.assertEqual(po.state, 'draft', "Approval hands the RFQ back; it is not auto-confirmed")
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')

    def test_08_sourcing_required_before_approval(self):
        po = self._create_po(self.unclassified_vendor, 10.0)
        self.assertFalse(po.sourcing_type)
        self.assertEqual(po.purchase_type, 'local', "Purchase type falls back to Local Purchase")
        with self.assertRaises(UserError):
            po.action_send_for_approval()
        po.sourcing_type = 'outside'
        po.action_send_for_approval()
        self.assertEqual(po.state, 'to_approve')
