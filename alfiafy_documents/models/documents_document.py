# -*- coding: utf-8 -*-
import logging

from odoo import api, Command, fields, models

_logger = logging.getLogger(__name__)

# Summary of the To-Do activity created by the expiry cron; used to find a
# reminder that is still open, so the cron never creates it twice.
EXPIRY_ACTIVITY_SUMMARY = "License expiry reminder"


class DocumentsDocument(models.Model):
    _inherit = 'documents.document'

    is_license_doc = fields.Boolean(
        string="Regulatory License", default=False, tracking=True,
        help="This document is a license or permit whose expiry is followed.")
    document_type = fields.Selection([
        ('pharmacy_license', 'Pharmacy License'),
        ('doctor_license', "Doctor / Practitioner License"),
        ('cr_license', 'Commercial Registration (CR)'),
        ('vehicle_permit', 'Vehicle Permit'),
        ('other', 'Other'),
    ], string="License Type", tracking=True)
    license_number = fields.Char(tracking=True)
    issuing_authority = fields.Char()
    branch_id = fields.Many2one('stock.warehouse', string="Branch")
    employee_id = fields.Many2one('hr.employee', string="Doctor / Employee")
    issue_date = fields.Date()
    expiry_date = fields.Date(index=True, tracking=True)
    alert_days_before = fields.Integer(
        string="Alert Days Before Expiry", default=60,
        help="The compliance managers are alerted this many days before the expiry date.")
    days_to_expiry = fields.Integer(
        string="Days to Expiry", compute='_compute_days_to_expiry',
        help="Days left until the expiry date (negative once expired).")
    expiry_status = fields.Selection([
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], compute='_compute_expiry_status', store=True, index=True,
        help="Refreshed every night by the license expiry scheduled action.")

    @api.depends('expiry_date')
    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for document in self:
            document.days_to_expiry = (document.expiry_date - today).days if document.expiry_date else 0

    @api.depends('is_license_doc', 'expiry_date', 'alert_days_before')
    def _compute_expiry_status(self):
        today = fields.Date.context_today(self)
        for document in self:
            if not (document.is_license_doc and document.expiry_date):
                document.expiry_status = False
                continue
            days = (document.expiry_date - today).days
            if days < 0:
                document.expiry_status = 'expired'
            elif days <= document.alert_days_before:
                document.expiry_status = 'expiring_soon'
            else:
                document.expiry_status = 'valid'

    def _get_expiry_activities(self):
        """Open expiry reminders of this document."""
        self.ensure_one()
        todo = self.env.ref('mail.mail_activity_data_todo')
        return self.activity_ids.filtered(
            lambda activity: activity.activity_type_id == todo
            and activity.summary == EXPIRY_ACTIVITY_SUMMARY)

    @api.model
    def _cron_check_document_expiry(self):
        """Nightly: alert the compliance managers about licenses entering
        their alert window (or expired), once per open reminder."""
        documents = self.search([('is_license_doc', '=', True), ('expiry_date', '!=', False)])
        # the stored status depends on today's date: refresh it first
        self.env.add_to_compute(self._fields['expiry_status'], documents)
        documents.flush_recordset(['expiry_status'])

        template = self.env.ref('alfiafy_documents.mail_template_license_expiry_alert')
        today = fields.Date.context_today(self)
        alerted = self.browse()
        for document in documents.filtered(lambda doc: doc.days_to_expiry <= doc.alert_days_before):
            if document._get_expiry_activities():
                continue  # a reminder is still open
            company = document.company_id or self.env.company
            managers = company.compliance_manager_ids.filtered('active')
            if not managers:
                _logger.warning("License expiry: no compliance alert recipients set for %s, %s not alerted.",
                                company.name, document.display_name)
                continue
            for user in managers:
                document.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=max(document.expiry_date, today),
                    summary=EXPIRY_ACTIVITY_SUMMARY,
                    note=self.env._("Renew %(license)s (expiry date %(date)s).",
                                    license=document.display_name, date=document.expiry_date),
                    user_id=user.id,
                )
            template.send_mail(document.id, email_values={
                'recipient_ids': [Command.set(managers.partner_id.ids)],
            })
            alerted |= document
        return alerted

    def _get_license_form_url(self):
        """Direct link to the license form (used in the alert e-mail)."""
        self.ensure_one()
        return '%s/odoo/action-alfiafy_documents.action_regulatory_licenses/%s' % (self.get_base_url(), self.id)
