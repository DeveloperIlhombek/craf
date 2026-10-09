{
    "name": "Craf Ishlab chiqarish (asos)",
    "version": "19.0.1.0.0",
    "summary": "Литейка, press va bo'yash hujjatlari uchun umumiy asos: smena, uskuna, operator, MRP buyurtmasi",
    "description": """
Umumiy asos (craf_foundry, craf_extrusion, craf_paint shu modulga tayanadi):
- smena, uskuna (Texnik xizmat ilovasidagi uskunalar), mas'ul xodim (Xodimlar ilovasi)
- hujjat tasdiqlanganda Odoo ishlab chiqarish buyurtmasi (MRP) yaratilib, darhol bajariladi
- sarf va chiqish zavod joylashuvlarida ko'rinadi (Zavod xaritasi yangilanadi)
- qoldiq yetarli bo'lmasa, hujjat tasdiqlanmaydi
- tayyor mahsulotdan pachka yorliqlari chiqarish
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_label", "craf_zavod", "mrp", "maintenance", "hr"],
    "data": [
        "data/craf_production_data.xml",
        "views/maintenance_equipment_views.xml",
        "views/craf_production_menus.xml",
    ],
    "installable": True,
    "application": False,
}
