from odoo import fields, models
from odoo.exceptions import UserError

from .craf_telegram import DEFAULT_HOUR, P_BOT, P_HOUR, P_TOKEN


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    craf_tg_token = fields.Char("Bot tokeni", config_parameter=P_TOKEN,
                                help="BotFather bergan token, masalan 123456789:AA...")
    craf_tg_bot_username = fields.Char("Bot", config_parameter=P_BOT, readonly=True)
    craf_tg_daily_hour = fields.Integer("Kunlik hisobot soati", config_parameter=P_HOUR, default=DEFAULT_HOUR,
                                        help="Toshkent vaqti bilan; hisobot kechagi kun uchun yuboriladi.")

    def set_values(self):
        if self.craf_tg_daily_hour and not 0 <= self.craf_tg_daily_hour <= 23:
            raise UserError("Kunlik hisobot soati 0 dan 23 gacha bo'ladi.")
        if self.craf_tg_token:
            self.craf_tg_token = self.craf_tg_token.strip()
        super().set_values()

    def action_craf_tg_check(self):
        self.set_values()
        username = self.env["craf.telegram"].sudo().check_bot()
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": "Bot ishlayapti: @%s. Mas'ullar botga /start bosib, Telegram ID sini olsin." % username,
                           "type": "success", "sticky": False, "next": {"type": "ir.actions.client", "tag": "reload"}}}

    def action_craf_tg_report_now(self):
        self.set_values()
        TG = self.env["craf.telegram"].sudo()
        if not TG._token():
            raise UserError("Avval bot tokenini yozing.")
        sent = TG.send_daily()
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": "Kunlik hisobot yuborildi: %s ta xabar." % sent,
                           "type": "success" if sent else "warning", "sticky": False}}
