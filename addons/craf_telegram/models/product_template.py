from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_tg_alert = fields.Boolean(
        "Telegram: minimal qoldiq xabari yuborilgan", copy=False,
        help="Qoldiq minimaldan kamayganda bir marta yuboriladi; tiklangach belgi olinadi.")
