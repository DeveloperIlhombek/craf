"""Ishlab chiqarish bo'limlari (Liteyka, Press, Bo'yash va qadoqlash) sozlamalari.

Har bo'limda mas'ul shaxslar ro'yxati: Odoo foydalanuvchisi (dasturdagi eslatma uchun) va Telegram ID
(umumiy bot orqali kunlik xabar va eslatma — keyingi bosqich). Bo'limlar soni qat'iy: 3 ta yozuv data da.
"""
from odoo import api, fields, models

BOLIMLAR = [("litey", "Liteyka"), ("press", "Press"), ("boyash", "Bo'yash va qadoqlash")]


class CrafBolim(models.Model):
    _name = "craf.bolim"
    _description = "Ishlab chiqarish bo'limi sozlamalari"
    _order = "sequence, id"

    name = fields.Char("Bo'lim", required=True)
    code = fields.Selection(BOLIMLAR, string="Kod", required=True, readonly=True)
    sequence = fields.Integer(default=10)
    contact_ids = fields.One2many("craf.bolim.contact", "bolim_id", string="Mas'ul shaxslar")
    forecast_days = fields.Integer(
        "Prognoz davri (kun)", default=30,
        help="Xom-ashyo necha kunga yetishi oxirgi shuncha kundagi o'rtacha kunlik sarfdan hisoblanadi.")
    warn_days = fields.Integer(
        "Ogohlantirish (kun)", default=7,
        help="Qoldiq minimalgacha shuncha kundan kam qolganda material «tez orada tugaydi» deb belgilanadi.")
    notify_app = fields.Boolean("Dasturda eslatma", default=True,
                                help="Minimal qoldiqdan kamaygan material uchun mas'ul foydalanuvchilarga Odoo eslatmasi.")
    note = fields.Text("Izoh")

    _code_uniq = models.Constraint("UNIQUE(code)", "Har bo'lim uchun bitta sozlama bo'ladi.")

    @api.model
    def _get(self, code):
        return self.sudo().search([("code", "=", code)], limit=1)

    def _notify_users(self):
        """Dasturda eslatma oladigan foydalanuvchilar (faol mas'ullar)."""
        self.ensure_one()
        return self.contact_ids.filtered(lambda c: c.active and c.user_id).user_id


class CrafBolimContact(models.Model):
    _name = "craf.bolim.contact"
    _description = "Bo'lim mas'ul shaxsi"
    _order = "sequence, id"

    bolim_id = fields.Many2one("craf.bolim", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean("Faol", default=True)
    name = fields.Char("F.I.Sh.", required=True)
    role = fields.Char("Lavozimi", help="Masalan: ombor mudiri, sex boshlig'i, direktor")
    user_id = fields.Many2one("res.users", string="Odoo foydalanuvchisi",
                              help="Bo'lsa, dasturning o'zida ham eslatma oladi.")
    telegram_id = fields.Char("Telegram ID", help="Botga /start bosgandan keyin bot ko'rsatadigan raqam (chat id).")
    phone = fields.Char("Telefon")
    notify_min_qty = fields.Boolean("Minimal qoldiq", default=True,
                                    help="Xom-ashyo minimal qoldiqdan kamayganda xabar oladi.")
    notify_daily = fields.Boolean("Kunlik hisobot", default=True, help="Har kuni bo'lim yakuni (Telegram bot).")

    @api.onchange("user_id")
    def _onchange_user_id(self):
        if self.user_id and not self.name:
            self.name = self.user_id.name
