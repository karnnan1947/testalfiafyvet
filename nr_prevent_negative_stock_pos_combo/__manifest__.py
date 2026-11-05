{
    "name": "Prevent Negative Stock for Combo Products (POS)",
    "version": "20.0.1.0.0",
    "license": "LGPL-3",
    "author": "AGM Info Solutions",
    "category": "Point of Sale",
    "summary": "Block the sale of a POS Combo Product when any of its component products is out of stock",
    "description": """
            Restrict Combo Product Sales in POS Based on Component Stock
    """,
    "depends": ["nr_prevent_negative_stock_pos"],
    "assets": {
        "point_of_sale._assets_pos": [
            "nr_prevent_negative_stock_pos_combo/static/src/js/pos_combo_negative_stock.js",
        ]
    },
    "installable": True,
    "application":True,
    "auto_install": False,
}
