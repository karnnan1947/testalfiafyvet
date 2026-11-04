# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta, timezone

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import date_utils
from odoo.tools.misc import format_date

# pos.order has no 'invoiced' state in Odoo 20: invoiced orders stay 'paid' / 'done'
COMPLETED_STATES = ('paid', 'done')


class PosBranchTarget(models.Model):
    _name = 'pos.branch.target'
    _description = "POS Branch Sales Target"
    _order = 'date_from desc, config_id'

    name = fields.Char(compute='_compute_name', store=True)
    config_id = fields.Many2one(
        'pos.config', string="POS Register", required=True, index=True,
        help="Branch register whose POS orders count for this target.")
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string="Branch Analytic Account",
        related='config_id.analytic_account_id', store=True)
    date_from = fields.Date(
        string="Start Date", required=True,
        default=lambda self: date_utils.start_of(fields.Date.context_today(self), 'month'))
    date_to = fields.Date(
        string="End Date", required=True,
        default=lambda self: date_utils.end_of(fields.Date.context_today(self), 'month'))
    target_amount = fields.Monetary(string="Sales Target", required=True)
    currency_id = fields.Many2one(
        'res.currency', string="Currency", required=True,
        compute='_compute_currency_id', store=True, readonly=False, precompute=True)

    # live KPIs, read from the POS orders of the register
    achieved_amount = fields.Monetary(string="Achieved Sales", compute='_compute_sales_kpis')
    achievement_ratio = fields.Float(string="Achievement (%)", digits=(16, 2), compute='_compute_sales_kpis')
    order_count = fields.Integer(string="Orders", compute='_compute_sales_kpis')
    customer_count = fields.Integer(string="Customers", compute='_compute_sales_kpis')
    average_ticket = fields.Monetary(string="Average Ticket", compute='_compute_sales_kpis')
    mom_growth_rate = fields.Float(
        string="MoM Growth (%)", digits=(16, 2), compute='_compute_mom_growth_rate',
        help="Average daily sales of the period (up to today) compared with the "
             "average daily sales of the previous calendar month.")

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for target in self:
            if target.date_to < target.date_from:
                raise ValidationError(self.env._("The end date of a sales target cannot be before its start date."))

    @api.depends('config_id')
    def _compute_currency_id(self):
        for target in self:
            target.currency_id = target.config_id.currency_id or target.currency_id or self.env.company.currency_id

    @api.depends('config_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for target in self:
            if not (target.config_id and target.date_from and target.date_to):
                target.name = target.config_id.name or False
                continue
            if (target.date_from == date_utils.start_of(target.date_from, 'month')
                    and target.date_to == date_utils.end_of(target.date_from, 'month')):
                period = format_date(self.env, target.date_from, date_format='MMMM y')
            else:
                period = "%s - %s" % (format_date(self.env, target.date_from), format_date(self.env, target.date_to))
            target.name = "%s - %s" % (target.config_id.name, period)

    # ------------------------------------------------------------------
    # KPI helpers
    # ------------------------------------------------------------------
    def _date_bounds_utc(self, date_from, date_to):
        """Local dates (user timezone) -> naive UTC datetimes [start, end)."""
        tz = self.env.tz
        start = datetime.combine(date_from, time.min, tzinfo=tz)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
        return (start.astimezone(timezone.utc).replace(tzinfo=None),
                end.astimezone(timezone.utc).replace(tzinfo=None))

    def _completed_orders_domain(self, date_from, date_to):
        self.ensure_one()
        start, end = self._date_bounds_utc(date_from, date_to)
        return [
            ('config_id', '=', self.config_id.id),
            ('state', 'in', COMPLETED_STATES),
            ('date_order', '>=', start),
            ('date_order', '<', end),
        ]

    def _read_sales(self, date_from, date_to):
        """(sales total, order count, distinct customers) of the register."""
        # aggregates only: also readable by accounting managers without POS rights
        [(total, count, customers)] = self.env['pos.order'].sudo()._read_group(
            self._completed_orders_domain(date_from, date_to),
            aggregates=['amount_total:sum', '__count', 'partner_id:count_distinct'],
        )
        return total or 0.0, count, customers

    @api.depends('config_id', 'date_from', 'date_to', 'target_amount')
    def _compute_sales_kpis(self):
        for target in self:
            if not (target.config_id and target.date_from and target.date_to):
                target.update({
                    'achieved_amount': 0.0, 'achievement_ratio': 0.0, 'order_count': 0,
                    'customer_count': 0, 'average_ticket': 0.0,
                })
                continue
            total, count, customers = target._read_sales(target.date_from, target.date_to)
            target.achieved_amount = total
            target.achievement_ratio = total / target.target_amount * 100.0 if target.target_amount else 0.0
            target.order_count = count
            target.customer_count = customers
            target.average_ticket = total / count if count else 0.0

    @api.depends('config_id', 'date_from', 'date_to')
    def _compute_mom_growth_rate(self):
        today = fields.Date.context_today(self)
        for target in self:
            target.mom_growth_rate = 0.0
            if not (target.config_id and target.date_from and target.date_to):
                continue
            # current period: days elapsed so far (whole period once it is over)
            period_end = min(target.date_to, today)
            if period_end < target.date_from:
                continue
            days = (period_end - target.date_from).days + 1
            current_daily = target._read_sales(target.date_from, period_end)[0] / days
            # preceding calendar month
            prev_from = date_utils.start_of(target.date_from, 'month') - relativedelta(months=1)
            prev_to = date_utils.end_of(prev_from, 'month')
            prev_days = (prev_to - prev_from).days + 1
            previous_daily = target._read_sales(prev_from, prev_to)[0] / prev_days
            if previous_daily:
                target.mom_growth_rate = (current_daily - previous_daily) / abs(previous_daily) * 100.0
