{
    "name": "Craf: hujjat va rasmlarni Odoo ichida ko'rish, chop etish",
    "version": "19.0.1.1.0",
    "summary": "PDF hisobotlar yuklab olinmaydi: Odoo ichida ko'rinadi va «Chop etish» bilan printerga yuboriladi",
    "description": """
Barcha PDF hisobotlar (Yuk xati, Pachka yorlig'i va keyin qo'shiladigan bo'lim hisobotlari):

- «Chop etish» bosilganda PDF yuklab olinmaydi — Odoo ichida oyna ochiladi, hujjat ko'rinadi
- oynadagi «Chop etish» tugmasi brauzerning chop etish oynasini to'g'ridan-to'g'ri ochadi
- kerak bo'lsa «PDF yuklab olish» tugmasi ham bor
- wkhtmltopdf ishlamasa, Odoo ning odatiy yo'li ishlaydi

Rasmlar (formadagi rasm maydonlari, biriktirilgan rasm/PDF fayllar — masalan mashina rasmlari):

- bosilganda yangi oynada ochilmaydi va yuklab olinmaydi — Odoo ichidagi ko'rish oynasida ko'rinadi
- oynada kattalashtirish, burish, chop etish va yuklab olish bor; bir nechta rasm bo'lsa ← → bilan o'tiladi
""",
    "author": "Craf",
    "category": "Hidden",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "craf_print/static/src/preview/print_preview.scss",
            "craf_print/static/src/preview/print_preview.js",
            "craf_print/static/src/preview/print_preview.xml",
            "craf_print/static/src/image_view/image_view.scss",
            "craf_print/static/src/image_view/image_view.js",
            "craf_print/static/src/image_view/image_view.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
