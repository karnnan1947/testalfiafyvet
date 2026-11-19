# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    visible_stock_warehouse_ids = fields.Many2many(
        'stock.warehouse',
        'alfiafy_user_visible_stock_wh_rel',
        'user_id',
        'warehouse_id',
        string="Additional Visible Stock Warehouses",
        help="Other branches or the main warehouse whose on-hand stock this user "
             "may see in addition to their Default Warehouse. Ignored when "
             "'View All Branches Stock' or Inventory Administrator is enabled.",
    )
    can_view_all_branches_stock = fields.Boolean(
        string="Can View All Branches Stock",
        compute='_compute_can_view_all_branches_stock',
    )

    def _compute_can_view_all_branches_stock(self):
        all_branches_group = self.env.ref(
            'alfiafy_stock.group_stock_all_branches', raise_if_not_found=False
        )
        for user in self:
            user.can_view_all_branches_stock = bool(
                user._is_superuser()
                or (all_branches_group and all_branches_group in user.sudo().all_group_ids)
            )

    def _get_visible_stock_warehouse_ids(self):
        """Return the warehouse IDs whose stock this user may see, or None if
        the user can view all branches and the main warehouse."""
        self.ensure_one()
        if self.env.su or self.can_view_all_branches_stock:
            return None
        warehouses = self.sudo().property_warehouse_id | self.sudo().visible_stock_warehouse_ids
        return warehouses.ids

    def write(self, vals):
        res = super().write(vals)
        if {'property_warehouse_id', 'visible_stock_warehouse_ids', 'group_ids'} & set(vals):
            self.env['ir.access'].sudo()._clear_caches()
        return res
