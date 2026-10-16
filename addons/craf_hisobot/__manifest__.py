{
    "name": "Craf Kunlik hisobot (1C uchun)",
    "version": "19.0.1.0.1",
    "summary": "Kunlik obxod va hisobot: bo'limlar sarfi va chiqishi, xom-ashyo harakati, Excel, 1C ga kiritildi belgisi",
    "description": """
Hisobchi / omborchi uchun bitta sahifa (Craf → Kunlik hisobot):

- tanlangan kun: Pech, Press, Kimyoviy ishlov, Bo'yash va qadoqlash, Omborga topshirish —
  har birida hujjatlar, sarf, chiqish va chiqindi; "+ Yozuv" bilan shu kunga hujjat ochish
- xom-ashyo harakati: boshlang'ich qoldiq, kirim, ishlab chiqarishdan, sarf, boshqa chiqim, oxirgi qoldiq;
  minimal qoldiqdan kamaygani belgilanadi
- tayyor mahsulot harakati: boshlang'ich, ishlab chiqarildi, jo'natildi, oxirgi
- Excel (1C ga kiritish uchun) yuklab olish
- "1C ga kiritildi" belgisi: kuniga 1–2 marta kiritilganda qaysi hujjat kiritilgani ko'rinadi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_korzinka"],
    "data": [
        "views/craf_hisobot_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_hisobot/static/src/kunlik/kunlik.scss",
            "craf_hisobot/static/src/kunlik/kunlik.js",
            "craf_hisobot/static/src/kunlik/kunlik.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
