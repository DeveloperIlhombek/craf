{
    "name": "Craf Korzinka va kimyoviy ishlov",
    "version": "19.0.1.3.0",
    "summary": "Press chiqishi korzinkalar bo'yicha, kimyoviy ishlov bosqichi, stalba chiqindisi, omborga topshirish",
    "description": """
Zavodning haqiqiy jarayoniga moslash:

- Korzinka: kodi, o'z og'irligi, sig'imi (120 dona); press smenasida korzinkalar to'ldiriladi
  (6 m va 5 m dona, tortilgan og'irlik) — profil chiqishi korzinkalardan hisoblanadi
- Press varag'i: korzinka (o'z og'irligi), 1-2 profil 6 m / 5 m dona, kryuchok, palka, brutto → netto;
  profil brak va pitak otxod Liteykaga; quyma sarfi ixtiyoriy (Liteyka qoldig'i orqali)
- Brak ajratish (bo'yashdan oldin): korzinkadan brak dona → kg Liteykaga, 6 m → 5 m kesilganlar
- Kimyoviy ishlov — alohida bosqich: korzinkalar tanlanadi, kimyo sarfi (me'yor: maydon × kg/m²);
  profillar "Kimyoviy ishlov" joyidan Bo'yash sexiga o'tadi
- Bo'yash: korzinkalardan to'ldirish; tayyor mahsulotni bir tugmada omborga topshirish
- Литейка: chiqqan quyma — stalba; kesilgan chiqindi (Сталба отход) alohida
- Zavod xaritasida "Kimyoviy ishlov" bo'limi, BoM da "Kimyoviy ishlov" operatsiyasi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_mrp", "craf_paint", "craf_dashboard"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_korzinka_data.xml",
        "data/craf_paint_sort_data.xml",
        "views/craf_basket_views.xml",
        "views/craf_chem_treatment_views.xml",
        "views/craf_extrusion_shift_views.xml",
        "views/craf_paint_batch_views.xml",
        "views/craf_paint_sort_views.xml",
        "views/craf_foundry_melt_views.xml",
        "views/craf_korzinka_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_korzinka/static/src/panel_korzinka.xml",
            "craf_korzinka/static/src/basket_dashboard/basket_dashboard.js",
            "craf_korzinka/static/src/basket_dashboard/basket_dashboard.xml",
            "craf_korzinka/static/src/basket_dashboard/basket_dashboard.scss",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
