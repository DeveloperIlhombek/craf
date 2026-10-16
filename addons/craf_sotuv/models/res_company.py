from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    craf_sale_location_id = fields.Many2one(
        "stock.location", "Sotuv: asosiy joy", domain=[("usage", "=", "internal")],
        help="Buyurtmada joy yozilmagan bo'lsa, mahsulot shu joydan beriladi (odatda Tayyor mahsulot ombori).")
    craf_sale_allow_negative = fields.Boolean(
        "Sotuv: qoldiq yetmasa ham berish",
        help="Yoqilsa, qoldiq yetmasa ham sotuv bajariladi va qoldiq manfiy bo'ladi. "
             "Haqiqiy sanoq kiritilguncha vaqtincha ishlatiladi.")
    craf_sale_use_price = fields.Boolean(
        "Sotuv: narxlarni hisoblash",
        help="O'chiq bo'lsa, Craf → Sotuv dan yaratilgan buyurtmalarda narx 0 (hozircha faqat miqdor).")
    craf_sale_use_scan = fields.Boolean(
        "Sotuv: pachka QR skaneri",
        help="Pachkalarga QR yorliq yopishtirilsa yoqing — sotuv va yuklash sahifalarida skaner maydoni chiqadi.")
