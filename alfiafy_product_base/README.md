# Alfiafyvet - Product Base (`alfiafy_product_base`, DES00134)

Foundation module of the Alfiafyvet Odoo 20 implementation. All other
`alfiafy_*` modules depend on it.

| Field | Label | Type |
|---|---|---|
| `name_ar` | Arabic Name | Char (searchable) |
| `description_ar` | Arabic Description | Text |
| `active_ingredient` | Active Ingredient / Molecule | Char (searchable) |
| `target_species_ids` | Target Species | Many2many `alfiafy.target.species` |
| `vet_item_type` | Item Type | Selection |
| `dosage_form` | Dosage Form | Selection |
| `strength` | Strength / Concentration | Char |
| `storage_condition` | Storage Condition | Selection |
| `prescription_required` | Prescription Required | Boolean |
| `manufacturer_id` | Manufacturer | Many2one `res.partner` |
| `supplier_id` | Supplier | Many2one `res.partner` |

* Stock on hand (`stock.quant`) carries stored `product_manufacturer_id` /
  `product_supplier_id`, so Inventory > Reporting > Stock can be filtered and
  grouped by them.
* Cost security comes from `restricted_cost_access` (Odoo 20 port): only
  members of **Show Cost and Margin** see cost / margin values.
* Target species are configured in Inventory > Configuration > Products >
  Target Species.

Tests: `--test-tags /alfiafy_product_base`
