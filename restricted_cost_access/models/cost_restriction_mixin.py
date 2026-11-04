# -*- coding: utf-8 -*-
"""Shared cost / margin redaction logic.

Every model that carries cost or margin figures inherits this mixin and only
declares *which* of its fields are sensitive. Users outside the
``group_manager_cost`` group then get those values redacted on every channel
the web client and the external API use:

* ``fields_get()``   -> the field is flagged non-exportable, non-searchable,
                        non-sortable, non-groupable and loses its aggregator,
                        so it disappears from Export, custom filters, Group By
                        and pivot/graph measures.  (Odoo 20: the field is *not*
                        popped any more -- a field referenced by a view arch but
                        missing from ``fields_get`` crashes the Owl client.)
* ``read()``         -> the value is replaced by ``0.0``.  ``web_read``,
                        ``web_search_read``, ``search_read`` and ``web_save``
                        all go through ``read()``.
* ``formatted_read_group()`` / ``formatted_read_grouping_sets()``
                     -> every aggregate (``field:sum`` ...) is forced to 0.0.
                        These replace ``read_group`` (now ``@typing.final``)
                        and ``web_read_group`` (which wraps them) in Odoo 20.
"""

from odoo import api, models

COST_GROUP = "restricted_cost_access.group_manager_cost"


class RestrictedCostMixin(models.AbstractModel):
    _name = "restricted.cost.mixin"
    _description = "Cost and Margin Visibility Restriction"

    #: values replaced by 0.0 in read() and grouped aggregates
    _restricted_cost_fields = ()
    #: extra fields only hidden from fields_get() (export / filters / measures)
    _restricted_cost_schema_fields = ()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _is_cost_restricted(self):
        """True when the current user must NOT see cost / margin figures."""
        return not self.env.user.has_group(COST_GROUP)

    @api.model
    def _redact_cost_group(self, group):
        """Zero every restricted key of one formatted group dict (recursively)."""
        restricted = set(self._restricted_cost_fields)
        for key in list(group):
            if key.split(":")[0] in restricted:
                group[key] = 0.0
        for rec in group.get("__records") or []:
            for fname in restricted.intersection(rec):
                rec[fname] = 0.0
        sub = group.get("__groups")
        if isinstance(sub, dict):
            for sub_group in sub.get("groups", []):
                self._redact_cost_group(sub_group)
        return group

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------
    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        if self._is_cost_restricted():
            for fname in set(self._restricted_cost_fields) | set(self._restricted_cost_schema_fields):
                desc = res.get(fname)
                if desc is None:
                    continue
                desc.update({
                    "exportable": False,
                    "searchable": False,
                    "sortable": False,
                    "groupable": False,
                })
                desc.pop("aggregator", None)
        return res

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        if self._restricted_cost_fields and self._is_cost_restricted():
            restricted = set(self._restricted_cost_fields)
            for values in res:
                for fname in restricted.intersection(values):
                    values[fname] = 0.0
        return res

    @api.model
    @api.readonly
    def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        res = super().formatted_read_group(
            domain, groupby=groupby, aggregates=aggregates, having=having,
            offset=offset, limit=limit, order=order,
        )
        if self._restricted_cost_fields and self._is_cost_restricted():
            for group in res:
                self._redact_cost_group(group)
        return res

    @api.model
    @api.readonly
    def formatted_read_grouping_sets(self, domain, grouping_sets, aggregates=(), *, order=None):
        res = super().formatted_read_grouping_sets(domain, grouping_sets, aggregates=aggregates, order=order)
        if self._restricted_cost_fields and self._is_cost_restricted():
            for groups in res:
                for group in groups:
                    self._redact_cost_group(group)
        return res
