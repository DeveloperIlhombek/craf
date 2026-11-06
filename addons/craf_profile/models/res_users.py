"""Telefonga bildirishnoma (veb-push) — barcha craf modullari uchun umumiy yordamchi.

Odoo 19 Community'da veb-push bor: foydalanuvchi brauzerda (yoki o'rnatilgan ilovada) bildirishnomaga ruxsat
bersa, Odoo qurilmani `mail.push.device` ga o'zi yozadi. Bu yerda faqat xabar navbatga qo'yiladi
(`mail.push` + cron) — hujjatni tasdiqlash tarmoqni kutmaydi; tranzaksiya bekor bo'lsa, xabar ham ketmaydi.
"""
import json

from odoo import api, models
from odoo.tools import html2plaintext

ICON = "/web/static/img/odoo-icon-192x192.png"


class ResUsers(models.Model):
    _inherit = "res.users"

    def _craf_web_push(self, title, body, tag=False, model=False, res_id=""):
        """Shu foydalanuvchilarning ruxsat bergan qurilmalariga bildirishnoma. Bosilganda
        `/odoo/<model>/<res_id>` ochiladi (model = «sale.order» yoki «action-<xmlid>»). Qurilmalar soni."""
        users = self.filtered(lambda u: u.active and not u.share)
        if not users:
            return 0
        devices = self.env["mail.push.device"].sudo().search([("partner_id", "in", users.partner_id.ids)])
        if not devices:
            return 0
        payload = json.dumps({
            "title": title,
            "options": {
                "body": (body or "")[:400],
                "icon": ICON,
                "tag": tag or "craf",
                "renotify": True,
                "vibrate": [200, 100, 200],
                "data": {"model": model or "action-mail.action_discuss", "res_id": res_id or ""},
            },
        })
        self.env["mail.push"].sudo().create([{"mail_push_device_id": d.id, "payload": payload} for d in devices])
        self.env.ref("mail.ir_cron_web_push_notification").sudo()._trigger()
        return len(devices)

    @api.model
    def craf_push_test(self):
        """Foydalanuvchi menyusi / banner: o'zining telefoniga sinov xabari. Qurilmalar soni (0 — hali yozilmagan)."""
        return self.env.user._craf_web_push(
            "Craf: bildirishnoma yoqildi ✅", "Endi sizga tegishli xabarlar telefonga keladi.",
            tag="craf-test", model=self.env.user._craf_push_home())

    def _craf_push_home(self):
        """Bildirishnoma bosilganda ochiladigan umumiy sahifa — foydalanuvchining bosh sahifasi."""
        self.ensure_one()
        action = self.sudo().action_id
        xmlid = action.get_external_id().get(action.id) if action else False
        return "action-%s" % xmlid if xmlid else "action-mail.action_discuss"


class MailActivity(models.Model):
    _inherit = "mail.activity"

    @api.model_create_multi
    def create(self, vals_list):
        """Har bir yangi vazifa / eslatma (minimal qoldiq, normadan past va h.k.) — mas'ulning telefoniga."""
        activities = super().create(vals_list)
        if self.env.context.get("craf_no_push"):
            return activities
        if self.env.context.get("mail_activity_quick_update"):
            return activities
        for act in activities:
            user = act.user_id
            # «Odoo ichida» (inbox) xabar oladiganlarga Odoo o'zi push yuboradi — takrorlanmasin
            if not user or user == self.env.user or user.notification_type == "inbox":
                continue
            title = act.summary or act.activity_type_id.name or "Yangi vazifa"
            body = html2plaintext(act.note or "").strip() or act.res_name or ""
            user._craf_web_push(title, body, tag="craf-act-%s" % act.id,
                                model=act.res_model, res_id=act.res_id)
        return activities
