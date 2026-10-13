from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    craf_vehicle = fields.Char("Mashina raqami", index="trigram", copy=False)


class StockMove(models.Model):
    _inherit = "stock.move"

    craf_price = fields.Float("Kirim narxi (1 birlik)", digits=(16, 2), copy=False,
                              help="Литейка kirimida yozilgan narx (mashina bo'yicha hisob uchun)")
