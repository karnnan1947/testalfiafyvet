# -*- coding: utf-8 -*-
import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytz

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Punch types by which a device reports the start / end of a work period.
IN_PUNCH_TYPES = ('in', 'break_in', 'ot_in')
OUT_PUNCH_TYPES = ('out', 'break_out', 'ot_out')


class HrAttendancePolicy(models.Model):
    """Attendance Policy Engine.

    A policy decides how a stream of raw biometric punches for a single
    employee is turned into ``hr.attendance`` check-in / check-out records.
    Four resolution *modes* are supported, each with its own pairing logic:

    * ``device_status`` - trust the punch's status code (in / out / break / ot).
    * ``first_check``   - first punch of the local day opens the day, later
      punches push the check-out to the latest punch.
    * ``flexible``      - toggle pairing bounded by a maximum shift span.
    * ``calendar``      - classify punches against the employee's work
      schedule boundaries (falls back to ``flexible`` when no calendar).
    * ``fixed_time``    - toggle pairing like ``flexible``, additionally
      rating every check-in / check-out against a fixed shift (check-in:
      on time / late arrival; check-out: early leave / on time, within a
      tolerance).
    """
    _name = 'hr.attendance.policy'
    _description = 'Attendance Policy'
    _order = 'name'

    name = fields.Char(required=True)
    mode = fields.Selection([
        ('device_status', 'Device Status Code'),
        ('first_check', 'First Check Time'),
        ('flexible', 'Flexible Period'),
        ('calendar', 'Work Schedule (Calendar)'),
        ('fixed_time', 'Fixed Working Time'),
    ], required=True, default='device_status')
    flexible_window_hours = fields.Float(
        string="Max Shift Span (h)", default=12.0,
        help="A punch beyond this span from the open check-in starts a new "
             "attendance.")
    dedup_window_seconds = fields.Integer(
        string="Duplicate Window (s)", default=60,
        help="Ignore a punch that repeats within this many seconds.")
    min_gap_minutes = fields.Integer(
        string="Min Gap After Check-out (min)", default=1,
        help="A check-in occurring within this many minutes of the previous "
             "check-out is merged back into that attendance instead of "
             "starting a new one.")
    shift_start_time = fields.Float(
        string="Shift Start", default=9.0,
        help="Fixed working time: expected check-in time as hours "
             "(9.5 = 09:30), in the employee's timezone.")
    shift_end_time = fields.Float(
        string="Shift End", default=18.0,
        help="Fixed working time: expected check-out time as hours, "
             "in the employee's timezone.")
    late_in_tolerance = fields.Integer(
        string="Check-in Tolerance (min)", default=5,
        help="Grace window after the shift start: a check-in up to this "
             "many minutes past the start is still 'On Time(IN)'; later is "
             "'Late arrival'. Any earlier check-in is 'On Time(IN)'.")
    early_out_tolerance = fields.Integer(
        string="Check-out Tolerance (min)", default=5,
        help="Grace window before the shift end: a check-out up to this "
             "many minutes before the end is still 'On Time(OUT)'; earlier "
             "is 'Early leave'. Any later check-out is 'On Time(OUT)'.")
    first_in_last_out = fields.Boolean(
        string="First IN / Last OUT Only",
        default=False,
        help="When enabled, only the day's first punch is treated as Check-In and the day's "
             "final punch as Check-Out. Intermediate punches are recorded as logs but do not "
             "close the session or create intermediate attendances. Preserves Fixed Shift ratings.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)
    note = fields.Text()

    @api.constrains('mode', 'shift_start_time', 'shift_end_time')
    def _check_fixed_time_shift(self):
        for policy in self:
            if policy.mode != 'fixed_time':
                continue
            for value in (policy.shift_start_time, policy.shift_end_time):
                if not 0.0 <= value < 24.0:
                    raise ValidationError(_(
                        "Fixed working time hours must be within 00:00-23:59."))
            if policy.shift_end_time <= policy.shift_start_time:
                raise ValidationError(_(
                    "The shift end time must be after the shift start time "
                    "(overnight shifts are not supported by the fixed "
                    "working time mode)."))

    # ==================================================================
    # Resolution
    # ==================================================================
    @api.model
    def _resolve_for_employee(self, employee, punch_date):
        """Return the policy that governs ``employee`` on ``punch_date``.

        The lookup never returns an empty recordset; it walks a priority
        chain and falls back to a sensible default:

        1. an employee policy line covering ``punch_date`` (open bounds ok);
        2. the employee's ``biometric_policy_id``;
        3. the company's ``zkteco_default_policy_id``;
        4. the first ``device_status`` policy of the company (or global);
        5. as a last resort, a new in-memory ``device_status`` policy.

        :param employee: an ``hr.employee`` record.
        :param punch_date: a ``datetime.date`` in the employee's local tz.
        """
        employee = employee.sudo()

        # 1) Employee-specific assignment lines matching the date.
        lines = employee.zkteco_policy_line_ids.filtered(lambda line: (
            (not line.date_from or line.date_from <= punch_date)
            and (not line.date_to or line.date_to >= punch_date)
            and line.policy_id
        ))
        if lines:
            # Prefer the most recently starting (most specific) assignment.
            line = lines.sorted(
                key=lambda line: (line.date_from or date.min), reverse=True)[0]
            return line.policy_id.sudo()

        # 2) Employee default policy.
        if employee.biometric_policy_id:
            return employee.biometric_policy_id.sudo()

        # 3) Company default policy.
        company = employee.company_id or self.env.company
        if company.zkteco_default_policy_id:
            return company.zkteco_default_policy_id.sudo()

        # 4) First device_status policy for the company (or a global one).
        policy = self.sudo().search([
            ('mode', '=', 'device_status'),
            '|', ('company_id', '=', company.id), ('company_id', '=', False),
        ], limit=1)
        if policy:
            return policy

        # 5) Any policy for the company, then the last-resort in-memory default.
        policy = self.sudo().search([
            '|', ('company_id', '=', company.id), ('company_id', '=', False),
        ], limit=1)
        if policy:
            return policy

        return self.sudo().new({
            'name': _("Default (Device Status)"),
            'mode': 'device_status',
            'company_id': company.id,
        })

    # ==================================================================
    # Dispatch
    # ==================================================================
    def apply_to_logs(self, logs):
        """Turn one employee's ascending ``logs`` into attendance records.

        Dispatches to the helper matching :attr:`mode`. ``logs`` is expected
        to hold a single employee's punches; they are (re)sorted defensively
        by punch time before processing.
        """
        self.ensure_one()
        if not logs:
            return
        logs = logs.sorted(key=lambda rec: (rec.punch_datetime, rec.id))
        mode = self.mode or 'device_status'
        if mode == 'first_check':
            self._apply_first_check(logs)
        elif mode == 'flexible':
            self._apply_flexible(logs)
        elif mode == 'calendar':
            self._apply_calendar(logs)
        elif mode == 'fixed_time':
            self._apply_fixed_time(logs)
        else:
            self._apply_device_status(logs)

    # ==================================================================
    # Mode: device status code
    # ==================================================================
    def _apply_device_status(self, logs):
        """Pair punches by the status the device reported for each one.

        ``in`` / ``break_in`` / ``ot_in`` open (or continue) an attendance;
        ``out`` / ``break_out`` / ``ot_out`` close the open attendance (opening
        one first if none is currently open).
        """
        self.ensure_one()
        in_types = IN_PUNCH_TYPES
        out_types = OUT_PUNCH_TYPES
        for log in logs:
            employee = log.employee_id
            dt = log.punch_datetime
            if not employee or not dt:
                self._mark_skipped(log, _("Missing employee or punch time."))
                continue
            if self._is_duplicate_punch(employee, dt):
                self._mark_duplicate(log)
                continue

            ptype = log.punch_type or 'unknown'
            if ptype in in_types:
                open_att = self._open_attendance(employee)
                if open_att:
                    # Already checked in (missed check-out): keep the session.
                    self._link_done(log, open_att)
                else:
                    self._checkin_respecting_gap(employee, dt, log)
            elif ptype in out_types:
                open_att = self._open_attendance(employee)
                if not open_att:
                    open_att = self._create_checkin(employee, dt, log)
                self._close_checkout(open_att, dt, log)
            else:
                self._mark_skipped(
                    log, _("Unknown device status; punch not classified."))

    # ==================================================================
    # Mode: first check time
    # ==================================================================
    def _apply_first_check(self, logs):
        """First punch of the local day opens the attendance.

        Every later punch of the same day pushes the check-out forward to the
        latest punch time. A single punch simply leaves the day open.

        Live devices push each punch in its own batch, so the day's
        attendance is looked up per punch and a later punch extends its
        recorded check-out rather than merely linking to it.
        """
        self.ensure_one()
        day_att = None
        for log in logs:
            employee = log.employee_id
            dt = log.punch_datetime
            if not employee or not dt:
                self._mark_skipped(log, _("Missing employee or punch time."))
                continue
            if self._is_duplicate_punch(employee, dt):
                self._mark_duplicate(log)
                continue

            if day_att is None:
                # Reuse an attendance already recorded for this local day
                # (real-time single-punch batches, reprocessing); a punch
                # later than what is on record pushes the check-out forward.
                # Otherwise open a fresh one, first closing any stale session
                # a previous day left open.
                day_att = self._day_attendance(employee, dt)
                if day_att:
                    if dt > day_att.check_in and (
                            not day_att.check_out or dt > day_att.check_out):
                        self._close_checkout(day_att, dt, log)
                    else:
                        self._link_done(log, day_att)
                else:
                    self._close_stale_open_attendance(employee, dt)
                    day_att = self._create_checkin(employee, dt, log)
            elif dt > day_att.check_in:
                self._close_checkout(day_att, dt, log)
            else:
                # Punch at/before the opening punch: nothing to extend.
                self._link_done(log, day_att)

    # ==================================================================
    # Mode: flexible period
    # ==================================================================
    def _apply_flexible(self, logs):
        """Toggle pairing bounded by :attr:`flexible_window_hours`.

        With an open attendance, a punch within the span closes it; a punch
        beyond the span is treated as a forgotten check-out - the stale
        session is closed at its own check-in and a new attendance is opened.
        """
        self.ensure_one()
        window = self.flexible_window_hours or 12.0
        for log in logs:
            employee = log.employee_id
            dt = log.punch_datetime
            if not employee or not dt:
                self._mark_skipped(log, _("Missing employee or punch time."))
                continue
            if self._is_duplicate_punch(employee, dt):
                self._mark_duplicate(log)
                continue

            open_att = self._open_attendance(employee)
            if open_att:
                span_hours = (dt - open_att.check_in).total_seconds() / 3600.0
                if 0 <= span_hours <= window:
                    self._close_checkout(open_att, dt, log)
                else:
                    # Forgotten check-out: close the stale session and reopen.
                    self._close_checkout(open_att, open_att.check_in, None)
                    self._create_checkin(employee, dt, log)
            else:
                self._checkin_respecting_gap(employee, dt, log)

    # ==================================================================
    # Mode: work schedule (calendar)
    # ==================================================================
    def _apply_calendar(self, logs):
        """Classify punches against the employee's work-schedule boundaries.

        Each punch is labelled a check-in or check-out by whichever calendar
        boundary (shift start vs shift end) it lands closest to, then paired
        with the standard toggle logic. Without a calendar or resource, the
        method degrades gracefully to :meth:`_apply_flexible`.
        """
        self.ensure_one()
        employee = logs[:1].employee_id.sudo()
        calendar = employee.resource_calendar_id
        resource = employee.resource_id
        if not calendar or not resource:
            return self._apply_flexible(logs)

        work_periods = self._calendar_work_periods(employee, logs)
        if not work_periods:
            # No scheduled work around these punches: flexible fallback.
            return self._apply_flexible(logs)

        for log in logs:
            emp = log.employee_id
            dt = log.punch_datetime
            if not emp or not dt:
                self._mark_skipped(log, _("Missing employee or punch time."))
                continue
            if self._is_duplicate_punch(emp, dt):
                self._mark_duplicate(log)
                continue

            kind = self._classify_by_calendar(dt, work_periods)
            open_att = self._open_attendance(emp)
            if kind is None:
                # Off-schedule punch: fall back to a simple toggle.
                kind = 'out' if open_att else 'in'

            if kind == 'in':
                if open_att:
                    self._link_done(log, open_att)
                else:
                    self._checkin_respecting_gap(emp, dt, log)
            else:
                if not open_att:
                    open_att = self._create_checkin(emp, dt, log)
                self._close_checkout(open_att, dt, log)

    def _calendar_work_periods(self, employee, logs):
        """Return the employee's work intervals (naive UTC) around ``logs``.

        :return: sorted list of ``(start_utc, end_utc)`` naive datetimes.
        """
        try:
            tz_name = employee._get_tz() or 'UTC'
            tz = pytz.timezone(tz_name)
            first_dt = logs[0].punch_datetime
            last_dt = logs[-1].punch_datetime
            start_local = pytz.utc.localize(first_dt).astimezone(tz).replace(
                hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            end_local = pytz.utc.localize(last_dt).astimezone(tz).replace(
                hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
            # Odoo 20: the resources are passed grouped by timezone.
            intervals = employee.resource_calendar_id._work_intervals_batch(
                start_local, end_local,
                resources_per_tz={ZoneInfo(tz_name): employee.resource_id},
            )[employee.resource_id.id]
        except Exception:  # never let scheduling quirks break ingestion
            _logger.warning(
                "ZKTeco: calendar work intervals unavailable for employee %s",
                employee.id, exc_info=True)
            return []

        periods = []
        for start, stop, _meta in intervals:
            start_utc = start.astimezone(pytz.utc).replace(tzinfo=None)
            stop_utc = stop.astimezone(pytz.utc).replace(tzinfo=None)
            periods.append((start_utc, stop_utc))
        periods.sort()
        return periods

    def _classify_by_calendar(self, dt, work_periods):
        """Label ``dt`` as ``'in'`` or ``'out'`` by nearest shift boundary.

        Returns ``None`` when no boundary lies within a reasonable window
        (12h) of the punch, letting the caller fall back to a plain toggle.
        """
        best_distance = None
        best_kind = None
        for start_utc, stop_utc in work_periods:
            d_start = abs((dt - start_utc).total_seconds())
            d_stop = abs((dt - stop_utc).total_seconds())
            if best_distance is None or d_start < best_distance:
                best_distance = d_start
                best_kind = 'in'
            if d_stop < best_distance:
                best_distance = d_stop
                best_kind = 'out'
        if best_distance is None or best_distance > 12 * 3600:
            return None
        return best_kind

    # ==================================================================
    # Mode: fixed working time
    # ==================================================================
    def _apply_fixed_time(self, logs):
        """Pair punches against a fixed shift, rating every edge.

        Without :attr:`first_in_last_out` the standard toggle pairing of
        :meth:`_apply_fixed_time_toggle` applies.  With it, the first punch
        of the local day is the check-in (rated against the shift start) and
        every later punch pushes the check-out forward to itself (re-rated
        against the shift end), so the day's final punch is the check-out.
        Intermediate punches are linked to the day's attendance as done and
        never close or split the session.
        """
        self.ensure_one()
        if not self.first_in_last_out:
            # Existing standard toggle logic remains untouched
            return self._apply_fixed_time_toggle(logs)

        # ------------------------------------------------------------------
        # Enhanced Mode: Fixed Working Time with First-IN / Last-OUT
        # ------------------------------------------------------------------
        for log in logs:
            employee = log.employee_id
            dt = log.punch_datetime
            if not employee or not dt:
                self._mark_skipped(log, _("Missing employee or punch time."))
                continue
            if self._is_duplicate_punch(employee, dt):
                self._mark_duplicate(log)
                continue

            day_att = self._day_attendance(employee, dt)
            if day_att:
                # An attendance already exists for today: a punch later than
                # what is on record pushes the Check-Out forward to it.  An
                # older punch arriving late (device offline sync) must not
                # pull the check-out back, it is only linked.
                if dt > day_att.check_in and (
                        not day_att.check_out or dt > day_att.check_out):
                    self._close_checkout(day_att, dt, log)
                    # Re-evaluate check-out rating against shift end (e.g. Early leave vs On Time)
                    day_att.sudo().write({
                        'check_out_status': self._rate_fixed_time(
                            employee, dt, self.shift_end_time,
                            self.early_out_tolerance, is_check_in=False),
                    })
                else:
                    self._link_done(log, day_att)
            else:
                # First punch of the day: opens the attendance session
                self._close_stale_open_attendance(employee, dt)
                day_att = self._create_checkin(employee, dt, log)
                day_att.sudo().write({
                    'check_in_status': self._rate_fixed_time(
                        employee, dt, self.shift_start_time,
                        self.late_in_tolerance, is_check_in=True),
                })

    def _apply_fixed_time_toggle(self, logs):
        """Toggle pairing against a fixed shift, rating every edge.

        Punches pair exactly like :meth:`_apply_flexible` (toggle bounded by
        :attr:`flexible_window_hours`; a punch beyond the span closes the
        stale session and reopens).  Additionally, each check-in is rated
        against :attr:`shift_start_time` (past the tolerance -> ``late``,
        otherwise ``on_time``) and each check-out against
        :attr:`shift_end_time` (before the tolerance -> ``early``, otherwise
        ``on_time``), both in the employee's timezone.
        """
        self.ensure_one()
        window = self.flexible_window_hours or 12.0
        for log in logs:
            employee = log.employee_id
            dt = log.punch_datetime
            if not employee or not dt:
                self._mark_skipped(log, _("Missing employee or punch time."))
                continue
            if self._is_duplicate_punch(employee, dt):
                self._mark_duplicate(log)
                continue

            open_att = self._open_attendance(employee)
            if open_att:
                span_hours = (dt - open_att.check_in).total_seconds() / 3600.0
                if 0 <= span_hours <= window:
                    attendance = self._close_checkout(open_att, dt, log)
                    attendance.sudo().write({
                        'check_out_status': self._rate_fixed_time(
                            employee, dt, self.shift_end_time,
                            self.early_out_tolerance, is_check_in=False),
                    })
                    continue
                # Forgotten check-out: close the stale session and reopen.
                self._close_checkout(open_att, open_att.check_in, None)

            # Nothing is open, yet the device reports this punch as the end of
            # a work period: the matching check-in never reached Odoo (device
            # enrolled mid-day, missed punch, failed sync).  Opening a session
            # from it would invent a check-in hours after the shift start -
            # rating a *check-out* as a "Late arrival" - and leave behind a
            # zero-duration attendance as soon as the next punch closes it.
            # Skip it instead, so the gap stays visible for HR to correct.
            if log.punch_type in OUT_PUNCH_TYPES:
                self._mark_skipped(log, _(
                    "Check-out with no open check-in: the matching check-in "
                    "for this employee is missing."))
                continue

            attendance = self._checkin_respecting_gap(employee, dt, log)
            if attendance:
                vals = {}
                if not attendance.check_in_status:
                    vals['check_in_status'] = self._rate_fixed_time(
                        employee, dt, self.shift_start_time,
                        self.late_in_tolerance)
                # A session reopened by the gap merge is open again: its old
                # check-out rating no longer describes anything.
                if not attendance.check_out and attendance.check_out_status:
                    vals['check_out_status'] = False
                if vals:
                    attendance.sudo().write(vals)

    def _rate_fixed_time(self, employee, dt_utc, boundary_hour, tolerance_min,
                         is_check_in=True):
        """Rate ``dt_utc`` against ``boundary_hour`` in the employee's tz.

        Only the unfavourable side of the boundary is flagged: a check-in is
        ``late`` past the tolerance and ``on_time`` otherwise (however early);
        a check-out is ``early`` before the tolerance and ``on_time``
        otherwise (however late).

        :param dt_utc: naive UTC punch datetime.
        :param boundary_hour: shift boundary as a float hour (9.5 = 09:30).
        :param tolerance_min: grace window in minutes.
        :param is_check_in: rate against the shift start (``True``) or the
            shift end (``False``).
        :return: ``'on_time'`` / ``'late'`` for a check-in,
            ``'early'`` / ``'on_time'`` for a check-out.
        """
        tz = pytz.timezone(employee.sudo()._zk_punch_tz())
        local = pytz.utc.localize(dt_utc).astimezone(tz)
        hour = int(boundary_hour)
        minute = int(round((boundary_hour - hour) * 60))
        if minute >= 60:
            hour, minute = hour + 1, minute - 60
        boundary = local.replace(
            hour=hour % 24, minute=minute, second=0, microsecond=0)
        delta_min = (local - boundary).total_seconds() / 60.0
        tolerance = max(tolerance_min or 0, 0)
        if is_check_in:
            return 'late' if delta_min > tolerance else 'on_time'
        return 'early' if delta_min < -tolerance else 'on_time'

    # ==================================================================
    # Shared attendance helpers
    # ==================================================================
    def _open_attendance(self, employee):
        """Return the latest still-open attendance for ``employee`` (or empty)."""
        return self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
        ], order='check_in desc', limit=1)

    def _close_stale_open_attendance(self, employee, dt):
        """Close an open attendance left over from an earlier punch.

        Core ``hr.attendance`` forbids two open attendances per employee, so
        a forgotten check-out would make every later check-in creation fail.
        Mirroring the flexible mode, the stale session is closed at its own
        check-in (zero duration) so it stays visible for HR to correct.
        """
        stale = self._open_attendance(employee)
        if stale and stale.check_in and stale.check_in < dt:
            self._close_checkout(stale, stale.check_in, None)

    def _create_checkin(self, employee, dt, log):
        """Create and return a technical check-in; link and finalize ``log``."""
        attendance = self.env['hr.attendance'].sudo().create({
            'employee_id': employee.id,
            'check_in': dt,
            'in_mode': 'technical',
        })
        if log is not None:
            self._link_done(log, attendance)
        return attendance

    def _close_checkout(self, attendance, dt, log):
        """Close ``attendance`` at ``dt`` (never before its check-in)."""
        if not attendance:
            return attendance
        if attendance.check_in and dt < attendance.check_in:
            dt = attendance.check_in
        attendance.sudo().write({
            'check_out': dt,
            'out_mode': 'technical',
        })
        if log is not None:
            self._link_done(log, attendance)
        return attendance

    def _checkin_respecting_gap(self, employee, dt, log):
        """Open a check-in, or merge into a just-closed attendance.

        If the previous attendance closed within :attr:`min_gap_minutes` of
        ``dt``, that session is reopened (its check-out cleared) rather than
        fragmenting one work period into two because of a stray out/in pair.
        """
        gap = self.min_gap_minutes or 0
        if gap > 0:
            recent = self.env['hr.attendance'].sudo().search([
                ('employee_id', '=', employee.id),
                ('check_out', '!=', False),
            ], order='check_out desc', limit=1)
            if recent and recent.check_out:
                delta = (dt - recent.check_out).total_seconds()
                if 0 <= delta <= gap * 60:
                    recent.sudo().write({'check_out': False})
                    self._link_done(log, recent)
                    return recent
        return self._create_checkin(employee, dt, log)

    def _is_duplicate_punch(self, employee, dt):
        """Return ``True`` if an attendance edge sits within the dedup window.

        A punch whose time is within :attr:`dedup_window_seconds` of an
        existing check-in or check-out for the employee is a device double
        read and should be ignored.
        """
        window = self.dedup_window_seconds or 0
        if window <= 0:
            return False
        delta = timedelta(seconds=window)
        lower = dt - delta
        upper = dt + delta
        Attendance = self.env['hr.attendance'].sudo()
        if Attendance.search_count([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', lower),
            ('check_in', '<=', upper),
        ], limit=1):
            return True
        if Attendance.search_count([
            ('employee_id', '=', employee.id),
            ('check_out', '>=', lower),
            ('check_out', '<=', upper),
        ], limit=1):
            return True
        return False

    def _day_attendance(self, employee, dt):
        """Return an attendance whose check-in falls on ``dt``'s local day."""
        tz = pytz.timezone(employee.sudo()._zk_punch_tz())
        local = pytz.utc.localize(dt).astimezone(tz)
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)
        return self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', start_utc),
            ('check_in', '<', end_utc),
        ], order='check_in asc', limit=1)

    # ------------------------------------------------------------------
    # Log finalization helpers
    # ------------------------------------------------------------------
    def _link_done(self, log, attendance):
        """Link ``log`` to ``attendance`` and flag it processed/done."""
        if log is None:
            return
        log.write({
            'hr_attendance_id': attendance.id if attendance else False,
            'processed': True,
            'process_state': 'done',
            'process_note': False,
        })

    def _mark_duplicate(self, log):
        """Finalize ``log`` as an ignored duplicate punch."""
        if log is None:
            return
        log.write({
            'processed': True,
            'process_state': 'duplicate',
            'process_note': _("Duplicate punch within the dedup window."),
        })

    def _mark_skipped(self, log, note=None):
        """Finalize ``log`` as skipped, optionally recording ``note``."""
        if log is None:
            return
        log.write({
            'processed': True,
            'process_state': 'skipped',
            'process_note': (note or _("Punch skipped."))[:255],
        })


class ZktecoEmployeePolicyLine(models.Model):
    _name = 'zkteco.employee.policy.line'
    _description = 'Employee Attendance Policy Assignment'
    _order = 'date_from desc'

    employee_id = fields.Many2one(
        'hr.employee', required=True, ondelete='cascade', index=True)
    policy_id = fields.Many2one(
        'hr.attendance.policy', required=True, ondelete='restrict')
    date_from = fields.Date()
    date_to = fields.Date()
    company_id = fields.Many2one(
        related='employee_id.company_id', store=True)

    @api.constrains('date_from', 'date_to')
    def _check_date_order(self):
        for line in self:
            if line.date_from and line.date_to and line.date_from > line.date_to:
                raise ValidationError(_(
                    "The start date (%(start)s) cannot be after the end date "
                    "(%(end)s) on an attendance policy assignment.",
                    start=line.date_from, end=line.date_to))
