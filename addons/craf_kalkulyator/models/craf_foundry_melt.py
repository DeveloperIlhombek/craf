from odoo import api, fields, models


class CrafFoundryMeltLine(models.Model):
    _inherit = "craf.foundry.melt.line"

    bags = fields.Float("O'ram", digits=(16, 2), help="Qop / quti / chushka soni — kg ga aylantiriladi")
    pkg_kg = fields.Float(related="product_id.craf_pkg_kg", string="1 o'ram, kg", digits=(16, 2))
    pkg_name = fields.Char(related="product_id.craf_pkg_name", string="O'ram nomi")

    @api.onchange("bags", "product_id")
    def _onchange_bags(self):
        if self.bags and self.pkg_kg:
            self.qty = round(self.bags * self.pkg_kg, 2)
