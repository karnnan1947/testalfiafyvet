# -*- coding: utf-8 -*-
import logging
import re
import uuid
from datetime import datetime, timedelta

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZktecoBiometricDevice(models.Model):
    _name = 'zkteco.biometric.device'
    _description = 'ZKTeco Biometric Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'device_name'
    _rec_name = 'device_name'

    @api.model
    def _tz_get(self):
        return [(tz, tz) for tz in sorted(pytz.all_timezones, key=str.lower)]

    device_name = fields.Char(required=True, tracking=True)
    serial_number = fields.Char(
        required=True, index=True, copy=False, tracking=True)
    mac_address = fields.Char()
    ip_address = fields.Char(string="IP Address")
    subnet_mask = fields.Char()
    gateway = fields.Char()
    port = fields.Integer(default=8069)
    location = fields.Char()
    tz = fields.Selection(
        _tz_get, string="Timezone",
        default=lambda self: self.env.user.tz or 'UTC')
    firmware_version = fields.Char(readonly=True, copy=False)
    verify_mode_palm = fields.Boolean(string="Palm", default=False)
    verify_mode_face = fields.Boolean(string="Face", default=True)
    verify_mode_fingerprint = fields.Boolean(string="Fingerprint", default=True)
    verify_modes_display = fields.Char(compute='_compute_verify_modes_display')
    state = fields.Selection(
        [('draft', 'Draft'),
         ('confirmed', 'Confirmed'),
         ('online', 'Online'),
         ('offline', 'Offline')],
        default='draft', required=True, tracking=True, copy=False)
    last_seen = fields.Datetime(readonly=True, copy=False, tracking=True)
    auth_token = fields.Char(
        string="Auth Token", copy=False,
        help="Optional shared secret. Leave EMPTY for a normal connection: the "
             "device is then authenticated by its serial number. A token only "
             "works when a reverse proxy in front of Odoo injects it on the "
             "device's behalf, because the terminal cannot send one itself. "
             "If a token is set WITHOUT such a proxy, the device is rejected "
             "with 'ACCESS DENIED'.")
    transaction_interval = fields.Integer(
        string="Upload Interval (min)", default=1)
    heartbeat_interval = fields.Integer(string="Heartbeat (sec)", default=30)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    command_ids = fields.One2many('zkteco.device.command', 'device_id')
    log_ids = fields.One2many('zkteco.biometric.attendance.log', 'device_id')
    log_count = fields.Integer(compute='_compute_counts')
    command_count = fields.Integer(compute='_compute_counts')
    pending_command_count = fields.Integer(compute='_compute_counts')

    # Device-reported information (populated when a "Query Info" / INFO command runs)
    device_user_count = fields.Integer(string="Users on Device", readonly=True, copy=False)
    device_fp_count = fields.Integer(string="Fingerprints", readonly=True, copy=False)
    device_face_count = fields.Integer(string="Faces", readonly=True, copy=False)
    device_transaction_count = fields.Integer(
        string="Records on Device", readonly=True, copy=False)
    last_info_date = fields.Datetime(string="Info Updated", readonly=True, copy=False)
    last_info_raw = fields.Text(string="Raw Device Info", readonly=True, copy=False)

    _serial_number_uniq = models.Constraint(
        'unique(serial_number)',
        'The serial number must be unique.',
    )

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------
    @api.depends('verify_mode_palm', 'verify_mode_face', 'verify_mode_fingerprint')
    def _compute_verify_modes_display(self):
        for device in self:
            modes = []
            if device.verify_mode_face:
                modes.append(_("Face"))
            if device.verify_mode_fingerprint:
                modes.append(_("Fingerprint"))
            if device.verify_mode_palm:
                modes.append(_("Palm"))
            device.verify_modes_display = ", ".join(modes)

    @api.depends('log_ids', 'command_ids', 'command_ids.state')
    def _compute_counts(self):
        log_map = {}
        cmd_map = {}
        pending_map = {}
        devices_with_id = self.filtered('id')
        if devices_with_id:
            log_groups = self.env['zkteco.biometric.attendance.log']._read_group(
                [('device_id', 'in', devices_with_id.ids)],
                ['device_id'], ['__count'])
            for device, count in log_groups:
                log_map[device.id] = count
            cmd_groups = self.env['zkteco.device.command']._read_group(
                [('device_id', 'in', devices_with_id.ids)],
                ['device_id', 'state'], ['__count'])
            for device, state, count in cmd_groups:
                cmd_map[device.id] = cmd_map.get(device.id, 0) + count
                if state == 'pending':
                    pending_map[device.id] = pending_map.get(device.id, 0) + count
        for device in self:
            device.log_count = log_map.get(device.id, 0)
            device.command_count = cmd_map.get(device.id, 0)
            device.pending_command_count = pending_map.get(device.id, 0)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_registered_device(self, serial_number):
        """Return the (single) device matching ``serial_number`` or empty."""
        if not serial_number:
            return self.browse()
        return self.sudo().search(
            [('serial_number', '=', serial_number)], limit=1)

    def _get_timezone_offset_minutes(self):
        """UTC offset of the device timezone, in whole minutes."""
        self.ensure_one()
        if not self.tz:
            return 0
        try:
            tzinfo = pytz.timezone(self.tz)
            offset = tzinfo.utcoffset(datetime.utcnow())
            if offset is None:
                return 0
            return int(offset.total_seconds() // 60)
        except Exception:
            _logger.warning(
                "Invalid timezone %r on device %s", self.tz, self.serial_number)
            return 0

    # ------------------------------------------------------------------
    # Workflow buttons
    # ------------------------------------------------------------------
    def action_confirm(self):
        # Confirm activates the device (authenticated by serial number). A
        # shared-secret token is NOT generated here: a stock terminal cannot
        # send one, so an auto-token would only reject the device. Use the
        # "Generate token" button to opt in when a reverse proxy will inject it.
        for device in self:
            if device.state != 'draft':
                continue
            device.write({'state': 'confirmed'})
        return True

    def action_generate_auth_token(self):
        """Opt-in: create a shared-secret token for this device.

        Only useful when a reverse proxy in front of Odoo injects the token on
        the device's behalf. For a normal direct connection leave the token
        empty and let the device authenticate by its serial number.
        """
        for device in self:
            device.auth_token = uuid.uuid4().hex
        return True

    def action_clear_auth_token(self):
        """Remove the shared secret so the device authenticates by serial number."""
        self.write({'auth_token': False})
        return True

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_set_offline(self):
        self.write({'state': 'offline'})
        return True

    def action_view_logs(self):
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(
                'zkteco_adms_attendance.action_zkteco_biometric_attendance_log')
        except (ValueError, KeyError):
            action = {
                'type': 'ir.actions.act_window',
                'name': _("Attendance Logs"),
                'res_model': 'zkteco.biometric.attendance.log',
                'view_mode': 'list,form',
            }
        action['domain'] = [('device_id', '=', self.id)]
        action['context'] = {
            'default_device_id': self.id,
            'search_default_device_id': self.id,
        }
        return action

    def action_view_commands(self):
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id(
                'zkteco_adms_attendance.action_zkteco_device_command')
        except (ValueError, KeyError):
            action = {
                'type': 'ir.actions.act_window',
                'name': _("Device Commands"),
                'res_model': 'zkteco.device.command',
                'view_mode': 'list,form',
            }
        action['domain'] = [('device_id', '=', self.id)]
        action['context'] = {
            'default_device_id': self.id,
            'search_default_device_id': self.id,
        }
        return action

    def action_upload_settings(self):
        for device in self:
            if device.state == 'draft':
                raise UserError(_(
                    "Confirm the device before pushing settings to it."))
            device.queue_command('info', 'INFO')
            device.queue_command(
                'option',
                'SET OPTION Realtime=1,TransInterval=%d,Delay=%d' % (
                    device.transaction_interval or 1,
                    device.heartbeat_interval or 30))
            device.message_post(body=_(
                "Queued INFO and OPTION commands; they will be delivered on the "
                "next device poll."))
        return True

    # ------------------------------------------------------------------
    # Device presence
    # ------------------------------------------------------------------
    def mark_online(self, firmware_version=None):
        """Register a device contact: refresh ``last_seen`` and go online."""
        now = fields.Datetime.now()
        for device in self:
            vals = {'last_seen': now}
            if firmware_version and firmware_version != device.firmware_version:
                vals['firmware_version'] = firmware_version
            if device.state in ('confirmed', 'offline', 'online'):
                vals['state'] = 'online'
            device.write(vals)
        return True

    def _apply_device_info(self, payload):
        """Parse a device INFO / options push and store firmware + capacity.

        Called from the controller when the terminal reports its information
        (in response to a "Query Info"/INFO command). The raw payload is always
        stored so the values can be read even if a key is not recognised.
        """
        self.ensure_one()
        if not payload:
            return False
        # ZKTeco reports options as ``key=value`` pairs separated by tab/newline;
        # values may contain spaces (e.g. firmware "Ver 8.0.4.6"), so split only
        # on tab/CR/LF, not spaces.
        info = {}
        for key, value in re.findall(r'([~\w.]+)=([^\t\r\n]*)', payload):
            info[key.lstrip('~').lower()] = value.strip()

        vals = {
            'last_info_raw': payload[:8000],
            'last_info_date': fields.Datetime.now(),
        }
        firmware = (info.get('fwversion') or info.get('zkfpversion')
                    or info.get('firmver') or info.get('zkfaceversion'))
        if firmware:
            vals['firmware_version'] = firmware

        def _as_int(*keys):
            for key in keys:
                value = info.get(key)
                if value and value.isdigit():
                    return int(value)
            return None

        count_map = {
            'device_user_count': ('usercount',),
            'device_fp_count': ('fpcount', 'fingercount'),
            'device_face_count': ('facecount',),
            'device_transaction_count': ('transactioncount', 'attlogcount'),
        }
        for field_name, keys in count_map.items():
            value = _as_int(*keys)
            if value is not None:
                vals[field_name] = value

        self.write(vals)
        _logger.info(
            "ZKTeco: device info stored for SN=%s (firmware=%s, users=%s)",
            self.serial_number, firmware, info.get('usercount'))
        return True

    # ------------------------------------------------------------------
    # ADMS / iClock protocol payloads
    # ------------------------------------------------------------------
    def _build_handshake_options(self):
        """Return the ADMS GET handshake body (``GET /iclock/cdata``)."""
        self.ensure_one()
        offset_minutes = self._get_timezone_offset_minutes()
        lines = [
            'GET OPTION FROM: %s' % (self.serial_number or ''),
            'Stamp=9999',
            'OpStamp=9999',
            'ErrorDelay=30',
            'Delay=%d' % (self.heartbeat_interval or 30),
            'TransTimes=00:00;14:05',
            'TransInterval=%d' % (self.transaction_interval or 1),
            'TransFlag=1111000000',
            'TimeZone=%d' % offset_minutes,
            'Realtime=1',
            'Encrypt=0',
        ]
        return '\r\n'.join(lines)

    def queue_command(self, command_type, command_text):
        """Create and return a pending command for this device."""
        self.ensure_one()
        return self.env['zkteco.device.command'].sudo().create({
            'device_id': self.id,
            'command_type': command_type,
            'command_text': command_text,
        })

    def get_pending_commands_payload(self):
        """Return the pending-command payload for ``GET /iclock/getrequest``.

        Each command is rendered as ``C:<id>:<command_text>`` on its own line
        and immediately flagged as sent. ``OK`` is returned when the queue is
        empty.
        """
        self.ensure_one()
        commands = self.env['zkteco.device.command'].sudo().search(
            [('device_id', '=', self.id),
             ('state', '=', 'pending')],
            order='create_date asc, id asc')
        if not commands:
            return 'OK'
        lines = [
            'C:%d:%s' % (command.id, command.command_text or '')
            for command in commands
        ]
        commands.mark_sent()
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_mark_offline(self):
        """Flip stale online devices to offline and warn the responsible user."""
        now = fields.Datetime.now()
        online_devices = self.sudo().search([('state', '=', 'online')])
        stale = self.browse()
        for device in online_devices:
            minutes = device.company_id.zkteco_device_offline_minutes or 5
            threshold = now - timedelta(minutes=minutes)
            if not device.last_seen or device.last_seen <= threshold:
                stale |= device
        if not stale:
            return False

        stale.write({'state': 'offline'})

        manager_group = self.env.ref(
            'hr_attendance.group_hr_attendance_manager',
            raise_if_not_found=False)
        admin_users = (
            manager_group.all_user_ids.filtered('active')
            if manager_group else self.env['res.users'])

        for device in stale:
            responsible = device.create_uid
            if not responsible or not responsible.active:
                responsible = admin_users[:1]
            if not responsible:
                responsible = self.env.user
            last_seen_txt = (
                fields.Datetime.to_string(device.last_seen)
                if device.last_seen else _("never"))
            try:
                device.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_("Biometric device offline"),
                    note=_(
                        'Device "%(name)s" (SN %(sn)s) has not reported since '
                        '%(seen)s (UTC) and was automatically marked offline. '
                        'Please verify network connectivity and power.',
                        name=device.device_name or '',
                        sn=device.serial_number or '',
                        seen=last_seen_txt),
                    user_id=responsible.id,
                )
            except Exception:
                _logger.warning(
                    "Failed to schedule offline activity for device %s",
                    device.serial_number, exc_info=True)
        return True
