from odoo import api, models


class CrafLiteyHisobot(models.AbstractModel):
    _inherit = "craf.litey.hisobot"

    @api.model
    def _craf_min_qty_sync(self, rows=None):
        """Odoo eslatmasidan tashqari — Telegram orqali ham (bir marta, tiklanganda xabar bilan)."""
        if rows is None:
            rows = self._forecast_rows()[3]
        res = super()._craf_min_qty_sync(rows)
        self.env["craf.telegram"].sudo()._min_qty_alerts(rows)
        return res
