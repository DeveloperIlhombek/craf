import re

from odoo import api, models
from odoo.exceptions import UserError, ValidationError


class CrafBolim(models.Model):
    _inherit = "craf.bolim"

    def action_tg_send_report(self):
        """Bo'lim hisobotini (kechagi) hozir «Kunlik hisobot» belgilangan mas'ullarga yuboradi."""
        self.ensure_one()
        TG = self.env["craf.telegram"].sudo()
        if not TG._token():
            raise UserError("Avval sozlamada Telegram bot tokenini yozing.")
        if not TG._contacts(self.code, "notify_daily"):
            raise UserError("«Kunlik hisobot» belgilangan, Telegram ID si yozilgan mas'ul yo'q.")
        sent = TG.send_daily([self.code])
        return _notify("Hisobot yuborildi: %s ta xabar. Natija — Telegram xabarlari jurnalida." % sent)


class CrafBolimContact(models.Model):
    _inherit = "craf.bolim.contact"

    @api.constrains("telegram_id")
    def _check_telegram_id(self):
        for rec in self:
            if rec.telegram_id and not re.fullmatch(r"-?\d{5,15}", rec.telegram_id.strip()):
                raise ValidationError("Telegram ID faqat raqam bo'ladi (masalan 123456789). Botga /start "
                                      "bosilganda bot shu raqamni yozib beradi: %s" % rec.telegram_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("telegram_id"):
                vals["telegram_id"] = vals["telegram_id"].strip()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("telegram_id"):
            vals["telegram_id"] = vals["telegram_id"].strip()
        return super().write(vals)

    def action_tg_test(self):
        self.ensure_one()
        TG = self.env["craf.telegram"].sudo()
        if not TG._token():
            raise UserError("Avval sozlamada Telegram bot tokenini yozing.")
        if not self.telegram_id:
            raise UserError("%s uchun Telegram ID yozilmagan." % self.name)
        ok = TG.send(self.telegram_id, "✅ Craf: sinov xabari.\n%s, siz <b>%s</b> bo'limi mas'ullari ro'yxatidasiz." % (
            self.name, self.bolim_id.name), kind="test", contact=self)
        if not ok:
            log = self.env["craf.telegram.log"].sudo().search([("contact_id", "=", self.id)], limit=1)
            raise UserError("Yuborilmadi: %s\n\nKishi botga /start bosganmi va ID to'g'rimi — tekshiring." % (
                log.error or "noma'lum xato"))
        return _notify("%s ga sinov xabari yuborildi." % self.name)


def _notify(message, kind="success"):
    return {"type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": kind, "sticky": False}}
