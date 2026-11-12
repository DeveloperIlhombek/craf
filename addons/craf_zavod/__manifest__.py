{
    "name": "Craf Zavod xaritasi",
    "version": "19.0.1.2.0",
    "summary": "Zavodning jonli xaritasi: har bir bo'limdagi qoldiq va real oqimlar animatsiyasi",
    "description": """
Craf -> Zavod xaritasi sahifasi (real ma'lumot):
- Bloklar — ombor joylashuvlari: jonli qoldiq (kg, dona/rulon, pachka), to'lish darajasi, korzinkalar
- Oqimlar — tanlangan davrdagi (bugun / 7 / 30 kun) bajarilgan ombor harakatlaridan: kirim, stalba, profil, bo'yalgan, sotuv, otxod, shlak; chiziq qalinligi va zarrachalar tezligi miqdorga mos
- KPI: kirim, stalba, press, bo'yash, sotuv, to'la korzinkalar
- Blokni bosganda: davrdagi kirim/chiqim, ishlab chiqarish, sarf, mahsulotlar (qidiruv), oxirgi harakatlar
- «Tartiblash»: bloklarni surish va yashirish (ombor menejeri), joyi saqlanadi
- «Bo'yash sexi» va «Qadoqlash» xaritada bitta blok — «Bo'yash va qadoqlash»
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_profile", "stock", "mrp"],
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
