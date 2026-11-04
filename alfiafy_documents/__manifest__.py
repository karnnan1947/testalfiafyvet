# -*- coding: utf-8 -*-
{
    'name': "Alfiafy Regulatory Compliance & License Expiry Alerts",
    'version': '20.0.1.0.0',
    'category': 'Productivity/Documents',
    'summary': "DES00141 - Pharmacy, doctor, CR and vehicle licenses stored in "
               "Documents with expiry dates, status and alerts to the compliance managers",
    'description': """
Alfiafy Regulatory Compliance & License Expiry Alerts (DES00141)
================================================================
BRD 1.7 customization #2: pharmacy licenses and doctors' / practitioners'
licenses are stored in Odoo Documents with an expiry date, and management is
alerted before they expire.

* License fields on documents: license document flag, type, number, issuing
  authority, branch (warehouse), employee (doctor), issue / expiry date,
  alert days before expiry.
* Days to expiry and expiry status (Valid / Expiring Soon / Expired).
* Nightly scheduled action: for licenses inside their alert window, a To-Do
  activity for each compliance manager and an e-mail alert (no duplicates
  while a reminder is still open).
* Compliance alert recipients in Documents settings.
* Documents > Regulatory Licenses (kanban by expiry status, list, form) and
  filters in the Documents app.
    """,
    'author': 'AGM Global Services',
    'website': 'https://www.agmglobal.co/',
    'license': 'OPL-1',
    'depends': [
        'documents',
        'hr',
        'stock',
        'mail',
        'alfiafy_product_base',
    ],
    'data': [
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/documents_document_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
