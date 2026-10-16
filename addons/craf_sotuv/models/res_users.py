from odoo import api, models


class ResUsers(models.Model):
    _inherit = "res.users"

    def _craf_loader_home(self):
        """Faqat yuklovchi bo'lgan foydalanuvchi Odoo ni ochganda to'g'ri Yuklash sahifasiga tushadi."""
        action = self.env.ref("craf_sotuv.action_craf_yuklash", raise_if_not_found=False)
        if not action:
            return
        for user in self.sudo():
            if user.share or user.action_id:
                continue
            if user.has_group("craf_sotuv.group_craf_loader") and not user.has_group("craf_sotuv.group_craf_seller"):
                user.action_id = action.id

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
