{
    "name": "Craf Stiker",
    "version": "19.0.1.0.0",
    "summary": "Bo'yash va qadoqlash: profilga yopishtiriladigan stiker lenta sarfi, qoldig'i va prognozi",
    "description": """
Stiker lenta (Bo'yash va qadoqlash → Stiker):
- stiker turlari: logo (CRAF, Alusam, Crose, Alrom …), yopishqoqlik (Medium 50 mic / High 80 mic), kenglik (40, 52, 68 mm), rulon uzunligi; har biriga ombor mahsuloti (metrda) o'zi yaratiladi
- profil normalari: qaysi kesimga qaysi kenglikdagi stiker necha tomonga (1 yoki 2) ketadi, kerak bo'lsa aniq stiker turi — to'liq CRUD
- rang yopishqoqligi: Antratsit (J306) — High, qolganlari — Medium (rang normalarida o'zgartiriladi)
- logo: kesim seriyasi logoga mos bo'lsa (ALUSAM, CRAF) — o'sha, aks holda smenada tanlangan logo
- bo'yash smenasi tasdiqlanganda: bo'yalgan dona × uzunlik × tomonlar = stiker metri, ombordan yechiladi (smenada qo'lda o'zgartirish mumkin); Bo'yash sahifasidan kiritilganda ham shunday
- qoldiq rulonda, oxirgi N kun sarfi bo'yicha necha kunga yetishi, minimal qoldiq eslatmasi, rulon sanash
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_paint"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_stiker_data.xml",
        "wizard/craf_sticker_count_views.xml",
        "views/craf_sticker_views.xml",
        "views/craf_paint_batch_views.xml",
        "views/craf_stiker_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
