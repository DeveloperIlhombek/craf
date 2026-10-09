{
    "name": "Craf Zavod xaritasi",
    "version": "19.0.1.0.0",
    "summary": "Zavodning 2D sxematik xaritasi: har bir nuqtadagi jonli qoldiq",
    "description": """
Craf -> Zavod xaritasi sahifasi:
- Ombor joylashuvlari zavod sxemasida bloklar ko'rinishida
- Har bir blokda jonli qoldiq: kg, шт, pachka, mahsulotlar soni
- Ishlab chiqarish oqimi strelkalar bilan
- Blokni bosganda o'sha joydagi mahsulotlar ro'yxati
Bloklarning joyi va o'lchami joylashuv kartochkasida (Zavod xaritasi bo'limi) o'zgartiriladi.
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_profile", "stock"],
    "data": [
        "views/stock_location_views.xml",
        "views/craf_zavod_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_zavod/static/src/xarita/xarita.scss",
            "craf_zavod/static/src/xarita/xarita.js",
            "craf_zavod/static/src/xarita/xarita.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
