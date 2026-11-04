{
    "name": "Craf: matritsa (qolip) xodimi",
    "version": "19.0.1.4.0",
    "summary": "Press: matritsalar (yaroqli / yaroqsiz), Ammiak va Azot ballonlari sarfi, kaustik soda — telefon sahifasi",
    "description": """
Press bo'limining qolip (matritsa) mutaxassisi uchun — kimyo xodimi kabi, telefon birinchi:

- Matritsalar: har biri raqami bilan, qaysi profil (kesim) uchun, rasmi (telefon kamerasidan), holati
  yaroqli / yaroqsiz (sababi bilan);
  profil bo'yicha jami, yaroqli va yaroqsiz soni
- Gaz: Ammiak va Azot ballonlari, qoldig'i; xodim faqat sarfni yozadi (to'ldirish — omborchida)
- Kaustik soda: qoliplarni tozalash uchun ombordan olinganda bir marta yoziladi, darhol sarfga yechiladi
- Qoldiq: kaustik soda, gaz, matritsalar

Xodim: rol «Sex ishchisi», «Ish joyi» — Matritsa (qoliplar). U faqat «Matritsa» ilovasini ko'radi, bosh sahifasi —
matritsa sahifasi, telefonda pastki panel (Matritsalar, Gaz, Soda, Qoldiq).
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_sex", "craf_gaz", "craf_korzinka"],
    "data": [
        "security/ir.model.access.csv",
        "views/craf_matrix_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_matritsa/static/src/matritsa/matritsa.scss",
            "craf_matritsa/static/src/matritsa/matritsa.js",
            "craf_matritsa/static/src/matritsa/matritsa.xml",
        ],
    },
    "installable": True,
    "application": False,
}
