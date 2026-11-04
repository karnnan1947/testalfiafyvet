# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'alfiafy')
class TestAlfiafySale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.salesman = new_test_user(
            cls.env, login='alf_salesman', name='Wholesale Salesman',
            groups='base.group_user,sales_team.group_sale_salesman,account.group_account_readonly')
        cls.admin = cls.env.ref('base.user_admin')  # approver of the "Any Discount" step
        Partner = cls.env['res.partner']
        cls.customer_a = Partner.create({'name': 'Customer A Farms', 'is_company': True})
        cls.customer_b = Partner.create({'name': 'Customer B Stables', 'is_company': True})
        Product = cls.env['product.product']
        cls.product_x = Product.create({
            'name': 'Ivermectin 1% 50 ml (test)', 'type': 'consu', 'is_storable': True,
            'list_price': 45.0, 'taxes_id': False,
        })
        cls.product_no_stock = Product.create({
            'name': 'Phenylbutazone paste (test)', 'type': 'consu', 'is_storable': True,
            'list_price': 95.0, 'taxes_id': False,
        })
        cls.env['stock.quant']._update_available_quantity(cls.product_x, cls.warehouse.lot_stock_id, 1000)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _quote(self, partner, product=None, qty=1.0, price=None, discount=0.0, user=None):
        env = self.env(user=user) if user else self.env
        line = {'product_id': (product or self.product_x).id, 'product_uom_qty': qty,
                'discount': discount, 'tax_ids': False}
        if price is not None:
            line['price_unit'] = price
        return env['sale.order'].create({
            'partner_id': partner.id,
            'warehouse_id': self.warehouse.id,
            'order_line': [Command.create(line)],
        })

    def _confirmed_sale(self, partner, price, discount=0.0, days_ago=0):
        order = self._quote(partner, price=price, discount=discount)
        if discount:
            # approve the discount first, then confirm
            order.action_confirm()
            order.with_user(self.admin).button_approve()
        order.action_confirm()
        order.date_order = fields.Datetime.now() - timedelta(days=days_ago)
        return order

    def _invoice(self, partner, amount, due_in_days):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today() - timedelta(days=60),
            'invoice_date_due': fields.Date.today() + timedelta(days=due_in_days),
            'invoice_line_ids': [Command.create({
                'name': 'Vet supplies', 'quantity': 1, 'price_unit': amount, 'tax_ids': False,
            })],
        })
        invoice.action_post()
        return invoice

    # ------------------------------------------------------------------
    # 6.1 Customer price history
    # ------------------------------------------------------------------
    def test_01_customer_price_history(self):
        # six confirmed sales to customer A, the most recent at 52.00 - 10%
        for days_ago, price in ((60, 40.0), (50, 41.0), (40, 42.0), (30, 43.0), (20, 44.0)):
            self._confirmed_sale(self.customer_a, price, days_ago=days_ago)
        self._confirmed_sale(self.customer_a, 52.0, discount=10.0, days_ago=10)
        # noise: another customer and a cancelled order of customer A
        self._confirmed_sale(self.customer_b, 30.0, days_ago=5)
        cancelled = self._quote(self.customer_a, price=10.0)
        cancelled.action_cancel()

        quote = self._quote(self.customer_a, price=45.0)
        line = quote.order_line
        self.assertAlmostEqual(line.last_customer_price, 46.8)  # 52 - 10 %
        self.assertIn('46.80', line.last_customer_price_str)

        action = line.action_view_price_history()
        wizard = self.env['sale.order.line.price.history'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 5, "exactly the last 5 confirmed sales")
        self.assertEqual(wizard.line_ids.mapped('net_price'), [46.8, 44.0, 43.0, 42.0, 41.0])
        self.assertNotIn(30.0, wizard.line_ids.mapped('price_unit'), "other customer excluded")
        self.assertNotIn(10.0, wizard.line_ids.mapped('price_unit'), "cancelled order excluded")
        # current net 45.00: lower than 46.80, higher than the others
        self.assertEqual(wizard.line_ids.mapped('comparison'), ['lower', 'higher', 'higher', 'higher', 'higher'])

        new_customer_quote = self._quote(self.env['res.partner'].create({'name': 'New Customer'}))
        self.assertEqual(new_customer_quote.order_line.last_customer_price_str, 'First Time Sale')

    # ------------------------------------------------------------------
    # 6.2 Out-of-stock restriction
    # ------------------------------------------------------------------
    def test_02_out_of_stock_blocks_confirmation(self):
        quote = self._quote(self.customer_a, product=self.product_no_stock, qty=2, user=self.salesman)
        line = quote.order_line
        self.assertEqual(quote.state, 'draft', "the quotation itself can be saved")
        self.assertTrue(line.is_out_of_stock)
        self.assertEqual(line.warehouse_free_qty, 0.0)
        with self.assertRaisesRegex(UserError, 'not enough stock'):
            quote.with_user(self.salesman).action_confirm()
        self.assertEqual(quote.state, 'draft')

        # more than the free quantity, spread over two lines
        quote2 = self._quote(self.customer_a, qty=600)
        quote2.order_line = [Command.create({'product_id': self.product_x.id, 'product_uom_qty': 500, 'tax_ids': False})]
        self.assertFalse(quote2.order_line[0].is_out_of_stock)
        with self.assertRaisesRegex(UserError, 'available 1,000.00'):
            quote2.action_confirm()
        quote2.order_line[1].unlink()
        quote2.action_confirm()
        self.assertEqual(quote2.state, 'sale')

    # ------------------------------------------------------------------
    # 6.3 Credit limit and overdue invoice hold
    # ------------------------------------------------------------------
    def test_03_credit_limit_hold(self):
        self.company.account_use_credit_limit = True
        self.customer_a.credit_limit = 1000.0
        self._invoice(self.customer_a, 800.0, due_in_days=30)  # not overdue
        quote = self._quote(self.customer_a, qty=5, price=45.0)  # 225 -> 1,025
        self.assertIn('Credit limit exceeded', quote.credit_warning_banner)
        with self.assertRaisesRegex(UserError, 'Credit limit exceeded'):
            quote.action_confirm()
        quote.order_line.product_uom_qty = 4  # 180 -> 980
        self.assertFalse(quote.credit_warning_banner)
        quote.action_confirm()
        self.assertEqual(quote.state, 'sale')

    def test_04_overdue_invoice_hold(self):
        invoice = self._invoice(self.customer_b, 500.0, due_in_days=-15)
        quote = self._quote(self.customer_b, qty=1, user=self.salesman)
        self.assertTrue(quote.has_overdue_invoices)
        self.assertEqual(quote.overdue_invoice_count, 1)
        self.assertEqual(quote.overdue_amount_total, 500.0)
        self.assertIn('Overdue invoices', quote.credit_warning_banner)
        with self.assertRaisesRegex(UserError, 'Overdue invoices'):
            quote.with_user(self.salesman).action_confirm()

        # settle the invoice in full: the hold is lifted
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        quote.invalidate_recordset()
        self.assertFalse(quote.has_overdue_invoices)
        quote.with_user(self.salesman).action_confirm()
        self.assertEqual(quote.state, 'sale')

    def test_05_overdue_hold_can_be_switched_off(self):
        self._invoice(self.customer_b, 500.0, due_in_days=-15)
        self.customer_b.block_on_overdue = False
        quote = self._quote(self.customer_b, qty=1)
        quote.action_confirm()
        self.assertEqual(quote.state, 'sale')

    # ------------------------------------------------------------------
    # 6.4 Discount approval
    # ------------------------------------------------------------------
    def test_06_discount_routes_to_approval(self):
        quote = self._quote(self.customer_a, qty=2, discount=5.0, user=self.salesman)
        self.assertTrue(quote.approval_required)
        quote.with_user(self.salesman).action_confirm()
        self.assertEqual((quote.state, quote.approval_status), ('to_approve', 'to_approve'))
        with self.assertRaises(AccessError):
            quote.with_user(self.salesman).button_approve()
        quote.with_user(self.admin).button_approve()
        self.assertEqual((quote.state, quote.approval_status), ('draft', 'approved'))
        quote.with_user(self.salesman).action_confirm()
        self.assertEqual(quote.state, 'sale')

        no_discount = self._quote(self.customer_a, qty=2, user=self.salesman)
        self.assertFalse(no_discount.approval_required)
        no_discount.with_user(self.salesman).action_confirm()
        self.assertEqual(no_discount.state, 'sale')

    def test_07_hard_stops_before_discount_approval(self):
        self._invoice(self.customer_b, 500.0, due_in_days=-15)
        quote = self._quote(self.customer_b, qty=1, discount=5.0)
        with self.assertRaisesRegex(UserError, 'Overdue invoices'):
            quote.action_confirm()
        self.assertEqual(quote.state, 'draft', "not sent for approval")

    # ------------------------------------------------------------------
    # 5.2 Posted invoice lock (standard access rules)
    # ------------------------------------------------------------------
    def test_08_salesman_cannot_change_posted_invoice(self):
        invoice = self._invoice(self.customer_a, 100.0, due_in_days=30)
        with self.assertRaises((AccessError, UserError)):
            invoice.with_user(self.salesman).write({'ref': 'changed'})
        with self.assertRaises((AccessError, UserError)):
            invoice.with_user(self.salesman).button_draft()
        with self.assertRaises((AccessError, UserError)):
            invoice.with_user(self.salesman).unlink()
