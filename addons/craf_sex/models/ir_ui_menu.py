"""Yuklovchi menyusi: faqat yuklovchi bo'lgan foydalanuvchi bitta «Yuklash» ilovasini ko'radi
(Sotuv — yuklash navbati, Tayyor mahsulot sanash). Qolganlar uchun bu ilova yashiriladi (u Odoo
ilovalarida allaqachon bor), administrator hammasini ko'radi.

Shaxsiy ilovali xodim (kimyo, matritsa) ham xuddi shunday — faqat o'z ilovasini ko'radi, boshqalarga u yashirin.

Natija guruhlarga va «Ish joyi»ga bog'liq — kesh kaliti ham shular.
"""
from odoo import api, models, tools


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    @tools.ormcache("frozenset(self.env.user._get_group_ids())", "self.env.user.craf_work_stage", "debug")
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug)
        user = self.env.user
        if user.has_group("base.group_system"):
            return visible
        roots = [("loader", "craf_sex.menu_craf_loader_root")]
        roots += [(key, app["menu"]) for key, app in user._craf_own_apps().items()]
        apps = {}
        for key, xmlid in roots:
            root = self.env.ref(xmlid, raise_if_not_found=False)
            if root:
                apps[key] = set(self.sudo().with_context(active_test=False).search([("id", "child_of", root.id)]).ids)
        own = "loader" if user._craf_is_loader_only() else user._craf_own_app()
        if own in apps:
            return frozenset(set(visible) & apps[own])
        hidden = set().union(*apps.values()) if apps else set()
        return frozenset(set(visible) - hidden)
