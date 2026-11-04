# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    biometric_log_ids = fields.One2many(
        'zkteco.biometric.attendance.log', 'hr_attendance_id',
        string="Biometric Logs")
    is_biometric = fields.Boolean(
        string="From Biometric Device",
        compute='_compute_is_biometric', store=True)
    biometric_device_id = fields.Many2one(
        'zkteco.biometric.device', string="Biometric Device",
        compute='_compute_is_biometric', store=True)
    check_in_status = fields.Selection([
        ('on_time', 'On Time(IN)'),
        ('late', 'Late arrival'),
    ], string="Check-In Status", copy=False,
        ondelete={
            'early': lambda recs: recs.write({'check_in_status': 'on_time'}),
        },
        help="Rating of the check-in against the fixed working time policy: "
             "at or before the shift start (within tolerance) is on time, "
             "after it is a late arrival.")
    check_out_status = fields.Selection([
        ('early', 'Early leave'),
        ('on_time', 'On Time(OUT)'),
    ], string="Check-Out Status", copy=False,
        ondelete={
            'late': lambda recs: recs.write({'check_out_status': 'on_time'}),
        },
        help="Rating of the check-out against the fixed working time policy: "
             "at or after the shift end (within tolerance) is on time, "
             "before it is an early leave.")

    @api.depends('biometric_log_ids')
    def _compute_is_biometric(self):
        for attendance in self:
            logs = attendance.biometric_log_ids
            attendance.is_biometric = bool(logs)
            attendance.biometric_device_id = logs[:1].device_id.id if logs else False
