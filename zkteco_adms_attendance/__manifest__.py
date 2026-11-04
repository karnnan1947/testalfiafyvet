# -*- coding: utf-8 -*-
{
    "name": "ZKTeco ADMS Attendance (Push)",
    "version": "20.0.1.3.1",
    "category": "Human Resources/Attendances",
    "summary": "Integrate ZKTeco biometric devices (SpeedFace-V5L) with HR Attendance "
               "using the ADMS / iClock cloud-push protocol.",
    "description": """
ZKTeco ADMS Attendance
======================

Push-based integration between ZKTeco biometric terminals (e.g. SpeedFace-V5L)
and Odoo *hr_attendance*.

The device acts as an HTTP client and pushes attendance transactions to Odoo
over the ADMS / iClock protocol (``/iclock/cdata`` ...). Odoo never polls the
device. Raw punches are stored in an immutable audit log and turned into
``hr.attendance`` records by a configurable **Attendance Policy Engine**.

Features
--------
* ADMS / iClock HTTP controller (handshake, ATTLOG/OPERLOG push, command queue).
* Biometric device registration workflow (Draft -> Confirmed -> Online/Offline).
* Immutable raw punch log with de-duplication of offline replays.
* Attendance Policy Engine (Device Status / First Check / Flexible / Calendar /
  Fixed Working Time with early / on-time / late punch rating).
* Safe reprocessing wizard (re-map logs without data loss).
* Live device dashboard + stale-device offline cron with admin activities.
* Multi-company record rules and dedicated access groups.
""",
    "author": "AGM Global",
    "website": "https://www.agmglobal.co",
    "license": "LGPL-3",
    "depends": [
        "hr_attendance",
        "resource",
        "mail",
    ],
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
        "data/attendance_policy_data.xml",
        "data/cron.xml",
        "views/biometric_device_views.xml",
        "views/biometric_attendance_log_views.xml",
        "views/zkteco_device_command_views.xml",
        "views/hr_attendance_policy_views.xml",
        "views/hr_attendance_views.xml",
        "views/hr_employee_views.xml",
        "views/res_config_settings_views.xml",
        "views/attendance_reprocess_wizard_views.xml",
        "views/zkteco_menus.xml",
    ],
    "assets": {},
    "installable": True,
    "application": True,
    "auto_install": False,
}
