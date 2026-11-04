# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    biometric_user_id = fields.Char(
        string="Biometric ID", copy=False, index=True,
        groups="hr_attendance.group_hr_attendance_officer",
        help="Enrollment ID (PIN) on the biometric device.")
    biometric_policy_id = fields.Many2one(
        'hr.attendance.policy', string="Attendance Policy",
        groups="hr_attendance.group_hr_attendance_officer",
        help="Default policy used to convert this employee's biometric "
             "punches into attendances.")
    zkteco_policy_line_ids = fields.One2many(
        'zkteco.employee.policy.line', 'employee_id',
        string="Policy Assignments",
        groups="hr_attendance.group_hr_attendance_officer")
    biometric_log_ids = fields.One2many(
        'zkteco.biometric.attendance.log', 'employee_id',
        string="Biometric Logs",
        groups="hr_attendance.group_hr_attendance_officer")
    biometric_log_count = fields.Integer(
        string="Biometric Log Count",
        compute='_compute_biometric_log_count',
        groups="hr_attendance.group_hr_attendance_officer")

    def _zk_punch_tz(self):
        """Return the timezone this employee's biometric punches live in.

        A biometric punch carries the device's wall-clock time and a fixed
        shift bound is a wall-clock time at the workplace, so the employee's
        own timezone wins.  (Odoo 19 resolved the working schedule timezone
        first in ``_get_tz()``; in Odoo 20 calendars have no timezone and
        ``_get_tz()`` returns the employee's, then the partner's, then the
        company's.)  ``_get_tz()`` stays the fallback when it is unset.
        """
        self.ensure_one()
        employee = self.sudo()
        return employee.tz or employee._get_tz() or 'UTC'

    @api.depends('biometric_log_ids')
    def _compute_biometric_log_count(self):
        employees = self.filtered('id')
        counts = {}
        if employees:
            groups = self.env['zkteco.biometric.attendance.log'].sudo()._read_group(
                [('employee_id', 'in', employees.ids)],
                ['employee_id'], ['__count'])
            counts = {employee.id: count for employee, count in groups}
        for employee in self:
            employee.biometric_log_count = counts.get(employee.id, 0)

    def action_view_biometric_logs(self):
        """Open the biometric logs recorded for this employee."""
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(
                'zkteco_adms_attendance.action_zkteco_biometric_attendance_log')
        except (ValueError, KeyError):
            action = {
                'type': 'ir.actions.act_window',
                'name': _("Biometric Logs"),
                'res_model': 'zkteco.biometric.attendance.log',
                'view_mode': 'list,form',
            }
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {
            'default_employee_id': self.id,
            'search_default_employee_id': self.id,
        }
        return action
