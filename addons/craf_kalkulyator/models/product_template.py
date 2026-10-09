from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_pkg_name = fields.Char(
        "O'ram nomi", default="qop",
        help="Bo'limlar shu birlikda yozadi: qop, quti, kanistr, chushka …")
    craf_pkg_kg = fields.Float(
        "1 o'ram, kg", digits=(16, 3), aggregator=None,
        help="Bitta qop (quti, kanistr) og'irligi. Kalkulyator va hujjatlarda o'ram soni shu bilan kg ga aylanadi.")
