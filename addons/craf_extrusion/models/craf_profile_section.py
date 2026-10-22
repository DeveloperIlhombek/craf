from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError


class CrafProfileSection(models.Model):
    _inherit = "craf.profile.section"

    craf_norm_yield_pct = fields.Float(
        "Chiqish normasi, %", digits=(16, 1), aggregator=None,
        help="Press smenasida chiqish % shundan (minus Press sozlamasidagi chetlanish) past bo'lsa, ogohlantiriladi.")
    craf_norm_productivity = fields.Float(
        "Unumdorlik normasi, kg/soat", digits=(16, 1), aggregator=None)
    craf_fact_yield_pct = fields.Float("Fakt chiqish, %", compute="_compute_craf_fact", digits=(16, 1),
                                       help="Oxirgi N kun (Press sozlamasi) tasdiqlangan smenalar, og'irlik bo'yicha")
    craf_fact_productivity = fields.Float("Fakt unumdorlik, kg/soat", compute="_compute_craf_fact", digits=(16, 1))
    craf_fact_output_kg = fields.Float("Fakt chiqish, kg", compute="_compute_craf_fact", digits=(16, 1))
    craf_fact_shift_count = fields.Integer("Smenalar", compute="_compute_craf_fact")

    def _compute_craf_fact(self):
        period = max(self.env["craf.bolim"]._get("press").forecast_days or 30, 1)
        start = fields.Date.context_today(self) - timedelta(days=period - 1)
        data = {
            section.id: (yield_pct, productivity, output_kg, count)
            for section, yield_pct, productivity, output_kg, count in self.env["craf.extrusion.shift"].sudo()._read_group(
                [("section_id", "in", self.ids), ("state", "=", "done"), ("date", ">=", start)],
                ["section_id"], ["yield_pct:avg", "productivity:avg", "output_kg:sum", "__count"])
        }
        for section in self:
            yield_pct, productivity, output_kg, count = data.get(section.id, (0.0, 0.0, 0.0, 0))
            section.craf_fact_yield_pct = yield_pct or 0.0
            section.craf_fact_productivity = productivity or 0.0
            section.craf_fact_output_kg = output_kg or 0.0
            section.craf_fact_shift_count = count

    def action_craf_norm_from_fact(self):
        """Normani oxirgi davrdagi faktdan olish (smenasi bor matritsalar uchun)."""
        sections = self.filtered("craf_fact_shift_count")
        if not sections:
            raise UserError("Tanlangan matritsalarda oxirgi davrda tasdiqlangan press smenasi yo'q.")
        for section in sections:
            section.write({
                "craf_norm_yield_pct": round(section.craf_fact_yield_pct, 1),
                "craf_norm_productivity": round(section.craf_fact_productivity, 1),
            })
        return True
