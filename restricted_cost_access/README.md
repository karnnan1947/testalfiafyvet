# Restricted Cost Access (restricted_cost_access) - Odoo 20.0

## Overview
The **Restricted Cost Access** module is a custom Odoo add-on designed to strictly enforce data privacy regarding product costs, margins, and inventory valuation. By default, Odoo makes cost and margin information widely accessible across the system. This module introduces a new security group, **"Show Cost and Margin"** (`restricted_cost_access.group_manager_cost`), and completely restricts access to financial cost data for any user who does not belong to this group.

This restriction applies globally across:
* **Sales** (Orders, Lines, Reports)
* **Point of Sale** (Orders, Lines, Reports, Session Loading)
* **Inventory** (Quants, Moves, Lots/Serial Numbers)
* **Products** (Templates, Variants)

## How Fields Are Hidden (Technical Implementation)
To guarantee that data cannot be leaked through the UI, exported, or extracted via API (XML-RPC), the module implements security at four distinct layers:

### 1. User Interface (XML Views)
Using standard Odoo view inheritance, the module locates specific `div`s, `field`s, and `column`s in the XML layout and appends the `groups="restricted_cost_access.group_manager_cost"` attribute. 
* **Result:** The web client physically removes these elements from the HTML DOM, preventing the user from seeing them on the screen.

### 2. Standard Data Retrieval (`read()`)
The module overrides the standard ORM `read()` method on relevant models. 
* **Result:** If an unauthorized user attempts to read a cost field, the backend intercepts the request and overwrites the returned dictionary value to `0.0`. This protects against custom views or API calls trying to fetch the raw database value.

### 3. Aggregations & Pivot Tables (`formatted_read_group()`, `formatted_read_grouping_sets()`)
To prevent data leakage through reporting tools (Pivot, Graph, grouped lists), the grouping methods used by the Odoo 20 web client are overridden.
* **Result:** every aggregate of a restricted field (`margin:sum`, ...) is forced to `0.0`. `web_read_group()` wraps `formatted_read_group()`, so grouped list/kanban views are covered too.
* *Odoo 20:* `read_group()` is now `@typing.final` (and returns tuples), so it is no longer overridden.

### 4. Export Dialog, Filters & Measures (`fields_get()`)
* **Result:** for unauthorised users each restricted field is flagged `exportable=False`, `searchable=False`, `sortable=False`, `groupable=False` and loses its `aggregator`, so it disappears from Export, custom filters, Group By and pivot/graph measures.
* *Odoo 20:* fields are no longer popped from `fields_get()`: a field referenced by a view arch but missing from the field descriptions crashes the Owl client.

### Implementation
All of the above lives in one abstract mixin, `restricted.cost.mixin` (`models/cost_restriction_mixin.py`). Each model inherits it and only declares `_restricted_cost_fields` (values zeroed) and `_restricted_cost_schema_fields` (only hidden from `fields_get`).

---

## Restricted Fields Breakdown
The following fields are restricted and forced to `0.0` or hidden for unauthorized users:

### Sales (`sale.order`, `sale.order.line`, `sale.report`)
* `margin`, `margin_percent`
* `purchase_price` (Cost) - also on the Odoo 20 "Projected Margins" report

### Point of Sale (`pos.order`, `pos.order.line`, `report.pos.order`)
* `margin`, `margin_percent`
* `total_cost`

### Products (`product.template`, `product.product`)
* `standard_price` (Cost)
* `total_cost`, `normal_cost`, `avg_cost`
* `expected_margin`, `total_margin`, `expected_margin_rate`, `total_margin_rate`
* `purchase_gap`, `sales_gap`, `turnover`, `sale_expected`
* `sale_avg_price`, `purchase_avg_price`
* `sale_num_invoiced`, `purchase_num_invoiced`

### Inventory (`stock.quant`, `stock.move`, `stock.lot`)
* **Inventory Valuation (Quant):** `value`
* **Stock Moves:** `value`, `remaining_value`, `standard_price`, `price_unit`
* **Lots/Serial Numbers:** `standard_price`, `avg_cost`, `total_value`

---

## Testing and Verification Guide

To verify that the module is working correctly, you should set up a sample user and walk through the system.

### Step 1: User Setup
1. Go to **Settings -> Users & Companies -> Users**.
2. Create a new user (e.g., "Trainer User").
3. Ensure this user has access to Sales, POS, and Inventory.
4. **Crucial:** Ensure the **"Show Cost and Margin"** checkbox is **UNCHECKED** for this user.
5. Log in as the "Trainer User" in an incognito window.

### Step 2: Testing Sales
1. **Sample Data:** Create a Sales Order with a product that has a cost of $50 and a sale price of $100.
2. **Form View Check:** Look at the bottom of the Sales Order; the total Margin should be hidden. Open the order line; the Cost field should be hidden.
3. **List View Check:** Go to the Orders list view. The Margin column should not be visible.
4. **Export Check:** Select a Sales Order, click **Action -> Export**. Search for `Margin` or `Cost`. They should not be available in the list.

### Step 3: Testing Point of Sale
1. **Sample Data:** Complete a POS session and create a few orders.
2. **Form/List View Check:** Go to POS -> Orders -> Orders. The Margin and Total Cost columns should be hidden from the table and the order details.
3. **Reporting Check:** Go to POS -> Reporting -> Orders. Open the Pivot view. Open the "Measures" dropdown. `Margin` should not be an option.

### Step 4: Testing Inventory and Products
1. **Sample Data:** Receive 10 units of "Office Chair" at $50 each to generate stock valuation.
2. **Product View Check:** Go to Products. Open "Office Chair". The "Cost" field should display as $0.00.
3. **Inventory Valuation Check:** Go to Inventory -> Reporting -> Locations. Ensure no "Value" columns exist. Select records and click **Action -> Export**. Verify `Value` is missing from the available fields.
4. **Stock Moves Check:** Go to Inventory -> Reporting -> Moves History. Verify `Value`, `Unit Price`, and `Remaining Value` are hidden from the screen and the Export dialog.
5. **Lots Check:** Go to Inventory -> Products -> Lots/Serial Numbers. Verify `Average Cost` and `Total Value` are invisible.

### Conclusion
If the unauthorized user is completely unable to view, report on, or export these specific financial fields across all mentioned modules, the testing is successful and the system is secure.
