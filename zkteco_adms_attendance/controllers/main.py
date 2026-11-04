# -*- coding: utf-8 -*-
import logging
import urllib.parse

from odoo import SUPERUSER_ID, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ZKTecoADMSController(http.Controller):
    """HTTP endpoints implementing the ZKTeco ADMS / iClock push protocol.

    The biometric terminal acts as the HTTP *client*: it periodically contacts
    these routes to fetch its configuration handshake, upload attendance
    transactions (ATTLOG) / operation logs (OPERLOG) and pull queued commands.
    Odoo never initiates a connection to the device.

    All routes run unauthenticated (``auth='none'``) because the device does
    not carry an Odoo session; every database access therefore goes through
    ``sudo()`` and the device is authenticated by its serial number (and its
    optional shared ``auth_token``).

    Odoo 20: ``auth='none'`` routes are read-only by default, so the routes that
    store data declare ``readonly=False``; and the request environment is set
    to the superuser, as the attendance defaults need a company.
    Every response is emitted as ``text/plain`` since that is all the firmware
    understands.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _text(self, body, status=200):
        """Wrap ``body`` in a plain-text HTTP response."""
        if body is None:
            body = ''
        return request.make_response(
            body,
            headers=[('Content-Type', 'text/plain')],
            status=status,
        )

    def _get_device(self, sn):
        """Return the registered device for serial ``sn`` or ``None``.

        A device that is absent from the database or still in the ``draft``
        state is treated as unknown, so pushes from unregistered terminals are
        rejected.
        """
        if not sn:
            return None
        # no user on auth='none' routes: run as superuser so env.company is set
        request.update_env(user=SUPERUSER_ID)
        device = request.env['zkteco.biometric.device'].sudo()._get_registered_device(sn)
        if not device or device.state == 'draft':
            return None
        return device

    def _check_auth(self, device, **kw):
        """Validate the device shared secret.

        When the device has an ``auth_token`` configured it must be presented on
        every request either through the ``Authorization`` header (optionally
        prefixed with ``Bearer ``), the ``X-ZKTeco-Token`` header, or a
        ``token`` query/form parameter. Devices without a token configured are
        accepted (open enrollment). Every rejection is logged with the serial
        number and the remote address.
        """
        if not device:
            return False
        token = device.auth_token
        if not token:
            return True

        httprequest = request.httprequest
        provided = (
            httprequest.headers.get('Authorization')
            or httprequest.headers.get('X-ZKTeco-Token')
            or kw.get('token')
        )
        if provided:
            provided = provided.strip()
            if provided.lower().startswith('bearer '):
                provided = provided[7:].strip()

        if provided and provided == token:
            return True

        _logger.warning(
            "ZKTeco ADMS: rejected request for SN=%s from %s "
            "(missing or invalid auth token).",
            device.serial_number, httprequest.remote_addr)
        return False

    def _deny(self, sn):
        """Log and return the ADMS ``ACCESS DENIED`` (HTTP 401) response."""
        _logger.warning(
            "ZKTeco ADMS: access denied for unregistered/draft SN=%s from %s.",
            sn, request.httprequest.remote_addr)
        return self._text('ACCESS DENIED', status=401)

    def _read_body(self):
        """Return the raw request body as text (never ``None``)."""
        return request.httprequest.get_data(as_text=True) or ''

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route(
        '/iclock/cdata', type='http', auth='none',
        methods=['GET', 'POST'], csrf=False, save_session=False, readonly=False)
    def cdata(self, **kw):
        """Handshake (GET) and data upload (POST) endpoint.

        * ``GET``  -> return the ADMS option handshake body.
        * ``POST`` -> ingest the uploaded ``table`` (ATTLOG / OPERLOG) and
          acknowledge with ``OK: <count>``.
        """
        sn = kw.get('SN')
        device = self._get_device(sn)
        if not device:
            return self._deny(sn)
        if not self._check_auth(device, **kw):
            return self._text('ACCESS DENIED', status=401)

        device.mark_online()

        if request.httprequest.method == 'GET':
            return self._text(device._build_handshake_options())

        # POST: upload of attendance transactions or operation logs.
        table = (kw.get('table') or 'ATTLOG').upper()
        body = self._read_body()
        Log = request.env['zkteco.biometric.attendance.log'].sudo()

        if table == 'ATTLOG':
            _created, count = Log.ingest_attlog(device, body)
            return self._text('OK: %d' % count)
        if table == 'OPERLOG':
            count = Log.ingest_operlog(device, body)
            return self._text('OK: %d' % count)

        # Device information push (firmware, capacity...) sent in response to a
        # "Query Info"/INFO command. Capture it so it shows on the device form.
        if table == 'OPTIONS' or 'FWVersion' in body or '~SerialNumber' in body:
            device._apply_device_info(body)
            return self._text('OK')

        # Any other table (e.g. BIODATA) is simply acknowledged.
        return self._text('OK')

    @http.route(
        '/iclock/getrequest', type='http', auth='none',
        methods=['GET'], csrf=False, save_session=False, readonly=False)
    def getrequest(self, **kw):
        """Return the queued command payload for the polling device."""
        sn = kw.get('SN')
        device = self._get_device(sn)
        if not device:
            return self._deny(sn)
        if not self._check_auth(device, **kw):
            return self._text('ACCESS DENIED', status=401)

        device.mark_online()
        return self._text(device.get_pending_commands_payload())

    @http.route(
        '/iclock/devicecmd', type='http', auth='none',
        methods=['POST'], csrf=False, save_session=False, readonly=False)
    def devicecmd(self, **kw):
        """Acknowledge command execution reported back by the device.

        The device posts ``ID=<cmd_id>&Return=<code>&CMD=<name>``; the matching
        queued command is flagged done (or error, depending on the return code).
        """
        sn = kw.get('SN')
        device = self._get_device(sn)
        if not device:
            return self._deny(sn)
        if not self._check_auth(device, **kw):
            return self._text('ACCESS DENIED', status=401)

        device.mark_online()

        body = self._read_body()
        params = urllib.parse.parse_qs(body, keep_blank_values=True)

        def _pick(name):
            if params.get(name):
                return params[name][0]
            return kw.get(name)

        cmd_id = _pick('ID')
        return_code = _pick('Return')
        cmd_name = _pick('CMD')

        command = None
        if cmd_id:
            try:
                cid = int(str(cmd_id).strip())
            except (TypeError, ValueError):
                cid = None
            if cid:
                command = request.env['zkteco.device.command'].sudo().search(
                    [('id', '=', cid), ('device_id', '=', device.id)], limit=1)

        if command:
            command.mark_done(return_code=return_code, response=cmd_name)
        else:
            _logger.info(
                "ZKTeco ADMS: devicecmd ack for unknown command ID=%r on SN=%s.",
                cmd_id, device.serial_number)

        # Some firmwares return the device information inline with the ack.
        if 'FWVersion' in body or 'UserCount' in body:
            device._apply_device_info(body)

        return self._text('OK')

    @http.route(
        '/iclock/ping', type='http', auth='none',
        methods=['GET'], csrf=False, save_session=False)
    def ping(self, **kw):
        """Lightweight health-check endpoint."""
        return self._text('OK')
