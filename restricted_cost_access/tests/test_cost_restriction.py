# -*- coding: utf-8 -*-
from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestCostRestriction(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salesman = new_test_user(
            cls.env, login='rca_salesman', name='Salesman',
            groups='base.group_user,sales_team.group_sale_salesman_all_leads,stock.group_stock_manager')
        cls.manager = new_test_user(
            cls.env, login='rca_manager', name='Cost Manager',
            groups='base.group_user,sales_team.group_sale_salesman_all_leads,stock.group_stock_manager,'
                   'restricted_cost_access.group_manager_cost')
        cls.product = cls.env['product.product'].create({
            'name': 'RCA test product', 'type': 'consu', 'is_storable': True,
            'standard_price': 50.0, 'list_price': 100.0,
        })
        cls.customer = cls.env['res.partner'].create({'name': 'RCA customer'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.customer.id,
            'order_line': [Command.create({'product_id': cls.product.id, 'product_uom_qty': 2})],
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.product, cls.env.ref('stock.warehouse0').lot_stock_id, 10)

    def test_sale_line_cost_and_margin(self):
        line = self.order.order_line
        self.assertEqual(line.margin, 100.0)
        hidden = line.with_user(self.salesman).read(['purchase_price', 'margin', 'margin_percent', 'price_unit'])[0]
        self.assertEqual((hidden['purchase_price'], hidden['margin'], hidden['margin_percent']), (0.0, 0.0, 0.0))
        self.assertEqual(hidden['price_unit'], 100.0, "Sales price stays visible")
        shown = line.with_user(self.manager).read(['purchase_price', 'margin'])[0]
        self.assertEqual((shown['purchase_price'], shown['margin']), (50.0, 100.0))

    def test_grouped_aggregates_redacted(self):
        SaleLine = self.env['sale.order.line']
        domain = [('order_id', '=', self.order.id)]
        hidden = SaleLine.with_user(self.salesman).formatted_read_group(domain, ['order_id'], ['margin:sum'])
        self.assertEqual(hidden[0]['margin:sum'], 0.0)
        shown = SaleLine.with_user(self.manager).formatted_read_group(domain, ['order_id'], ['margin:sum'])
        self.assertEqual(shown[0]['margin:sum'], 100.0)
        web = SaleLine.with_user(self.salesman).web_read_group(domain, ['order_id'], ['margin:sum'])
        self.assertEqual(web['groups'][0]['margin:sum'], 0.0)

    def test_order_margin_and_schema(self):
        self.assertEqual(self.order.with_user(self.salesman).read(['margin'])[0]['margin'], 0.0)
        desc = self.env['sale.order.line'].with_user(self.salesman).fields_get(['purchase_price'])['purchase_price']
        self.assertFalse(desc['exportable'])
        self.assertTrue(
            self.env['sale.order.line'].with_user(self.manager).fields_get(['purchase_price'])['purchase_price'].get('exportable', True))

    def test_stock_valuation_redacted(self):
        quant = self.env['stock.quant'].search([('product_id', '=', self.product.id)])
        self.assertEqual(quant.with_user(self.salesman).read(['value'])[0]['value'], 0.0)
        self.assertNotEqual(quant.with_user(self.manager).read(['value'])[0]['value'], 0.0)

    def test_sale_form_hides_cost_columns(self):
        arch = self.env['sale.order'].with_user(self.salesman).get_views([(False, 'form')])['views']['form']['arch']
        self.assertNotIn('name="purchase_price"', arch)
        arch = self.env['sale.order'].with_user(self.manager).get_views([(False, 'form')])['views']['form']['arch']
        self.assertIn('name="purchase_price"', arch)
