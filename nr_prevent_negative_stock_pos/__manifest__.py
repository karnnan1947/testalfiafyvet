{
    "name": "Prevent Negative Stock (POS) Odoo Online, Odoo.sh, On Premise",
    "version": "20.0.1.0.0",
    "license": "OPL-1",
    "author": "Nirav Rathod",
    "website": "https://github.com/niravrathod",
    "category": "Point of Sale",
    "summary": "Prevent adding products with negative stock in POS For Odoo Online, Odoo.sh, On Premise",
    "depends": ["point_of_sale", "web", "stock", "pos_stock"],
    "assets": {
        "point_of_sale._assets_pos": [
            "nr_prevent_negative_stock_pos/static/src/js/pos_negative_stock.js",
        ]
    },
    "images": ["static/description/image.gif"],
    "live_test_url": "https://demo41.odoo.com/web/login?login=guest&password=guest",
    "installable": True,
    "auto_install": False,
    "currency": "USD",
    "price": 15
}
