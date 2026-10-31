from odoo import fields, models


class CrafDillerLoginWizard(models.TransientModel):
    _name = "craf.diller.login.wizard"
    _description = "Diller uchun yangi login"

    partner_id = fields.Many2one("res.partner", "Diller", required=True)
    name = fields.Char("Ism", required=True)
    phone = fields.Char("Telefon")
    done = fields.Boolean()
    url = fields.Char("Taklif havolasi", readonly=True,
                      help="7 kun amal qiladi. Dillerga yuboring: u shu havolada parol o'rnatadi.")

    def action_create(self):
        self.ensure_one()
        _user, url = self.partner_id.sudo()._craf_diller_add_login(self.name, self.phone)
        self.write({"done": True, "url": url})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
                "target": "new", "name": "Taklif havolasi"}
