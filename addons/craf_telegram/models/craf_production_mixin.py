from odoo import api, models


class CrafProductionMixin(models.AbstractModel):
    _inherit = "craf.production.mixin"

    @api.model
    def _craf_min_qty_sync(self, rows, bolim_code, act_xmlid, label):
        """Press (quyma) va Bo'yash (kukun, kimyo...) — Odoo eslatmasidan tashqari Telegram orqali ham."""
        res = super()._craf_min_qty_sync(rows, bolim_code, act_xmlid, label)
        self.env["craf.telegram"].sudo()._min_qty_alerts(rows, bolim_code)
        return res
