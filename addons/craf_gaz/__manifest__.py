{
    "name": "Craf: Gaz ballonlari",
    "version": "19.0.1.1.0",
    "summary": "Azot, Ammiak, Argon va boshqa gazlar: ballonlar, to'ldirish, sarf",
    "category": "Inventory",
    "depends": ["stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/gaz_views.xml",
        "data/gaz_data.xml",
    ],
    "assets": {"web.assets_backend": ["craf_gaz/static/src/**/*"]},
    "license": "LGPL-3",
    "installable": True,
}
