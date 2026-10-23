{
    "name": "Craf: Telegram bot",
    "version": "19.0.1.1.0",
    "summary": "Bitta umumiy Telegram bot: bo'lim mas'ullariga kunlik hisobot va minimal qoldiq eslatmasi",
    "description": """
Telegram bot (Ishlab chiqarish → Konfiguratsiya → Sozlamalar → Craf Telegram bot):

- Token sozlamada yoziladi (BotFather bergan); «Botni tekshirish» bot nomini ko'rsatadi
- Mas'ul shaxslar va Telegram ID — har bo'lim sozlamasida (Liteyka, Press, Bo'yash va qadoqlash)
- Kishi botga /start bosadi — bot unga Telegram ID sini yozib beradi; ID sozlamaga yozilgach
  bot uni taniydi
- Kunlik hisobot (har kuni belgilangan soatda, standart 11:00, «Kunlik hisobot» belgilanganlarga) — ixcham:
  bo'lim bo'yicha kechagi ish yakuni (Liteyka: plavka, sarf, kirim; Press: korzinka, netto, brak, pitak;
  Bo'yash: kimyo, brak ajratish, bo'yash) va faqat muammoli qoldiq — tugagan, kam, tez tugaydigan
- Minimal qoldiq eslatmasi (Liteyka, Press quymasi, Bo'yash materiallari): minimaldan kamaysa yoki tugasa — darhol
  («Minimal qoldiq» belgilanganlarga), tiklanganda yana kuzatiladi
- Buyruqlar (faqat ro'yxatdagi mas'ullar uchun): /qoldiq — kam qolgan va tugagan materiallar,
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
