from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Barcha bo'limlar (Liteyka, Press, Bo'yash, sotuv, panel, Telegram) shu belgiga qaraydi: o'chirilgan
    # mahsulot kam qolgan / tugagan ro'yxatlarida, eslatmalarda va Telegram xabarlarida ko'rinmaydi.
    craf_track_low = fields.Boolean(
        "Kam qolishi kuzatiladi", default=True,
        help="Yoqilgan bo'lsa — mahsulot kam qolsa yoki tugasa, «Kam qolgan / tugagan» ro'yxatida, "
             "eslatmalarda va Telegram xabarlarida ko'rinadi. O'chirilsa — qoldig'i ko'rsatiladi, lekin "
             "ogohlantirilmaydi.")
