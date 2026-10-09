from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    craf_map_show = fields.Boolean("Xaritada ko'rsatish")
    craf_map_kind = fields.Selection(
        [("raw", "Xom-ashyo"), ("process", "Sex / jarayon"), ("finished", "Tayyor mahsulot"), ("waste", "Chiqindi")],
        string="Blok turi", default="process")
    craf_map_sequence = fields.Integer("Tartib", default=10)
    craf_map_x = fields.Integer("X", default=40)
    craf_map_y = fields.Integer("Y", default=40)
    craf_map_w = fields.Integer("Eni", default=240)
    craf_map_h = fields.Integer("Bo'yi", default=180)
