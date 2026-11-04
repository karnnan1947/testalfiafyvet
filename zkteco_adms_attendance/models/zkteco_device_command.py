# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Raw ADMS command text auto-filled when a Command Type is chosen. Types not
# listed here (Sync Time, Custom) leave the text untouched so the user can type
# their own — the exact command can vary by firmware.
COMMAND_TEXT_DEFAULTS = {
    'info': 'INFO',
    'reboot': 'REBOOT',
    'sync_users': 'DATA QUERY USERINFO',
    'clear_data': 'CLEAR LOG',
    'unlock': 'AC_UNLOCK',
    'option': 'SET OPTION Realtime=1,TransInterval=1,Delay=30',
}


class ZktecoDeviceCommand(models.Model):
    _name = 'zkteco.device.command'
    _description = 'ZKTeco Device Command'
    _order = 'create_date desc'

    device_id = fields.Many2one(
        'zkteco.biometric.device', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='device_id.company_id', store=True, index=True)
    command_type = fields.Selection(
        [('info', 'Query Info'),
         ('reboot', 'Reboot'),
         ('sync_time', 'Sync Time'),
         ('sync_users', 'Sync Users'),
         ('clear_data', 'Clear Attendance Data'),
         ('unlock', 'Unlock Door'),
         ('option', 'Set Options'),
         ('custom', 'Custom')],
        required=True, default='custom')
    command_text = fields.Char(
        required=True,
        help="Raw ADMS command body, e.g. 'REBOOT' or 'CLEAR LOG'.")
    state = fields.Selection(
        [('pending', 'Pending'),
         ('sent', 'Sent'),
         ('done', 'Done'),
         ('error', 'Error')],
        default='pending', required=True, index=True)
    return_code = fields.Char(copy=False)
    response = fields.Char(copy=False)
    sent_date = fields.Datetime(copy=False)
    ack_date = fields.Datetime(copy=False)

    @api.onchange('command_type')
    def _onchange_command_type(self):
        """Auto-fill the raw command text for the chosen type (still editable)."""
        default = COMMAND_TEXT_DEFAULTS.get(self.command_type)
        if default:
            self.command_text = default

    def mark_sent(self):
        """Flag the command(s) as delivered to the device."""
        self.write({
            'state': 'sent',
            'sent_date': fields.Datetime.now(),
        })
        return True

    def mark_done(self, return_code=None, response=None):
        """Acknowledge command execution reported by the device.

        The command is marked ``done`` on a success return code and ``error``
        otherwise (anything not in ``('0', 0, None, '')``).
        """
        now = fields.Datetime.now()
        is_error = return_code not in ('0', 0, None, '')
        for command in self:
            vals = {
                'state': 'error' if is_error else 'done',
                'ack_date': now,
            }
            if return_code is not None:
                vals['return_code'] = str(return_code)
            if response is not None:
                vals['response'] = response
            command.write(vals)
        return True
