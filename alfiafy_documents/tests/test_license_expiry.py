# -*- coding: utf-8 -*-
"""DES00141 - license expiry status and nightly alerts (implementation plan, phase 4)."""
from datetime import timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.alfiafy_documents.models.documents_document import EXPIRY_ACTIVITY_SUMMARY


@tagged('post_install', '-at_install', 'alfiafy')
class TestLicenseExpiry(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['documents.document'])
        cls.manager = cls.env['res.users'].create({
            'name': 'Compliance Manager (test)',
            'login': 'compliance_manager_test',
            'email': 'compliance@example.com',
            'group_ids': [Command.link(cls.env.ref('base.group_user').id)],
        })
        cls.env.company.compliance_manager_ids = cls.manager
        cls.branch = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.todo = cls.env.ref('mail.mail_activity_data_todo')

    def _license(self, days, alert=60, **vals):
        return self.env['documents.document'].create({
            'name': 'Pharmacy License (test %s)' % days,
            'is_license_doc': True,
            'document_type': 'pharmacy_license',
            'license_number': 'PL-%s' % days,
            'issuing_authority': 'Ministry of Public Health',
            'branch_id': self.branch.id,
            'expiry_date': self.today + timedelta(days=days),
            'alert_days_before': alert,
            'raw': b'%PDF-1.4 license scan',
            **vals,
        })

    def _expiry_activities(self, document):
        return document.activity_ids.filtered(
            lambda a: a.activity_type_id == self.todo and a.summary == EXPIRY_ACTIVITY_SUMMARY)

    def test_01_expiring_soon(self):
        """Plan 4.1: expiry in 25 days, alert 30 days before."""
        document = self._license(25, alert=30)
        self.assertEqual(document.days_to_expiry, 25)
        self.assertEqual(document.expiry_status, 'expiring_soon')

    def test_02_expired_and_valid(self):
        """Plan 4.2: expiry date in the past; also a license outside its alert window."""
        expired = self._license(-3)
        self.assertEqual(expired.days_to_expiry, -3)
        self.assertEqual(expired.expiry_status, 'expired')
        valid = self._license(200)
        self.assertEqual(valid.expiry_status, 'valid')
        not_license = self.env['documents.document'].create({
            'name': 'Leaflet (test)', 'raw': b'leaflet', 'expiry_date': self.today + timedelta(days=5)})
        self.assertFalse(not_license.expiry_status)

    def test_03_cron_activity_mail_and_no_duplicate(self):
        """Plan 4.3: cron creates the activity for the compliance manager, once."""
        expiring = self._license(25, alert=30)
        valid = self._license(200)
        Mail = self.env['mail.mail']
        alert_domain = [('subject', '=like', '[URGENT] License Expiry Alert:%')]
        mails_before = Mail.search(alert_domain)

        self.env['documents.document']._cron_check_document_expiry()
        activity = self._expiry_activities(expiring)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.manager)
        self.assertEqual(activity.date_deadline, expiring.expiry_date)
        self.assertFalse(self._expiry_activities(valid))
        # (the activity assignment also notifies the manager: only the alert is counted)
        mail = Mail.search(alert_domain) - mails_before
        self.assertEqual(len(mail), 1)
        self.assertEqual(mail.subject, '[URGENT] License Expiry Alert: %s (25 Days Left)' % expiring.name)
        self.assertEqual(mail.recipient_ids, self.manager.partner_id)
        self.assertIn('PL-25', mail.body_html)

        # re-run at once: the open reminder prevents a duplicate (no activity, no mail)
        self.env['documents.document']._cron_check_document_expiry()
        self.assertEqual(self._expiry_activities(expiring), activity)
        self.assertEqual(len(Mail.search(alert_domain) - mails_before), 1)

        # once the reminder is done, a later run reminds again
        activity.action_feedback(feedback='Renewal requested')
        self.env['documents.document']._cron_check_document_expiry()
        self.assertEqual(len(self._expiry_activities(expiring)), 1)

    def test_04_cron_refreshes_stored_status(self):
        """The stored status follows the calendar: the nightly run updates it."""
        document = self._license(61, alert=60)
        self.assertEqual(document.expiry_status, 'valid')
        with freeze_time(self.today + timedelta(days=2)):
            self.env['documents.document']._cron_check_document_expiry()
            self.assertEqual(document.expiry_status, 'expiring_soon')
            self.assertEqual(len(self._expiry_activities(document)), 1)
        with freeze_time(self.today + timedelta(days=62)):
            self.env['documents.document']._cron_check_document_expiry()
            self.assertEqual(document.expiry_status, 'expired')

    def test_05_no_recipients_no_alert(self):
        self.env.company.compliance_manager_ids = False
        document = self._license(10)
        self.env['documents.document']._cron_check_document_expiry()
        self.assertFalse(self._expiry_activities(document))
