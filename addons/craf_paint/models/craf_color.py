from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError


class CrafColor(models.Model):
    _inherit = "craf.color"

    craf_powder_norm = fields.Float(
        "Kukun normasi, g/m²", digits=(16, 1),
        help="Bo'yash smenasida shu rang uchun kukun normasi. Bo'sh bo'lsa — 120 g/m².")
    craf_fact_powder_g_m2 = fields.Float("Fakt kukun, g/m²", compute="_compute_craf_fact", digits=(16, 1),
                                         help="Oxirgi N kun (Bo'yash sozlamasi) tasdiqlangan smenalar, "
                                              "og'irlik bo'yicha")
    craf_fact_defect_pct = fields.Float("Fakt brak, %", compute="_compute_craf_fact", digits=(16, 2))
    craf_fact_area = fields.Float("Maydon, m²", compute="_compute_craf_fact", digits=(16, 1))
    craf_fact_batch_count = fields.Integer("Smenalar", compute="_compute_craf_fact")

    def _compute_craf_fact(self):
        period = max(self.env["craf.bolim"]._get("boyash").forecast_days or 30, 1)
        start = fields.Date.context_today(self) - timedelta(days=period - 1)
        data = {
            color.id: rest for color, *rest in self.env["craf.paint.batch"].sudo()._read_group(
                [("color_id", "in", self.ids), ("state", "=", "done"), ("date", ">=", start)],
                ["color_id"], ["powder_g_m2:avg", "defect_pct:avg", "area_total:sum", "__count"])
        }
        for color in self:
            powder, defect, area, count = data.get(color.id, (0.0, 0.0, 0.0, 0))
            color.craf_fact_powder_g_m2 = powder or 0.0
            color.craf_fact_defect_pct = defect or 0.0
            color.craf_fact_area = area or 0.0
            color.craf_fact_batch_count = count

    def action_craf_norm_from_fact(self):
        """Kukun normasini oxirgi davrdagi faktdan olish (kukun yozilgan smenasi bor ranglar uchun)."""
        colors = self.filtered(lambda c: c.craf_fact_batch_count and c.craf_fact_powder_g_m2)
        if not colors:
            raise UserError("Tanlangan ranglarda oxirgi davrda kukun sarfi yozilgan bo'yash smenasi yo'q.")
        for color in colors:
            color.craf_powder_norm = round(color.craf_fact_powder_g_m2, 0)
        return True
