from datetime import timedelta

from odoo import api, fields, models


class CrafDashboard(models.AbstractModel):
    _inherit = "craf.dashboard"

    @api.model
    def get_data(self, period="7"):
        data = super().get_data(period)
        start = fields.Date.from_string(data["start"])
        end = fields.Date.from_string(data["end"])
        Load = self.env["craf.basket.load"]
        filled = Load.search([("date", ">=", start), ("date", "<=", end), ("shift_state", "=", "done")])
        today = fields.Date.context_today(self)
        data["baskets"] = {
            "filled": len(filled),
            "filled_today": len(filled.filtered(lambda l: l.date == today)),
            "pcs": sum(filled.mapped("pcs_total")),
            "kg": sum(l.net_kg or l.kg_theory for l in filled),
            "waiting_chem": Load.search_count([("state", "=", "press"), ("shift_state", "=", "done")]),
            "ready_paint": Load.search_count([("state", "=", "kimyo")]),
        }
        return data
