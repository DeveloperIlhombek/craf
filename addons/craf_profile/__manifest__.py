{
    "name": "Craf Profil",
    "version": "19.0.1.3.2",
    "summary": "Alyuminiy profil kesimlari, ranglar va pachka / dona / metr / kg kalkulyatori",
    "description": """
Craf zavodi uchun asosiy modul:
- Profil kesimlari (kg/m, matritsa, kesim chizmasi)
- Ranglar (bo'yoq bilan bog'langan)
- Mahsulotda uzunlik, dona/pachka, 1 dona va 1 pachka og'irligi
- Qoldiqni pachka + dona va kg da ko'rsatish
- Pachka / dona / metr / kg kalkulyatori
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["stock", "mrp", "sale_management", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "views/craf_profile_section_views.xml",
        "views/craf_color_views.xml",
        "views/product_template_views.xml",
        "wizard/craf_calculator_views.xml",
        "views/craf_menus.xml",
    ],
    "installable": True,
    "application": True,
}
