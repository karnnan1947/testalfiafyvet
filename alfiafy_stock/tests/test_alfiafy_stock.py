# -*- coding: utf-8 -*-
"""DES00138 alfiafy_stock - verification checklist of the implementation plan."""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.alfiafy_stock.models.stock_picking import DELAY_ACTIVITY_SUMMARY
from odoo.addons.alfiafy_stock.models.stock_quant import APPROVAL_ACTIVITY_SUMMARY


@tagged('post_install', '-at_install', 'alfiafy')
class TestAlfiafyStock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Warehouse = cls.env['stock.warehouse']
        cls.main_wh = Warehouse.search([('company_id', '=', cls.company.id)], limit=1)
        cls.branch1 = Warehouse.create({'name': 'Test Branch One', 'code': 'TB1'})
        cls.branch2 = Warehouse.create({'name': 'Test Branch Two', 'code': 'TB2'})

        stock_user = cls.env.ref('stock.group_stock_user')
        stock_manager = cls.env.ref('stock.group_stock_manager')

        def user(login, name, group, warehouse):
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': name, 'login': login, 'email': '%s@example.com' % login,
                'group_ids': [Command.set([cls.env.ref('base.group_user').id, group.id])],
                'property_warehouse_id': warehouse.id,
            })
        cls.storekeeper = user('t_storekeeper', 'Storekeeper (test)', stock_user, cls.main_wh)
        cls.branch1_user = user('t_branch1', 'Branch One User (test)', stock_user, cls.branch1)
        cls.branch2_user = user('t_branch2', 'Branch Two User (test)', stock_user, cls.branch2)
        cls.manager = user('t_stock_manager', 'Stock Manager (test)', stock_manager, cls.main_wh)

        cls.product = cls.env['product.product'].create({
            'name': 'Ivermectin 1% (branch test)', 'is_storable': True,
            'standard_price': 100.0, 'max_transfer_qty': 10.0,
        })
        Quant = cls.env['stock.quant']
        Quant._update_available_quantity(cls.product, cls.main_wh.lot_stock_id, 100)
        Quant._update_available_quantity(cls.product, cls.branch1.lot_stock_id, 30)
        # tests 1-8: direct storekeeper approval (no Internal Transfer approval step)
        cls.env['approval.steps'].search([('type', '=', 'internal_transfer')]).unlink()

    def _transfer(self, user, source_wh, dest_wh, qty, product=None):
        product = product or self.product
        return self.env['stock.picking'].with_user(user).create({
            'picking_type_id': source_wh.int_type_id.id,
            'location_id': source_wh.lot_stock_id.id,
            'location_dest_id': dest_wh.lot_stock_id.id,
            'move_ids': [Command.create({
                'product_id': product.id, 'product_uom_qty': qty,
                'location_id': source_wh.lot_stock_id.id, 'location_dest_id': dest_wh.lot_stock_id.id,
            })],
        })

    def _qty(self, warehouse, product=None):
        return (product or self.product).with_context(warehouse_id=warehouse.id).qty_available

    # 1. transfer limit
    def test_01_branch_transfer_limit(self):
        with self.assertRaisesRegex(UserError, 'transfer limit exceeded'):
            self._transfer(self.branch1_user, self.branch1, self.branch2, 15)
        ok = self._transfer(self.branch1_user, self.branch1, self.branch2, 10)
        self.assertEqual(ok.move_ids.product_uom_qty, 10)
        with self.assertRaisesRegex(UserError, 'transfer limit exceeded'):
            ok.move_ids.with_user(self.branch1_user).product_uom_qty = 12
        # management may authorise more; main warehouse resupply is not limited
        self.assertTrue(self._transfer(self.manager, self.branch1, self.branch2, 15))
        self.assertTrue(self._transfer(self.storekeeper, self.main_wh, self.branch1, 50))

    # 2. status lifecycle
    def test_02_transfer_status_lifecycle(self):
        picking = self._transfer(self.branch1_user, self.main_wh, self.branch1, 20)
        self.assertEqual(picking.transfer_status, 'draft')
        # requester from another branch cannot approve, dispatch, or validate directly
        self.assertFalse(picking.with_user(self.branch1_user).can_dispatch_transfer)
        with self.assertRaises(AccessError):
            picking.with_user(self.branch1_user).action_approve_transfer()
        with self.assertRaisesRegex(UserError, 'cannot be validated directly'):
            picking.with_user(self.branch1_user).button_validate()
        with self.assertRaisesRegex(UserError, 'cannot be validated directly'):
            picking.with_user(self.storekeeper).button_validate()
        # storekeeper of the dispatching warehouse reviews, approves, and dispatches
        self.assertTrue(picking.with_user(self.storekeeper).can_dispatch_transfer)
        picking.with_user(self.storekeeper).action_approve_transfer()
        self.assertEqual(picking.transfer_status, 'approved')
        with self.assertRaises(AccessError):
            picking.with_user(self.branch1_user).action_dispatch_goods()
        with self.assertRaisesRegex(UserError, 'cannot be validated directly'):
            picking.with_user(self.storekeeper).button_validate()
        picking.with_user(self.storekeeper).action_dispatch_goods()
        self.assertEqual((picking.transfer_status, picking.state), ('transit', 'assigned'))
        self.assertTrue(picking.dispatch_date)
        self.assertFalse(picking.is_delayed)
        with self.assertRaisesRegex(UserError, 'not been dispatched'):
            self._transfer(self.storekeeper, self.main_wh, self.branch1, 1).action_confirm_receipt()
        picking.with_user(self.branch1_user).action_confirm_receipt()
        self.assertEqual((picking.transfer_status, picking.state), ('done', 'done'))
        self.assertEqual(self._qty(self.branch1), 50)
        self.assertEqual(self._qty(self.main_wh), 80)

    # 3. delayed transit alert
    def test_03_delayed_transit_alert(self):
        picking = self._transfer(self.storekeeper, self.main_wh, self.branch1, 5)
        picking.action_approve_transfer()
        picking.action_dispatch_goods()
        picking.dispatch_date = fields.Datetime.now() - timedelta(hours=49)
        self.assertTrue(picking.is_delayed)
        self.env['stock.picking']._cron_check_delayed_transfers()
        activities = picking.activity_ids.filtered(lambda a: a.summary == DELAY_ACTIVITY_SUMMARY)
        # users of the dispatching warehouse (storekeeper, manager) and of the receiving branch,
        # plus any user of the database whose default warehouse is one of the two
        expected = self.env['res.users'].search([
            ('property_warehouse_id', 'in', (self.main_wh | self.branch1).ids), ('share', '=', False)])
        self.assertEqual(activities.user_id, expected)
        self.assertLessEqual(self.storekeeper | self.manager | self.branch1_user, activities.user_id)
        self.assertNotIn(self.branch2_user, activities.user_id)
        self.env['stock.picking']._cron_check_delayed_transfers()
        self.assertEqual(picking.activity_ids.filtered(lambda a: a.summary == DELAY_ACTIVITY_SUMMARY), activities)
        # less than 48 hours: no alert
        recent = self._transfer(self.storekeeper, self.main_wh, self.branch1, 5)
        recent.action_approve_transfer()
        recent.action_dispatch_goods()
        self.env['stock.picking']._cron_check_delayed_transfers()
        self.assertFalse(recent.activity_ids)

    # 4 + 5. variance approval
    def test_04_variance_approval(self):
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', self.branch1.lot_stock_id.id)])
        counted = quant.with_user(self.branch1_user).with_context(inventory_mode=True)
        counted.inventory_quantity = 24          # -6 x 100 = -600, above 500
        self.assertTrue(quant.variance_exceeded)
        res = counted.action_apply_inventory()
        self.assertEqual(res['params']['type'], 'warning')
        self.assertEqual(quant.quantity, 30)     # not applied
        self.assertEqual(quant.approval_state, 'to_approve')
        activities = self.product.product_tmpl_id.activity_ids.filtered(
            lambda a: a.summary == APPROVAL_ACTIVITY_SUMMARY)
        self.assertIn(self.manager, activities.user_id)
        self.assertEqual(self.env['stock.quant'].search_count(
            [('approval_state', '=', 'to_approve'), ('id', '=', quant.id)]), 1)
        # the Stock Manager approves by applying it
        quant.with_user(self.manager).with_context(inventory_mode=True).action_apply_inventory()
        self.assertEqual(quant.quantity, 24)
        self.assertEqual(quant.approval_state, 'approved')

    def test_05_small_variance_applied_directly(self):
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id', '=', self.branch1.lot_stock_id.id)])
        counted = quant.with_user(self.branch1_user).with_context(inventory_mode=True)
        counted.inventory_quantity = 28          # -2 x 100 = -200
        self.assertFalse(quant.variance_exceeded)
        counted.action_apply_inventory()
        self.assertEqual(quant.quantity, 28)
        self.assertEqual(quant.approval_state, 'draft')

    # 6. branch-specific expiry alert
    def test_06_branch_near_expiry_digest(self):
        product = self.env['product.product'].create({
            'name': 'Oxytetracycline LA (expiry test)', 'is_storable': True,
            'tracking': 'lot', 'use_expiration_date': True, 'expiry_alert_days': 180,
        })
        now = fields.Datetime.now()
        Lot = self.env['stock.lot']
        Quant = self.env['stock.quant']
        for name, days, warehouse in (('EXP-TEST', -5, self.branch1), ('NEAR-TEST', 90, self.branch1),
                                      ('FAR-TEST', 400, self.branch1), ('NEAR2-TEST', 60, self.branch2)):
            lot = Lot.create({'name': name, 'product_id': product.id, 'expiration_date': now + timedelta(days=days)})
            Quant._update_available_quantity(product, warehouse.lot_stock_id, 5, lot_id=lot)
        mails = self.env['stock.lot']._cron_branch_near_expiry_alerts()
        mail1 = mails.filtered(lambda m: self.branch1.name in m.subject)
        mail2 = mails.filtered(lambda m: self.branch2.name in m.subject)
        self.assertEqual(len(mail1), 1)
        self.assertIn(self.branch1_user.partner_id, mail1.recipient_ids)
        self.assertIn(self.manager.partner_id, mail1.recipient_ids)
        self.assertNotIn(self.branch2_user.partner_id, mail1.recipient_ids)
        self.assertNotIn(self.storekeeper.partner_id, mail1.recipient_ids)
        self.assertIn('EXP-TEST', mail1.body_html)
        self.assertIn('NEAR-TEST', mail1.body_html)
        self.assertNotIn('FAR-TEST', mail1.body_html)
        self.assertIn('#f8d7da', mail1.body_html)       # expired highlighted in red
        self.assertIn('1 expired', mail1.subject)
        self.assertIn(self.branch2_user.partner_id, mail2.recipient_ids)
        self.assertNotIn(self.branch1_user.partner_id, mail2.recipient_ids)

    # 7. scrap restricted to the Stock Manager
    def test_07_scrap_manager_only(self):
        def scrap(user):
            return self.env['stock.move'].with_user(user).create({
                'product_id': self.product.id, 'product_uom_qty': 1, 'quantity': 1,
                'location_id': self.branch1.lot_stock_id.id,
                'location_dest_id': self.company.scrap_location_id.id or self.env.ref('stock.stock_location_scrapped').id,
                'is_scrap': True,
            })
        with self.assertRaises(AccessError):
            scrap(self.branch1_user).action_scrap()
        move = scrap(self.manager)
        move.action_scrap()
        self.assertEqual(move.state, 'done')
        manager_group = self.env.ref('stock.group_stock_manager')
        for xmlid in ('stock.stock_scrapped_moves_action', 'stock.action_scrap_picking',
                      'stock.action_scrap_lot', 'stock.menu_stock_scrap'):
            self.assertEqual(self.env.ref(xmlid).group_ids, manager_group, xmlid)

    # 8. branch-wise stock visibility control (BRD 1.5 #5)
    def test_08_branch_visibility(self):
        # Put 12 units in branch2 so branch2_user has own-branch stock to verify
        self.env['stock.quant']._update_available_quantity(
            self.product, self.branch2.lot_stock_id, 12
        )
        Quant = self.env['stock.quant'].with_user(self.branch2_user)
        prod_b2 = self.product.with_user(self.branch2_user)

        # Default: branch2_user sees ONLY branch2 stock (main_wh and branch1 hidden)
        self.assertTrue(Quant.search([('location_id', '=', self.branch2.lot_stock_id.id)]))
        self.assertFalse(Quant.search([('location_id', '=', self.branch1.lot_stock_id.id)]))
        self.assertFalse(Quant.search([('location_id', '=', self.main_wh.lot_stock_id.id)]))
        self.assertEqual(prod_b2.qty_available, 12)
        with self.assertRaises(AccessError):
            self.env['product.value'].with_user(self.branch2_user).search([], limit=1)

        # Granular grant: add main_wh to Additional Visible Stock Warehouses
        self.branch2_user.visible_stock_warehouse_ids = [Command.set([self.main_wh.id])]
        self.env.invalidate_all()
        self.assertTrue(Quant.search([('location_id', '=', self.main_wh.lot_stock_id.id)]))
        self.assertFalse(Quant.search([('location_id', '=', self.branch1.lot_stock_id.id)]))
        self.assertEqual(prod_b2.qty_available, 112)

        # All-branches group grant: sees main_wh, branch1, and branch2 (valuation still blocked)
        all_branches_grp = self.env.ref('alfiafy_stock.group_stock_all_branches')
        self.branch2_user.group_ids = [Command.link(all_branches_grp.id)]
        self.env.invalidate_all()
        self.assertTrue(Quant.search([('location_id', '=', self.branch1.lot_stock_id.id)]))
        self.assertTrue(Quant.search([('location_id', '=', self.main_wh.lot_stock_id.id)]))
        self.assertEqual(prod_b2.qty_available, 142)
        with self.assertRaises(AccessError):
            self.env['product.value'].with_user(self.branch2_user).search([], limit=1)

        # Stock Manager automatically sees all branches
        QuantMgr = self.env['stock.quant'].with_user(self.manager)
        self.assertTrue(QuantMgr.search([('location_id', '=', self.branch1.lot_stock_id.id)]))
        self.assertTrue(QuantMgr.search([('location_id', '=', self.branch2.lot_stock_id.id)]))
        self.assertTrue(QuantMgr.search([('location_id', '=', self.main_wh.lot_stock_id.id)]))

    # 9-13. Internal Transfer approval steps (sale_and_purchase_approvals_steps)
    def _internal_steps(self, *rows):
        return self.env['approval.steps'].create([
            {'type': 'internal_transfer', 'sequence': seq, 'user_id': user.id,
             'warehouse_id': warehouse.id if warehouse else False}
            for seq, user, warehouse in rows])

    def _ops_manager(self):
        """An approver who is neither a Stock Manager nor a user of the dispatching warehouse."""
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Operations Manager (test)', 'login': 't_ops_manager', 'email': 't_ops_manager@example.com',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                      self.env.ref('stock.group_stock_user').id])],
            'property_warehouse_id': self.branch2.id,
        })

    def _approval_required(self, picking):
        return picking.activity_ids.filtered(lambda a: a.summary == 'Approval Required')

    def test_09_approval_steps_sequence_chain(self):
        ops = self._ops_manager()
        self._internal_steps((10, self.storekeeper, None), (20, ops, None))
        picking = self._transfer(self.branch1_user, self.main_wh, self.branch1, 20).with_env(self.env)
        self.assertTrue(picking.internal_approval_required)
        self.assertTrue(picking.with_user(self.branch1_user).can_submit_internal_approval)
        with self.assertRaisesRegex(UserError, 'Approve'):
            picking.with_user(self.storekeeper).action_dispatch_goods()
        with self.assertRaisesRegex(UserError, 'cannot be validated directly'):
            picking.with_user(self.storekeeper).button_validate()

        picking.with_user(self.branch1_user).action_submit_internal_transfer_approval()
        self.assertEqual((picking.state, picking.transfer_status, picking.approval_step_sequence),
                         ('to_approve', 'to_approve', 10))
        self.assertEqual(self._approval_required(picking).user_id, self.storekeeper)
        for user in (self.branch1_user, ops):
            with self.assertRaises(AccessError):
                picking.with_user(user).button_approve_delivery()
        with self.assertRaises(UserError):
            picking.with_user(self.storekeeper).button_validate()
        with self.assertRaises(UserError):
            picking.with_user(self.storekeeper).action_dispatch_goods()

        picking.with_user(self.storekeeper).button_approve_delivery()
        self.assertEqual((picking.transfer_status, picking.approval_step_sequence), ('to_approve', 20))
        self.assertEqual(self._approval_required(picking).user_id, ops)
        self.assertIn(picking, self.env['stock.picking'].with_user(ops).search([('show_approve_button', '=', True)]))

        picking.with_user(ops).button_approve_delivery()
        self.assertEqual((picking.approval_status, picking.transfer_status), ('approved', 'approved'))
        self.assertNotEqual(picking.state, 'to_approve')
        self.assertFalse(self._approval_required(picking))
        follow_up = picking.activity_ids.filtered(lambda a: a.summary == 'Approved - Dispatch Goods')
        self.assertEqual(follow_up.user_id, ops)
        # the approver may dispatch; the requesting branch may not
        self.assertTrue(picking.with_user(ops).can_dispatch_transfer)
        self.assertFalse(picking.with_user(self.branch1_user).can_dispatch_transfer)

        picking.with_user(self.storekeeper).action_dispatch_goods()
        self.assertEqual(picking.transfer_status, 'transit')
        self.assertTrue(picking.dispatch_date)
        picking.with_user(self.branch1_user).action_confirm_receipt()
        self.assertEqual((picking.transfer_status, picking.state), ('done', 'done'))
        self.assertEqual(self._qty(self.branch1), 50)
        self.assertEqual(self._qty(self.main_wh), 80)

    def test_10_parallel_approvers(self):
        ops = self._ops_manager()
        self._internal_steps((10, self.storekeeper, None), (10, ops, None))
        picking = self._transfer(self.branch1_user, self.main_wh, self.branch1, 5).with_env(self.env)
        picking.with_user(self.branch1_user).action_submit_internal_transfer_approval()
        self.assertEqual(self._approval_required(picking).user_id, self.storekeeper | ops)
        # either of them approves; the other one's pending approval goes away
        picking.with_user(ops).button_approve_delivery()
        self.assertEqual((picking.approval_status, picking.transfer_status), ('approved', 'approved'))
        self.assertFalse(self._approval_required(picking))

    def test_11_rejection_reason(self):
        self._internal_steps((10, self.storekeeper, None))
        picking = self._transfer(self.branch1_user, self.main_wh, self.branch1, 5).with_env(self.env)
        picking.with_user(self.branch1_user).action_submit_internal_transfer_approval()
        action = picking.with_user(self.storekeeper).action_cancel()
        self.assertEqual(action['res_model'], 'approval.cancel.wizard')
        wizard = self.env['approval.cancel.wizard'].with_user(self.storekeeper).with_context(
            action['context']).create({'reason': 'Not enough stock for the main store'})
        wizard.action_confirm_cancel()
        self.assertEqual((picking.state, picking.approval_status, picking.transfer_status),
                         ('cancel', 'cancelled', 'draft'))
        self.assertTrue(any('Not enough stock for the main store' in (m.body or '') for m in picking.message_ids))

    def test_12_source_warehouse_filter(self):
        self._internal_steps((10, self.manager, self.branch1))
        # resupply from the main warehouse: not matched, direct storekeeper approval
        resupply = self._transfer(self.storekeeper, self.main_wh, self.branch1, 5).with_env(self.env)
        self.assertFalse(resupply.internal_approval_required)
        self.assertFalse(resupply.can_submit_internal_approval)
        resupply.with_user(self.storekeeper).action_approve_transfer()
        self.assertEqual(resupply.transfer_status, 'approved')
        # leaving Branch One: matched, so the direct Approve submits it for approval
        branch = self._transfer(self.branch1_user, self.branch1, self.branch2, 5).with_env(self.env)
        self.assertTrue(branch.internal_approval_required)
        branch.with_user(self.branch1_user).action_approve_transfer()
        self.assertEqual((branch.state, branch.transfer_status), ('to_approve', 'to_approve'))
        self.assertEqual(self._approval_required(branch).user_id, self.manager)

    def test_13_transfers_approved_before_steps(self):
        in_transit = self._transfer(self.storekeeper, self.main_wh, self.branch1, 5).with_env(self.env)
        in_transit.with_user(self.storekeeper).action_approve_transfer()
        in_transit.with_user(self.storekeeper).action_dispatch_goods()
        approved = self._transfer(self.storekeeper, self.main_wh, self.branch1, 5).with_env(self.env)
        approved.with_user(self.storekeeper).action_approve_transfer()
        self._internal_steps((10, self.manager, None))
        # already dispatched: received as usual, not sent back for approval
        in_transit.with_user(self.branch1_user).action_confirm_receipt()
        self.assertEqual(in_transit.transfer_status, 'done')
        # approved directly but not dispatched: must now clear the approval steps
        with self.assertRaisesRegex(UserError, 'approval steps'):
            approved.with_user(self.storekeeper).action_dispatch_goods()
        self.assertTrue(approved.can_submit_internal_approval)
        approved.with_user(self.storekeeper).action_submit_internal_transfer_approval()
        approved.with_user(self.manager).button_approve_delivery()
        approved.with_user(self.storekeeper).action_dispatch_goods()
        self.assertEqual(approved.transfer_status, 'transit')
