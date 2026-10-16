from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _craf_loader_home(self):
        """Bosh sahifa (faqat qo'lda tanlanmagan bo'lsa): yuklovchi → Yuklash, sotuvchi → Buyurtma."""
        loader = self.env.ref("craf_sotuv.action_craf_yuklash", raise_if_not_found=False)
        seller = self.env.ref("craf_sotuv.action_craf_sotuv", raise_if_not_found=False)
        if not loader or not seller:
            return
        for user in self.sudo():
            if user.share or user.action_id:
                continue
            if user.has_group("craf_sotuv.group_craf_seller"):
                user.action_id = seller.id
            elif user.has_group("craf_sotuv.group_craf_loader"):
                user.action_id = loader.id

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._craf_loader_home()
        return users

    def write(self, vals):
        res = super().write(vals)
        if "action_id" not in vals and any(k.startswith(("group_ids", "sel_groups_", "in_group_")) for k in vals):
            self._craf_loader_home()
        return res
