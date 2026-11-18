# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestApprovalStepsV20(TransactionCase):
    """Smoke tests of the Odoo 20 port: sale and purchase approval chains."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = new_test_user(
            cls.env, login='apv_manager', name='Sales Manager',
            groups='base.group_user,sales_team.group_sale_manager,purchase.group_purchase_manager')
        cls.salesman = new_test_user(
            cls.env, login='apv_salesman', name='Salesman',
            groups='base.group_user,sales_team.group_sale_salesman_all_leads,purchase.group_purchase_user')
        Steps = cls.env['approval.steps']
        Steps.search([]).unlink()
        Steps.create([
            {'type': 'sale', 'sequence': 10, 'user_id': cls.approver.id,
             'sale_criteria_type': 'amount', 'amount_operator': '>', 'amount_value': 1000},
            {'type': 'purchase', 'sequence': 10, 'user_id': cls.approver.id,
             'amount_operator': '>', 'amount_value': 1000},
        ])
        cls.product = cls.env['product.product'].create({
            'name': 'Approval test product', 'type': 'consu', 'list_price': 600.0, 'standard_price': 400.0,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Approval partner'})

    def test_sale_order_needs_approval_above_threshold(self):
        so = self.env['sale.order'].with_user(self.salesman).create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 3, 'tax_ids': False})],
        })
        self.assertTrue(so.approval_required)
        with self.assertRaises(UserError):
            so.action_confirm()
        so.action_send_for_approval()
        self.assertEqual(so.state, 'to_approve')
        with self.assertRaises(AccessError):
            so.button_approve()
        so.with_user(self.approver).button_approve()
        self.assertEqual((so.state, so.approval_status), ('draft', 'approved'))
        so.action_confirm()
        self.assertEqual(so.state, 'sale')

    def test_small_sale_order_confirms_directly(self):
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1, 'tax_ids': False})],
        })
        self.assertFalse(so.approval_required)
        so.action_confirm()
        self.assertEqual(so.state, 'sale')

    def test_purchase_rejection_needs_reason(self):
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_qty': 5, 'price_unit': 400.0, 'tax_ids': False})],
        })
        if 'sourcing_type' in po._fields:  # alfiafy_purchase requires it
            po.sourcing_type = 'outside'
        po.action_send_for_approval()
        action = po.with_user(self.approver).button_cancel()
        self.assertEqual(action['res_model'], 'approval.cancel.wizard')
        wizard = self.env['approval.cancel.wizard'].with_user(self.approver).with_context(action['context']).create(
            {'reason': 'Price too high'})
        wizard.action_confirm_cancel()
        self.assertEqual((po.state, po.approval_status), ('cancel', 'cancelled'))


@tagged('post_install', '-at_install')
class TestInternalTransferApprovalSteps(TransactionCase):
    """Internal Transfer approval steps: Type, Sequence, User, Source Warehouse.

    Written to pass with or without alfiafy_stock (which adds Dispatch Goods /
    Confirm Receipt on top of the approval)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = 'base.group_user,stock.group_stock_user'
        cls.requester = new_test_user(cls.env, login='itr_requester', name='Transfer Requester', groups=groups)
        cls.approver_10 = new_test_user(cls.env, login='itr_storekeeper', name='Storekeeper Step 10', groups=groups)
        cls.approver_10b = new_test_user(cls.env, login='itr_ops', name='Operations Manager Step 10', groups=groups)
        cls.approver_20 = new_test_user(cls.env, login='itr_director', name='Director Step 20', groups=groups)
        cls.env['approval.steps'].search([]).unlink()
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.other_wh = cls.env['stock.warehouse'].create({'name': 'Approval Test WH', 'code': 'ATW'})
        cls.shelf = cls.env['stock.location'].create({
            'name': 'Approval Shelf', 'usage': 'internal', 'location_id': cls.warehouse.lot_stock_id.id})
        cls.product = cls.env['product.product'].create({'name': 'Transfer approval product', 'is_storable': True})
        cls.env['stock.quant']._update_available_quantity(cls.product, cls.warehouse.lot_stock_id, 50)

    def _steps(self, *rows):
        return self.env['approval.steps'].create([
            {'type': 'internal_transfer', 'sequence': seq, 'user_id': user.id,
             'warehouse_id': wh.id if wh else False}
            for seq, user, wh in rows])

    def _transfer(self, qty=5, warehouse=None):
        """Draft internal transfer raised by the requester, to a shelf of the
        main warehouse."""
        warehouse = warehouse or self.warehouse
        picking = self.env['stock.picking'].with_user(self.requester).create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.shelf.id,
            'move_ids': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': qty,
                'location_id': warehouse.lot_stock_id.id, 'location_dest_id': self.shelf.id,
            })],
        })
        return picking.with_env(self.env)

    def _approval_activities(self, picking):
        activity_type = self.env.ref('sale_and_purchase_approvals_steps.mail_activity_data_approval')
        return picking.activity_ids.filtered(
            lambda a: a.activity_type_id == activity_type and a.summary == 'Approval Required')

    def test_step_configuration(self):
        step_all, step_wh = self._steps((10, self.approver_10, None), (20, self.approver_20, self.other_wh))
        # no amount condition is needed for an internal transfer step
        step_all.write({'amount_operator': False, 'amount_value': 0})
        self.assertEqual(step_all.condition_display, 'All Internal Transfers')
        self.assertEqual(step_wh.condition_display, 'Internal Transfers from Approval Test WH')
        self.assertEqual(self._transfer()._get_matching_internal_transfer_steps(), step_all)
        other = self._transfer(warehouse=self.other_wh)
        self.assertEqual(other._get_matching_internal_transfer_steps(), step_all | step_wh)
        # the steps only apply to internal transfers
        delivery = self.env['stock.picking'].new({'picking_type_id': self.warehouse.out_type_id.id})
        self.assertFalse(step_all._matches_internal_transfer(delivery))

    def test_sequence_chain(self):
        self._steps((10, self.approver_10, None), (20, self.approver_20, None))
        picking = self._transfer()
        self.assertTrue(picking.with_user(self.requester).can_submit_internal_approval)
        with self.assertRaises(UserError):
            picking.with_user(self.requester).button_validate()
        picking.with_user(self.requester).action_submit_internal_transfer_approval()
        self.assertEqual((picking.state, picking.approval_status, picking.approval_step_sequence),
                         ('to_approve', 'to_approve', 10))
        self.assertFalse(picking.can_submit_internal_approval)
        self.assertEqual(self._approval_activities(picking).user_id, self.approver_10)
        # neither the requester nor the step 20 approver can approve step 10
        for user in (self.requester, self.approver_20):
            self.assertFalse(picking.with_user(user).show_approve_button)
            with self.assertRaises(AccessError):
                picking.with_user(user).button_approve_delivery()
        with self.assertRaises(UserError):
            picking.with_user(self.approver_10).button_validate()
        # Inventory > Operations > My Approvals
        my_approvals = self.env['stock.picking'].with_user(self.approver_10).search(
            [('show_approve_button', '=', True)])
        self.assertIn(picking, my_approvals)

        picking.with_user(self.approver_10).button_approve_delivery()
        self.assertEqual((picking.state, picking.approval_step_sequence), ('to_approve', 20))
        self.assertEqual(self._approval_activities(picking).user_id, self.approver_20)
        with self.assertRaises(AccessError):
            picking.with_user(self.approver_10).button_approve_delivery()

        picking.with_user(self.approver_20).button_approve_delivery()
        self.assertEqual(picking.approval_status, 'approved')
        self.assertIn(picking.state, ('confirmed', 'assigned'))
        self.assertFalse(self._approval_activities(picking))
        if 'transfer_status' not in picking._fields:  # alfiafy_stock adds Dispatch / Receipt
            picking.move_ids.write({'quantity': 5, 'picked': True})
            picking.with_user(self.approver_10).button_validate()
            self.assertEqual(picking.state, 'done')

    def test_parallel_approvers(self):
        self._steps((10, self.approver_10, None), (10, self.approver_10b, None), (20, self.approver_20, None))
        picking = self._transfer()
        picking.with_user(self.requester).action_submit_internal_transfer_approval()
        self.assertEqual(self._approval_activities(picking).user_id, self.approver_10 | self.approver_10b)
        self.assertTrue(picking.with_user(self.approver_10b).show_approve_button)
        # either approver of step 10 can approve it; the other one's activity goes away
        picking.with_user(self.approver_10b).button_approve_delivery()
        self.assertEqual(picking.approval_step_sequence, 20)
        self.assertEqual(self._approval_activities(picking).user_id, self.approver_20)
        picking.with_user(self.approver_20).button_approve_delivery()
        self.assertEqual(picking.approval_status, 'approved')

    def test_rejection_needs_reason(self):
        self._steps((10, self.approver_10, None))
        picking = self._transfer()
        picking.with_user(self.requester).action_submit_internal_transfer_approval()
        action = picking.with_user(self.approver_10).action_cancel()
        self.assertEqual(action['res_model'], 'approval.cancel.wizard')
        self.assertTrue(action['context']['default_is_approver'])
        wizard = self.env['approval.cancel.wizard'].with_user(self.approver_10).with_context(
            action['context']).create({'reason': 'Branch is overstocked'})
        wizard.action_confirm_cancel()
        self.assertEqual((picking.state, picking.approval_status), ('cancel', 'cancelled'))
        self.assertTrue(any('Branch is overstocked' in (m.body or '') for m in picking.message_ids))
        # someone who is neither approver nor requester cannot cancel during approval
        other = self._transfer()
        other.with_user(self.requester).action_submit_internal_transfer_approval()
        with self.assertRaises(AccessError):
            other.with_user(self.approver_20).action_cancel()

    def test_no_steps_no_approval(self):
        picking = self._transfer()
        self.assertFalse(picking.can_submit_internal_approval)
        with self.assertRaises(UserError):
            picking.action_submit_internal_transfer_approval()
