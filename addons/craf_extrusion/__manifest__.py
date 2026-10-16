{
    "name": "Craf Press",
    "version": "19.0.1.0.1",
    "summary": "Press smena hisoboti: matritsa, quyma sarfi, profil chiqishi, qoldiq va brak",
    "description": """
Press smenasi:
- matritsa (kesim), quyma mahsuloti va partiyasi (plavka raqami), quyma sarfi kg
- chiqish: bo'yalmagan profil dona bo'yicha, nazariy kg avtomatik (dona × uzunlik × kg/m)
- press qoldig'i (питак) va brak profil kg — Chiqindiga
- chiqish %, hisobga olinmagan farq, unumdorlik kg/soat
- bo'yaladigan profillar uchun bo'yalmagan yarim tayyor mahsulotlar avtomatik yaratiladi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_foundry"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_extrusion_data.xml",
        "views/craf_extrusion_shift_views.xml",
        "views/craf_extrusion_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
