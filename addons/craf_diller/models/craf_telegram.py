import base64

import requests

from odoo import api, models

from odoo.addons.craf_telegram.models.craf_telegram import API_URL, TelegramError, esc


class CrafTelegram(models.AbstractModel):
    _inherit = "craf.telegram"

    @api.model
    def send_photo(self, chat_id, attachment, caption=""):
        token = self._token()
        if not token:
            raise TelegramError("Telegram bot tokeni sozlamada yozilmagan.")
        raw = base64.b64decode(attachment.sudo().datas or b"")
        try:
            resp = requests.post(API_URL % (token, "sendPhoto"), data={"chat_id": chat_id, "caption": caption[:1000]},
                                 files={"photo": (attachment.name or "rasm.jpg", raw, "image/jpeg")}, timeout=30)
            data = resp.json()
        except (requests.RequestException, ValueError) as err:
            raise TelegramError("Telegram bilan aloqa yo'q: %s" % err) from err
        if not data.get("ok"):
            raise TelegramError(data.get("description") or "Telegram xatosi (%s)" % resp.status_code)
        return True

    @api.model
    def handle_message(self, chat_id, text, first_name=""):
        chat_id = str(chat_id)
        Partner = self.env["res.partner"].sudo()
        words = (text or "").strip().split()
        if len(words) == 2 and words[0].lower() == "/start" and words[1].startswith("d_"):
            person = Partner.search([("craf_telegram_token", "=", words[1][2:])], limit=1)
            if not person:
                return self._reply(chat_id, "Havola eskirgan. Portaldagi «Telegram ulash» tugmasini qayta bosing.")
            Partner.search([("craf_telegram_id", "=", chat_id)]).craf_telegram_id = False
            person.write({"craf_telegram_id": chat_id, "craf_telegram_token": False})
            return self._reply(chat_id, "✅ %s, Telegram ulandi. Buyurtma holati va xabarlar shu yerga keladi." % esc(
                person.name))
        person = Partner.search([("craf_telegram_id", "=", chat_id)], limit=1)
        if person and not self._contacts().filtered(lambda c: c.telegram_id.strip() == chat_id):
            return self._reply(chat_id, "Buyurtma portal orqali beriladi: %s/diller" % person.get_base_url())
        return super().handle_message(chat_id, text, first_name)
