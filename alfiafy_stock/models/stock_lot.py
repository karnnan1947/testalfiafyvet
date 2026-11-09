# -*- coding: utf-8 -*-
import logging
from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import Command, api, fields, models

_logger = logging.getLogger(__name__)

# expiry color-coding used in the branch digest
EXPIRY_COLORS = {
    'expired': ('#f8d7da', '#842029'),       # red: expired
    'near_expiry': ('#fff3cd', '#664d03'),   # orange: inside the alert window
}


class StockLot(models.Model):
    _inherit = 'stock.lot'

    def _get_expiry_alert_state(self, now=None):
        """'expired', 'near_expiry' (inside the product's alert window, 180 days
        by default) or False."""
        self.ensure_one()
        if not self.expiration_date:
            return False
        now = now or fields.Datetime.now()
        if self.expiration_date <= now:
            return 'expired'
        window = self.product_id.expiry_alert_days or 180
        if self.expiration_date <= now + timedelta(days=window):
            return 'near_expiry'
        return False

    @api.model
    def _get_branch_alert_recipients(self, warehouse):
        """Users of the branch (Default Warehouse = branch) and management
        (Stock Managers). Nobody else receives the branch's alert."""
        Users = self.env['res.users'].sudo()
        branch_users = Users.with_company(warehouse.company_id).search([
            ('property_warehouse_id', '=', warehouse.id), ('share', '=', False)])
        managers = self.env.ref('stock.group_stock_manager').sudo().all_user_ids.filtered(
            lambda u: not u.share and warehouse.company_id in u.company_ids)
        return (branch_users | managers).filtered(
            lambda u: u.active and u.id != self.env.ref('base.user_root').id)

    @api.model
    def _cron_branch_near_expiry_alerts(self):
        """Daily: one digest per warehouse of its near-expiry and expired lots,
        sent only to that branch's users and to management."""
        now = fields.Datetime.now()
        quants = self.env['stock.quant'].sudo().search([
            ('lot_id.expiration_date', '!=', False),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ])
        lines_by_wh = defaultdict(list)
        for quant in quants:
            state = quant.lot_id._get_expiry_alert_state(now)
            if state and quant.location_id.warehouse_id:
                lines_by_wh[quant.location_id.warehouse_id].append((quant, state))
        mails = self.env['mail.mail']
        for warehouse, lines in lines_by_wh.items():
            recipients = self._get_branch_alert_recipients(warehouse)
            if not recipients:
                _logger.warning("Near-expiry alert: no recipient for %s", warehouse.name)
                continue
            lines.sort(key=lambda line: (line[1] != 'expired', line[0].lot_id.expiration_date))
            expired = sum(1 for _quant, state in lines if state == 'expired')
            mails |= self.env['mail.mail'].sudo().create({
                'subject': self.env._("[Stock Alert] %(wh)s: %(near)s near-expiry and %(expired)s expired lot(s)",
                                      wh=warehouse.name, near=len(lines) - expired, expired=expired),
                'body_html': self._render_expiry_digest(warehouse, lines, now),
                'email_from': warehouse.company_id.email_formatted or self.env.user.email_formatted,
                'recipient_ids': [Command.set(recipients.partner_id.ids)],
                'auto_delete': False,
            })
        return mails

    @api.model
    def _render_expiry_digest(self, warehouse, lines, now):
        rows = []
        for quant, state in lines:
            lot = quant.lot_id
            bg, fg = EXPIRY_COLORS[state]
            days = (lot.expiration_date.date() - now.date()).days
            label = self.env._("Expired") if state == 'expired' else self.env._("Near expiry")
            rows.append(Markup(
                '<tr style="background-color:%s;color:%s;">'
                '<td style="padding:4px 8px;">%s</td><td style="padding:4px 8px;">%s</td>'
                '<td style="padding:4px 8px;">%s</td><td style="padding:4px 8px;text-align:right;">%s %s</td>'
                '<td style="padding:4px 8px;">%s</td><td style="padding:4px 8px;text-align:right;">%s</td>'
                '<td style="padding:4px 8px;font-weight:bold;">%s</td></tr>') % (
                bg, fg, quant.product_id.display_name, lot.name, quant.location_id.display_name,
                quant.quantity, quant.product_id.uom_id.name, lot.expiration_date.date().strftime('%d/%m/%Y'), days, label))
        header = ''.join('<th style="padding:4px 8px;text-align:left;">%s</th>' % escape(h) for h in (
            self.env._("Product"), self.env._("Lot"), self.env._("Location"), self.env._("Quantity"),
            self.env._("Expiry Date"), self.env._("Days Left"), self.env._("Status")))
        return Markup(
            '<div style="font-size:13px;"><p>%s</p>'
            '<table style="border-collapse:collapse;font-size:13px;" border="1" bordercolor="#dee2e6">'
            '<thead style="background-color:#e9ecef;"><tr>%s</tr></thead><tbody>%s</tbody></table>'
            '<p style="color:#888;">%s</p></div>') % (
            self.env._("Near-expiry and expired stock at %(wh)s on %(date)s:",
                       wh=warehouse.name, date=now.strftime('%d/%m/%Y')),
            Markup(header), Markup('').join(rows),
            self.env._("Sent to the users of this branch and to management only. Expired lots are listed first "
                       "(red); near-expiry lots are inside the product's alert window (orange)."))
