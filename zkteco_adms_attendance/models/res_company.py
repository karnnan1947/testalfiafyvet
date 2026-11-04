# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    zkteco_default_policy_id = fields.Many2one(
        'hr.attendance.policy', string="Default Attendance Policy",
        help="Policy applied to biometric punches when an employee has no "
             "specific policy assignment.")
    zkteco_device_offline_minutes = fields.Integer(
        string="Device Offline After (min)", default=5,
        help="A device that has not reported within this many minutes is "
             "automatically marked offline by the scheduled action.")
