{
    "name": "Craf Ishlab chiqarish me'yorlari",
    "version": "19.0.1.0.1",
    "summary": "Bosqichlar (Литейка → Press → Bo'yash → Qadoqlash), ish markazlari, har mahsulot uchun BoM va xom-ashyo sarfi",
    "description": """
Odoo Manufacturing ni zavod jarayoniga moslaydi:

- bosqich operatsiya turlari: Литейка, Press, Press → Qadoqlash, Bo'yash (o'z sexlari bilan)
- ish markazlari: eritish pechi, press №1 / №2, bo'yash liniyasi, qadoqlash
- har bir profil uchun ko'p bosqichli BoM: bo'yalgan profil = bo'yalmagan profil + kukun + kimyo;
  bo'yalmagan profil = quyma (+ press qoldig'i, brak); quyma = shixta
- me'yorlar bitta sahifada (press chiqishi, kukun g/m², kimyo, tezliklar); BoM lar qayta hisoblanadi
- mahsulot kartochkasida bosqichlar va 1 dona / 1 pachka / 1000 dona uchun jami xom-ashyo sarfi
- "Xom-ashyo sarfi" hisoboti: haqiqiy sarf me'yor bilan solishtirib
- Plavka / Press / Bo'yash hujjatlaridan yaratilgan buyurtmalar o'z bosqich turiga tushadi
- ishlab chiqarish buyurtmasida "Oldingi bosqichlarni rejalash": yetishmagan bo'yalmagan profil va quyma uchun
  Press va Литейка buyurtmalari ochiladi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_paint", "mrp"],
    "data": [
        "security/ir.model.access.csv",
        "data/mrp_workcenter_data.xml",
        "views/craf_mrp_norm_views.xml",
        "views/product_template_views.xml",
        "views/mrp_production_views.xml",
        "report/craf_mrp_consumption_views.xml",
        "views/craf_mrp_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
