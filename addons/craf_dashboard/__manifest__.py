{
    "name": "Craf Panel",
    "version": "19.0.1.0.0",
    "summary": "Kunlik panel: ishlab chiqarish, qoldiq, chiqish koeffitsienti",
    "description": """
Rahbar uchun bitta sahifa:
- davr: bugun / 7 kun / 30 kun
- tayyor profil (kg, dona), quyma, press chiqishi, bo'yash, pachkalar, sotuv
- угар %, press chiqishi %, bo'yash braki % — me'yor bilan
- kunlar bo'yicha ishlab chiqarish grafigi (jadval ko'rinishi bilan)
- zavod nuqtalaridagi qoldiq, kam qolgan tayyor mahsulotlar, oxirgi hujjatlar
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_paint", "sale_management"],
    "data": [
        "views/craf_dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_dashboard/static/src/panel/panel.scss",
            "craf_dashboard/static/src/panel/panel.js",
            "craf_dashboard/static/src/panel/panel.xml",
        ],
    },
    "installable": True,
    "application": False,
}
