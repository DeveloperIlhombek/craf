"""Yuklovchining telefondagi pastki paneli: bandlar session orqali (faqat yuklovchi roliga), navbat soni."""
from odoo import api, models
from odoo.http import request


def loader_nav_items(env):
    def act(xmlid):
        rec = env.ref(xmlid, raise_if_not_found=False)
        return rec.id if rec else False

    return [
        {"key": "load", "label": "Yuklash", "icon": "fa-truck", "tab": "load"},
        {"key": "sales", "label": "Bugun", "icon": "fa-list-ul", "tab": "sales"},
        {"key": "stock", "label": "Qoldiq", "icon": "fa-cubes", "tab": "stock"},
        {"key": "count", "label": "Sanash", "icon": "fa-check-square-o",
         "action_id": act("craf_sotuv.action_craf_tayyor_sanash"), "res_model": "stock.quant"},
        {"key": "waybill", "label": "Yuk xati", "icon": "fa-file-text-o",
         "action_id": act("craf_sotuv.action_craf_waybill"), "res_model": "stock.picking"},
    ]


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        user = self.env.user
        if request and request.session.uid and user and not user.share and user._craf_is_loader_only():
            info["craf_loader_nav"] = loader_nav_items(self.env)
        return info


class CrafSotuv(models.AbstractModel):
    _inherit = "craf.sotuv"

    @api.model
    def loader_nav_counts(self):
        """Pastki paneldagi belgilar: yuklash navbatidagi buyurtmalar soni."""
        self._check_loader()
        return {"load": self.env["sale.order"].sudo().search_count(self._queue_domain())}
