from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    craf_kpi_trial = fields.Boolean("KPI sinov rejimida", default=True,
                                    help="Yoqilgan: KPI hisoblanadi va ko'rsatiladi, lekin tabel/maoshga «sinov» deb chiqadi")
    craf_kpi_w_att = fields.Integer("KPI: davomat ulushi, %", default=40)
    craf_kpi_w_punct = fields.Integer("KPI: intizom (kechikmaslik) ulushi, %", default=20)
    craf_kpi_w_prod = fields.Integer("KPI: ishlab chiqarish ulushi, %", default=40)
    craf_kpi_litey_loss = fields.Float("KPI: Литейка угар me'yori, % (ko'pi bilan)", default=3.0)
    craf_kpi_press_yield = fields.Float("KPI: press chiqishi me'yori, % (kamida)", default=80.0)
    craf_kpi_paint_defect = fields.Float("KPI: bo'yash braki me'yori, % (ko'pi bilan)", default=2.0)
