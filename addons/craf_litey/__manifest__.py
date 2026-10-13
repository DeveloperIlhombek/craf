{
    "name": "Craf Литейка: daftar va hisobot",
    "version": "19.0.1.0.0",
    "summary": "Plavka daftar ko'rinishida, Литейка qoldig'i → sarf → stalba → otxod sikli, Excel eksport va import",
    "description": """
Литейка (pech) ishini ishchilar daftari va Excel jadvaliga moslash:

- Nomenklatura: Бухоро чушка Юмшоқ, Брикет/Питак (вторичка, русал), Алюминий диск,
  sarf buyumlari (Пробка, Керамический фильтр, Стекловата)
- Plavka: kun ichidagi №, daftar tartibidagi shixta qatorlari, "993+600+351" kabi tortishlar,
  sarf buyumlari alohida, chiqish: stalba kg va uzunligi, Сталба отход, Литейка отход, шлак;
  balans paneli (kirdi / chiqdi / угар) va me'yordan tashqarida izoh talab qilinadi;
  Литейка da yetmagan material boshqa ichki joydan avtomatik ko'chiriladi
- Литейка hisoboti (Craf → Литейка hisoboti): davr bo'yicha qoldiq, kirim, plavkaga sarf,
  ishlab chiqarilgan stalba va otxod; kunlik qoldiq jadvali (Excel Лист1 ko'rinishida);
  plavkalar jadvali; kirimlar (mashina raqami bilan)
- Excel eksport (4 varaq) va Excel jadvalidagi qoldiqni yuklash (taqqoslash va tuzatish)
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_hisobot", "craf_kalkulyator"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_litey_data.xml",
        "views/craf_foundry_melt_views.xml",
        "views/product_views.xml",
        "views/stock_picking_views.xml",
        "views/craf_litey_kirim_views.xml",
        "views/craf_litey_import_views.xml",
        "views/craf_litey_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_litey/static/src/litey/litey.scss",
            "craf_litey/static/src/litey/litey.js",
            "craf_litey/static/src/litey/litey.xml",
            "craf_litey/static/src/litey/kunlik_link.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
