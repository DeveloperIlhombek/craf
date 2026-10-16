{
    "name": "Craf: davomat (Hikvision), tabel va KPI",
    "version": "19.0.1.1.0",
    "summary": "Hikvision yuz terminali yozuvlari → Odoo davomati, kunlik davomat, oylik tabel (Excel), KPI (sinov rejimi)",
    "description": """
Davomat sahifasi (Craf → Davomat, /odoo/craf-davomat), telefon birinchi:

- Hikvision terminali har bir tanish yozuvini o'zi yuboradi (ISAPI «HTTP Listening»):
  /craf/davomat/hik/<qurilma kaliti> — JSON, multipart (event_log + Picture) va XML; heartbeat;
  takror yozuv (serialNo), 2 daqiqalik takror tanish, rad etilgan tanish, noma'lum xodim — jurnalda
- Kirish / chiqish: qurilma holati bo'lsa — shu bo'yicha; bo'lmasa ochiq yozuv — chiqish, yo'q — kirish;
  16 soatdan eski ochiq yozuv «chiqish unutilgan» bo'lib jadval bo'yicha yopiladi
- Bugun: keldi / ishda / kechikdi / kelmadi; xodim kartochkasi — kunlar, qo'lda tuzatish, Terminal ID, ish jadvali
- Tabel: oy bo'yicha kunlar (soat, K — kelmadi, D — dam), jami kun, soat, kechikish; Excel
- KPI: davomat, intizom (kechikmaslik) va ishlab chiqarish (Литейка угар, press chiqishi, bo'yash braki —
  xodim mas'ul bo'lgan hujjatlardan) — ulush va me'yorlar sozlanadi; sinov rejimi
- Terminallar: qurilmalar, yuboradigan manzil, oxirgi aloqa, yozuvlar jurnali, noma'lum Terminal ID ni
  xodimga biriktirish, sinov yozuvi
""",
    "author": "Craf",
    "category": "Human Resources",
    "license": "LGPL-3",
    "depends": ["craf_sex", "hr_attendance"],
    "data": [
        "security/craf_davomat_security.xml",
        "security/ir.model.access.csv",
        "data/craf_davomat_data.xml",
        "views/craf_davomat_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_davomat/static/src/davomat/davomat.scss",
            "craf_davomat/static/src/davomat/davomat.js",
            "craf_davomat/static/src/davomat/davomat.xml",
        ],
    },
    "installable": True,
    "application": False,
}
