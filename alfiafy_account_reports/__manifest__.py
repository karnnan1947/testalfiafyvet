# -*- coding: utf-8 -*-
{
    'name': "Alfiafy Financial Intelligence & Branch KPI Dashboards",
    'version': '20.0.1.0.0',
    'category': 'Accounting/Reporting',
    'summary': "DES00140 - Branch analytic tagging of POS sessions (branch P&L), "
               "POS branch sales targets and KPI dashboard, fast / slow-moving items",
    'description': """
Alfiafy Financial Intelligence & Branch KPI Dashboards (DES00140)
=================================================================
BRD 1.6 customization #1 (branch-wise profit tracking) and 1.7 #1 / #3:

* "Branches" analytic plan with one analytic account per branch (6 POS
  branches, Main Warehouse (Wholesale), Oman Branch Operations).
* Each POS register has a Branch Analytic Account; the revenue lines of the
  session closing entry are tagged with it, so the standard Profit & Loss
  can be filtered / split per branch.
* POS Branch Sales Targets: target per register and period with live KPIs
  (achieved sales, achievement %, orders, customers, average ticket,
  month-over-month growth) and an executive kanban dashboard
  (Point of Sale > Reporting > Branch Performance Dashboard).
* Fast-Moving / Slow-Moving Items favorites in Point of Sale > Reporting >
  Orders (product quantity by product, sorted descending / ascending).
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'account',
        'point_of_sale',
        'analytic',
        'alfiafy_product_base',
    ],
    'data': [
        'security/ir.access.csv',
        'data/analytic_data.xml',
        'data/pos_report_filters.xml',
        'views/res_config_settings_views.xml',
        'views/pos_branch_target_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
