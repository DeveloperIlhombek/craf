{
    "name": "Craf Hisobot va kalkulyator",
    "version": "19.0.1.0.0",
    "summary": "Kunlik hisobot ichida kalkulyator: pachka/qop yozuvlarini jami dona va kg ga aylantirish (1C uchun)",
    "description": """
Bo'limlar yozib bergan miqdorlarni 1C ga kiritiladigan birlikka aylantiradi:

- profil: pachka + dona → jami dona va kg (har mahsulotning o'z "dona / pachka" qiymati bilan: 5, 6, …)
- xom-ashyo: qop (quti, kanistr) + kg → jami kg (mahsulotdagi "1 o'ram, kg" bilan)
- kalkulyator Kunlik hisobot sahifasida: bo'lim tanlanadi, qatorlar kiritiladi, jami dona va kg chiqadi,
  1C uchun nusxa olinadi yoki Bo'yash / Pech hujjatiga qoralama sifatida yoziladi
- Bo'yash hujjatida "Qadoqlandi: pachka + dona" ustunlari va tekshiruv (qadoqlangan = bo'yalgan)
- Pech hujjatida va kukun bo'yoqda "qop" bilan kiritish
- hisobot jadvallarida jami dona va kg qatori, profil chiqishida pachka ko'rinishi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_hisobot"],
    "data": [
        "views/craf_kalkulyator_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_kalkulyator/static/src/kalkulyator/kalkulyator.scss",
            "craf_kalkulyator/static/src/kalkulyator/kalkulyator.js",
            "craf_kalkulyator/static/src/kalkulyator/kalkulyator.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
