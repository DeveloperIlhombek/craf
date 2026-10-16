from odoo import api, fields, models

WORK_STAGES = [
    ("litey", "Литейка"),
    ("press", "Press"),
    ("kimyo", "Kimyoviy ishlov"),
    ("boyash", "Bo'yash va qadoqlash"),
]


class ResUsers(models.Model):
    _inherit = "res.users"

    craf_work_stage = fields.Selection(
        WORK_STAGES, string="Ish joyi (sex)",
        help="Sex ishchisi Odoo ni ochganda shu sex sahifasiga tushadi; Sexlar sahifasi ham shu sexdan ochiladi.")

    def _craf_role_home(self):
        """Bosh sahifa roli bo'yicha (faqat bosh sahifa qo'lda tanlanmagan bo'lsa):
        Direktor → Zavod paneli, Omborchi → Kunlik hisobot, Sex ishchisi → o'z sexi."""
        refs = {
            "director": "craf_dashboard.action_craf_dashboard",
            "accountant": "craf_hisobot.action_craf_kunlik",
            "litey": "craf_litey.action_craf_litey",
            "sex": "craf_sex.action_craf_sex",
        }
        actions = {k: self.env.ref(v, raise_if_not_found=False) for k, v in refs.items()}
        managed = {a.id for a in actions.values() if a}
        for ref in ("craf_sotuv.action_craf_yuklash", "craf_sotuv.action_craf_sotuv"):
            sale_action = self.env.ref(ref, raise_if_not_found=False)
            if sale_action:
                managed.add(sale_action.id)
        for user in self.sudo():
            if user.share or (user.action_id and user.action_id.id not in managed):
                continue
            if user.has_group("craf_sex.group_craf_director"):
                key = "director"
            elif user.has_group("craf_sex.group_craf_accountant"):
                key = "accountant"
            elif user.has_group("craf_sex.group_craf_worker"):
                key = "litey" if user.craf_work_stage == "litey" else "sex"
            else:
                continue
            if actions.get(key) and user.action_id != actions[key]:
                user.action_id = actions[key].id

    @api.model
    def _craf_apply_homes(self):
        """Modul yangilanganda: bosh sahifasi tanlanmagan foydalanuvchilarga rol bo'yicha bosh sahifa."""
        users = self.sudo().search([("share", "=", False)])
        users._craf_loader_home()
        users._craf_role_home()

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._craf_role_home()
        return users

    def write(self, vals):
        res = super().write(vals)
        if "action_id" not in vals and ("craf_work_stage" in vals or any(
                k.startswith(("group_ids", "sel_groups_", "in_group_")) for k in vals)):
            self._craf_role_home()
        return res
