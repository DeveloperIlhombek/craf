"""Yuklovchi menyusi: faqat yuklovchi bo'lgan foydalanuvchi bitta «Yuklash» ilovasini ko'radi
(Sotuv — yuklash navbati, Tayyor mahsulot sanash). Qolganlar uchun bu ilova yashiriladi (u Odoo
ilovalarida allaqachon bor), administrator hammasini ko'radi.

Kimyo xodimi ham xuddi shunday — faqat «Kimyo» ilovasini ko'radi, boshqalarga u yashirin.

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
        apps = {}
        for key, xmlid in (("loader", "craf_sex.menu_craf_loader_root"), ("kimyo", "craf_sex.menu_craf_kimyo_root")):
            root = self.env.ref(xmlid, raise_if_not_found=False)
            if root:
                apps[key] = set(self.sudo().with_context(active_test=False).search([("id", "child_of", root.id)]).ids)
        own = "loader" if user._craf_is_loader_only() else ("kimyo" if user._craf_is_kimyo_only() else None)
        if own in apps:
            return frozenset(set(visible) & apps[own])
        hidden = set().union(*apps.values()) if apps else set()
        return frozenset(set(visible) - hidden)
