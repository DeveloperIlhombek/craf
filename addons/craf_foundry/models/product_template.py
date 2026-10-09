from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_not_metal = fields.Boolean(
        "Metall emas (Литейка)",
        help="Флюс, тальк, beton kabi qo'shimchalar: shixtada sarflanadi, lekin угар hisobiga kirmaydi.")
