"""Telefondagi pastki panel bandlari session orqali: yuklovchi (navbat soni) va kimyo xodimi (kutayotgan korzinkalar)."""
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


def kimyo_nav_items(env):
    # kimyo sahifasining o'z varaqlari (Ish / Hujjatlar / Qoldiq) — telefonda pastki panelda
    ctx = {"craf_stage": "kimyo"}
    return [
        {"key": "ish", "label": "Korzinkalar", "icon": "fa-shopping-basket", "tab": "ish", "tag": "craf_sex",
         "context": ctx},
        {"key": "hujjat", "label": "Hujjatlar", "icon": "fa-list-ul", "tab": "hujjat", "tag": "craf_sex",
         "context": ctx},
        {"key": "kislota", "label": "Kislota", "icon": "fa-flask", "tab": "kislota", "tag": "craf_sex",
         "context": ctx},
        {"key": "qoldiq", "label": "Qoldiq", "icon": "fa-archive", "tab": "qoldiq", "tag": "craf_sex", "context": ctx},
    ]


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        user = self.env.user
        if request and request.session.uid and user and not user.share and user._craf_is_loader_only():
            info["craf_loader_nav"] = loader_nav_items(self.env)
            info["craf_nav_counts"] = ["craf.sotuv", "loader_nav_counts"]
        elif request and request.session.uid and user and not user.share and user._craf_is_kimyo_only():
            info["craf_loader_nav"] = kimyo_nav_items(self.env)
            info["craf_nav_counts"] = ["craf.sex", "nav_counts"]
        return info


class CrafSotuv(models.AbstractModel):
    _inherit = "craf.sotuv"

    @api.model
    def loader_nav_counts(self):
        """Pastki paneldagi belgilar: yuklash navbatidagi buyurtmalar soni."""
        self._check_loader()
        return {"load": self.env["sale.order"].sudo().search_count(self._queue_domain())}
