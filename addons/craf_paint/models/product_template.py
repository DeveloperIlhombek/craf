from odoo import fields, models

from odoo.addons.craf_production.models.craf_production_mixin import FORECAST_STATUS


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Bo'yash va qadoqlash materiallari prognozi (Bo'yash va qadoqlash → Materiallar qoldig'i va prognoz)
    craf_boyash_material = fields.Boolean("Bo'yash materiali", compute="_compute_craf_boyash_material",
                                          search="_search_craf_boyash_material")
    craf_boyash_qty = fields.Float("Zavodda", compute="_compute_craf_boyash_forecast", digits=(16, 2))
    craf_boyash_in_sex = fields.Float("Sexlarda", compute="_compute_craf_boyash_forecast", digits=(16, 2),
                                      help="Kimyoviy ishlov, Bo'yash sexi va Qadoqlash joylarida")
    craf_boyash_used = fields.Float("Sarf (davr)", compute="_compute_craf_boyash_forecast", digits=(16, 2))
    craf_boyash_period = fields.Integer("Davr, kun", compute="_compute_craf_boyash_forecast")
    craf_boyash_avg = fields.Float("O'rtacha kunlik sarf", compute="_compute_craf_boyash_forecast", digits=(16, 2))
    craf_boyash_days_left = fields.Float("Necha kunga yetadi", compute="_compute_craf_boyash_forecast",
                                         digits=(16, 1))
    craf_boyash_days_text = fields.Char("Yetadi", compute="_compute_craf_boyash_forecast")
    craf_boyash_end_date = fields.Date("Tugash sanasi", compute="_compute_craf_boyash_forecast")
    craf_boyash_status = fields.Selection(FORECAST_STATUS, string="Holat", compute="_compute_craf_boyash_forecast")

    def _compute_craf_boyash_material(self):
        materials = self.env["craf.paint.batch"]._craf_material_products().product_tmpl_id
        for tmpl in self:
            tmpl.craf_boyash_material = tmpl in materials

    def _search_craf_boyash_material(self, operator, value):
        if operator not in ("=", "!=", "in", "not in"):
            raise NotImplementedError
        values = [value] if operator in ("=", "!=") else list(value)
        positive = any(values)
        if operator in ("!=", "not in"):
            positive = not positive
        ids = self.env["craf.paint.batch"]._craf_material_products().product_tmpl_id.ids
        return [("id", "in" if positive else "not in", ids)]

    def _compute_craf_boyash_forecast(self):
        Batch = self.env["craf.paint.batch"]
        rows = Batch._craf_material_forecast(self.product_variant_ids)
        for tmpl in self:
            r = rows.get(tmpl.product_variant_id.id)
            days = r["days_left"] if r else None
            tmpl.craf_boyash_qty = r["qty"] if r else 0.0
            tmpl.craf_boyash_in_sex = r["in_sex"] if r else 0.0
            tmpl.craf_boyash_used = r["used"] if r else 0.0
            tmpl.craf_boyash_period = r["period"] if r else 0
            tmpl.craf_boyash_avg = r["avg"] if r else 0.0
            tmpl.craf_boyash_days_left = days or 0.0
            tmpl.craf_boyash_days_text = Batch._craf_days_text(days)
            tmpl.craf_boyash_end_date = r["end_date"] if days is not None and days <= 365 else False
            tmpl.craf_boyash_status = r["status"] if r else False
