{
    "name": "Craf Pachka yorlig'i",
    "version": "19.0.1.0.1",
    "summary": "Pachka yorlig'i (PDF, QR): tur, rang, dona, nazariy va haqiqiy kg",
    "description": """
Pachkalar ro'yxati va yorliq:
- har bir pachka o'z raqamini oladi (masalan P26-000123)
- yorliqda: mahsulot, kesim, rang, uzunlik, dona, nazariy va haqiqiy kg, sana, manba hujjat, QR
- QR telefon kamerasi bilan skanerlansa, pachka kartochkasi Odoo da ochiladi
- Zavod xaritasidagi ko'chirish oynasida pachka raqami / QR kiritilsa, mahsulot va miqdor o'zi to'ladi
""",
    "author": "Craf",
    "category": "Inventory",
    "license": "LGPL-3",
    "depends": ["craf_profile", "craf_kochirish"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "report/craf_pack_report.xml",
        "wizard/craf_pack_wizard_views.xml",
        "views/craf_pack_views.xml",
        "views/product_template_views.xml",
        "views/craf_zavod_transfer_views.xml",
        "views/craf_label_menus.xml",
    ],
    "installable": True,
    "application": False,
}
