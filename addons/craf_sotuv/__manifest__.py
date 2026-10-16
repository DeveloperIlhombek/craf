{
    "name": "Craf Sotuv (Berildi)",
    "version": "19.0.1.6.0",
    "summary": "Sotuv bo'limi: sotuvchi buyurtma kiritadi, yuklovchi yuklaydi, «Berildi» da mahsulot ombordan ayriladi (telefon uchun)",
    "description": """
Sotuv bo'limi (telefon birinchi):

- Sotuvchi (Craf → Sotuv → Buyurtma): buyurtmani qisqa yozadi (1-qator mijoz, keyin joy, seriya/rang,
  «L 28», «T 3+5dona») yoki mahsulotni ro'yxatdan tanlaydi, tekshiradi va «Yuklovchiga yuboradi» —
  mahsulot tanlangan joyda (Zavod = Tayyor mahsulot ombori, Parnik, Rohat) band qilinadi
- Yuklovchi (Craf → Sotuv → Yuklash): navbatda yangi buyurtma o'zi chiqadi (xabar va tebranish),
  buyurtmani ko'radi va «Qabul qilish» ni bosadi (holat «Yuklanmoqda», sotuvchiga xabar boradi),
  qatorlarni «Yuklandi» deb belgilaydi yoki haqiqiy pachka + dona yozadi, yuklab bo'lgach mashinani
  rasmga oladi (buyurtmaga biriktiriladi), «Berildi» — mahsulot ombordan ayriladi va sotuvchiga xabar boradi; to'liq yuklanmasa qolgani navbatda qoladi yoki bekor qilinadi
- yuklangan miqdor joydagi qoldiqdan oshsa to'xtaydi (pachka + dona da ko'rsatadi)
- Sotuvlar (kun, holat: Qabul kutilmoqda / Yuklanmoqda / Berildi) va Qoldiq (joy bo'yicha) varaqlari
- qisqartmalar lug'ati; tanilmagan qisqartma bir marta tanlansa eslab qoladi
- Kunlik hisobotda «Sotuv» bo'limi va «Sotildi» ustuni, Excel da «Sotuv» varag'i, 1C belgisi
- mijoz kartochkasida berilgan mahsulotlar tarixi
- pachka QR skaneri (ixtiyoriy, sozlamada yoqiladi)
""",
    "author": "Craf",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": ["sale_management", "sale_stock", "craf_label", "craf_kalkulyator"],
    "data": [
        "security/craf_sotuv_security.xml",
        "security/ir.model.access.csv",
        "views/craf_sotuv_alias_views.xml",
        "views/sale_order_views.xml",
        "views/craf_pack_views.xml",
        "views/res_partner_views.xml",
        "views/stock_location_views.xml",
        "views/craf_sotuv_menus.xml",
        "views/craf_sanash_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "craf_sotuv/static/src/sotuv/sotuv.scss",
            "craf_sotuv/static/src/sotuv/sotuv.js",
            "craf_sotuv/static/src/sotuv/sotuv.xml",
            "craf_sotuv/static/src/sotuv/kunlik_sotuv.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
