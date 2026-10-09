from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_min_qty = fields.Float("Minimal qoldiq", digits=(16, 1),
                                help="Qoldiq shundan kamaysa, kunlik hisobotda va panelda ogohlantiriladi.")
