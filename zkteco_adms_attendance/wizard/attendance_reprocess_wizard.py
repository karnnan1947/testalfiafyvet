# -*- coding: utf-8 -*-
from datetime import datetime, time

from odoo import models, fields, api, _


class ZktecoAttendanceReprocessWizard(models.TransientModel):
    _name = 'zkteco.attendance.reprocess.wizard'
    _description = 'Reprocess Biometric Logs'

    device_ids = fields.Many2many(
        'zkteco.biometric.device',
        string="Devices (empty = all)",
        help="Restrict reprocessing to these devices. Leave empty to include every device.")
    date_from = fields.Date(
        string="Date From",
        help="Only include punches on or after this date (device-agnostic, UTC boundary).")
    date_to = fields.Date(
        string="Date To",
        help="Only include punches on or before this date.")
    scope = fields.Selection([
        ('unmatched', 'Only unmatched logs'),
        ('unprocessed', 'All unprocessed logs'),
        ('all', 'Full rebuild (delete generated attendances & recreate)'),
    ], string="Scope", default='unmatched', required=True)
    log_count_preview = fields.Integer(
        string="Matching Logs",
        compute='_compute_log_count_preview',
        help="Number of logs the current selection would reprocess.")

    # ------------------------------------------------------------------
    # Domain / selection helpers
    # ------------------------------------------------------------------
    def _get_domain(self):
        """Build the search domain from the wizard's device/date/scope inputs."""
        self.ensure_one()
        domain = []
        if self.device_ids:
            domain.append(('device_id', 'in', self.device_ids.ids))
        if self.date_from:
            domain.append(('punch_datetime', '>=', datetime.combine(self.date_from, time.min)))
        if self.date_to:
            domain.append(('punch_datetime', '<=', datetime.combine(self.date_to, time.max)))

        if self.scope == 'unmatched':
            # Logs explicitly flagged unmatched, OR still-unprocessed logs that
            # never resolved to an employee.
            domain += [
                '|',
                ('process_state', '=', 'unmatched'),
                '&', ('processed', '=', False), ('employee_id', '=', False),
            ]
        elif self.scope == 'unprocessed':
            domain.append(('processed', '=', False))
        # scope == 'all': no state restriction -> every log in the range/devices.
        return domain

    def _get_logs(self):
        """Return the recordset of logs selected by this wizard."""
        self.ensure_one()
        Log = self.env['zkteco.biometric.attendance.log'].sudo()
        return Log.search(self._get_domain())

    @api.depends('device_ids', 'date_from', 'date_to', 'scope')
    def _compute_log_count_preview(self):
        Log = self.env['zkteco.biometric.attendance.log'].sudo()
        for wizard in self:
            wizard.log_count_preview = Log.search_count(wizard._get_domain())

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------
    def action_reprocess(self):
        """Reset (per scope) and re-run the attendance engine on the selected logs.

        - ``all``:          delete every attendance linked to the selected logs,
                            then reset the logs to a pending/unprocessed state.
        - ``unprocessed``:  reset the logs to a pending/unprocessed state.
        - ``unmatched``:    re-run matching without a reset (picks up newly
                            assigned biometric ids on employees).

        Afterwards the logs are re-matched and reprocessed, and a notification
        summarizes how many logs were reprocessed and how many attendance
        records resulted, then reloads the web client.
        """
        self.ensure_one()
        logs = self._get_logs()
        log_count = len(logs)

        if not logs:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Reprocess Biometric Logs"),
                    'message': _("No logs matched the selected criteria."),
                    'type': 'warning',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }

        if self.scope == 'all':
            # Full rebuild: drop the generated attendances first, then reset.
            linked = logs.mapped('hr_attendance_id')
            if linked:
                linked.sudo().unlink()
            logs.write({
                'processed': False,
                'process_state': 'pending',
                'process_note': False,
                'hr_attendance_id': False,
            })
        elif self.scope == 'unprocessed':
            logs.write({
                'processed': False,
                'process_state': 'pending',
            })

        # Re-run matching and the processing engine on the selected logs.
        logs._match_employee()
        logs._process_logs()

        attendance_count = len(logs.mapped('hr_attendance_id'))
        message = _(
            "%(logs)s log(s) reprocessed. %(att)s attendance record(s) affected.",
            logs=log_count, att=attendance_count,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Reprocess Complete"),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }
