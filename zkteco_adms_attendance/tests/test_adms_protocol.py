# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta

from odoo import fields
from odoo.tests.common import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestADMSProtocol(TransactionCase):
    """Unit tests for the ZKTeco ADMS ingestion + attendance engine.

    Every fixture is built in :meth:`setUp` so each test runs against a clean,
    isolated transaction (rolled back afterwards) and is fully deterministic.
    The employee is pinned to the UTC timezone (Odoo 20: calendars carry no
    timezone) so that ``employee._get_tz()`` resolves to ``'UTC'`` and punch
    timestamps never drift across a local day boundary regardless of the
    host/company timezone.
    """

    def setUp(self):
        super().setUp()
        self.Device = self.env['zkteco.biometric.device']
        self.Log = self.env['zkteco.biometric.attendance.log']
        self.Policy = self.env['hr.attendance.policy']
        self.Attendance = self.env['hr.attendance']
        self.company = self.env.company

        # A dedicated calendar (the employee's own tz, UTC, sets the timezone).
        self.calendar = self.env['resource.calendar'].sudo().create({
            'name': 'ZKTeco Test Calendar',
            'company_id': self.company.id,
        })

        # A confirmed device operating in UTC.
        self.device = self.Device.sudo().create({
            'device_name': 'Test SpeedFace-V5L',
            'serial_number': 'TESTSN0001',
            'tz': 'UTC',
            'company_id': self.company.id,
        })
        self.device.action_confirm()

        # Primary device-status policy plus a flexible one (per contract).
        self.policy_status = self.Policy.sudo().create({
            'name': 'Test Device Status',
            'mode': 'device_status',
            'dedup_window_seconds': 60,
            'min_gap_minutes': 0,
            'company_id': self.company.id,
        })
        self.policy_flexible = self.Policy.sudo().create({
            'name': 'Test Flexible',
            'mode': 'flexible',
            'flexible_window_hours': 12.0,
            'dedup_window_seconds': 60,
            'min_gap_minutes': 0,
            'company_id': self.company.id,
        })

        # An employee enrolled on the device and pinned to the status policy.
        self.employee = self.env['hr.employee'].sudo().create({
            'name': 'Alice Tester',
            'company_id': self.company.id,
            'tz': 'UTC',
            'resource_calendar_id': self.calendar.id,
            'biometric_user_id': '1001',
            'biometric_policy_id': self.policy_status.id,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _line(self, pin, dt_str, status='0', verify='1', workcode='0'):
        """Build a single tab-separated ATTLOG line."""
        return '\t'.join([pin, dt_str, status, verify, workcode])

    def _make_log(self, when, status='0', ptype='in', pin=None, employee=True):
        """Create a raw log directly (bypassing ingest) for engine unit tests."""
        vals = {
            'device_id': self.device.id,
            'biometric_user_id': pin or self.employee.biometric_user_id,
            'punch_datetime': when,
            'status_code': status,
            'punch_type': ptype,
        }
        if employee:
            vals['employee_id'] = self.employee.id
        return self.Log.sudo().create(vals)

    def _employee_attendances(self, day=None):
        domain = [('employee_id', '=', self.employee.id)]
        if day is not None:
            start = datetime(day.year, day.month, day.day)
            domain += [
                ('check_in', '>=', start),
                ('check_in', '<', start + timedelta(days=1)),
            ]
        return self.Attendance.search(domain, order='check_in asc')

    # ------------------------------------------------------------------
    # _parse_attlog_line
    # ------------------------------------------------------------------
    def test_parse_attlog_line_valid(self):
        parsed = self.Log._parse_attlog_line(
            self._line('1001', '2024-01-15 09:00:00', '0', '1', '0'))
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed['biometric_user_id'], '1001')
        self.assertEqual(parsed['datetime_str'], '2024-01-15 09:00:00')
        self.assertEqual(parsed['status_code'], '0')
        self.assertEqual(parsed['verify_code'], '1')
        self.assertIn('raw', parsed)

    def test_parse_attlog_line_whitespace_fallback(self):
        # No tabs: the parser rebuilds the timestamp from two tokens.
        parsed = self.Log._parse_attlog_line('1001 2024-01-15 09:00:00 0 1')
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed['biometric_user_id'], '1001')
        self.assertEqual(parsed['datetime_str'], '2024-01-15 09:00:00')
        self.assertEqual(parsed['status_code'], '0')

    def test_parse_attlog_line_blank(self):
        self.assertIsNone(self.Log._parse_attlog_line(''))
        self.assertIsNone(self.Log._parse_attlog_line('   '))
        self.assertIsNone(self.Log._parse_attlog_line('\t\t'))
        self.assertIsNone(self.Log._parse_attlog_line(None))

    def test_parse_attlog_line_malformed(self):
        # Single token, nothing resembling a timestamp.
        self.assertIsNone(self.Log._parse_attlog_line('garbage'))
        # Only a PIN, no datetime column.
        self.assertIsNone(self.Log._parse_attlog_line('1001'))
        # A datetime column that does not parse.
        self.assertIsNone(
            self.Log._parse_attlog_line('1001\tnot-a-date\t0\t1'))
        # Empty PIN.
        self.assertIsNone(
            self.Log._parse_attlog_line('\t2024-01-15 09:00:00\t0\t1'))

    # ------------------------------------------------------------------
    # ingest_attlog: creation + de-duplication of an identical replay
    # ------------------------------------------------------------------
    def test_ingest_attlog_creates_logs(self):
        body = self._line('1001', '2024-01-15 09:00:00', '0', '1')
        created, count = self.Log.ingest_attlog(self.device, body)
        self.assertEqual(count, 1)
        self.assertEqual(len(created), 1)

        log = created
        # Timestamp stored as naive UTC (device tz is UTC).
        self.assertEqual(log.punch_datetime, datetime(2024, 1, 15, 9, 0, 0))
        self.assertEqual(log.punch_type, 'in')
        self.assertEqual(log.verify_mode, 'fingerprint')
        # Employee matched and processed by the device-status policy.
        self.assertEqual(log.employee_id, self.employee)
        self.assertTrue(log.processed)
        self.assertEqual(log.process_state, 'done')
        self.assertTrue(log.hr_attendance_id)

    def test_ingest_attlog_dedups_identical_replay(self):
        body = self._line('1001', '2024-01-15 09:00:00', '0', '1')

        created1, count1 = self.Log.ingest_attlog(self.device, body)
        self.assertEqual(count1, 1)
        total_after_first = self.Log.search_count(
            [('device_id', '=', self.device.id)])

        # Replaying the very same line must create nothing (punch_uniq).
        created2, count2 = self.Log.ingest_attlog(self.device, body)
        self.assertEqual(count2, 0)
        self.assertFalse(created2)
        total_after_replay = self.Log.search_count(
            [('device_id', '=', self.device.id)])

        # Log count is stable across the replay.
        self.assertEqual(total_after_first, total_after_replay)

    # ------------------------------------------------------------------
    # _match_employee
    # ------------------------------------------------------------------
    def test_match_employee_links_employee(self):
        log = self._make_log(datetime(2024, 1, 15, 9, 0, 0), employee=False)
        self.assertFalse(log.employee_id)
        log._match_employee()
        self.assertEqual(log.employee_id, self.employee)

    def test_match_employee_unmatched(self):
        log = self._make_log(
            datetime(2024, 1, 15, 9, 0, 0), pin='9999', employee=False)
        log._match_employee()
        self.assertFalse(log.employee_id)
        self.assertEqual(log.process_state, 'unmatched')

    # ------------------------------------------------------------------
    # Policy: device_status — creating then closing an attendance
    # ------------------------------------------------------------------
    def test_device_status_creates_then_closes_attendance(self):
        # Check-in push.
        created_in, n_in = self.Log.ingest_attlog(
            self.device, self._line('1001', '2024-01-15 09:00:00', '0', '1'))
        self.assertEqual(n_in, 1)
        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 9, 0, 0))
        self.assertFalse(atts.check_out)

        # Check-out push (status 1) some hours later.
        created_out, n_out = self.Log.ingest_attlog(
            self.device, self._line('1001', '2024-01-15 17:30:00', '1', '1'))
        self.assertEqual(n_out, 1)

        atts = self._employee_attendances()
        # Same attendance, now closed — no second record created.
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 9, 0, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 15, 17, 30, 0))
        self.assertEqual(created_out.punch_type, 'out')
        self.assertEqual(created_out.hr_attendance_id, atts)
        # Device-status mode does not rate punches: statuses stay blank.
        self.assertFalse(created_in.punch_status)
        self.assertFalse(created_out.punch_status)

    # ------------------------------------------------------------------
    # Policy: first_check
    # ------------------------------------------------------------------
    def test_first_check_policy(self):
        policy = self.Policy.sudo().create({
            'name': 'Test First Check',
            'mode': 'first_check',
            'dedup_window_seconds': 60,
            'min_gap_minutes': 0,
            'company_id': self.company.id,
        })
        logs = (
            self._make_log(datetime(2024, 1, 15, 8, 0, 0))
            | self._make_log(datetime(2024, 1, 15, 12, 0, 0))
            | self._make_log(datetime(2024, 1, 15, 17, 0, 0))
        )
        policy.apply_to_logs(logs)

        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        # First punch opens the day; the latest punch is the check-out.
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 8, 0, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 15, 17, 0, 0))
        self.assertTrue(all(logs.mapped('processed')))

    def _make_first_check_policy(self, name='Test First Check'):
        return self.Policy.sudo().create({
            'name': name,
            'mode': 'first_check',
            'dedup_window_seconds': 60,
            'min_gap_minutes': 0,
            'company_id': self.company.id,
        })

    def test_first_check_streaming_one_punch_per_batch(self):
        # Live devices push each punch in its own batch: a later punch of the
        # same day must extend the recorded check-out, not merely link to the
        # attendance and leave it open.
        policy = self._make_first_check_policy('Test First Check Streaming')
        for when in (datetime(2024, 1, 15, 8, 0, 0),
                     datetime(2024, 1, 15, 12, 0, 0),
                     datetime(2024, 1, 15, 17, 0, 0)):
            policy.apply_to_logs(self._make_log(when))

        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 8, 0, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 15, 17, 0, 0))

    def test_first_check_closes_stale_day_before_new_checkin(self):
        # A single-punch day leaves its attendance open; the next day's first
        # punch must close that stale session (at its own check-in) instead
        # of tripping the core one-open-attendance constraint.
        policy = self._make_first_check_policy('Test First Check Stale')
        policy.apply_to_logs(self._make_log(datetime(2024, 1, 15, 8, 0, 0)))
        policy.apply_to_logs(self._make_log(datetime(2024, 1, 16, 8, 30, 0)))
        policy.apply_to_logs(self._make_log(datetime(2024, 1, 16, 17, 0, 0)))

        day1 = self._employee_attendances(day=date(2024, 1, 15))
        self.assertEqual(len(day1), 1)
        # Stale session closed at its own check-in (zero duration).
        self.assertEqual(day1.check_out, day1.check_in)

        day2 = self._employee_attendances(day=date(2024, 1, 16))
        self.assertEqual(len(day2), 1)
        self.assertEqual(day2.check_in, datetime(2024, 1, 16, 8, 30, 0))
        self.assertEqual(day2.check_out, datetime(2024, 1, 16, 17, 0, 0))

    def test_process_logs_failure_leaves_no_orphan_attendance(self):
        # An existing closed attendance overlapping the punch makes the
        # engine's create fail (core overlap constraint). The failure must
        # roll back cleanly: log flagged 'error', no half-created attendance
        # row left behind.
        self.Attendance.sudo().create({
            'employee_id': self.employee.id,
            'check_in': datetime(2024, 1, 15, 9, 0, 0),
            'check_out': datetime(2024, 1, 15, 17, 0, 0),
        })
        log = self._make_log(datetime(2024, 1, 15, 11, 0, 0), ptype='in')
        log._process_logs()

        self.assertEqual(log.process_state, 'error')
        self.assertFalse(log.processed)
        self.assertTrue(log.process_note)
        self.assertEqual(len(self._employee_attendances()), 1)

    # ------------------------------------------------------------------
    # Policy: flexible
    # ------------------------------------------------------------------
    def test_flexible_policy_toggle_within_window(self):
        logs = (
            self._make_log(datetime(2024, 1, 15, 9, 0, 0), ptype='in')
            | self._make_log(datetime(2024, 1, 15, 12, 0, 0), ptype='out')
        )
        self.policy_flexible.apply_to_logs(logs)

        atts = self._employee_attendances()
        # A second punch within the shift span closes the open attendance.
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 9, 0, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 15, 12, 0, 0))

    def test_flexible_policy_beyond_window_starts_new(self):
        # Two punches 14.5h apart exceed the 12h flexible window: the first
        # session is treated as a forgotten check-out and a new one is opened.
        logs = (
            self._make_log(datetime(2024, 1, 15, 9, 0, 0), ptype='in')
            | self._make_log(datetime(2024, 1, 15, 23, 30, 0), ptype='in')
        )
        self.policy_flexible.apply_to_logs(logs)

        atts = self._employee_attendances()
        self.assertEqual(len(atts), 2)
        # The most recent attendance is the freshly opened (still-open) one.
        latest = atts.sorted(key=lambda a: a.check_in)[-1]
        self.assertEqual(latest.check_in, datetime(2024, 1, 15, 23, 30, 0))
        self.assertFalse(latest.check_out)

    # ------------------------------------------------------------------
    # Policy: fixed working time
    # ------------------------------------------------------------------
    def _make_fixed_time_policy(self, **overrides):
        vals = {
            'name': 'Test Fixed Time',
            'mode': 'fixed_time',
            'shift_start_time': 9.0,
            'shift_end_time': 18.0,
            'late_in_tolerance': 5,
            'early_out_tolerance': 5,
            'flexible_window_hours': 12.0,
            'dedup_window_seconds': 60,
            'min_gap_minutes': 0,
            'company_id': self.company.id,
        }
        vals.update(overrides)
        return self.Policy.sudo().create(vals)

    def test_fixed_time_early_punches(self):
        # 08:50 is before the 09:00 start -> early arrivals count as On
        # Time(IN); 17:50 is more than 5 min before the 18:00 end -> Early
        # leave. Punches are streamed one per batch, as a live device sends
        # them.
        policy = self._make_fixed_time_policy()
        log_in = self._make_log(datetime(2024, 1, 15, 8, 50, 0))
        policy.apply_to_logs(log_in)
        log_out = self._make_log(datetime(2024, 1, 15, 17, 50, 0))
        policy.apply_to_logs(log_out)

        att = self._employee_attendances(day=date(2024, 1, 15))
        self.assertEqual(len(att), 1)
        self.assertEqual(att.check_in, datetime(2024, 1, 15, 8, 50, 0))
        self.assertEqual(att.check_out, datetime(2024, 1, 15, 17, 50, 0))
        self.assertEqual(att.check_in_status, 'on_time')
        self.assertEqual(att.check_out_status, 'early')
        # The log mirrors the rating of the edge it produced.
        self.assertEqual(log_in.punch_status, 'in_on_time')
        self.assertEqual(log_out.punch_status, 'out_early')

    def test_fixed_time_late_punches(self):
        # 09:10 is more than 5 min after the start -> Late arrival; 18:10 is
        # after the end -> late leaves count as On Time(OUT).
        policy = self._make_fixed_time_policy()
        log_in = self._make_log(datetime(2024, 1, 15, 9, 10, 0))
        policy.apply_to_logs(log_in)
        log_out = self._make_log(datetime(2024, 1, 15, 18, 10, 0))
        policy.apply_to_logs(log_out)

        att = self._employee_attendances(day=date(2024, 1, 15))
        self.assertEqual(len(att), 1)
        self.assertEqual(att.check_in_status, 'late')
        self.assertEqual(att.check_out_status, 'on_time')
        self.assertEqual(log_in.punch_status, 'in_late')
        self.assertEqual(log_out.punch_status, 'out_on_time')

    def test_fixed_time_on_time_within_tolerance(self):
        # 09:03 and 17:57 both fall inside the 5-minute grace window.
        policy = self._make_fixed_time_policy()
        log_in = self._make_log(datetime(2024, 1, 15, 9, 3, 0))
        policy.apply_to_logs(log_in)
        log_out = self._make_log(datetime(2024, 1, 15, 17, 57, 0))
        policy.apply_to_logs(log_out)

        att = self._employee_attendances(day=date(2024, 1, 15))
        self.assertEqual(len(att), 1)
        self.assertEqual(att.check_in_status, 'on_time')
        self.assertEqual(att.check_out_status, 'on_time')
        self.assertEqual(log_in.punch_status, 'in_on_time')
        self.assertEqual(log_out.punch_status, 'out_on_time')

    def test_fixed_time_rates_in_employee_tz_not_company_tz(self):
        # The employee works in Qatar (+3) while the company timezone is
        # Asia/Calcutta (+5:30).  Rating against the company timezone would
        # drag every punch 2h30 forward: a 07:40 arrival would read as 10:10
        # ("Late arrival") and a 16:08 departure as 18:38 ("On Time(OUT)").
        # Ratings must follow the employee's own timezone.  (In Odoo 19 the
        # offending timezone came from the work schedule; Odoo 20 calendars
        # carry none.)
        self.company.tz = 'Asia/Calcutta'
        calendar = self.env['resource.calendar'].sudo().create({
            'name': 'ZKTeco Test Calendar (company)',
            'company_id': self.company.id,
        })
        employee = self.env['hr.employee'].sudo().create({
            'name': 'Qatar Tester',
            'company_id': self.company.id,
            'tz': 'Asia/Qatar',
            'resource_calendar_id': calendar.id,
            'biometric_user_id': '1002',
        })
        self.assertEqual(employee._zk_punch_tz(), 'Asia/Qatar')

        policy = self._make_fixed_time_policy(
            shift_start_time=8.0, shift_end_time=17.0,
            late_in_tolerance=0, early_out_tolerance=0)

        def _punch(when, status, ptype):
            return self.Log.sudo().create({
                'device_id': self.device.id,
                'biometric_user_id': employee.biometric_user_id,
                'punch_datetime': when,
                'status_code': status,
                'punch_type': ptype,
                'employee_id': employee.id,
            })

        # 04:40 UTC = 07:40 in Qatar, 20 min before the 08:00 start.
        log_in = _punch(datetime(2024, 1, 15, 4, 40, 0), '0', 'in')
        policy.apply_to_logs(log_in)
        # 13:08 UTC = 16:08 in Qatar, 52 min before the 17:00 end.
        log_out = _punch(datetime(2024, 1, 15, 13, 8, 0), '1', 'out')
        policy.apply_to_logs(log_out)

        att = self.Attendance.search([('employee_id', '=', employee.id)])
        self.assertEqual(len(att), 1)
        self.assertEqual(att.check_in_status, 'on_time')
        self.assertEqual(att.check_out_status, 'early')
        self.assertEqual(log_in.punch_status, 'in_on_time')
        self.assertEqual(log_out.punch_status, 'out_early')

    def test_fixed_time_orphan_out_punch_is_skipped(self):
        # A device enrolled mid-day delivers a check-out whose check-in Odoo
        # never received.  It must not open a session (which would rate a
        # *check-out* as a "Late arrival") nor leave an attendance behind.
        policy = self._make_fixed_time_policy()
        log_out = self._make_log(
            datetime(2024, 1, 15, 14, 31, 0), status='1', ptype='out')
        policy.apply_to_logs(log_out)

        self.assertFalse(self._employee_attendances())
        self.assertTrue(log_out.processed)
        self.assertEqual(log_out.process_state, 'skipped')
        self.assertFalse(log_out.hr_attendance_id)
        self.assertFalse(log_out.punch_status)

    def test_fixed_time_orphan_out_punch_does_not_block_next_day(self):
        # Because the orphan check-out left nothing open, the next morning's
        # punch opens a clean attendance instead of closing a stale session at
        # its own check-in (a zero-duration record rated "Late arrival").
        policy = self._make_fixed_time_policy()
        policy.apply_to_logs(self._make_log(
            datetime(2024, 1, 15, 14, 31, 0), status='1', ptype='out'))

        policy.apply_to_logs(self._make_log(datetime(2024, 1, 16, 8, 55, 0)))
        policy.apply_to_logs(self._make_log(
            datetime(2024, 1, 16, 18, 5, 0), status='1', ptype='out'))

        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 16, 8, 55, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 16, 18, 5, 0))
        self.assertEqual(atts.check_in_status, 'on_time')
        self.assertEqual(atts.check_out_status, 'on_time')

    def test_fixed_time_first_in_last_out_enabled(self):
        # When first_in_last_out is True:
        # First punch of the day opens the attendance (Check-In).
        # Intermediate punches (11:00, 12:00) are recorded as done logs
        # without closing or splitting the session.
        # The final punch (15:00) sets/pushes Check-Out.
        # Exactly one attendance record is produced, spanning the full first-to-last duration.
        policy = self._make_fixed_time_policy(
            shift_start_time=8.0, shift_end_time=17.0,
            late_in_tolerance=15, early_out_tolerance=0,
            first_in_last_out=True)

        # Punches on Jan 15: 08:00, 11:00, 12:00, 15:00
        # Stream punches one per batch (as live device pushes them):
        log_1 = self._make_log(datetime(2024, 1, 15, 8, 0, 0), status='0', ptype='in')
        policy.apply_to_logs(log_1)

        log_2 = self._make_log(datetime(2024, 1, 15, 11, 0, 0), status='0', ptype='in')
        policy.apply_to_logs(log_2)

        log_3 = self._make_log(datetime(2024, 1, 15, 12, 0, 0), status='0', ptype='in')
        policy.apply_to_logs(log_3)

        log_4 = self._make_log(datetime(2024, 1, 15, 15, 0, 0), status='1', ptype='out')
        policy.apply_to_logs(log_4)

        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 8, 0, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 15, 15, 0, 0))
        self.assertEqual(atts.worked_hours, 7.0)
        self.assertEqual(atts.check_in_status, 'on_time')
        self.assertEqual(atts.check_out_status, 'early')

        # Check logs linking and statuses
        self.assertEqual(log_1.hr_attendance_id, atts)
        self.assertEqual(log_2.hr_attendance_id, atts)
        self.assertEqual(log_3.hr_attendance_id, atts)
        self.assertEqual(log_4.hr_attendance_id, atts)
        self.assertEqual(log_1.punch_status, 'in_on_time')
        self.assertFalse(log_2.punch_status)
        self.assertFalse(log_3.punch_status)
        self.assertEqual(log_4.punch_status, 'out_early')

    def test_fixed_time_first_in_last_out_disabled_toggle(self):
        # When first_in_last_out is False:
        # Standard toggle behavior applies: 08:00 (IN) pairs with 11:00 (OUT),
        # 12:00 (IN) pairs with 15:00 (OUT), resulting in 2 separate attendances.
        policy = self._make_fixed_time_policy(
            shift_start_time=8.0, shift_end_time=17.0,
            late_in_tolerance=15, early_out_tolerance=0,
            first_in_last_out=False)

        log_1 = self._make_log(datetime(2024, 1, 15, 8, 0, 0), status='0', ptype='in')
        policy.apply_to_logs(log_1)

        log_2 = self._make_log(datetime(2024, 1, 15, 11, 0, 0), status='1', ptype='out')
        policy.apply_to_logs(log_2)

        log_3 = self._make_log(datetime(2024, 1, 15, 12, 0, 0), status='0', ptype='in')
        policy.apply_to_logs(log_3)

        log_4 = self._make_log(datetime(2024, 1, 15, 15, 0, 0), status='1', ptype='out')
        policy.apply_to_logs(log_4)

        atts = self._employee_attendances().sorted('check_in')
        self.assertEqual(len(atts), 2)
        # Session 1: 08:00 - 11:00 (3.0 hrs)
        self.assertEqual(atts[0].check_in, datetime(2024, 1, 15, 8, 0, 0))
        self.assertEqual(atts[0].check_out, datetime(2024, 1, 15, 11, 0, 0))
        self.assertEqual(atts[0].worked_hours, 3.0)
        self.assertEqual(atts[0].check_in_status, 'on_time')
        self.assertEqual(atts[0].check_out_status, 'early')

        # Session 2: 12:00 - 15:00 (3.0 hrs)
        self.assertEqual(atts[1].check_in, datetime(2024, 1, 15, 12, 0, 0))
        self.assertEqual(atts[1].check_out, datetime(2024, 1, 15, 15, 0, 0))
        self.assertEqual(atts[1].worked_hours, 3.0)
        self.assertEqual(atts[1].check_in_status, 'late')
        self.assertEqual(atts[1].check_out_status, 'early')

    def test_fixed_time_first_in_last_out_batch_upload(self):
        # Even when all punches arrive in a single multi-line batch (offline device sync),
        # first_in_last_out produces a single attendance record with first as IN, last as OUT.
        policy = self._make_fixed_time_policy(
            shift_start_time=8.0, shift_end_time=17.0,
            late_in_tolerance=15, early_out_tolerance=0,
            first_in_last_out=True)
        self.employee.biometric_policy_id = policy

        body = '\n'.join([
            self._line(self.employee.biometric_user_id, '2024-01-15 08:00:00', '0', '1'),
            self._line(self.employee.biometric_user_id, '2024-01-15 11:00:00', '0', '1'),
            self._line(self.employee.biometric_user_id, '2024-01-15 12:00:00', '0', '1'),
            self._line(self.employee.biometric_user_id, '2024-01-15 15:00:00', '1', '1'),
        ])
        created, count = self.Log.ingest_attlog(self.device, body)
        self.assertEqual(count, 4)

        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 8, 0, 0))
        self.assertEqual(atts.check_out, datetime(2024, 1, 15, 15, 0, 0))
        self.assertEqual(atts.worked_hours, 7.0)
        self.assertEqual(atts.check_in_status, 'on_time')
        self.assertEqual(atts.check_out_status, 'early')

    # ------------------------------------------------------------------
    # Duplicate suppression within dedup_window_seconds
    # ------------------------------------------------------------------
    def test_punch_status_after_time_rule_split(self):
        # Odoo 20 time rules may split a long attendance: the source ends at the
        # working time and an overtime attendance carries the rest.  The
        # check-out punch keeps the rating of the attendance it produced.
        policy = self._make_fixed_time_policy()
        log_in = self._make_log(datetime(2024, 1, 15, 8, 55, 0), status='0', ptype='in')
        log_out = self._make_log(datetime(2024, 1, 15, 18, 30, 0), status='1', ptype='out')
        policy.apply_to_logs(log_in | log_out)
        att = log_out.hr_attendance_id
        self.assertEqual(log_out.punch_status, 'out_on_time')
        Attendance = self.Attendance.sudo().with_context(skip_time_rules=True)
        att.with_context(skip_time_rules=True).write({'check_out': datetime(2024, 1, 15, 17, 0, 0)})
        Attendance.create({
            'employee_id': self.employee.id,
            'check_in': datetime(2024, 1, 15, 17, 0, 0),
            'check_out': datetime(2024, 1, 15, 18, 30, 0),
            'source_attendance_id': att.id,
        })
        self.assertEqual(log_in.punch_status, 'in_on_time')
        self.assertEqual(log_out.punch_status, 'out_on_time')

    def test_calendar_policy_uses_work_schedule(self):
        # Odoo 20 computes work intervals per timezone (resources_per_tz).
        # Punches without a device status are classified by the nearest
        # boundary of the employee's work schedule (default 08:00-17:00).
        policy = self.Policy.sudo().create({
            'name': 'Test Calendar',
            'mode': 'calendar',
            'dedup_window_seconds': 60,
            'min_gap_minutes': 0,
            'company_id': self.company.id,
        })
        logs = self.Log.browse()
        for when in (datetime(2024, 1, 15, 8, 2, 0), datetime(2024, 1, 15, 17, 1, 0)):
            logs |= self._make_log(when, status='', ptype='unknown')
        periods = policy._calendar_work_periods(self.employee, logs)
        self.assertTrue(periods)
        policy.apply_to_logs(logs)
        att = self._employee_attendances(date(2024, 1, 15))
        self.assertEqual(len(att), 1)
        self.assertEqual(att.check_in, datetime(2024, 1, 15, 8, 2, 0))
        self.assertEqual(att.check_out, datetime(2024, 1, 15, 17, 1, 0))
        self.assertEqual(set(logs.mapped('process_state')), {'done'})

    def test_dedup_within_window(self):
        # Two 'in' punches 30s apart; dedup window is 60s. Both survive the DB
        # unique constraint (distinct timestamps) but the engine must flag the
        # second one as a duplicate and not spawn a second attendance edge.
        body = '\n'.join([
            self._line('1001', '2024-01-15 09:00:00', '0', '1'),
            self._line('1001', '2024-01-15 09:00:30', '0', '1'),
        ])
        created, count = self.Log.ingest_attlog(self.device, body)
        self.assertEqual(count, 2)

        second = created.filtered(
            lambda r: r.punch_datetime == datetime(2024, 1, 15, 9, 0, 30))
        self.assertEqual(len(second), 1)
        self.assertEqual(second.process_state, 'duplicate')

        # Only one attendance, opened by the first punch.
        atts = self._employee_attendances()
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts.check_in, datetime(2024, 1, 15, 9, 0, 0))

    # ------------------------------------------------------------------
    # _cron_mark_offline
    # ------------------------------------------------------------------
    def test_cron_mark_offline_flips_stale_device(self):
        self.device.mark_online()
        self.assertEqual(self.device.state, 'online')

        # Make the device look stale: last contact well beyond the threshold.
        self.company.sudo().write({'zkteco_device_offline_minutes': 5})
        self.device.sudo().write({
            'last_seen': fields.Datetime.now() - timedelta(hours=1),
        })

        self.Device._cron_mark_offline()
        self.assertEqual(self.device.state, 'offline')

    def test_cron_mark_offline_keeps_fresh_device(self):
        # A device seen just now must NOT be flipped offline.
        self.device.mark_online()
        self.company.sudo().write({'zkteco_device_offline_minutes': 5})
        self.device.sudo().write({'last_seen': fields.Datetime.now()})

        self.Device._cron_mark_offline()
        self.assertEqual(self.device.state, 'online')


