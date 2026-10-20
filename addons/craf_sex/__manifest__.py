{
    "name": "Craf: sexlar (Press, Kimyo, Bo'yash) va rollar",
    "version": "19.0.1.8.0",
    "summary": "Press, kimyoviy ishlov, bo'yash va qadoqlash — telefon uchun sahifa; direktor, omborchi, sex ishchisi rollari",
    "description": """
Sexlar sahifasi (Craf → Sexlar, /odoo/craf-sex), telefon birinchi:

- Press: smenani ochish (press, matritsa, smena, mas'ul), korzinkani to'ldirish (6 m / 5 m dona,
  tortilgan og'irlik → netto), korzinkasiz chiqish (sotiladigan bo'yalmagan profil), quyma sarfi,
  press qoldig'i (питак) va brak; chiqish %, farq, kg/soat; tasdiqlash
- Kimyoviy ishlov: kutayotgan korzinkalarni belgilash, kimyo sarfi me'yordan, tasdiqlash
- Bo'yash va qadoqlash: rang, tayyor korzinkalar, kirdi / brak / pachka + dona, kukun (o'ram yoki kg),
  tasdiqlash, omborga topshirish, pachka yorliqlari
- Har sexda: korzinkalar holati, sexdagi qoldiq, davr hujjatlari, 1C belgisi (omborchi)

Hisobchi kunlik yakuni (Kunlik hisobot): xom-ashyo kirimi (yetkazib beruvchidan, qaytarish) va
inventarizatsiya farqlari bo'limlari; kirim, omborga topshirish va sanash hujjatlari ham 1C belgisini oladi.

Rollar (Sozlamalar → Foydalanuvchilar → Craf / Zavod rollari): Sex ishchisi, Omborchi, Direktor;
foydalanuvchida «Ish joyi» (Литейка, Press, Kimyo, Bo'yash) — bosh sahifa va sahifadagi sex shu bo'yicha.

Sahifalar rol bo'yicha:
- Administrator: hamma ilovalar, bosh sahifa har doim «Boshqaruv panellari»
- Yuklovchi (boshqa roli bo'lmasa): faqat «Yuklash» ilovasi — Sotuv (yuklash navbati, bosh sahifa) va
  Tayyor mahsulot sanash; telefonda pastki panel (Yuklash, Bugun, Qoldiq, Sanash, Yuk xati)
- Sotuvchi: Inventarizatsiyaga to'liq ruxsat (ombor administratori, Craf ombor sahifalari, Kunlik hisobot);
  Xodimlar va Davomat ilovalari ko'rinmaydi (Xodimlar — kadrlar xodimi, direktor, administrator)
- Inventarizatsiya soddalashtirilgan: umumiy ko'rinishda faqat ombor operatsiyalari; Fizik inventarizatsiya,
  Chiqindi, To'ldirish, umumiy Mahsulotlar, baholash va tahlil hisobotlari, saqlash/joylash qoidalari —
  faqat texnik (debug) rejimda
- Muhokama (Discuss) ilovasi va tepadagi chat belgisi yashirilgan (texnik rejimda ilova ochiladi)
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_litey", "craf_sotuv", "maintenance", "spreadsheet_dashboard"],
    "data": [
        "security/craf_sex_security.xml",
        "security/ir.model.access.csv",
        "data/craf_menu_access.xml",
        "data/craf_inventory_menus.xml",
        "views/craf_sex_views.xml",
        "views/craf_c1_views.xml",
        "views/craf_role_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_sex/static/src/sex/sex.scss",
            "craf_sex/static/src/sex/sex.js",
            "craf_sex/static/src/sex/sex.xml",
            "craf_sex/static/src/kunlik/kunlik_yakun.xml",
            "craf_sex/static/src/loader_nav/loader_nav.scss",
            "craf_sex/static/src/loader_nav/loader_nav.js",
            "craf_sex/static/src/loader_nav/loader_nav.xml",
            "craf_sex/static/src/no_discuss.js",
        ],
    },
    "installable": True,
    "application": False,
}
