{
    "name": "Craf: diller portali",
    "version": "19.0.1.0.0",
    "summary": "Diller o'zi buyurtma beradi (/diller, telefon uchun), sotuvchi tasdiqlaydi — mavjud yuklash, "
               "hisob-faktura va qarz oqimiga tushadi",
    "description": """
Diller portali — mavjud sotuv oqimining yangi kirish nuqtasi:

- Diller = kontragent, bitta login: telefon + parol, taklif havolasi bilan
- Katalog: tur, seriya, rang, uzunlik; dillerga xos narx (Odoo narxlar ro'yxati); mavjudlik faqat daraja bilan;
  qisqartmalar lug'ati bilan qidiruv; sevimlilar va ko'p olinadiganlar
- Savat: pachka + dona, kerakli sana, mashina, izoh (olish joyini diller ko'rmaydi, uni zavod belgilaydi); qarz chegarasidan oshsa — bloklanmaydi,
  «Tasdiq kutilmoqda (qarz)» ga tushadi
- Zavod: Sotish → Diller buyurtmalari; tasdiqlanganda yuklovchi navbatiga tushadi va mahsulot band qilinadi
- Holat kuzatish, mashina rasmi, hisob-faktura PDF, qarz paneli, akt sverka (PDF/Excel), statistika
- Qaytarish so'rovi: sotuvchi tasdiqlaydi, mahsulot kelganda mavjud «Qaytarish» ishga tushadi
- Bildirishnoma: portal qo'ng'iroqchasi va Telegram bot; ilova kabi o'rnatish (PWA)
""",
    "author": "Craf",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": ["craf_pul", "craf_telegram", "portal"],
    "data": [
        "security/craf_diller_security.xml",
        "security/ir.model.access.csv",
        "data/craf_diller_cron.xml",
        "report/craf_diller_akt_report.xml",
        "wizard/craf_diller_login_wizard_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/craf_diller_return_views.xml",
        "views/craf_diller_notice_views.xml",
        "views/craf_diller_menus.xml",
        "views/craf_diller_templates.xml",
    ],
    "assets": {
        "craf_diller.assets": [
            "web/static/src/module_loader.js",
            "web/static/lib/owl/owl.js",
            "web/static/lib/owl/odoo_module.js",
            "craf_diller/static/src/diller/diller.css",
            "craf_diller/static/src/diller/diller.js",
        ],
    },
    "post_init_hook": "_craf_diller_post_init",
    "installable": True,
    "application": False,
}
