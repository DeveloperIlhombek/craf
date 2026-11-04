import json

from odoo import api, models

# bildirishnoma bosilganda ochiladigan sahifa: Odoo service worker «/odoo/<model>/<res_id>» ni ochadi
PUSH_OPEN = "action-craf_sotuv.action_craf_yuklash"


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

    def _craf_web_push(self, title, body, tag=False):
        """Telefonga (o'rnatilgan ilova / brauzer) bildirishnoma — Odoo veb-push navbati orqali, buyurtmani
        tasdiqlash tarmoqni kutmaydi. Faqat bildirishnomaga ruxsat bergan qurilmalarga boradi."""
        devices = self.env["mail.push.device"].sudo().search([("partner_id", "in", self.partner_id.ids)])
        if not devices:
            return 0
        payload = json.dumps({
            "title": title,
            "options": {
                "body": body,
                "icon": "/web/static/img/odoo-icon-192x192.png",
                "tag": tag or "craf",
                "renotify": True,
                "vibrate": [200, 100, 200],
                "data": {"model": PUSH_OPEN, "res_id": ""},
            },
        })
        self.env["mail.push"].sudo().create([{"mail_push_device_id": d.id, "payload": payload} for d in devices])
        self.env.ref("mail.ir_cron_web_push_notification").sudo()._trigger()
        return len(devices)
