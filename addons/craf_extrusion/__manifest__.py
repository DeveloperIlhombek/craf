{
    "name": "Craf Press",
    "version": "19.0.1.2.0",
    "summary": "Press smena hisoboti: matritsa, quyma sarfi, profil chiqishi, qoldiq va brak",
    "description": """
Press smenasi:
- matritsa (kesim), quyma mahsuloti va partiyasi (plavka raqami), quyma sarfi kg
- chiqish: bo'yalmagan profil dona bo'yicha, nazariy kg avtomatik (dona × uzunlik × kg/m)
- press qoldig'i (питак) va brak profil kg — Chiqindiga
- chiqish %, hisobga olinmagan farq, unumdorlik kg/soat
- bo'yaladigan profillar uchun bo'yalmagan yarim tayyor mahsulotlar avtomatik yaratiladi
- guruh va jami qatorlarida chiqish % va unumdorlik og'irlik bo'yicha (Σ chiqish / Σ quyma), oddiy o'rtacha emas
- matritsa normasi (chiqish %, kg/soat) va fakt; normadan past smena belgilanadi, mas'ullarga eslatma boradi
- quyma qoldig'i va prognoz: oxirgi N kun press sarfi bo'yicha necha kunga yetishi, minimal qoldiq eslatmasi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_foundry"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_extrusion_data.xml",
        "data/craf_extrusion_norm_data.xml",
        "views/craf_extrusion_shift_views.xml",
        "views/craf_briket_views.xml",
        "views/craf_extrusion_norm_views.xml",
        "views/craf_extrusion_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_extrusion/static/src/weighted_avg.js",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
