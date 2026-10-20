"""Yuklovchi menyusi: faqat yuklovchi bo'lgan foydalanuvchi bitta «Yuklash» ilovasini ko'radi
(Sotuv — yuklash navbati, Tayyor mahsulot sanash). Qolganlar uchun bu ilova yashiriladi (u Odoo
ilovalarida allaqachon bor), administrator hammasini ko'radi.

Natija faqat guruhlarga bog'liq — Odoo keshi ham guruhlar bo'yicha.
"""
from odoo import api, models, tools


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    @tools.ormcache("frozenset(self.env.user._get_group_ids())", "debug")
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug)
        root = self.env.ref("craf_sex.menu_craf_loader_root", raise_if_not_found=False)
        if not root:
            return visible
        user = self.env.user
        if user.has_group("base.group_system"):
            return visible
        app = set(self.sudo().with_context(active_test=False).search([("id", "child_of", root.id)]).ids)
        if user._craf_is_loader_only():
            return frozenset(set(visible) & app)
        return frozenset(set(visible) - app)
