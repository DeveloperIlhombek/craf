{
    "name": "Craf: Telegram bot",
    "version": "19.0.1.0.0",
    "summary": "Bitta umumiy Telegram bot: bo'lim mas'ullariga kunlik hisobot va minimal qoldiq eslatmasi",
    "description": """
Telegram bot (Ishlab chiqarish → Konfiguratsiya → Sozlamalar → Craf Telegram bot):

- Token sozlamada yoziladi (BotFather bergan); «Botni tekshirish» bot nomini ko'rsatadi
- Mas'ul shaxslar va Telegram ID — har bo'lim sozlamasida (Liteyka, Press, Bo'yash va qadoqlash)
- Kishi botga /start bosadi — bot unga Telegram ID sini yozib beradi; ID sozlamaga yozilgach
  bot uni taniydi
- Kunlik hisobot (har kuni belgilangan soatda, «Kunlik hisobot» belgilanganlarga):
  Liteyka — kechagi plavka, kirim, tugagan / kam qolgan / tez tugaydigan xom-ashyo;
  Press — smenalar, quyma sarfi, profil chiqishi; Bo'yash va qadoqlash — kimyoviy ishlov va bo'yash
- Minimal qoldiq eslatmasi: material minimaldan kamaysa yoki tugasa — darhol
  («Minimal qoldiq» belgilanganlarga), tiklanganda yana kuzatiladi
- Buyruqlar (faqat ro'yxatdagi mas'ullar uchun): /qoldiq — Liteyka xom-ashyo holati,
  /hisobot — kechagi hisobot, /id — Telegram ID
- Barcha yuborilgan xabarlar jurnali (Konfiguratsiya → Telegram xabarlari)
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_sex"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_telegram_cron.xml",
        "views/craf_telegram_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