@tagged('post_install', '-at_install')
class TestADMSController(HttpCase):
    """HTTP-level checks for the ADMS controller."""

    def test_cdata_unregistered_sn_denied(self):
        # A GET from an unregistered serial number must be rejected.
        resp = self.url_open('/iclock/cdata?SN=doesnotexist')
        self.assertEqual(resp.status_code, 401)
        self.assertIn('ACCESS DENIED', resp.text)

    def test_attlog_push_creates_attendance(self):
        # Real device path: the push runs without a user (auth='none').  Odoo 20
        # attendances need a work entry type taken from the company, so this
        # must still create the attendance.
        device = self.env['zkteco.biometric.device'].sudo().create({
            'device_name': 'HTTP Test SpeedFace', 'serial_number': 'HTTPSN0001', 'tz': 'UTC'})
        device.action_confirm()
        employee = self.env['hr.employee'].sudo().create({
            'name': 'HTTP Tester', 'tz': 'UTC', 'biometric_user_id': '7001'})
        resp = self.url_open('/iclock/cdata?SN=HTTPSN0001&options=all')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('GET OPTION FROM: HTTPSN0001', resp.text)
        body = '7001\t2024-01-15 08:00:00\t0\t15\t0\n7001\t2024-01-15 17:00:00\t1\t15\t0'
        resp = self.url_open('/iclock/cdata?SN=HTTPSN0001&table=ATTLOG&Stamp=9999', data=body,
                             headers={'Content-Type': 'text/plain'})
        self.assertEqual(resp.text, 'OK: 2')
        attendance = self.env['hr.attendance'].search([('employee_id', '=', employee.id)])
        self.assertEqual(len(attendance), 1)
        self.assertEqual(attendance.check_out, datetime(2024, 1, 15, 17, 0, 0))
        self.assertTrue(attendance.work_entry_type_id)
        self.assertEqual(device.state, 'online')
