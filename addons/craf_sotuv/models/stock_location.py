from odoo import fields, models


class StockLocation(models.Model):
    _inherit = "stock.location"

    craf_sale_point = fields.Boolean(
        "Sotuv joyi", help="Shu joydan mijozga mahsulot beriladi (Craf → Sotuv dagi Zavod / Parnik / Rohat).")
    craf_sale_label = fields.Char("Sotuvdagi nomi", help="Qisqa nom: Zavod, Parnik, Rohat")
    craf_sale_sequence = fields.Integer("Sotuv tartibi", default=10)

    def _craf_sale_label(self):
        self.ensure_one()
        return self.craf_sale_label or self.name
