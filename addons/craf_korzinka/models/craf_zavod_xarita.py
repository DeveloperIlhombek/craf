from odoo import api, models


class CrafZavodXarita(models.AbstractModel):
    _inherit = "craf.zavod.xarita"

    @api.model
    def get_map_data(self, top_limit=12, period="today", **kwargs):
        """Korzinkalar soni craf_zavod da (craf.basket.load mavjud bo'lsa) hisoblanadi; oqimlar — real harakatlardan.
        Bu yerda faqat «uzoq turgan» to'la korzinkalar qo'shiladi."""
        data = super().get_map_data(top_limit=top_limit, period=period, **kwargs)
        stale = self.env["craf.basket"].search([("is_stale", "=", True)])
        for zone in data["zones"]:
            zone["baskets_stale"] = len(stale.filtered(lambda b, zid=zone["id"]: b.location_id.id == zid))
        return data
