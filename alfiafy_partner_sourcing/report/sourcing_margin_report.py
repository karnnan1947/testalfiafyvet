# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import SQL
from odoo.tools.sql import column_exists, drop_view_if_exists

from ..models.selections import LINE_SOURCING_TYPES

REVENUE = 'price_subtotal:sum'
PROFIT = 'gross_profit:sum'


class SourcingMarginReport(models.Model):
    """Revenue, cost of goods sold and margin by sourcing.

    One row per posted customer invoice / credit note line, plus one row per
    POS order line that was not invoiced (retail sales). The cost of goods
    sold is the purchase cost of the lots sold (stored on the invoice / POS
    line when its sourcing is set from the lots); lines without it use the
    product cost.
    """
    _name = 'alfiafy.sourcing.margin.report'
    _description = "Sourcing Margin Analysis"
    _auto = False
    _order = 'invoice_date desc'
    _rec_name = 'product_id'

    origin = fields.Selection(
        [('invoice', 'Customer Invoice'), ('pos', 'POS Order (not invoiced)')],
        string="Document Type", readonly=True)
    move_id = fields.Many2one('account.move', string="Invoice", readonly=True)
    pos_order_id = fields.Many2one('pos.order', string="POS Order", readonly=True)
    company_id = fields.Many2one('res.company', string="Company", readonly=True)
    currency_id = fields.Many2one('res.currency', string="Currency", readonly=True)
    invoice_date = fields.Date(string="Date", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Customer", readonly=True)
    product_id = fields.Many2one('product.product', string="Product", readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string="Product Template", readonly=True)
    categ_id = fields.Many2one('product.category', string="Product Category", readonly=True)
    sourcing_type = fields.Selection(LINE_SOURCING_TYPES, string="Sourcing", readonly=True)
    qty_invoiced = fields.Float(string="Quantity Sold", digits='Product Unit', readonly=True)
    price_subtotal = fields.Monetary(string="Revenue", currency_field='currency_id', readonly=True)
    cogs_amount = fields.Monetary(string="Cost of Goods Sold", currency_field='currency_id', readonly=True)
    gross_profit = fields.Monetary(string="Gross Profit", currency_field='currency_id', readonly=True)
    margin_percent = fields.Float(string="Margin %", digits=(16, 2), aggregator='avg', readonly=True)

    def _pos_qty_expression(self):
        # The unit sold on a POS line is a stored column only with
        # pos_multi_uom_price; otherwise POS lines are in the product unit.
        if column_exists(self.env.cr, 'pos_order_line', 'product_uom_id'):
            return SQL("pol.qty * COALESCE(line_uom.factor, prod_uom.factor) / prod_uom.factor"), \
                SQL("LEFT JOIN uom_uom line_uom ON line_uom.id = pol.product_uom_id")
        return SQL("pol.qty"), SQL("")

    def _query(self):
        pos_qty, pos_uom_join = self._pos_qty_expression()
        return SQL(
            """
            SELECT rows.id, rows.origin, rows.move_id, rows.pos_order_id, rows.company_id,
                   rows.currency_id, rows.invoice_date, rows.partner_id, rows.product_id,
                   rows.product_tmpl_id, rows.categ_id, rows.sourcing_type, rows.qty_invoiced,
                   rows.price_subtotal,
                   rows.cogs_amount_raw AS cogs_amount,
                   rows.price_subtotal - rows.cogs_amount_raw AS gross_profit,
                   CASE WHEN rows.price_subtotal <> 0
                        THEN (rows.price_subtotal - rows.cogs_amount_raw) / rows.price_subtotal * 100
                        ELSE 0 END AS margin_percent
              FROM (
                SELECT inv.id, inv.origin, inv.move_id, inv.pos_order_id, inv.company_id,
                       inv.currency_id, inv.invoice_date, inv.partner_id, inv.product_id,
                       pp.product_tmpl_id, pt.categ_id, inv.sourcing_type, inv.qty_invoiced,
                       inv.price_subtotal,
                       inv.qty_invoiced * COALESCE(NULLIF(inv.unit_cost, 0), %(product_cost)s) AS cogs_amount_raw
                  FROM (
                    -- posted customer invoices and credit notes
                    SELECT aml.id * 2 AS id,
                           'invoice' AS origin,
                           am.id AS move_id,
                           NULL::integer AS pos_order_id,
                           am.company_id,
                           company.currency_id,
                           am.invoice_date,
                           COALESCE(partner.commercial_partner_id, am.partner_id) AS partner_id,
                           aml.product_id,
                           aml.sourcing_type,
                           (CASE WHEN am.move_type = 'out_refund' THEN -1 ELSE 1 END)
                               * aml.quantity * COALESCE(line_uom.factor, prod_uom.factor) / prod_uom.factor AS qty_invoiced,
                           -aml.balance AS price_subtotal,
                           aml.sourcing_unit_cost AS unit_cost
                      FROM account_move_line aml
                      JOIN account_move am ON am.id = aml.move_id
                      JOIN res_company company ON company.id = am.company_id
                      JOIN product_product pp2 ON pp2.id = aml.product_id
                      JOIN product_template pt2 ON pt2.id = pp2.product_tmpl_id
                      JOIN uom_uom prod_uom ON prod_uom.id = pt2.uom_id
                 LEFT JOIN uom_uom line_uom ON line_uom.id = aml.product_uom_id
                 LEFT JOIN res_partner partner ON partner.id = am.partner_id
                     WHERE am.state = 'posted'
                       AND am.move_type IN ('out_invoice', 'out_refund')
                       AND aml.display_type = 'product'
                       AND aml.product_id IS NOT NULL

                    UNION ALL

                    -- POS orders paid but not invoiced (retail sales)
                    SELECT pol.id * 2 + 1 AS id,
                           'pos' AS origin,
                           NULL::integer AS move_id,
                           po.id AS pos_order_id,
                           po.company_id,
                           company.currency_id,
                           po.date_order::date AS invoice_date,
                           COALESCE(partner.commercial_partner_id, po.partner_id) AS partner_id,
                           pol.product_id,
                           pol.sourcing_type,
                           %(pos_qty)s AS qty_invoiced,
                           -- Odoo 20 stores POS line amounts as positive values; the
                           -- sign comes from the quantity (refunds) and the price
                           (CASE WHEN pol.qty * pol.price_unit < 0 THEN -1 ELSE 1 END)
                               * ABS(pol.price_subtotal) / COALESCE(NULLIF(po.currency_rate, 0), 1) AS price_subtotal,
                           pol.sourcing_unit_cost AS unit_cost
                      FROM pos_order_line pol
                      JOIN pos_order po ON po.id = pol.order_id
                      JOIN res_company company ON company.id = po.company_id
                      JOIN product_product pp2 ON pp2.id = pol.product_id
                      JOIN product_template pt2 ON pt2.id = pp2.product_tmpl_id
                      JOIN uom_uom prod_uom ON prod_uom.id = pt2.uom_id
                      %(pos_uom_join)s
                 LEFT JOIN res_partner partner ON partner.id = po.partner_id
                     WHERE po.state IN ('paid', 'done')
                       AND po.account_move IS NULL
                       AND pt2.type != 'combo'
                  ) inv
                  JOIN product_product pp ON pp.id = inv.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
              ) rows
            """,
            product_cost=SQL("COALESCE((pp.standard_price ->> inv.company_id::text)::numeric, 0)"),
            pos_qty=pos_qty,
            pos_uom_join=pos_uom_join,
        )

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL("CREATE OR REPLACE VIEW %s AS (%s)", SQL.identifier(self._table), self._query()))

    # ------------------------------------------------------------------
    # Margin % of a group = gross profit / revenue (not the average of rows)
    # ------------------------------------------------------------------
    @api.model
    def _alf_margin_aggregates(self, aggregates):
        aggregates = list(aggregates or [])
        margin_keys = [agg for agg in aggregates if agg.split(':')[0] == 'margin_percent']
        extra = [agg for agg in (REVENUE, PROFIT) if margin_keys and agg not in aggregates]
        return aggregates + extra, margin_keys, extra

    @api.model
    def _alf_fix_margin(self, groups, margin_keys, extra):
        for group in groups:
            revenue = group.get(REVENUE) or 0.0
            profit = group.get(PROFIT) or 0.0
            for key in margin_keys:
                group[key] = profit / revenue * 100 if revenue else 0.0
            for key in extra:
                group.pop(key, None)

    @api.model
    @api.readonly
    def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        aggregates, margin_keys, extra = self._alf_margin_aggregates(aggregates)
        res = super().formatted_read_group(
            domain, groupby=groupby, aggregates=aggregates, having=having,
            offset=offset, limit=limit, order=order)
        if margin_keys:
            self._alf_fix_margin(res, margin_keys, extra)
        return res

    @api.model
    @api.readonly
    def formatted_read_grouping_sets(self, domain, grouping_sets, aggregates=(), *, order=None):
        aggregates, margin_keys, extra = self._alf_margin_aggregates(aggregates)
        res = super().formatted_read_grouping_sets(domain, grouping_sets, aggregates=aggregates, order=order)
        if margin_keys:
            for groups in res:
                self._alf_fix_margin(groups, margin_keys, extra)
        return res
