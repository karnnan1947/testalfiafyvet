# -*- coding: utf-8 -*-
import logging
from collections import defaultdict
from datetime import datetime

import pytz
from psycopg2 import IntegrityError

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

# ADMS ATTLOG datetime format sent by ZKTeco devices (device-local time).
ATTLOG_DT_FORMAT = '%Y-%m-%d %H:%M:%S'

# Device attendance status code -> punch_type.  Fallback: 'unknown'.
STATUS_MAP = {
    '0': 'in',
    '1': 'out',
    '2': 'break_out',
    '3': 'break_in',
    '4': 'ot_in',
    '5': 'ot_out',
}

# Device verify code -> verify_mode.  Fallback: 'other'.
VERIFY_MAP = {
    '0': 'password',
    '1': 'fingerprint',
    '2': 'card',
    '15': 'face',
    '9': 'palm',
}


class ZktecoBiometricAttendanceLog(models.Model):
    _name = 'zkteco.biometric.attendance.log'
    _description = 'Biometric Attendance Log (Raw Punch)'
    _order = 'punch_datetime desc, id desc'

    # Expose the mapping dicts as class attributes as well as module-level names,
    # so callers may reference either ``STATUS_MAP`` or ``record.STATUS_MAP``.
    STATUS_MAP = STATUS_MAP
    VERIFY_MAP = VERIFY_MAP

    device_id = fields.Many2one(
        'zkteco.biometric.device', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='device_id.company_id', store=True, index=True)
    biometric_user_id = fields.Char(
        string="Biometric ID", required=True, index=True,
        help="Enrollment ID (PIN) reported by the biometric device.")
    employee_id = fields.Many2one(
        'hr.employee', index=True, ondelete='set null')
    punch_datetime = fields.Datetime(
        string="Punch Time", required=True, index=True,
        help="Punch timestamp stored in naive UTC.")
    punch_type = fields.Selection([
        ('in', 'Check In'),
        ('out', 'Check Out'),
        ('break_out', 'Break Out'),
        ('break_in', 'Break In'),
        ('ot_in', 'Overtime In'),
        ('ot_out', 'Overtime Out'),
        ('unknown', 'Unknown'),
    ], default='unknown')
    status_code = fields.Char(help="Raw device status field from the ATTLOG line.")
    verify_mode = fields.Selection([
        ('password', 'Password'),
        ('fingerprint', 'Fingerprint'),
        ('card', 'Card'),
        ('face', 'Face'),
        ('palm', 'Palm'),
        ('other', 'Other'),
    ], default='other')
    raw_payload = fields.Char(help="Original raw ATTLOG line as received from the device.")
    processed = fields.Boolean(default=False, index=True)
    process_state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Processed'),
        ('unmatched', 'Unmatched Employee'),
        ('duplicate', 'Duplicate'),
        ('skipped', 'Skipped'),
        ('error', 'Error'),
    ], default='pending', index=True)
    process_note = fields.Char()
    hr_attendance_id = fields.Many2one(
        'hr.attendance', ondelete='set null', copy=False, index=True,
        help="Attendance record generated from this punch (traceability).")
    punch_status = fields.Selection([
        # in_early / out_late are legacy values: the engine no longer
        # produces them (early arrivals and late leaves rate as on time),
        # but rows written before the unification may still carry them.
        ('in_early', 'On Time(IN)'),
        ('in_on_time', 'On Time(IN)'),
        ('in_late', 'Late arrival'),
        ('out_early', 'Early leave'),
        ('out_on_time', 'On Time(OUT)'),
        ('out_late', 'On Time(OUT)'),
    ], compute='_compute_punch_status', store=True,
        help="Rating of this punch against the fixed working time policy, "
             "taken from the attendance edge the punch produced.")

    # Odoo 19+ no longer honors the classic ``_sql_constraints`` list, so the
    # unique constraint is declared with the ``models.Constraint`` API.  The
    # attribute name ``_punch_uniq`` produces a DB constraint whose short name
    # is ``punch_uniq``; this actually enforces uniqueness, which the offline
    # replay de-duplication (IntegrityError) relies on.
    _punch_uniq = models.Constraint(
        'unique(device_id, biometric_user_id, punch_datetime, status_code)',
        'This punch was already recorded (duplicate replay ignored).',
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------
    @api.depends('hr_attendance_id', 'punch_datetime',
                 'hr_attendance_id.check_in', 'hr_attendance_id.check_out',
                 'hr_attendance_id.check_in_status',
                 'hr_attendance_id.check_out_status',
                 'hr_attendance_id.overtime_attendance_ids.check_out')
    def _compute_punch_status(self):
        """Mirror the rating of the attendance edge this punch produced.

        The punch's role (check-in vs check-out) is derived by comparing its
        timestamp to the linked attendance's edges — the device punch *type*
        is not reliable, as some pairing modes ignore it.  Punches that are
        not an edge (middle punches, unprocessed logs) or whose attendance
        carries no rating stay blank.
        """
        for rec in self:
            att = rec.hr_attendance_id
            status = False
            if att and rec.punch_datetime:
                # Odoo 20 time rules can split a long attendance: the part
                # beyond the working time becomes an overtime attendance and
                # the source ends earlier.  The check-out punch then ends the
                # last part, and the rating stays on the source attendance.
                check_outs = [dt for dt in [att.check_out] + att.overtime_attendance_ids.mapped('check_out') if dt]
                if (att.check_in and rec.punch_datetime == att.check_in
                        and att.check_in_status):
                    status = 'in_%s' % att.check_in_status
                elif (check_outs and rec.punch_datetime == max(check_outs)
                        and att.check_out_status):
                    status = 'out_%s' % att.check_out_status
            rec.punch_status = status

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @api.model
    def _parse_attlog_line(self, line):
        """Parse a single raw ATTLOG line.

        ATTLOG columns (tab separated, whitespace tolerated):
            pin, 'YYYY-MM-DD HH:MM:SS', status, verify, workcode, ...

        :return: dict with keys ``biometric_user_id``, ``datetime_str``,
                 ``status_code``, ``verify_code`` and ``raw``; or ``None`` for
                 blank / malformed lines.
        """
        if not line:
            return None
        raw = line
        stripped = line.strip()
        if not stripped:
            return None

        if '\t' in stripped:
            parts = [p.strip() for p in stripped.split('\t')]
        else:
            # Whitespace fallback: the datetime itself spans two tokens
            # (date + time), so reconstruct it explicitly.
            tokens = stripped.split()
            if len(tokens) < 3:
                return None
            parts = [tokens[0], '%s %s' % (tokens[1], tokens[2])] + tokens[3:]

        if len(parts) < 2:
            return None

        biometric_user_id = (parts[0] or '').strip()
        datetime_str = (parts[1] or '').strip()
        if not biometric_user_id or not datetime_str:
            return None

        # Validate the timestamp; a line we cannot read a datetime from is malformed.
        try:
            datetime.strptime(datetime_str, ATTLOG_DT_FORMAT)
        except (ValueError, TypeError):
            return None

        status_code = (parts[2].strip() if len(parts) > 2 else '') or ''
        verify_code = (parts[3].strip() if len(parts) > 3 else '') or ''

        return {
            'biometric_user_id': biometric_user_id,
            'datetime_str': datetime_str,
            'status_code': status_code,
            'verify_code': verify_code,
            'raw': raw,
        }

    @api.model
    def _local_str_to_utc(self, datetime_str, tz):
        """Convert a device-local datetime string to a naive UTC datetime.

        :param datetime_str: 'YYYY-MM-DD HH:MM:SS' in the device timezone.
        :param tz: a ``pytz`` timezone object for the device.
        :return: naive ``datetime`` in UTC, or ``None`` on failure.
        """
        try:
            naive_local = datetime.strptime(datetime_str, ATTLOG_DT_FORMAT)
        except (ValueError, TypeError):
            return None
        try:
            local_dt = tz.localize(naive_local)
        except Exception:
            # e.g. non-existent/ambiguous DST wall-clock time
            local_dt = tz.localize(naive_local, is_dst=None) if hasattr(tz, 'localize') else naive_local
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    # ------------------------------------------------------------------
    # Ingestion (called by the ADMS controller)
    # ------------------------------------------------------------------
    @api.model
    def ingest_attlog(self, device, body_text):
        """Ingest a raw ATTLOG POST body for ``device``.

        Parses each line, converts the device-local timestamp to naive UTC,
        maps status/verify codes, de-duplicates offline replays and creates
        the log records (as sudo).  Then matches employees and runs the
        processing engine on the freshly created logs.

        :return: tuple ``(created_recordset, created_count)``.
        """
        Log = self.sudo()
        if not device or not body_text:
            return Log.browse(), 0

        device = device.sudo()
        tz = pytz.timezone(device.tz or 'UTC')

        # 1) Parse + normalize every line, de-duplicating within this batch.
        prepared = []
        seen_keys = set()
        for line in body_text.splitlines():
            parsed = self._parse_attlog_line(line)
            if not parsed:
                continue
            punch_dt = self._local_str_to_utc(parsed['datetime_str'], tz)
            if punch_dt is None:
                continue
            status_code = parsed['status_code'] or False
            key = (device.id, parsed['biometric_user_id'], punch_dt, status_code)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            prepared.append({
                'device_id': device.id,
                'biometric_user_id': parsed['biometric_user_id'],
                'punch_datetime': punch_dt,
                'status_code': status_code,
                'punch_type': STATUS_MAP.get(parsed['status_code'], 'unknown'),
                'verify_mode': VERIFY_MAP.get(parsed['verify_code'], 'other'),
                'raw_payload': parsed['raw'],
            })

        if not prepared:
            return Log.browse(), 0

        # 2) Pre-search existing punches to skip offline replays cheaply.
        pins = list({v['biometric_user_id'] for v in prepared})
        stamps = list({v['punch_datetime'] for v in prepared})
        existing = Log.search([
            ('device_id', '=', device.id),
            ('biometric_user_id', 'in', pins),
            ('punch_datetime', 'in', stamps),
        ])
        existing_keys = {
            (r.device_id.id, r.biometric_user_id, r.punch_datetime, r.status_code or False)
            for r in existing
        }

        # 3) Create the survivors.  Each create runs in its own savepoint so a
        #    concurrent replay hitting the unique constraint is skipped
        #    silently without aborting the whole ingest.
        created = Log.browse()
        for vals in prepared:
            key = (vals['device_id'], vals['biometric_user_id'],
                   vals['punch_datetime'], vals['status_code'] or False)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            try:
                with self.env.cr.savepoint():
                    rec = Log.create(vals)
                created |= rec
            except IntegrityError:
                # Duplicate replay caught by the punch_uniq constraint.
                _logger.debug(
                    "ZKTeco: duplicate punch ignored (device=%s pin=%s at=%s)",
                    device.id, vals['biometric_user_id'], vals['punch_datetime'])
                continue

        # 4) Match employees and run the engine on the new logs.
        if created:
            created._match_employee()
            created._process_logs()

        return created, len(created)

    @api.model
    def ingest_operlog(self, device, body_text):
        """Minimal OPERLOG handler.

        Scans the operation log for user-related records.  This never raises;
        it merely returns the number of ``USER`` lines seen so the controller
        can acknowledge the upload.
        """
        if not body_text:
            return 0
        count = 0
        try:
            for line in body_text.splitlines():
                token = line.strip().upper()
                if not token:
                    continue
                # ADMS operation-log user records, e.g. "USER PIN=1\t..." or
                # "OPLOG ... USER ...".
                if token.startswith('USER') or ' USER ' in (' %s ' % token):
                    count += 1
        except Exception:  # never raise from an ingest path
            _logger.exception("ZKTeco: failed to scan OPERLOG for device %s",
                              device.id if device else None)
        return count

    # ------------------------------------------------------------------
    # Employee matching
    # ------------------------------------------------------------------
    def _match_employee(self):
        """Resolve ``employee_id`` for each log from its biometric id.

        Prefers an employee in the same company as the punch, then falls back
        to any employee carrying the biometric id.  Logs with no match are
        flagged ``unmatched`` and left unprocessed.
        """
        Employee = self.env['hr.employee'].sudo()
        for rec in self:
            pin = rec.biometric_user_id
            if not pin:
                rec.write({
                    'employee_id': False,
                    'process_state': 'unmatched',
                    'processed': False,
                    'process_note': _("No biometric id on the punch."),
                })
                continue

            employee = self.env['hr.employee']
            if rec.company_id:
                employee = Employee.search([
                    ('biometric_user_id', '=', pin),
                    ('company_id', '=', rec.company_id.id),
                ], limit=1)
            if not employee:
                employee = Employee.search([
                    ('biometric_user_id', '=', pin),
                ], limit=1)

            if employee:
                vals = {'employee_id': employee.id}
                # Clear a previous "unmatched" verdict so the engine can retry.
                if rec.process_state == 'unmatched':
                    vals['process_state'] = 'pending'
                    vals['process_note'] = False
                rec.write(vals)
            else:
                rec.write({
                    'employee_id': False,
                    'process_state': 'unmatched',
                    'processed': False,
                    'process_note': _("No employee with biometric id '%s'.", pin),
                })

    # ------------------------------------------------------------------
    # Processing engine
    # ------------------------------------------------------------------
    def _process_logs(self):
        """Main engine: turn matched, unprocessed punches into attendances.

        Records without an employee are flagged ``unmatched`` and skipped.
        Matched, unprocessed records are grouped by employee; for each employee
        the punches are grouped by their *local* calendar date, the applicable
        policy is resolved for that date and the policy is asked to build the
        attendances from the ascending-sorted punches of that date.
        """
        Policy = self.env['hr.attendance.policy']

        # Unmatched punches: mark and skip (never mark them processed).
        unmatched = self.filtered(lambda r: not r.employee_id)
        for rec in unmatched:
            if not rec.processed and rec.process_state != 'unmatched':
                rec.write({'process_state': 'unmatched'})

        to_process = self.filtered(lambda r: r.employee_id and not r.processed)
        if not to_process:
            return

        # Group logs by employee.
        by_employee = defaultdict(lambda: self.browse())
        for rec in to_process:
            by_employee[rec.employee_id] |= rec

        for employee, emp_logs in by_employee.items():
            tz = pytz.timezone(employee.sudo()._zk_punch_tz())

            # Group this employee's punches by their local calendar date.
            logs_by_date = defaultdict(lambda: self.browse())
            for log in emp_logs:
                local_date = pytz.utc.localize(log.punch_datetime).astimezone(tz).date()
                logs_by_date[local_date] |= log

            # Apply the resolved policy per local date, in chronological order.
            for local_date in sorted(logs_by_date):
                date_logs = logs_by_date[local_date].sorted(
                    key=lambda r: (r.punch_datetime, r.id))
                policy = Policy._resolve_for_employee(employee, local_date)
                # Odoo 20: hr.attendance requires a work entry type, defaulted
                # from env.company.  Device pushes run without a user (auth='none'),
                # so the employee's company is set explicitly.
                company = employee.sudo().company_id
                try:
                    # Savepoint: a failing policy must not leave partial
                    # writes behind (an attendance row is INSERTed before its
                    # constraints fire; catching the error without a rollback
                    # would commit that orphan open attendance).
                    with self.env.cr.savepoint():
                        policy.sudo().with_company(company).apply_to_logs(
                            date_logs.sudo().with_company(company))
                except Exception as exc:  # keep other employees/dates flowing
                    _logger.exception(
                        "ZKTeco: policy '%s' failed for employee %s on %s",
                        policy.display_name if policy else '?', employee.id, local_date)
                    date_logs.write({
                        'process_state': 'error',
                        'process_note': str(exc)[:255],
                    })

        # Safety normalization: any punch the policy linked to an attendance
        # but did not explicitly finalize is marked done/processed.
        for rec in to_process:
            if rec.hr_attendance_id and not rec.processed:
                vals = {'processed': True}
                if rec.process_state in ('pending', False):
                    vals['process_state'] = 'done'
                rec.write(vals)

    def action_reprocess(self):
        """Button: reset the selected punches and run the engine again."""
        self.write({
            'processed': False,
            'process_state': 'pending',
            'process_note': False,
            'hr_attendance_id': False,
        })
        self._match_employee()
        self._process_logs()
        return True
