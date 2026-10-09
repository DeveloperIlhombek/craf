from odoo import api, models

FLOWS = [
    ("Xom-ashyo ombori", "Литейка", "shixta"),
    ("Литейка", "Press sexi", "stalba"),
    ("Press sexi", "Kimyoviy ishlov", "korzinka"),
    ("Kimyoviy ishlov", "Bo'yash sexi", "profil"),
    ("Bo'yash sexi", "Qadoqlash", "bo'yalgan"),
    ("Qadoqlash", "Tayyor mahsulot ombori", "pachka"),
    ("Chiqindi", "Литейка", "qayta eritish"),
]


class CrafZavodXarita(models.AbstractModel):
    _inherit = "craf.zavod.xarita"

    @api.model
    def get_map_data(self, top_limit=12):
        data = super().get_map_data(top_limit=top_limit)
        by_name = {z["name"]: z["id"] for z in data["zones"]}
        if "Kimyoviy ishlov" in by_name:
            data["flows"] = [
                {"from": by_name[a], "to": by_name[b], "label": label}
                for a, b, label in FLOWS if a in by_name and b in by_name
            ]
        # korzinkalar: qaysi bo'limda nechta
        loads = self.env["craf.basket.load"].search([("state", "in", ("press", "kimyo"))])
        for zone in data["zones"]:
            zl = loads.filtered(lambda l, zid=zone["id"]: l.location_id.id == zid)
            zone["baskets"] = len(zl)
        return data
