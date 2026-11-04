.. image:: https://img.shields.io/badge/license-AGPL--3-blue.svg
    :target: https://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3

POS multi uom price
===================
With this module you can sell your products with different units of measure in POS.

Odoo 20 version
---------------
* Product form, Point of Sale tab, "UOM Price": the own price of ONE unit of
  each other unit of measure (e.g. Box of 5 = 300.00, Box of 10 = 500.00 while
  one Unit = 100.00). The product's own unit keeps its sales price / pricelist.
  Prices are never derived from the unit price (no proportional price).
* In the POS, select the order line and click "UoM": the list shows the
  product's own unit and the units that have a price in the table; the line
  takes the price of the chosen unit.
* Returns: on the Orders screen, select a line sold per pack and press
  "Return Units" to return single pieces (e.g. 1 piece of a Pack of 6 sold at
  300.00 is refunded 50.00, the price paid per piece; stock +1 piece). The
  numpad there refunds whole packs. When some pieces were already returned,
  the rest of the pack is refunded per piece. Point of Sale settings >
  "Block Fractional Returns" (per register) allows whole packs only.
* The line keeps its unit on the order and the invoice; stock is moved in the
  product's unit (1 Box of 10 = 10 Units, lots included) and the cost / margin
  are computed for the unit sold.

Autor
-----
ehuerta _at_ ixer.mx

License
-------
GNU AFFERO GENERAL PUBLIC LICENSE v3.0 (AGPL-3)
(https://www.gnu.org/licenses/agpl-3.0-standalone.html)

Support This Project
--------------------
This module is free to use. If you’d like, feel free to buy me a coffee! 😉

.. image:: https://ko-fi.com/img/githubbutton_sm.svg
    :target: https://ko-fi.com/ehuerta
    :alt: Support me on Ko-fi
