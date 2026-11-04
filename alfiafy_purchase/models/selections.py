# -*- coding: utf-8 -*-
"""Selections shared by vendors, purchase orders, receipts and lots."""

SOURCING_TYPES = [
    ('partner', 'Official Partner'),
    ('outside', 'Outside Supplier'),
]

PURCHASE_TYPES = [
    ('local', 'Local Purchase'),
    ('import', 'Import Shipment'),
]

SHIPMENT_STATUSES = [
    ('not_shipped', 'Not Yet Shipped'),
    ('in_transit', 'In Transit'),
    ('at_port', 'Arrived at Port'),
    ('customs', 'Customs Clearance'),
    ('delivered', 'Delivered to Warehouse'),
]

PRICE_TRENDS = [
    ('up', '▲ Increased'),
    ('down', '▼ Decreased'),
    ('same', '─ Same'),
]
