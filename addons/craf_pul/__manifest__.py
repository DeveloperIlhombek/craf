{
    "name": "Craf: pul — narx, to'lov, qarz",
    "version": "19.0.1.1.1",
    "summary": "Narxlar (1 kg / 1 dona), «Berildi» da mijozga hisob-faktura, Литейка kirimida yetkazib beruvchi "
               "hisob-fakturasi, to'lovlar (naqd, plastik, bank), qarzlar va akt sverka — telefon uchun sahifa",
    "description": """
Pul sahifasi (Craf → Pul, /odoo/craf-pul), telefon birinchi:

- Qarzlar: mijozlar qarzi va yetkazib beruvchilarga qarz; mijoz kartochkasi — harakatlar (akt sverka),
  to'lov qo'shish, Excel akt sverka
- To'lovlar: kun bo'yicha tushum va to'lovlar (naqd, plastik, bank o'tkazma), kassa qoldig'i, 1C belgisi
- Narxlar: tayyor mahsulot narxi 1 kg yoki 1 dona bo'yicha (pachka narxi hisoblanadi), filtr bo'yicha
  hammasiga bir narx
- Sotuv: «Berildi» bo'lganda berilgan mahsulotga hisob-faktura avtomatik (narxi yo'q bo'lsa — «Narx kerak»
  ro'yxatiga tushadi); qisman berilsa — berilgan qismiga
- Xarid: Литейка kirimida narx va yetkazib beruvchi bo'lsa — yetkazib beruvchi hisob-fakturasi avtomatik,
  qaytarishda bekor qilinadi yoki qaytarish hisob-fakturasi; narxsiz kirimga keyin narx yoziladi
- To'lov eng eski qarzdan boshlab yopiladi (avans ham keyingi hisob-fakturaga o'tadi)
- Kunlik hisobotda «To'lovlar» bo'limi va 1C belgisi
- Sotuv sahifasida buyurtma yozilayotganda mijozning qarzi ko'rinadi

O'rnatilganda: kompaniya valyutasi so'm (buxgalteriya yozuvi bo'lmasa), Naqd / Plastik / Bank kassalari,
soliqlar mahsulotdan olinadi (narx yakuniy), sotuvda hisob-faktura berilgan miqdor bo'yicha.
""",
    "author": "Craf",
    "category": "Accounting",
    "license": "LGPL-3",
    "depends": ["craf_sex", "account", "sale_stock"],
    "data": [
        "views/craf_pul_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_pul/static/src/pul/pul.scss",
            "craf_pul/static/src/pul/pul.js",
            "craf_pul/static/src/pul/pul.xml",
            "craf_pul/static/src/sotuv/sotuv_qarz.scss",
            "craf_pul/static/src/sotuv/sotuv_qarz.xml",
        ],
    },
    "post_init_hook": "_craf_pul_post_init",
    "installable": True,
    "application": False,
}
