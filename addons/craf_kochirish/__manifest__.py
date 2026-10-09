{
    "name": "Craf Ko'chirish",
    "version": "19.0.1.0.0",
    "summary": "Zavod xaritasidan ichki ko'chirish: bir nuqtadan boshqasiga mahsulot berish",
    "description": """
Zavod xaritasidagi blokdan "Ko'chirish" tugmasi:
- qayerdan / qayerga / mahsulot / miqdor (pachka + dona yoki kg)
- mavjud qoldiqdan ortiq ko'chirib bo'lmaydi
- Odoo ichki ko'chirish hujjati yaratiladi va darhol bajariladi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_zavod"],
    "data": [
        "security/ir.model.access.csv",
        "views/craf_zavod_transfer_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_kochirish/static/src/kochirish.js",
            "craf_kochirish/static/src/kochirish.xml",
        ],
    },
    "installable": True,
    "application": False,
}
