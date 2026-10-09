from odoo import fields, models


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    craf_auto = fields.Boolean(
        "Craf me'yoridan", copy=False,
        help="Bu BoM Craf me'yorlaridan avtomatik hisoblangan. 'BoM larni qayta hisoblash' uni yangilaydi.")
