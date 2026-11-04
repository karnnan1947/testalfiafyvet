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
