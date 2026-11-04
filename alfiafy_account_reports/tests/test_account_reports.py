# -*- coding: utf-8 -*-
"""DES00140 - branch analytic tagging of the POS session closing entry and
POS branch sales target KPIs (implementation plan, phase 7)."""
from datetime import date

from odoo import fields
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install', 'alfiafy')
class TestBranchKpi(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.branch_1 = cls.env.ref('alfiafy_account_reports.analytic_branch_1_al_rayyan')
        categ = cls.env['product.category'].create({'name': 'Vet (branch KPI test)'})
        cls.product_500 = cls.create_product('Branch KPI item 500', categ, 500.0)
        cls.product_50 = cls.create_product('Branch KPI item 50', categ, 50.0)

    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def _sync_orders(self, specs):
        """specs: (date_order 'YYYY-MM-DD HH:MM:SS', product, qty, customer)"""
        result = self.env['pos.order'].sync_from_ui([
            self.create_ui_order_data([(product, qty)], {'date_order': date_order}, customer=customer)
            for date_order, product, qty, customer in specs
        ])
        return self.env['pos.order'].browse([vals['id'] for vals in result['pos.order']])

    def _target(self, date_from, date_to, amount):
        return self.env['pos.branch.target'].create({
            'config_id': self.config.id,
            'date_from': date_from,
            'date_to': date_to,
            'target_amount': amount,
        })

    def test_00_branch_analytic_accounts(self):
        plan = self.env.ref('alfiafy_account_reports.analytic_plan_branches')
        self.assertEqual(plan.name, 'Branches')
        self.assertEqual(sorted(plan.account_ids.mapped('name')), sorted([
            'Branch 1 - Al Rayyan', 'Branch 2 - Al Wakra', 'Branch 3 - Al Khor',
            'Branch 4 - Al Shahaniya', 'Branch 5 - Umm Salal', 'Branch 6 - Doha Central',
            'Main Warehouse (Wholesale)', 'Oman Branch Operations',
        ]))

    def test_01_session_closing_entry_tagged_with_branch(self):
        """Task 7.1: revenue lines of the closing entry carry Branch 1 - Al Rayyan."""
        self.config.analytic_account_id = self.branch_1
        self.open_new_session()
        now = fields.Datetime.to_string(fields.Datetime.now())
        orders = self._sync_orders([
            (now, self.product_500, 2, False),
            (now, self.product_50, 3, False),
        ])
        self.assertEqual(sum(orders.mapped('amount_total')), 1150.0)
        cash_pm = self.config.payment_method_ids.filtered(lambda pm: pm.type == 'cash')[:1]
        self.pos_session.close_session_from_ui({cash_pm.id: 1150.0})
        self.assertEqual(self.pos_session.state, 'closed')

        move = self.pos_session.sale_move_ids
        self.assertEqual(len(move), 1)
        self.assertEqual(move.state, 'posted')
        revenue_lines = move.line_ids.filtered(lambda line: line.display_type == 'product')
        self.assertTrue(revenue_lines)
        for line in revenue_lines:
            self.assertEqual(line.analytic_distribution, {str(self.branch_1.id): 100.0})
        self.assertFalse(any((move.line_ids - revenue_lines).mapped('analytic_distribution')))
        # analytic items (column of the Branches plan) feed the branch P&L
        analytic_lines = revenue_lines.analytic_line_ids
        self.assertEqual(analytic_lines.mapped(self.branch_1.plan_id._column_name()), self.branch_1)
        self.assertAlmostEqual(sum(analytic_lines.mapped('amount')), 1150.0)

    def test_02_session_closing_without_branch_is_not_tagged(self):
        self.open_new_session()
        now = fields.Datetime.to_string(fields.Datetime.now())
        self._sync_orders([(now, self.product_50, 1, False)])
        cash_pm = self.config.payment_method_ids.filtered(lambda pm: pm.type == 'cash')[:1]
        self.pos_session.close_session_from_ui({cash_pm.id: 50.0})
        self.assertFalse(any(self.pos_session.sale_move_ids.line_ids.mapped('analytic_distribution')))

    def test_03_target_kpis(self):
        """Task 7.2: 100 orders / 80 customers / 50,000 QAR against a 100,000 QAR October target."""
        self.open_new_session()
        customers = self.env['res.partner'].create([
            {'name': 'KPI customer %02d' % i, 'phone': '+974 5100 %04d' % i} for i in range(80)
        ])
        self._sync_orders([
            ('2025-10-%02d 10:00:00' % (1 + i % 28), self.product_500, 1, customers[i % 80])
            for i in range(100)
        ])
        target = self._target(date(2025, 10, 1), date(2025, 10, 31), 100000.0)
        self.assertEqual(target.name, '%s - October 2025' % self.config.name)
        self.assertEqual(target.currency_id, self.config.currency_id)
        self.assertAlmostEqual(target.achieved_amount, 50000.0)
        self.assertAlmostEqual(target.achievement_ratio, 50.0)
        self.assertEqual(target.order_count, 100)
        self.assertEqual(target.customer_count, 80)
        self.assertAlmostEqual(target.average_ticket, 500.0)
        # orders outside the period do not count
        other = self._target(date(2025, 11, 1), date(2025, 11, 30), 100000.0)
        self.assertEqual((other.achieved_amount, other.order_count), (0.0, 0))

    def test_04_mom_growth_rate(self):
        """Task 7.3: average daily sales vs the previous calendar month."""
        self.open_new_session()
        self._sync_orders([
            ('2025-07-10 10:00:00', self.product_50, 31, False),  # July: 3,100 / 31 days = 100 a day
            ('2025-07-20 10:00:00', self.product_50, 31, False),
            ('2025-08-15 10:00:00', self.product_50, 31, False),  # August: 1,550 / 31 days = 50 a day
            ('2025-09-05 10:00:00', self.product_50, 30, False),  # September: 3,000 / 30 days = 100 a day
            ('2025-09-25 10:00:00', self.product_50, 30, False),
        ])
        august = self._target(date(2025, 8, 1), date(2025, 8, 31), 2000.0)
        september = self._target(date(2025, 9, 1), date(2025, 9, 30), 2000.0)
        self.assertAlmostEqual(august.achieved_amount, 1550.0)
        self.assertAlmostEqual(august.mom_growth_rate, -50.0)
        self.assertAlmostEqual(september.achieved_amount, 3000.0)
        self.assertAlmostEqual(september.mom_growth_rate, 100.0)
        # no sales in the previous month: no growth figure
        july = self._target(date(2025, 7, 1), date(2025, 7, 31), 2000.0)
        self.assertEqual(july.mom_growth_rate, 0.0)
